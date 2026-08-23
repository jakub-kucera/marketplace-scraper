"""One unusable listing must not take out the whole query walk.

On 2026-08-23 a Bazos ad longer than `short_description`'s `varchar(300)` raised DataError
inside `_resolve_ad`, aborting the walk. The marketplace kept serving that ad, so it
aborted on every pass — the query was dead for two hours until the column was widened.
The column is fixed; these tests pin the guard that stops the next one being an outage,
since every field here is scraped free text against a max_length nobody measured.

Note on how the DataError is produced. These raise it from a patched `save` rather than
provoking a real overflow. In production the walk runs in **autocommit**, where a failed
statement is self-contained — but pytest-django wraps each test in an atomic block, so a
genuinely failed statement poisons the test's own transaction and every query after it,
which is a failure mode the daemon cannot have. `django_db(transaction=True)` would mirror
production faithfully, but it truncates the database on teardown and that breaks the
migration tests sharing the run. The real column bound is covered against real Postgres by
`test_short_description_accepts_more_than_300_characters`.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.db import DataError

from bazos.exceptions import MarketplaceBlockedError
from bazos.models import Ad, AdDelivery
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.query_runner import QueryRunner


def save_failing_on(external_id: int):
    """Patch for `Ad.save` that fails exactly one ad the way Postgres would."""
    original_save = Ad.save  # captured before patching, or the patch recurses into itself

    def failing_save(self, *args, **kwargs):
        if self.external_id == external_id:
            raise DataError("value too long for type character varying(120)")
        return original_save(self, *args, **kwargs)

    return failing_save


def walk(query, products):
    with patch.object(BazosScraper, "run_query", lambda self, q: iter(products)):
        runner = QueryRunner(query, MagicMock())
        runner.run()
    return runner


@pytest.mark.django_db
def test_one_unusable_ad_does_not_abort_the_whole_walk(query, make_ad):
    query.new_query = False
    query.save()
    products = [make_ad(query, external_id) for external_id in (1, 2, 3)]

    with patch.object(Ad, "save", save_failing_on(2)):
        runner = walk(query, products)

    delivered = set(AdDelivery.objects.filter(query=query).values_list("ad__external_id", flat=True))
    assert delivered == {1, 3}
    assert runner.rows_seen_counter == 3


@pytest.mark.django_db
def test_the_walk_recovers_when_the_very_first_ad_is_unusable(query, make_ad):
    """The bad row goes first, so ads 2 and 3 prove the walk genuinely recovered rather
    than merely not having reached the failure yet.
    """
    query.new_query = False
    query.save()
    products = [make_ad(query, external_id) for external_id in (1, 2, 3)]

    with patch.object(Ad, "save", save_failing_on(1)):
        walk(query, products)

    delivered = set(AdDelivery.objects.filter(query=query).values_list("ad__external_id", flat=True))
    assert delivered == {2, 3}


@pytest.mark.django_db
def test_a_dead_detail_transport_is_not_swallowed_as_a_bad_ad(query, make_ad):
    """The guard catches DatabaseError only, and this is why.

    `requests.ConnectionError` is not a `URLError`, so before the retry tuple was widened
    it escaped `run_request` entirely. A bare `except Exception` in the guard then
    swallowed it: the walk completed, the QueryRun kept its default success=True, and
    rows_seen>0 with new_ads=0 landed in the canary's "quiet market or dedup drift"
    bucket. A dead transport has to fail loudly.
    """
    query.new_query = False
    query.load_full_description = True
    query.save()
    products = [make_ad(query, external_id) for external_id in (1, 2, 3)]

    with patch.object(BazosScraper, "load_full_description",
                      side_effect=requests.exceptions.ConnectionError("tor down")):
        with pytest.raises(requests.exceptions.ConnectionError):
            walk(query, products)


@pytest.mark.django_db
def test_a_block_is_still_raised_through_the_per_ad_guard(query, make_ad):
    """MarketplaceBlockedError is not a DatabaseError, so it propagates on its own —
    swallowing it would leave the runner with nothing to rotate on.
    """
    query.new_query = False
    query.save()

    with patch.object(QueryRunner, "_handle_new_product", side_effect=MarketplaceBlockedError()):
        with pytest.raises(MarketplaceBlockedError):
            walk(query, [make_ad(query, 1)])


@pytest.mark.django_db
def test_short_description_accepts_more_than_300_characters(query, make_ad):
    """Runs against real Postgres, so this genuinely exercises the old varchar(300) limit."""
    ad = make_ad(query, 1)
    ad.short_description = "x" * 5000
    ad.save()

    ad.refresh_from_db()
    assert len(ad.short_description) == 5000
