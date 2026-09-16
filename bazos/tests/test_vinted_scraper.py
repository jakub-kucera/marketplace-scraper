"""Tests for `VintedScraper` — the catalog-page rewrite.

The previous suite mocked `vinted_scraper.VintedScraper`, a library class that is no
longer a dependency: Vinted withdrew `/api/v2/catalog/items` around 2026-09-08. These
tests drive the parser from **real** captured payloads
(`fixtures/vinted_listing.txt`, `fixtures/vinted_item_detail.txt`) so the field names and
the awkward values — a decimal FX price, a quote inside a title, a promoted row — are the
ones the site actually serves. Nothing here touches the network.

See docs/research/marketplaces/VINTED.md for the measurements and
docs/backlog/VINTED_REWRITE.md §3 for the decisions.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from bazos.filters import parse_price
from bazos.models import Marketplace, PriceType, Query
from bazos.scraping.vinted import flight
from bazos.scraping.vinted.vinted_scraper import VintedScraper

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "vinted_listing.txt").read_text(encoding="utf-8")
DETAIL = (FIXTURES / "vinted_item_detail.txt").read_text(encoding="utf-8")

PLAIN_ID = 10018212520        # MacBook Pro 16", 13000.00 CZK, not promoted
PROMOTED_ID = 10016781365     # a promoted Nike jacket — junk in a "macbook" search
FX_ID = 10018404418           # 311.59 CZK, FX-converted from PLN
QUOTED_ID = 10015514053       # title contains a `"`


@pytest.fixture(autouse=True)
def no_detail_pacing():
    """`load_full_description` sleeps VINTED_DETAIL_WAIT_TIME (0.5-1.5s) before every
    request. Real and deliberate in production; ~8s of dead time across this file."""
    with patch("bazos.scraping.vinted.vinted_scraper.sleep"):
        yield


@pytest.fixture
def scraper():
    return VintedScraper(session=None)


@pytest.fixture
def vinted_query(db):
    return Query.objects.create(
        text="macbook", marketplace=Marketplace.VINTED,
        price_lower=0, price_upper=0, new_query=False,
        extra_params={"catalog_ids": [3580], "brand_ids": [54661]},
    )


def run(scraper, query, pages):
    """Drive run_query against canned payloads, returning the yielded Ads."""
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.side_effect = pages
        return list(scraper.run_query(query))


def rows_of(payload):
    return {r["productItem"]["id"]: r for r in flight.items(payload)}


# --------------------------------------------------------------------------- mapping

def test_maps_a_listing_row_to_an_ad(scraper):
    ad = scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.cz")

    assert ad.external_id == PLAIN_ID
    assert ad.marketplace == Marketplace.VINTED.value
    assert ad.name == "MacBook Pro 16”"
    assert ad.url == "https://www.vinted.cz/items/10018212520-macbook-pro-16"
    assert ad.price == 13000
    assert ad.price_raw == "13000 CZK"
    assert ad.price_type == PriceType.EXACT
    assert ad.short_description == "Apple MacBook Pro 2019 · Velmi dobrý"
    assert ad.topped is False
    assert ad.location == ""
    assert ad.publisher_name == ""


def test_price_is_ex_fee(scraper):
    """The decision in VINTED_REWRITE.md §1.1: store `price`, not `totalItemPrice`.

    Vinted's own price_from/price_to filter works on `price`, so storing the all-in figure
    made a price_upper=5000 query return rows whose stored price was 5268 — which
    price_range then rejected.
    """
    item = rows_of(LISTING)[PLAIN_ID]["productItem"]
    assert item["totalItemPrice"]["amount"] == "13668.00"      # what a buyer pays
    assert item["serviceFee"]["amount"] == "668.00"

    ad = scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.cz")
    assert ad.price == 13000, "stored the all-in price instead of the asking price"


def test_decimal_fx_price_does_not_multiply_by_ten(scraper):
    """`parse_price` strips non-digits, so "311.59 CZK" would parse to 31159 — a silent
    10x error that would wreck both price_range and price_drop. 78% of .cz prices are
    FX-converted and therefore non-round."""
    item = rows_of(LISTING)[FX_ID]["productItem"]
    assert item["price"]["amount"] == "311.59"

    ad = scraper._map_row(rows_of(LISTING)[FX_ID], "https://www.vinted.cz")
    assert ad.price == 312
    assert ad.price_raw == "312 CZK"
    assert parse_price(ad.price_raw) == ad.price, "price_raw must round-trip through parse_price"


def test_promoted_maps_to_topped(scraper):
    """Promoted rows sit far out of chronological order — position 75 was newer than
    position 50 — so the dedup walk depends on this flag."""
    ad = scraper._map_row(rows_of(LISTING)[PROMOTED_ID], "https://www.vinted.cz")
    assert ad.topped is True


def test_title_with_a_quote_survives_parsing(scraper):
    """The balanced scanner exists for this: a regex cannot find the end of a JSON string
    containing `"`."""
    ad = scraper._map_row(rows_of(LISTING)[QUOTED_ID], "https://www.vinted.cz")
    assert ad.name == 'Apple Macbook Pro 16" (2019)'


def test_relative_url_is_joined_to_the_base(scraper):
    """URLs are relative now, unlike the old API's absolute ones."""
    assert rows_of(LISTING)[PLAIN_ID]["productItem"]["url"].startswith("/items/")
    ad = scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.sk")
    assert ad.url == "https://www.vinted.sk/items/10018212520-macbook-pro-16"


def test_short_description_is_not_empty(scraper):
    """The regression that matters for filtering: the shipped scraper stored "", which
    silently disabled blocklist_keyword and required_keyword on every Vinted ad."""
    for external_id in (PLAIN_ID, PROMOTED_ID, FX_ID, QUOTED_ID):
        ad = scraper._map_row(rows_of(LISTING)[external_id], "https://www.vinted.cz")
        assert ad.short_description, f"row {external_id} produced no short_description"


def test_short_description_excludes_the_price(scraper):
    """Not accessibilityLabel: it embeds both prices, so it would change whenever the
    price does — and run_existing_query compares price_raw by string."""
    ad = scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.cz")
    assert "13000" not in ad.short_description
    assert "Kč" not in ad.short_description


def test_no_synthesised_date_or_view_count(scraper):
    """Neither exists anywhere in the payload; a fake value is worse than a null one
    because nothing downstream can tell it is fake."""
    ad = scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.cz")
    assert ad.publish_date is None
    assert ad.view_count is None


def test_free_price_is_not_exact(scraper):
    """"Zdarma" is not the same as "unknown" — see docs/research/PRICE_PARSING.md §3.3.
    Defensive: no zero-price row was observed live."""
    row = {"productItem": {"id": 1, "title": "Free", "url": "/items/1-free",
                           "price": {"amount": "0.00", "currencyCode": "CZK"}}}
    ad = scraper._map_row(row, "https://www.vinted.cz")
    assert ad.price == 0
    assert ad.price_type == PriceType.FREE


@pytest.mark.parametrize("row, reason", [
    ({}, "no productItem"),
    ({"productItem": {"title": "x", "url": "/items/1-x"}}, "no id"),
    ({"productItem": {"id": 1, "url": "/items/1-x"}}, "no title"),
    ({"productItem": {"id": 1, "title": "x"}}, "no url"),
    ({"productItem": {"id": 1, "title": "x", "url": "/items/1-x"}}, "no price"),
])
def test_unusable_rows_are_skipped_not_raised(scraper, row, reason):
    """Returning None keeps the generator alive; raising here would truncate the rest of
    the query's pass."""
    assert scraper._map_row(row, "https://www.vinted.cz") is None, reason


@pytest.mark.django_db
def test_big_external_id_survives_save(scraper):
    """Vinted ids exceed int4 (2,147,483,647) — BigIntegerField is load-bearing, and
    SQLite would not catch a regression here."""
    ad = scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.cz")
    ad.save()
    ad.refresh_from_db()
    assert ad.external_id == PLAIN_ID


# --------------------------------------------------------------------------- params

def test_order_is_always_newest_first(scraper, vinted_query):
    """Vinted's default sort is relevance, which silently breaks the dedup walk."""
    params = scraper._search_params(vinted_query, {})
    assert ("order", "newest_first") in params


def test_list_params_repeat(scraper, vinted_query):
    params = scraper._search_params(vinted_query, dict(vinted_query.extra_params))
    assert ("catalog[]", 3580) in params
    assert ("brand_ids[]", 54661) in params


def test_multiple_catalog_ids_each_become_a_pair(scraper, vinted_query):
    params = scraper._search_params(vinted_query, {"catalog_ids": [3580, 3581]})
    assert [v for k, v in params if k == "catalog[]"] == [3580, 3581]


def test_scalar_catalog_id_is_tolerated(scraper, vinted_query):
    """An operator typing `{"catalog_ids": 3580}` in the admin should not iterate an int."""
    params = scraper._search_params(vinted_query, {"catalog_ids": 3580})
    assert [v for k, v in params if k == "catalog[]"] == [3580]


def test_per_page_is_never_sent(scraper, vinted_query):
    """Retired with the v2 API; the page is server-fixed at 96."""
    assert "per_page" not in {k for k, _ in scraper._search_params(vinted_query, {})}


def test_price_bounds_omitted_when_zero(scraper, vinted_query):
    names = {k for k, _ in scraper._search_params(vinted_query, {})}
    assert "price_from" not in names and "price_to" not in names and "currency" not in names


def test_price_bounds_carry_a_currency(scraper, vinted_query):
    """Without `currency` the bounds are ignored."""
    vinted_query.price_lower, vinted_query.price_upper = 1000, 5000
    params = scraper._search_params(vinted_query, {})
    assert ("price_from", 1000) in params
    assert ("price_to", 5000) in params
    assert ("currency", "CZK") in params


def test_base_url_selects_the_domain_and_is_not_sent(scraper, vinted_query):
    """It picks which Vinted domain to read; sending it as a search param would be
    meaningless. Driven through run_query, since that is where it is popped."""
    vinted_query.extra_params = {"base_url": "https://www.vinted.sk", "catalog_ids": [3580]}

    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = LISTING
        ads = list(scraper.run_query(vinted_query))

    client_for.assert_called_with("https://www.vinted.sk")
    sent = client_for.return_value.get_flight.call_args[0][1]
    assert "base_url" not in {name for name, _ in sent}
    assert ("catalog[]", 3580) in sent
    assert ads[0].url.startswith("https://www.vinted.sk/")


def test_unknown_extra_params_pass_through(scraper, vinted_query):
    """So a new Vinted filter is usable from the admin before this module knows it."""
    params = scraper._search_params(vinted_query, {"color_ids[]": 7})
    assert ("color_ids[]", 7) in params


# --------------------------------------------------------------------------- paging

def test_stops_on_a_short_page(scraper, vinted_query):
    ads = run(scraper, vinted_query, [LISTING])
    assert len(ads) == 4          # fixture has 4 rows, i.e. < VINTED_PAGE_SIZE


def test_stops_when_a_page_has_no_rows(scraper, vinted_query):
    ads = run(scraper, vinted_query, ['1:{"items":{"items":[]}}'])
    assert ads == []


def test_empty_first_page_does_not_raise(scraper, vinted_query):
    """An unparseable payload is the only block signal there is — no status code, and
    "datadome" appears on healthy pages too. It must degrade to "no rows", not an
    exception."""
    assert run(scraper, vinted_query, ["garbage that is not a flight payload"]) == []


def test_mismatched_sort_logs_a_warning(scraper, vinted_query):
    """The canary for Vinted renaming a param. Asserted on the logger call: the `bazos`
    logger has propagate=False, so caplog never sees it."""
    payload = LISTING.replace('"sortBy":"newest_first"', '"sortBy":"relevance"')
    with patch("bazos.scraping.vinted.vinted_scraper.logger") as logger:
        run(scraper, vinted_query, [payload])
    warned = " ".join(str(c) for c in logger.warning.call_args_list)
    assert "sortBy" in warned


def test_matching_params_log_nothing(scraper, vinted_query):
    with patch("bazos.scraping.vinted.vinted_scraper.logger") as logger:
        run(scraper, vinted_query, [LISTING])
    assert logger.warning.call_args_list == []


# --------------------------------------------------------------------------- detail

def test_load_full_description_reads_json_ld(scraper):
    ad = _ad_for_detail(scraper)
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = DETAIL
        scraper.load_full_description(ad)
    assert ad.full_description.startswith("Prodám MacBook Pro 16”")


def test_load_full_description_captures_attributes(scraper):
    ad = _ad_for_detail(scraper)
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = DETAIL
        scraper.load_full_description(ad)

    assert ad.attributes["computer_ram"] == "16 GB"
    assert ad.attributes["computer_storage_capacity"] == "1 TB"
    assert ad.attributes["computer_cpu_line"] == "Intel Core Ultra 9"


def test_attributes_are_verbatim_strings(scraper):
    """Raw, never normalised on write — same split as price_raw/price."""
    ad = _ad_for_detail(scraper)
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = DETAIL
        scraper.load_full_description(ad)
    assert isinstance(ad.attributes["computer_ram"], str)
    assert ad.attributes["computer_ram"] != 16


def test_upload_date_stays_in_attributes(scraper):
    """It is relative display text; parsing it into publish_date would synthesise a date."""
    ad = _ad_for_detail(scraper)
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = DETAIL
        scraper.load_full_description(ad)
    assert "upload_date" in ad.attributes
    assert ad.publish_date is None


def test_load_full_description_never_overwrites_price(scraper):
    """JSON-LD `offers.price` is in the SELLER's currency — a .cz listing returned
    2500 PLN — so reading a price from here would be wrong and would look like a price
    change on the next pass."""
    ad = _ad_for_detail(scraper)
    before_price, before_raw = ad.price, ad.price_raw
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = DETAIL
        scraper.load_full_description(ad)
    assert (ad.price, ad.price_raw) == (before_price, before_raw)


def test_load_full_description_survives_a_failed_fetch(scraper):
    """Routine on a resale marketplace: the listing sold between the search and this call.
    QueryRunner calls this with no try/except and the guard around it catches only
    DatabaseError, so nothing may escape."""
    ad = _ad_for_detail(scraper)
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.side_effect = RuntimeError("404")
        assert scraper.load_full_description(ad) is ad
    assert ad.full_description is None


def test_load_full_description_tolerates_a_payload_without_a_description(scraper):
    ad = _ad_for_detail(scraper)
    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.return_value = '1:{"nothing":true}'
        scraper.load_full_description(ad)
    assert ad.full_description is None
    assert ad.attributes == {}


def test_run_query_completes_when_one_detail_fetch_raises(scraper, vinted_query):
    """The regression that matters: a single sold listing must not truncate the pass."""
    ads = run(scraper, vinted_query, [LISTING])
    assert len(ads) == 4

    with patch.object(VintedScraper, "_client_for") as client_for:
        client_for.return_value.get_flight.side_effect = RuntimeError("410 Gone")
        for ad in ads:
            assert scraper.load_full_description(ad) is ad


def test_check_blacklisted_is_false(scraper):
    assert scraper.check_blacklisted() is False


def _ad_for_detail(scraper):
    return scraper._map_row(rows_of(LISTING)[PLAIN_ID], "https://www.vinted.cz")
