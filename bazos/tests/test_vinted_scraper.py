"""Tests for VintedScraper — the vinted-scraper-backed MarketplaceScraper impl.

Mocks VintedApiClient.search / .item directly (injected into `_clients`); never hits the
network. Field shapes mirror a live probe of `vinted-scraper` 4.0.0 against `vinted.cz` —
see docs/refactor/STAGE8_VINTED_SPEC.md.
"""
from unittest.mock import MagicMock

import pytest
from vinted_scraper.models import VintedItem

from bazos.const import VINTED_BASE_URL, VINTED_PAGE_SIZE
from bazos.filters import parse_price
from bazos.models import Ad, Marketplace
from bazos.scraping.vinted.vinted_scraper import VintedScraper


def make_item(**overrides) -> VintedItem:
    defaults = dict(
        id=123456789,
        title="MacBook Pro 13 2019",
        description=None,
        currency="CZK",
        price=5990.0,
        total_item_price=6307.5,
        promoted=False,
        url="https://www.vinted.cz/items/123456789-macbook-pro-13-2019",
    )
    defaults.update(overrides)
    return VintedItem(**defaults)


def make_ad_stub(external_id: int, full_description=None) -> Ad:
    """A plain, unsaved Ad — enough for load_full_description, no DB needed."""
    return Ad(
        external_id=external_id,
        marketplace=Marketplace.VINTED.value,
        url=f"https://www.vinted.cz/items/{external_id}-x",
        name="x",
        price_raw="1 CZK",
        location="",
        topped=False,
        short_description="",
        publisher_name="",
        full_description=full_description,
    )


def scraper_with_client(fake_client, base_url: str = VINTED_BASE_URL) -> VintedScraper:
    """A VintedScraper with `fake_client` pre-cached for `base_url`, so `_client_for`
    hits the cache and never attempts a real (network) construction.
    """
    scraper = VintedScraper()
    scraper._clients[base_url] = fake_client
    return scraper


# ---------------------------------------------------------------------------
# _map_item — field mapping, pure, no client
# ---------------------------------------------------------------------------

class TestMapItem:
    def test_maps_search_result_to_ad(self):
        item = make_item()
        assert item.title is not None
        ad = VintedScraper._map_item(item)

        assert isinstance(ad, Ad)
        assert ad.external_id == item.id
        assert ad.marketplace == Marketplace.VINTED.value
        assert ad.url == item.url
        assert ad.name == item.title[:120]
        assert ad.price_raw == "6308 CZK"
        assert ad.location == ""
        assert ad.view_count is None
        assert ad.publish_date is None
        assert ad.topped is False
        assert ad.short_description == ""
        assert ad.publisher_name == ""

    def test_promoted_maps_to_topped(self):
        ad = VintedScraper._map_item(make_item(promoted=True))
        assert ad.topped is True

    def test_long_title_is_truncated_to_120_chars(self):
        ad = VintedScraper._map_item(make_item(title="x" * 200))
        assert len(ad.name) == 120

    def test_publish_date_and_view_count_are_none(self):
        ad = VintedScraper._map_item(make_item())
        assert ad.publish_date is None
        assert ad.view_count is None

    @pytest.mark.django_db
    def test_big_external_id_survives_save(self):
        ad = VintedScraper._map_item(make_item(id=9734229070))
        ad.save()
        reloaded = Ad.objects.get(pk=ad.pk)
        assert reloaded.external_id == 9734229070


# ---------------------------------------------------------------------------
# _format_price — the decimal trap
# ---------------------------------------------------------------------------

class TestFormatPrice:
    def test_price_uses_total_item_price_and_is_integer(self):
        item = make_item(total_item_price=6307.5, currency="CZK")
        price_raw = VintedScraper._format_price(item)
        assert price_raw == "6308 CZK"
        assert parse_price(price_raw) == 6308

    def test_price_falls_back_to_price_when_total_missing(self):
        item = make_item(total_item_price=None, price=100.0, currency="CZK")
        assert VintedScraper._format_price(item) == "100 CZK"


# ---------------------------------------------------------------------------
# run_query — params, base_url handling, pagination
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRunQuery:
    def test_search_params_include_newest_first_order(self, query):
        fake_client = MagicMock()
        fake_client.search.return_value = []
        scraper = scraper_with_client(fake_client)

        list(scraper.run_query(query))

        params = fake_client.search.call_args.args[0]
        assert params["order"] == "newest_first"

    def test_base_url_is_stripped_from_search_params(self, query):
        query.extra_params = {"base_url": "https://www.vinted.sk"}
        fake_client = MagicMock()
        fake_client.search.return_value = []
        scraper = scraper_with_client(fake_client, base_url="https://www.vinted.sk")

        list(scraper.run_query(query))

        params = fake_client.search.call_args.args[0]
        assert "base_url" not in params

    def test_price_bounds_omitted_when_zero(self, query):
        assert query.price_lower == 0 and query.price_upper == 0
        fake_client = MagicMock()
        fake_client.search.return_value = []
        scraper = scraper_with_client(fake_client)

        list(scraper.run_query(query))

        params = fake_client.search.call_args.args[0]
        assert "price_from" not in params
        assert "price_to" not in params

    def test_pagination_stops_on_short_page(self, query):
        page1 = [make_item(id=i) for i in range(VINTED_PAGE_SIZE)]
        page2 = [make_item(id=i) for i in range(VINTED_PAGE_SIZE, VINTED_PAGE_SIZE + 5)]
        fake_client = MagicMock()
        fake_client.search.side_effect = [page1, page2]
        scraper = scraper_with_client(fake_client)

        ads = list(scraper.run_query(query))

        assert fake_client.search.call_count == 2
        assert len(ads) == VINTED_PAGE_SIZE + 5

    def test_pagination_stops_on_empty_page(self, query):
        page1 = [make_item(id=i) for i in range(VINTED_PAGE_SIZE)]
        fake_client = MagicMock()
        fake_client.search.side_effect = [page1, []]
        scraper = scraper_with_client(fake_client)

        ads = list(scraper.run_query(query))

        assert fake_client.search.call_count == 2
        assert len(ads) == VINTED_PAGE_SIZE


# ---------------------------------------------------------------------------
# load_full_description — both failure modes
# ---------------------------------------------------------------------------

class TestLoadFullDescription:
    def test_load_full_description_sets_full_description(self):
        ad = make_ad_stub(123)
        fake_client = MagicMock()
        fake_client.item.return_value = make_item(id=123, description="Full text here")
        scraper = scraper_with_client(fake_client)

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description == "Full text here"

    def test_load_full_description_tolerates_id_only_response(self):
        ad = make_ad_stub(123)
        fake_client = MagicMock()
        fake_client.item.return_value = VintedItem(id=123)  # only `id` populated
        scraper = scraper_with_client(fake_client)

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description is None

    def test_load_full_description_survives_runtime_error(self):
        ad = make_ad_stub(123)
        fake_client = MagicMock()
        fake_client.item.side_effect = RuntimeError(
            "Cannot perform API call to endpoint /items/123, error code: 404"
        )
        scraper = scraper_with_client(fake_client)

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description is None

    def test_run_query_completes_when_one_detail_fetch_raises(self):
        """The regression that matters: a caller looping load_full_description with no
        try/except (BazosQueryRunner._handle_new_product does exactly this) must not
        have its loop cut short by one sold/deleted listing.
        """
        ads = [make_ad_stub(1), make_ad_stub(2), make_ad_stub(3)]
        fake_client = MagicMock()
        fake_client.item.side_effect = [
            make_item(id=1, description="d1"),
            RuntimeError("Cannot perform API call to endpoint /items/2, error code: 404"),
            make_item(id=3, description="d3"),
        ]
        scraper = scraper_with_client(fake_client)

        processed = [scraper.load_full_description(ad) for ad in ads]

        assert [a.external_id for a in processed] == [1, 2, 3]
        assert processed[0].full_description == "d1"
        assert processed[1].full_description is None
        assert processed[2].full_description == "d3"


# ---------------------------------------------------------------------------
# check_blacklisted
# ---------------------------------------------------------------------------

class TestCheckBlacklisted:
    def test_check_blacklisted_always_false(self):
        assert VintedScraper().check_blacklisted() is False
