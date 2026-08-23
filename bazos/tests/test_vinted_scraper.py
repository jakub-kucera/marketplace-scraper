"""Tests for VintedScraper — the vinted-scraper-backed MarketplaceScraper impl.

Mocks VintedApiClient.search / .item directly (injected into `_clients`); never hits the
network. Field shapes mirror a live probe of `vinted-scraper` 4.0.0 against `vinted.cz` —
see docs/archive/shipped/VINTED_SCRAPER.md.
"""
from unittest.mock import MagicMock

import pytest
from vinted_scraper.models import VintedItem

import bazos.scraping.vinted.vinted_scraper as vinted_scraper_module
from bazos.const import VINTED_BASE_URL, VINTED_PAGE_SIZE
from bazos.filters import parse_price
from bazos.models import Ad, Marketplace, PriceType
from bazos.scraping.vinted.vinted_scraper import VintedScraper


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """load_full_description paces itself (VINTED_DETAIL_WAIT_TIME) — don't actually
    wait in the test suite. Individual tests can re-patch `sleep` again to observe calls.
    """
    monkeypatch.setattr(vinted_scraper_module, "sleep", lambda s: None)


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


def make_ad_stub(external_id: int, full_description=None, url: str | None = None) -> Ad:
    """A plain, unsaved Ad — enough for load_full_description, no DB needed."""
    return Ad(
        external_id=external_id,
        marketplace=Marketplace.VINTED.value,
        url=url or f"https://www.vinted.cz/items/{external_id}-x",
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

    def test_price_and_type_are_set(self):
        """Regression: PriceRangeRule/PriceDropRule now read ad.price/price_type
        directly (P22) — Vinted must populate them itself, it always has a real,
        placeholder-free numeric price (unlike Bazos)."""
        ad = VintedScraper._map_item(make_item(total_item_price=6307.5))
        assert ad.price == 6308
        assert ad.price_type == PriceType.EXACT

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

    def test_external_id_field_is_widened_to_biginteger(self):
        """Kept as a second, backend-independent check on the round trip above.

        The suite runs on Postgres now, so the save/reload does enforce int4's
        2,147,483,647 cap for real (see VINTED_SCRAPER.md §2.1). It stops enforcing
        anything the moment it is run under `TEST_DB=sqlite`, which has no fixed-width
        integer columns and would pass identically against a plain IntegerField. Pinning
        the field type directly holds either way.
        """
        assert Ad._meta.get_field("external_id").get_internal_type() == "BigIntegerField"

    def test_skips_item_missing_id(self):
        assert VintedScraper._map_item(make_item(id=None)) is None

    def test_skips_item_missing_title(self):
        assert VintedScraper._map_item(make_item(title=None)) is None

    def test_skips_item_missing_url(self):
        assert VintedScraper._map_item(make_item(url=None)) is None

    def test_skips_item_with_no_usable_price(self):
        item = make_item(total_item_price=None, price=None)
        assert VintedScraper._map_item(item) is None


# ---------------------------------------------------------------------------
# _format_price — the decimal trap, and missing-data guards
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

    def test_returns_none_when_both_prices_missing(self):
        item = make_item(total_item_price=None, price=None)
        assert VintedScraper._format_price(item) is None

    def test_returns_none_when_currency_missing(self):
        """Never fall back to the literal string "None" as a unit — that's both
        cosmetically broken and, since price_raw comparison is a plain string compare
        (run_existing_query), a currency flip alone would register as a price change.
        """
        item = make_item(currency=None)
        assert VintedScraper._format_price(item) is None


class TestPriceAmount:
    def test_rounds_total_item_price(self):
        item = make_item(total_item_price=6307.5)
        assert VintedScraper._price_amount(item) == 6308

    def test_falls_back_to_price_when_total_missing(self):
        item = make_item(total_item_price=None, price=100.0)
        assert VintedScraper._price_amount(item) == 100

    def test_none_when_both_prices_missing(self):
        item = make_item(total_item_price=None, price=None)
        assert VintedScraper._price_amount(item) is None


# ---------------------------------------------------------------------------
# run_query — params, base_url handling, pagination, malformed rows
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

    def test_extra_params_cannot_override_mandatory_order_and_per_page(self, query):
        """extra_params is spread into the params dict for pass-through keys like
        catalog_ids, but order/per_page are mandatory — dedup assumes newest-first and
        the pagination sentinel assumes VINTED_PAGE_SIZE exactly. A query with
        extra_params={"order": ...} must not be able to silently defeat either.
        """
        query.extra_params = {"order": "relevance", "per_page": 10}
        fake_client = MagicMock()
        fake_client.search.return_value = []
        scraper = scraper_with_client(fake_client)

        list(scraper.run_query(query))

        params = fake_client.search.call_args.args[0]
        assert params["order"] == "newest_first"
        assert params["per_page"] == VINTED_PAGE_SIZE

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

    def test_malformed_row_is_skipped_without_aborting_the_pass(self, query):
        """One bad row (plausible under the anti-bot throttling VINTED_SCRAPER_DESIGN.md
        §1a measured) must not raise out of the generator — that would abort the rest of
        the pass, the exact failure mode load_full_description's try/except exists to
        avoid one function over.
        """
        items = [make_item(id=1), make_item(id=None), make_item(id=3)]
        fake_client = MagicMock()
        fake_client.search.return_value = items
        scraper = scraper_with_client(fake_client)

        ads = list(scraper.run_query(query))

        assert [ad.external_id for ad in ads] == [1, 3]


# ---------------------------------------------------------------------------
# load_full_description — both failure modes, pacing, base-url derivation
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

    def test_load_full_description_paces_between_requests(self, monkeypatch):
        sleep_calls = []
        monkeypatch.setattr(vinted_scraper_module, "sleep", lambda s: sleep_calls.append(s))
        ad = make_ad_stub(123)
        fake_client = MagicMock()
        fake_client.item.return_value = make_item(id=123, description="d")
        scraper = scraper_with_client(fake_client)

        scraper.load_full_description(ad)

        assert len(sleep_calls) == 1

    def test_load_full_description_paces_even_on_runtime_error(self, monkeypatch):
        sleep_calls = []
        monkeypatch.setattr(vinted_scraper_module, "sleep", lambda s: sleep_calls.append(s))
        ad = make_ad_stub(123)
        fake_client = MagicMock()
        fake_client.item.side_effect = RuntimeError("404")
        scraper = scraper_with_client(fake_client)

        scraper.load_full_description(ad)

        assert len(sleep_calls) == 1

    @pytest.mark.django_db
    def test_load_full_description_uses_ads_own_domain_not_last_run_query(self, query):
        """Regression for the _last_base_url coupling that used to exist here:
        load_full_description must derive its client from ad.url, not from whichever
        base_url run_query happened to touch most recently on this scraper instance.
        """
        cz_client = MagicMock()
        cz_client.search.return_value = []
        sk_client = MagicMock()
        sk_client.item.return_value = make_item(id=1, description="sk desc")

        scraper = VintedScraper()
        scraper._clients[VINTED_BASE_URL] = cz_client
        scraper._clients["https://www.vinted.sk"] = sk_client

        list(scraper.run_query(query))  # touches the .cz client last

        sk_ad = make_ad_stub(1, url="https://www.vinted.sk/items/1-x")
        result = scraper.load_full_description(sk_ad)

        assert result.full_description == "sk desc"
        cz_client.item.assert_not_called()

    @pytest.mark.django_db
    def test_run_query_then_load_full_description_survives_one_detail_failure(self, query):
        """The regression that matters, exercised through the real caller shape:
        BazosQueryRunner._handle_new_product iterates `scraper.run_query(query)` and
        calls `scraper.load_full_description(ad)` per ad with no try/except. One ad's
        detail fetch raising RuntimeError (sold/deleted between search and this call)
        must not cut that loop short.
        """
        search_client = MagicMock()
        search_client.search.return_value = [make_item(id=1), make_item(id=2), make_item(id=3)]
        search_client.item.side_effect = [
            make_item(id=1, description="d1"),
            RuntimeError("Cannot perform API call to endpoint /items/2, error code: 404"),
            make_item(id=3, description="d3"),
        ]
        scraper = scraper_with_client(search_client)

        processed = [scraper.load_full_description(ad) for ad in scraper.run_query(query)]

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
