"""One unusable listing must not take out the whole query walk.

On 2026-08-23 a Bazos ad longer than `short_description`'s `varchar(300)` raised DataError
inside `_resolve_ad`, aborting the walk. The marketplace kept serving that ad, so it
aborted on every pass — the query was dead for two hours until the column was widened.
The column is fixed; these tests pin the guard that stops the next one being an outage,
since every field here is scraped free text against a max_length nobody measured.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.exceptions import MarketplaceBlockedError
from bazos.models import AdDelivery
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.query_runner import QueryRunner


@pytest.mark.django_db
def test_one_unusable_ad_does_not_abort_the_whole_walk(query, make_ad):
    query.new_query = False
    query.save()
    products = [make_ad(query, external_id) for external_id in (1, 2, 3)]
    # A real overflow rather than a mocked raise: `name` is CharField(120), so against the
    # Postgres this suite runs on, this is the same DataError that wedged the live query —
    # just in the next field of the same class.
    products[1].name = "x" * 500

    with patch.object(BazosScraper, "run_query", lambda self, q: iter(products)):
        runner = QueryRunner(query, MagicMock())
        runner.run()

    delivered = set(AdDelivery.objects.filter(query=query).values_list("ad__external_id", flat=True))
    assert delivered == {1, 3}
    assert runner.rows_seen_counter == 3


@pytest.mark.django_db
def test_the_walk_survives_the_aborted_transaction_the_bad_ad_leaves_behind(query, make_ad):
    """The reason the guard needs a savepoint rather than a bare `except`.

    A swallowed DB error leaves the transaction aborted, and *every* later query in it
    raises TransactionManagementError — so a bare guard converts one bad ad into a
    differently broken walk. This asserts the ads after the bad one still get written,
    which is exactly what fails without `transaction.atomic`.
    """
    query.new_query = False
    query.save()
    products = [make_ad(query, external_id) for external_id in (1, 2, 3)]
    products[0].name = "x" * 500  # the *first* ad poisons it, so 2 and 3 prove recovery

    with patch.object(BazosScraper, "run_query", lambda self, q: iter(products)):
        QueryRunner(query, MagicMock()).run()

    delivered = set(AdDelivery.objects.filter(query=query).values_list("ad__external_id", flat=True))
    assert delivered == {2, 3}


@pytest.mark.django_db
def test_a_block_is_still_raised_through_the_per_ad_guard(query, make_ad):
    """MarketplaceBlockedError means the transport is blocked, not that the ad is bad —
    swallowing it would leave the runner with nothing to rotate on.
    """
    query.new_query = False
    query.save()

    with patch.object(BazosScraper, "run_query", lambda self, q: iter([make_ad(query, 1)])), \
         patch.object(QueryRunner, "_handle_new_product", side_effect=MarketplaceBlockedError()):
        with pytest.raises(MarketplaceBlockedError):
            QueryRunner(query, MagicMock()).run()


@pytest.mark.django_db
def test_short_description_accepts_more_than_300_characters(query, make_ad):
    """Runs on real Postgres, so this genuinely exercises the old varchar(300) limit."""
    ad = make_ad(query, 1)
    ad.short_description = "x" * 5000
    ad.save()

    ad.refresh_from_db()
    assert len(ad.short_description) == 5000
