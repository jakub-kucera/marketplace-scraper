"""Tests for SbazarScraper — the Sbazar public-JSON-API MarketplaceScraper impl.

Mocks `requests.Session.get` directly via recorded fixture dicts shaped like real
`/api/v1/items/search` and `/api/v1/items/<id>` responses; never hits the network.
Field shapes and the four traps below come from a live probe of the Sbazar API —
see docs/archive/shipped/SBAZAR_SCRAPER.md and docs/research/marketplaces/SBAZAR.md §5a.
"""
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
import requests
from django.utils import timezone

from marketplace.const import (
    BAZOS_BASE_URL,
    SBAZAR_BASE_URL,
    SBAZAR_DEDUP_BREAK_STREAK,
    SBAZAR_MAX_PAGES,
    SBAZAR_PAGE_SIZE,
    VINTED_BASE_URL,
)
from marketplace.filters import parse_price
from marketplace.models import Ad, Marketplace, PriceType, Query
from marketplace.scraping.sbazar.sbazar_scraper import SbazarScraper


def make_row(**overrides) -> dict:
    defaults = dict(
        id=233201958,
        seo_name="233201958-acer-aspire-go-15-8-gb-ram-skvely-stav",
        name="Acer Aspire Go 15 | 8 GB RAM | Skvělý stav",
        price=11990,
        price_by_agreement=False,
        topped=False,
        create_date="2026-08-17T20:13:31",
        locality={
            "municipality": "Červený Kostelec",
            "district": "Náchod",
            "region": "Královéhradecký kraj",
        },
        user={
            "id": 326577859,
            "user_service": {
                "shop_url": "opaque-handle-123",
                "shop_name": "Real Person Name",  # must never end up in publisher_name
            },
        },
    )
    defaults.update(overrides)
    return defaults


def make_ad_stub(external_id: int) -> Ad:
    """A plain, unsaved Ad — enough for load_full_description, no DB needed."""
    return Ad(
        external_id=external_id,
        marketplace=Marketplace.SBAZAR.value,
        url=f"{SBAZAR_BASE_URL}/inzerat/{external_id}-x",
        name="x",
        price_raw="1000 Kč",
        location="",
        topped=False,
        short_description="",
        publisher_name="",
    )


def fake_response(payload: dict):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


# ---------------------------------------------------------------------------
# _map_item — field mapping, pure, no session
# ---------------------------------------------------------------------------

class TestMapItem:
    def test_maps_search_result_to_ad(self):
        row = make_row()
        ad = SbazarScraper._map_item(row, SBAZAR_BASE_URL)

        assert isinstance(ad, Ad)
        assert ad.external_id == row["id"]
        assert ad.marketplace == Marketplace.SBAZAR.value
        assert ad.url == f"{SBAZAR_BASE_URL}/inzerat/{row['seo_name']}"
        assert ad.name == row["name"]
        assert ad.price_raw == "11990 Kč"
        assert ad.location == "Červený Kostelec, Náchod, Královéhradecký kraj"
        assert ad.view_count is None
        assert ad.topped is False
        assert ad.short_description == ""
        assert ad.publisher_name == "opaque-handle-123"

    def test_price_and_type_are_set_for_normal_price(self):
        """Regression: PriceRangeRule/PriceDropRule now read ad.price/price_type
        directly (P22) — Sbazar must populate them itself, not via the Bazos-vocabulary
        parser (it can't see price_by_agreement, and would misclassify a real "0 Kč"
        giveaway as EXACT-0 instead of FREE — see spec §6)."""
        ad = SbazarScraper._map_item(make_row(price=11990, price_by_agreement=False), SBAZAR_BASE_URL)
        assert ad.price == 11990
        assert ad.price_type == PriceType.EXACT

    def test_price_by_agreement_is_negotiable_with_null_price(self):
        ad = SbazarScraper._map_item(make_row(price=0, price_by_agreement=True), SBAZAR_BASE_URL)
        assert ad.price is None
        assert ad.price_type == PriceType.NEGOTIABLE

    def test_zero_price_without_agreement_is_free_not_exact(self):
        """The giveaway case (§6): 0.8% of zero-priced rows are real frees, not
        negotiables — must never be branch on price == 0 alone."""
        ad = SbazarScraper._map_item(make_row(price=0, price_by_agreement=False), SBAZAR_BASE_URL)
        assert ad.price == 0
        assert ad.price_type == PriceType.FREE

    def test_topped_maps_bool(self):
        ad = SbazarScraper._map_item(make_row(topped=True), SBAZAR_BASE_URL)
        assert ad.topped is True

    def test_long_name_is_truncated_to_120_chars(self):
        ad = SbazarScraper._map_item(make_row(name="x" * 200), SBAZAR_BASE_URL)
        assert len(ad.name) == 120

    def test_view_count_is_never_synthesised(self):
        ad = SbazarScraper._map_item(make_row(), SBAZAR_BASE_URL)
        assert ad.view_count is None

    def test_publish_date_is_timezone_aware(self):
        ad = SbazarScraper._map_item(make_row(), SBAZAR_BASE_URL)
        assert ad.publish_date is not None
        assert timezone.is_aware(ad.publish_date)

    def test_uses_shop_url_not_shop_name(self):
        ad = SbazarScraper._map_item(make_row(), SBAZAR_BASE_URL)
        assert ad.publisher_name == "opaque-handle-123"
        assert "Real Person Name" not in ad.publisher_name

    @pytest.mark.django_db
    def test_big_external_id_survives_save(self):
        ad = SbazarScraper._map_item(make_row(id=233341956), SBAZAR_BASE_URL)
        ad.save()
        reloaded = Ad.objects.get(pk=ad.pk)
        assert reloaded.external_id == 233341956


# ---------------------------------------------------------------------------
# _format_price — the price-by-agreement trap (spec §6.1)
# ---------------------------------------------------------------------------

class TestFormatPrice:
    def test_normal_price(self):
        price_raw = SbazarScraper._format_price({"price": 11990, "price_by_agreement": False})
        assert price_raw == "11990 Kč"
        assert parse_price(price_raw) == 11990

    def test_price_by_agreement_becomes_dohodou_and_unparseable(self):
        price_raw = SbazarScraper._format_price({"price": 0, "price_by_agreement": True})
        assert price_raw == "Dohodou"
        assert parse_price(price_raw) is None

    def test_zero_price_without_agreement_flag_is_not_dohodou(self):
        """The giveaway case — price == 0 does NOT imply price_by_agreement."""
        price_raw = SbazarScraper._format_price({"price": 0, "price_by_agreement": False})
        assert price_raw == "0 Kč"
        assert parse_price(price_raw) == 0


class TestPriceAndType:
    def test_normal_price_is_exact(self):
        assert SbazarScraper._price_and_type({"price": 11990, "price_by_agreement": False}) == (
            11990, PriceType.EXACT,
        )

    def test_price_by_agreement_is_negotiable_regardless_of_price_value(self):
        """MUST branch on the boolean first — even a nonzero `price` alongside
        price_by_agreement=True (never observed live, but not something to trust) must
        still be treated as negotiable, not EXACT."""
        assert SbazarScraper._price_and_type({"price": 500, "price_by_agreement": True}) == (
            None, PriceType.NEGOTIABLE,
        )

    def test_zero_without_agreement_is_free(self):
        assert SbazarScraper._price_and_type({"price": 0, "price_by_agreement": False}) == (
            0, PriceType.FREE,
        )


# ---------------------------------------------------------------------------
# _format_location — municipality can be empty, district/region never are
# ---------------------------------------------------------------------------

class TestFormatLocation:
    def test_empty_municipality_no_leading_comma(self):
        loc = {"municipality": "", "district": "Náchod", "region": "Královéhradecký kraj"}
        assert SbazarScraper._format_location({"locality": loc}) == "Náchod, Královéhradecký kraj"

    def test_all_parts_present(self):
        loc = {"municipality": "Praha", "district": "Praha", "region": "Praha"}
        assert SbazarScraper._format_location({"locality": loc}) == "Praha, Praha, Praha"

    def test_missing_locality_returns_empty_string(self):
        assert SbazarScraper._format_location({}) == ""


# ---------------------------------------------------------------------------
# _parse_date — naive local time -> Europe/Prague aware
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_naive_datetime_becomes_prague_aware(self):
        parsed = SbazarScraper._parse_date("2026-08-17T20:13:31")
        assert timezone.is_aware(parsed)
        assert parsed.utcoffset() == timedelta(hours=2)  # CEST in August

    def test_missing_value_returns_none(self):
        assert SbazarScraper._parse_date(None) is None

    def test_unparseable_value_returns_none(self):
        assert SbazarScraper._parse_date("not-a-date") is None


# ---------------------------------------------------------------------------
# run_query — params, base_url handling, pagination
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRunQuery:
    def test_search_includes_phrase_when_text_present(self, query):
        session = MagicMock()
        session.get.return_value = fake_response({"results": []})
        scraper = SbazarScraper(session)

        list(scraper.run_query(query))

        params = session.get.call_args.kwargs["params"]
        assert params["phrase"] == "macbook"

    def test_price_bounds_omitted_when_zero(self, query):
        assert query.price_lower == 0 and query.price_upper == 0
        session = MagicMock()
        session.get.return_value = fake_response({"results": []})
        scraper = SbazarScraper(session)

        list(scraper.run_query(query))

        params = session.get.call_args.kwargs["params"]
        assert "price_from" not in params
        assert "price_to" not in params

    def test_price_bounds_included_when_set(self, query):
        query.price_lower = 100
        query.price_upper = 5000
        session = MagicMock()
        session.get.return_value = fake_response({"results": []})
        scraper = SbazarScraper(session)

        list(scraper.run_query(query))

        params = session.get.call_args.kwargs["params"]
        assert params["price_from"] == 100
        assert params["price_to"] == 5000

    def test_category_id_passed_through_extra_params(self, query):
        query.extra_params = {"category_id": 22}
        session = MagicMock()
        session.get.return_value = fake_response({"results": []})
        scraper = SbazarScraper(session)

        list(scraper.run_query(query))

        params = session.get.call_args.kwargs["params"]
        assert params["category_id"] == 22

    def test_base_url_is_stripped_from_params_and_used_in_request(self, query):
        query.extra_params = {"base_url": "https://staging.sbazar.cz", "category_id": 22}
        session = MagicMock()
        session.get.return_value = fake_response({"results": [make_row()]})
        scraper = SbazarScraper(session)

        ads = list(scraper.run_query(query))

        args, kwargs = session.get.call_args
        assert args[0] == "https://staging.sbazar.cz/api/v1/items/search"
        assert "base_url" not in kwargs["params"]
        assert ads[0].url.startswith("https://staging.sbazar.cz/inzerat/")

    def test_pagination_stops_on_short_page(self, query):
        page1 = {"results": [make_row(id=i) for i in range(SBAZAR_PAGE_SIZE)]}
        page2 = {"results": [make_row(id=i) for i in range(SBAZAR_PAGE_SIZE, SBAZAR_PAGE_SIZE + 5)]}
        session = MagicMock()
        session.get.side_effect = [fake_response(page1), fake_response(page2)]
        scraper = SbazarScraper(session)

        ads = list(scraper.run_query(query))

        assert session.get.call_count == 2
        assert len(ads) == SBAZAR_PAGE_SIZE + 5

    def test_pagination_stops_on_empty_results(self, query):
        page1 = {"results": [make_row(id=i) for i in range(SBAZAR_PAGE_SIZE)]}
        session = MagicMock()
        session.get.side_effect = [fake_response(page1), fake_response({"results": []})]
        scraper = SbazarScraper(session)

        ads = list(scraper.run_query(query))

        assert session.get.call_count == 2
        assert len(ads) == SBAZAR_PAGE_SIZE

    def test_pagination_stops_when_offset_reaches_total(self, query):
        payload = {
            "results": [make_row(id=i) for i in range(SBAZAR_PAGE_SIZE)],
            "pagination": {"limit": SBAZAR_PAGE_SIZE, "offset": 0, "total": SBAZAR_PAGE_SIZE},
        }
        session = MagicMock()
        session.get.return_value = fake_response(payload)
        scraper = SbazarScraper(session)

        ads = list(scraper.run_query(query))

        assert session.get.call_count == 1
        assert len(ads) == SBAZAR_PAGE_SIZE

    def test_offset_advances_between_requests(self, query):
        page1 = {"results": [make_row(id=i) for i in range(SBAZAR_PAGE_SIZE)]}
        page2 = {"results": [make_row(id=i) for i in range(5)]}
        session = MagicMock()
        session.get.side_effect = [fake_response(page1), fake_response(page2)]
        scraper = SbazarScraper(session)

        list(scraper.run_query(query))

        second_call_params = session.get.call_args_list[1].kwargs["params"]
        assert second_call_params["offset"] == SBAZAR_PAGE_SIZE

    def test_max_pages_is_a_hard_safety_stop(self, query):
        query.extra_params = {}
        session = MagicMock()
        session.get.side_effect = lambda *a, **k: fake_response(
            {"results": [make_row(id=i) for i in range(SBAZAR_PAGE_SIZE)]}
        )
        scraper = SbazarScraper(session)

        ads = list(scraper.run_query(query))

        assert session.get.call_count == SBAZAR_MAX_PAGES
        assert len(ads) == SBAZAR_MAX_PAGES * SBAZAR_PAGE_SIZE


# ---------------------------------------------------------------------------
# load_full_description — detail-only field, truncation, both failure modes
# ---------------------------------------------------------------------------

class TestLoadFullDescription:
    def test_truncates_long_description_to_300_keeps_full(self):
        ad = make_ad_stub(233341956)
        long_description = "x" * 679
        session = MagicMock()
        session.get.return_value = fake_response({"description": long_description})
        scraper = SbazarScraper(session)

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description == long_description
        assert len(result.full_description) == 679
        assert result.short_description == long_description[:300]
        assert len(result.short_description) == 300

    def test_detail_url_has_no_trailing_slash(self):
        ad = make_ad_stub(233341956)
        session = MagicMock()
        session.get.return_value = fake_response({"description": "x"})
        scraper = SbazarScraper(session)

        scraper.load_full_description(ad)

        url = session.get.call_args.args[0]
        assert url == f"{SBAZAR_BASE_URL}/api/v1/items/233341956"
        assert not url.endswith("/")

    def test_empty_description_leaves_ad_unchanged(self):
        ad = make_ad_stub(233341956)
        session = MagicMock()
        session.get.return_value = fake_response({"description": ""})
        scraper = SbazarScraper(session)

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description is None
        assert result.short_description == ""

    def test_survives_request_exception_and_raises_nothing(self):
        ad = make_ad_stub(233341956)
        session = MagicMock()
        session.get.side_effect = requests.RequestException("boom")
        scraper = SbazarScraper(session)

        result = scraper.load_full_description(ad)

        assert result is ad
        assert result.full_description is None


# ---------------------------------------------------------------------------
# check_blacklisted
# ---------------------------------------------------------------------------

class TestCheckBlacklisted:
    def test_check_blacklisted_always_false(self):
        assert SbazarScraper(MagicMock()).check_blacklisted() is False


# ---------------------------------------------------------------------------
# dedup_break_streak — Sbazar's sort key is edit time, not creation time
# (spec §11), so QueryRunner.run_existing_query needs more than one known
# hit before it can safely stop. See bazos/scraping/marketplace.py and
# query_runner.run_existing_query's docstring for how this is consumed.
# ---------------------------------------------------------------------------

class TestDedupBreakStreak:
    def test_sbazar_scraper_overrides_the_default_streak_of_one(self):
        scraper = SbazarScraper(MagicMock())
        assert scraper.dedup_break_streak == SBAZAR_DEDUP_BREAK_STREAK
        assert scraper.dedup_break_streak > 1


# ---------------------------------------------------------------------------
# Query.url — the §2.3 fix, and a regression guard on the other branches
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestQueryUrl:
    def test_sbazar_branch_returns_sbazar_base_url(self):
        query = Query(marketplace=Marketplace.SBAZAR.value, location_radius=25, price_lower=0, price_upper=0)
        assert query.url == SBAZAR_BASE_URL

    def test_sbazar_branch_respects_base_url_override(self):
        query = Query(
            marketplace=Marketplace.SBAZAR.value,
            extra_params={"base_url": "https://staging.sbazar.cz"},
            location_radius=25,
            price_lower=0,
            price_upper=0,
        )
        assert query.url == "https://staging.sbazar.cz"

    def test_vinted_branch_unchanged(self):
        query = Query(marketplace=Marketplace.VINTED.value, location_radius=25, price_lower=0, price_upper=0)
        assert query.url == VINTED_BASE_URL

    def test_bazos_branch_unchanged_without_section_or_category(self):
        query = Query(marketplace=Marketplace.BAZOS.value, location_radius=25, price_lower=0, price_upper=0)
        assert query.url == BAZOS_BASE_URL
