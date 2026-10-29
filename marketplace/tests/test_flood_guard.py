"""One query must not be able to empty a marketplace's catalog into Discord.

Measured on 2026-09-20: a newly added Sbazar query suppressed 71 ads on its first pass and
then sent **1 536 in the next hour**. Two separate defects produced that, and this file
pins both — the first-run walk that stopped early, and the absent per-pass ceiling.
"""
from unittest.mock import patch

import pytest

from marketplace.const import MAX_NEW_ADS_NOTIFIED_PER_PASS, NEW_PRODUCT_LOAD_MAX
from marketplace.models import Ad, AdDelivery, AdStatus, Marketplace, PriceType
from marketplace.scraping.query_runner import QueryRunner


def _catalog(n, start=1):
    """`n` listings, as a scraper would yield them."""
    return [
        Ad(
            external_id=start + i, marketplace=Marketplace.BAZOS,
            url=f"https://pc.bazos.cz/inzerat/{start + i}/x.php", name=f"Ad {start + i}",
            price_raw="10 000 Kč", price=10_000, price_type=PriceType.EXACT,
            location="Praha", short_description="x", publisher_name="p", topped=False,
        )
        for i in range(n)
    ]


@pytest.fixture
def runner(query):
    import requests

    with patch("marketplace.scraping.query_runner.get_scraper") as get_scraper:
        r = QueryRunner(query, requests.Session())
        r.scraper = get_scraper.return_value
        r.scraper.dedup_break_streak = 1
        yield r


@pytest.mark.django_db
def test_a_pass_notifies_at_most_the_cap(runner, query):
    """The rest are recorded, not dropped: the query must know them next pass."""
    found = MAX_NEW_ADS_NOTIFIED_PER_PASS + 40
    runner.scraper.run_query.return_value = iter(_catalog(found))

    runner.run_existing_query()

    assert AdDelivery.objects.filter(query=query, status=AdStatus.PENDING).count() == MAX_NEW_ADS_NOTIFIED_PER_PASS
    assert AdDelivery.objects.filter(query=query, status=AdStatus.SUPPRESSED).count() == 40
    assert AdDelivery.objects.filter(query=query).count() == found, "every ad is recorded"
    assert runner.flood_suppressed_counter == 40


@pytest.mark.django_db
def test_suppressed_ads_say_why(runner, query):
    runner.scraper.run_query.return_value = iter(_catalog(MAX_NEW_ADS_NOTIFIED_PER_PASS + 1))

    runner.run_existing_query()

    suppressed = AdDelivery.objects.get(query=query, status=AdStatus.SUPPRESSED)
    assert "one pass" in (suppressed.filter_reason or "")


@pytest.mark.django_db
def test_the_next_pass_is_quiet(runner, query):
    """The point of recording them: catching up must happen once, not every pass."""
    catalog = _catalog(MAX_NEW_ADS_NOTIFIED_PER_PASS + 30)
    runner.scraper.run_query.return_value = iter(catalog)
    runner.run_existing_query()

    second = QueryRunner.__new__(QueryRunner)
    second.query = query
    second.scraper = runner.scraper
    second.session = runner.session
    second.rows_seen_counter = 0
    second.new_product_counter = 0
    second.flood_suppressed_counter = 0
    runner.scraper.run_query.return_value = iter(_catalog(len(catalog)))

    second.run_existing_query()

    assert second.new_product_counter == 0, "nothing should look new the second time"


@pytest.mark.django_db
def test_a_suppressed_first_run_walks_past_the_notification_cap(runner, query):
    """`ignore_first_run` means "nothing that already exists should notify me".

    Stopping at NEW_PRODUCT_LOAD_MAX left the rest of the catalog unknown, so the *next*
    pass delivered all of it. Nothing is notified here, so the cap has nothing to bound.
    """
    query.ignore_first_run = True
    query.new_query = True
    query.save()
    catalog_size = NEW_PRODUCT_LOAD_MAX * 3
    runner.scraper.run_query.return_value = iter(_catalog(catalog_size))

    runner.run_new_query()

    assert AdDelivery.objects.filter(query=query).count() == catalog_size
    assert not AdDelivery.objects.filter(query=query).exclude(status=AdStatus.SUPPRESSED).exists()


@pytest.mark.django_db
def test_an_unsuppressed_first_run_still_stops_at_the_load_cap(runner, query):
    """Without `ignore_first_run` the cap is doing its original job: bounding how many
    notifications a brand-new query fires on day one."""
    query.ignore_first_run = False
    query.new_query = True
    query.save()
    runner.scraper.run_query.return_value = iter(_catalog(NEW_PRODUCT_LOAD_MAX * 3))

    runner.run_new_query()

    assert AdDelivery.objects.filter(query=query).count() <= NEW_PRODUCT_LOAD_MAX


@pytest.mark.django_db
def test_flood_suppressed_ads_skip_the_detail_fetch(runner, query):
    """1 500 paced detail GETs is an hour of Tor traffic enriching undelivered ads."""
    query.load_full_description = True
    query.save()
    runner.scraper.load_full_description.side_effect = lambda ad: ad
    runner.scraper.run_query.return_value = iter(_catalog(MAX_NEW_ADS_NOTIFIED_PER_PASS + 20))

    runner.run_existing_query()

    assert runner.scraper.load_full_description.call_count == MAX_NEW_ADS_NOTIFIED_PER_PASS
