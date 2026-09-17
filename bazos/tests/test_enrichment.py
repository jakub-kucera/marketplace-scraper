"""Tests for `bazos/enrichment.py` — re-reading facts about one already-scraped ad.

The property that matters most here is that `refresh_ad` cannot become a second, divergent
copy of the sweep's write path. A price seen by a refresh is a price change like any other:
it has to write `PriceChange` history and re-enter the filter, or a listing that dropped 30%
is re-filtered against its pre-drop residual and the append-only history loses an entry.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.enrichment import NotRefreshable, fetch_full_description, refresh_ad
from bazos.models import Ad, AdDelivery, AdStatus, Marketplace, PriceChange


@pytest.fixture
def bazos_ad(db):
    return Ad.objects.create(
        external_id=4242, marketplace=Marketplace.BAZOS,
        url="https://pc.bazos.cz/inzerat/4242/old.php",
        name="MacBook Pro 14", price_raw="31 000 Kč", price=31000,
        location="Praha, 110 00", short_description="", publisher_name="Seller",
    )


def listing_row(external_id=4242, **overrides):
    row = {
        "id": external_id,
        "price_formatted": "31 000 Kč",
        "topped": "false",
        "url": "https://pc.bazos.cz/inzerat/4242/old.php",
        "views": "10",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# refresh_ad — the price path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_a_price_change_writes_history_and_re_enters_the_filter(bazos_ad, query):
    """Routed through `apply_batch`, so this cannot drift from the sweep's behaviour."""
    delivery = AdDelivery.objects.create(ad=bazos_ad, query=query, status=AdStatus.SENT)

    with patch("bazos.enrichment.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_by_ids.return_value = {
            4242: listing_row(price_formatted="27 000 Kč")
        }
        result = refresh_ad(bazos_ad, MagicMock())

    bazos_ad.refresh_from_db()
    delivery.refresh_from_db()
    assert bazos_ad.price == 27000
    assert PriceChange.objects.filter(ad=bazos_ad).count() == 1
    assert delivery.status == AdStatus.PRICE_CHANGED
    assert "price changed" in result


@pytest.mark.django_db
def test_an_ad_the_api_omits_is_recorded_as_removed(bazos_ad):
    """`{}` from a successful response means it is genuinely gone — the same signal the
    sweep reads."""
    with patch("bazos.enrichment.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_by_ids.return_value = {}
        result = refresh_ad(bazos_ad, MagicMock())

    bazos_ad.refresh_from_db()
    assert bazos_ad.removed_at is not None
    assert "no longer listed" in result


@pytest.mark.django_db
def test_no_usable_response_raises_instead_of_recording_a_removal(bazos_ad):
    """The 2026-09-17 regression, in this new call site. `None` is "no usable answer" and
    must never reach `apply_batch`, which reads an empty payload as "all of these are gone"."""
    with patch("bazos.enrichment.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_by_ids.return_value = None
        with pytest.raises(RuntimeError):
            refresh_ad(bazos_ad, MagicMock())

    bazos_ad.refresh_from_db()
    assert bazos_ad.removed_at is None
    assert bazos_ad.last_seen_at is None


# ---------------------------------------------------------------------------
# refresh_ad — the listing facts, and the one deliberately left frozen
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_topped_and_url_are_refreshed(bazos_ad):
    with patch("bazos.enrichment.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_by_ids.return_value = {
            4242: listing_row(topped="true", url="https://pc.bazos.cz/inzerat/4242/new.php")
        }
        result = refresh_ad(bazos_ad, MagicMock())

    bazos_ad.refresh_from_db()
    assert bazos_ad.topped is True
    assert bazos_ad.url.endswith("new.php")
    assert "topped" in result and "url" in result


@pytest.mark.django_db
def test_view_count_is_deliberately_not_refreshed(bazos_ad):
    """`view_count` means "views at the time of discovery", and two research documents
    reason about it on exactly that basis — it correlates ~0.06 with age *because* it is
    captured once, which makes it a staleness measure rather than a demand one. Overwriting
    it in place would quietly convert every historical row to a different quantity.
    """
    bazos_ad.view_count = 10
    bazos_ad.save(update_fields=["view_count"])

    with patch("bazos.enrichment.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_by_ids.return_value = {4242: listing_row(views="9999")}
        refresh_ad(bazos_ad, MagicMock())

    bazos_ad.refresh_from_db()
    assert bazos_ad.view_count == 10


@pytest.mark.django_db
def test_a_marketplace_without_a_bulk_endpoint_declines_clearly(bazos_ad):
    """Vinted and Sbazar would need a detail fetch per ad, which is a different job."""
    bazos_ad.marketplace = Marketplace.VINTED
    bazos_ad.save(update_fields=["marketplace"])

    with pytest.raises(NotRefreshable):
        refresh_ad(bazos_ad, MagicMock())


# ---------------------------------------------------------------------------
# fetch_full_description
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_description_is_fetched_through_the_ads_own_marketplace(bazos_ad):
    """Dispatches through `get_scraper`, so a new marketplace needs no change here."""
    def load(ad):
        ad.full_description = "a long description"
        return ad

    with patch("bazos.enrichment.get_scraper") as get_scraper:
        get_scraper.return_value.load_full_description.side_effect = load
        fetch_full_description(bazos_ad, MagicMock())

    assert get_scraper.call_args.args[0] == Marketplace.BAZOS
    bazos_ad.refresh_from_db()
    assert bazos_ad.full_description == "a long description"
