"""Tests for BazosApiScraper — the hidden-API-based MarketplaceScraper impl.

Fixture JSON under fixtures/bazos_api/ is captured verbatim from live probes
documented in docs/research/bazos-api/HIDDEN_API.md (§5.1 listing, §5.2
detail).
"""
import copy
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from django.utils import timezone

from bazos.models import Ad, EmailPublisher, PhonePublisher, PriceType, Query
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.bazos.bazos_scraper import BazosScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "bazos_api"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text())


def make_listing_item(**overrides) -> dict:
    item = copy.deepcopy(load_fixture("listing_item.json"))
    item.update(overrides)
    return item


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json_data


# ---------------------------------------------------------------------------
# _build_query_params — pure, no DB access to the API
# ---------------------------------------------------------------------------

class TestBuildQueryParams:
    def test_maps_text_category_and_location(self, query):
        params = BazosApiScraper._build_query_params(query)
        assert params["query"] == "macbook"
        assert params["category"] == query.category.bazos_id
        assert params["zip_code"] == "12345"
        assert params["distance"] == 25
        assert params["sort"] == "date"

    def test_zero_price_is_omitted(self, query):
        params = BazosApiScraper._build_query_params(query)
        assert "price_from" not in params
        assert "price_to" not in params

    def test_nonzero_price_is_included(self, category):
        query = Query.objects.create(
            text="iphone", category=category, price_lower=100, price_upper=500,
        )
        params = BazosApiScraper._build_query_params(query)
        assert params["price_from"] == 100
        assert params["price_to"] == 500

    def test_section_only_query_maps_section_not_category(self, section):
        query = Query.objects.create(text="", section=section, price_lower=0, price_upper=0)
        params = BazosApiScraper._build_query_params(query)
        assert params["section"] == section.bazos_id
        assert "category" not in params

    def test_no_location_omits_zip_and_distance(self, category):
        query = Query.objects.create(text="test", category=category, location_center="", price_lower=0, price_upper=0)
        params = BazosApiScraper._build_query_params(query)
        assert "zip_code" not in params
        assert "distance" not in params


# ---------------------------------------------------------------------------
# _parse_listing_item / extract_product — pure JSON parsing, no DB
# ---------------------------------------------------------------------------

class TestParseListingItem:
    def test_external_id_is_int(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item())
        assert parsed["external_id"] == 221354384
        assert isinstance(parsed["external_id"], int)

    def test_name_from_title(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(title="Test Ad"))
        assert parsed["name"] == "Test Ad"

    def test_price_raw_from_price_formatted(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(price_formatted="1 000 Kč"))
        assert parsed["price_raw"] == "1 000 Kč"

    def test_price_and_type_parsed_from_price_formatted(self):
        """The listing payload has no price_type field (§5.1) — price_formatted is
        parsed the same way as the HTML scraper's price_raw."""
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(price_formatted="1 000 Kč"))
        assert parsed["price"] == 1000
        assert parsed["price_type"] == PriceType.EXACT

    def test_price_and_type_parsed_for_placeholder(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(price_formatted="Dohodou"))
        assert parsed["price"] is None
        assert parsed["price_type"] == PriceType.NEGOTIABLE

    def test_view_count_is_int(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(views="42"))
        assert parsed["view_count"] == 42
        assert isinstance(parsed["view_count"], int)

    def test_topped_true_string_parses_to_bool_true(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(topped="true"))
        assert parsed["topped"] is True

    def test_topped_false_string_parses_to_bool_false(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(topped="false"))
        assert parsed["topped"] is False

    def test_publish_date_is_timezone_aware(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(**{"from": "2026-07-19 09:45:51"}))
        assert timezone.is_aware(parsed["publish_date"])

    def test_publish_date_values(self):
        parsed = BazosApiScraper._parse_listing_item(make_listing_item(**{"from": "2026-07-19 09:45:51"}))
        d = parsed["publish_date"]
        assert (d.year, d.month, d.day, d.hour, d.minute) == (2026, 7, 19, 9, 45)


class TestExtractProduct:
    def test_returns_ad_with_bazos_api_marketplace(self):
        ad = BazosApiScraper.extract_product(make_listing_item())
        assert isinstance(ad, Ad)
        assert ad.marketplace == "bazos_api"

    def test_short_description_is_empty_thin_payload(self):
        ad = BazosApiScraper.extract_product(make_listing_item())
        assert ad.short_description == ""

    def test_price_and_type_set_from_listing(self):
        ad = BazosApiScraper.extract_product(make_listing_item(price_formatted="429 000 Kč"))
        assert ad.price == 429000
        assert ad.price_type == PriceType.EXACT

    def test_publishers_unset_until_detail_fetch(self):
        ad = BazosApiScraper.extract_product(make_listing_item())
        assert ad.email_publisher_id is None
        assert ad.phone_publisher_id is None


# ---------------------------------------------------------------------------
# check_blacklisted
# ---------------------------------------------------------------------------

class TestCheckBlacklisted:
    def test_returns_false_on_200(self):
        scraper = BazosApiScraper(session=MagicMock())
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=[])
        assert scraper.check_blacklisted() is False

    def test_returns_true_on_403(self):
        scraper = BazosApiScraper(session=MagicMock())
        scraper.session.get.return_value = FakeResponse(status_code=403, json_data={})
        assert scraper.check_blacklisted() is True

    def test_returns_true_on_429(self):
        scraper = BazosApiScraper(session=MagicMock())
        scraper.session.get.return_value = FakeResponse(status_code=429, json_data={})
        assert scraper.check_blacklisted() is True

    def test_assumes_ok_when_request_fails(self):
        scraper = BazosApiScraper(session=MagicMock())
        scraper.session.get.side_effect = requests.exceptions.ConnectionError()
        assert scraper.check_blacklisted() is False


# ---------------------------------------------------------------------------
# run_query — pagination against x-total-count
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRunQuery:
    def _scraper_not_blacklisted(self, monkeypatch):
        import bazos.scraping.bazos.bazos_api_scraper as mod
        monkeypatch.setattr(mod, "sleep", lambda s: None)
        scraper = BazosApiScraper(session=MagicMock())
        return scraper

    def test_paginates_until_total_count_reached(self, monkeypatch, query):
        scraper = self._scraper_not_blacklisted(monkeypatch)

        page1 = [make_listing_item(id=str(i)) for i in (1, 2)]
        page2 = [make_listing_item(id=str(i)) for i in (3,)]

        def fake_get(url, params=None, headers=None, **kwargs):
            if params["offset"] == 0:
                return FakeResponse(status_code=200, json_data=page1, headers={"x-total-count": "3"})
            if params["offset"] == 2:
                return FakeResponse(status_code=200, json_data=page2, headers={"x-total-count": "3"})
            return FakeResponse(status_code=200, json_data=[], headers={"x-total-count": "3"})

        scraper.session.get.side_effect = fake_get

        ads = list(scraper.run_query(query))
        assert [ad.external_id for ad in ads] == [1, 2, 3]

    def test_stops_on_empty_page_when_total_count_missing(self, monkeypatch, query):
        scraper = self._scraper_not_blacklisted(monkeypatch)

        page1 = [make_listing_item(id=str(i)) for i in (1, 2)]

        def fake_get(url, params=None, headers=None, **kwargs):
            if params["offset"] == 0:
                return FakeResponse(status_code=200, json_data=page1, headers={})
            return FakeResponse(status_code=200, json_data=[], headers={})

        scraper.session.get.side_effect = fake_get

        ads = list(scraper.run_query(query))
        assert [ad.external_id for ad in ads] == [1, 2]

    def test_single_page_query_sends_exactly_one_request(self, monkeypatch, query):
        """No separate blacklist probe (P26) — one page of results is one ads.php request."""
        scraper = self._scraper_not_blacklisted(monkeypatch)
        page1 = [make_listing_item(id=str(i)) for i in (1, 2)]
        scraper.session.get.return_value = FakeResponse(
            status_code=200, json_data=page1, headers={"x-total-count": "2"}
        )

        ads = list(scraper.run_query(query))

        assert [ad.external_id for ad in ads] == [1, 2]
        assert scraper.sent_requests_count == 1

    @pytest.mark.parametrize("status_code", [403, 429])
    def test_raises_when_real_request_is_blocked(self, monkeypatch, query, status_code):
        """A block is detected on the real ads.php request, not a separate probe (P26) —
        the probe that used to sit at the top of run_query is gone.
        """
        from bazos.exceptions import MarketplaceBlockedError

        scraper = self._scraper_not_blacklisted(monkeypatch)
        # The API answers a block in JSON rather than nginx's HTML, but names the IP in
        # the same shape — measured live 2026-08-29.
        scraper.session.get.return_value = FakeResponse(
            status_code=status_code,
            json_data={},
            text='{"error_code":"403","message":"You don\'t have permission to access '
                 'this server. IP: 86.54.28.49"}',
        )

        with pytest.raises(MarketplaceBlockedError) as excinfo:
            list(scraper.run_query(query))

        assert excinfo.value.exit_ip == "86.54.28.49"
        assert scraper.sent_requests_count == 1


# ---------------------------------------------------------------------------
# load_full_description
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestLoadFullDescription:
    def test_sets_full_description(self, make_ad, query):
        ad = make_ad(query, bazos_id=221354384)
        scraper = BazosApiScraper(session=MagicMock())
        detail = load_fixture("ad_detail.json")
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=detail)

        result = scraper.load_full_description(ad)

        assert result.full_description == detail["description"]

    def test_resolves_publishers_from_email_and_phone_id(self, make_ad, query):
        ad = make_ad(query, bazos_id=221354384)
        scraper = BazosApiScraper(session=MagicMock())
        detail = load_fixture("ad_detail.json")
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=detail)

        result = scraper.load_full_description(ad)

        assert result.email_publisher.bazos_id == int(detail["email_id"])
        assert result.phone_publisher.bazos_id == int(detail["phone_id"])
        assert EmailPublisher.objects.filter(bazos_id=int(detail["email_id"])).exists()
        assert PhonePublisher.objects.filter(bazos_id=int(detail["phone_id"])).exists()

    def test_handles_410_deleted_without_raising(self, make_ad, query):
        ad = make_ad(query, bazos_id=999)
        scraper = BazosApiScraper(session=MagicMock())
        scraper.session.get.return_value = FakeResponse(
            status_code=410, json_data={"idad": "1", "status": "deleted"}
        )

        result = scraper.load_full_description(ad)

        assert result.full_description is None

    def test_returns_product_unchanged_when_request_fails(self, make_ad, query):
        ad = make_ad(query, bazos_id=111)
        scraper = BazosApiScraper(session=MagicMock())
        scraper.session.get.side_effect = requests.exceptions.ConnectionError()

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description is None

    def test_exact_price_type_sets_numeric_price(self, make_ad, query):
        """Fixture's detail payload is the real measured sample (§4 of the research doc):
        price="429000" (a string), price_type="EXACT"."""
        ad = make_ad(query, bazos_id=221354384)
        ad.price, ad.price_type = None, PriceType.UNKNOWN  # simulate not-yet-parsed
        scraper = BazosApiScraper(session=MagicMock())
        detail = load_fixture("ad_detail.json")
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=detail)

        result = scraper.load_full_description(ad)

        assert result.price == 429000
        assert result.price_type == PriceType.EXACT

    def test_negotiated_price_type_maps_to_negotiable_with_null_price(self, make_ad, query):
        """detail `price` just echoes the placeholder for non-EXACT types (§4) — must not
        be int()'d."""
        ad = make_ad(query, bazos_id=221354384)
        scraper = BazosApiScraper(session=MagicMock())
        detail = load_fixture("ad_detail.json")
        detail = {**detail, "price": "Dohodou", "price_type": "NEGOTIATED", "price_formatted": "Dohodou"}
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=detail)

        result = scraper.load_full_description(ad)

        assert result.price is None
        assert result.price_type == PriceType.NEGOTIABLE

    def test_malformed_exact_price_keeps_listing_parsed_value_without_raising(self, make_ad, query):
        """price_type=EXACT but price isn't a plain int string — must not raise (see
        _handle_new_product's docstring: a raise from load_full_description truncates
        the whole scrape pass) and must not silently corrupt the already-good
        listing-parsed price either."""
        ad = make_ad(query, bazos_id=221354384)
        ad.price, ad.price_type = 429000, PriceType.EXACT  # what the listing parse already set
        scraper = BazosApiScraper(session=MagicMock())
        detail = load_fixture("ad_detail.json")
        detail = {**detail, "price": "15 000", "price_type": "EXACT"}  # not a plain digit string
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=detail)

        result = scraper.load_full_description(ad)

        assert result.price == 429000
        assert result.price_type == PriceType.EXACT

    def test_unrecognised_api_price_type_keeps_listing_parsed_value(self, make_ad, query):
        """Zdarma/Nerozhoduje weren't observed in the live API sample (§4/§10) — an
        unmapped price_type must not silently invent a value."""
        ad = make_ad(query, bazos_id=221354384)
        ad.price, ad.price_type = 0, PriceType.FREE  # what the listing parse already set
        scraper = BazosApiScraper(session=MagicMock())
        detail = load_fixture("ad_detail.json")
        detail = {**detail, "price": "Zdarma", "price_type": "SOME_FUTURE_VALUE", "price_formatted": "Zdarma"}
        scraper.session.get.return_value = FakeResponse(status_code=200, json_data=detail)

        result = scraper.load_full_description(ad)

        assert result.price == 0
        assert result.price_type == PriceType.FREE


# ---------------------------------------------------------------------------
# Registry — confirms normal Query rows (marketplace="bazos") still get the
# HTML scraper, and "bazos_api" is available but not production-wired.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestScraperRegistry:
    def test_registry_includes_all_scrapers(self):
        from bazos.scraping.query_runner import _build_scrapers
        from bazos.scraping.sbazar.sbazar_scraper import SbazarScraper
        from bazos.scraping.vinted.vinted_scraper import VintedScraper

        scrapers = _build_scrapers(MagicMock())
        assert isinstance(scrapers["bazos"], BazosScraper)
        assert isinstance(scrapers["bazos_api"], BazosApiScraper)
        assert isinstance(scrapers["vinted"], VintedScraper)
        assert isinstance(scrapers["sbazar"], SbazarScraper)

    def test_default_query_marketplace_still_resolves_html_scraper(self, query):
        from bazos.scraping.query_runner import QueryRunner

        assert query.marketplace == "bazos"
        runner = QueryRunner(query, MagicMock())
        assert isinstance(runner.scraper, BazosScraper)
