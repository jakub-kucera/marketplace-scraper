"""Live contract check for Vinted — the mechanism that would have caught the outage.

`/api/v2/catalog/items` was withdrawn around 2026-09-08 and every Vinted query failed for
eight days without anything noticing: the runner's per-query guard contained the error,
and the zero-rows canary counts rows across *all* queries in a pass, so Bazos returning
rows masked Vinted returning none.

Cassette-based tests only prove the parser handles the payload recorded the day it was
made. These re-parse the live site, so partial drift — a renamed field, a changed sort
param — surfaces here rather than in production.

Run by .github/workflows/contract-check.yml (weekly, self-hosted runner), deselected
everywhere else (`addopts = -m "not live"` in pytest.ini):

    pytest -m live                      # just these
    pytest -m "live or not live"        # everything

⚠️ These must not touch the database — that job runs with TEST_DB=sqlite in a container
with no Postgres — so every assertion here works on unsaved `Ad` objects.

⚠️ Vantage point is UNTESTED for Vinted. The Bazos contract tests next door need the
self-hosted Pi runner because Bazos refuses GitHub-hosted IPs; whether Vinted does the
same was never measured — the 2026-09-16 probe ran from a residential Czech connection
only. They share that runner anyway, so this is a note for whoever moves them, not a
current problem.
"""
import pytest

from bazos.models import Marketplace, Query
from bazos.scraping.vinted import flight
from bazos.scraping.vinted.client import VintedClient
from bazos.scraping.vinted.vinted_scraper import CATALOG_PATH, VintedScraper

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def payload():
    """One real catalog page: laptops, Apple, newest first."""
    client = VintedClient()
    scraper = VintedScraper()
    query = Query(text="", marketplace=Marketplace.VINTED, price_lower=0, price_upper=0)
    params = scraper._search_params(query, {"catalog_ids": [3580], "brand_ids": [54661]})
    return flight.decode(client.get_flight(CATALOG_PATH, params + [("page", 1)]))


def test_catalog_page_still_yields_rows(payload):
    """The check that fails first if the transport changes again."""
    assert flight.items(payload), "Vinted returned no parseable rows"


def test_rows_still_map_to_ads(payload):
    scraper = VintedScraper()
    ads = [scraper._map_row(row, "https://www.vinted.cz") for row in flight.items(payload)]
    mapped = [ad for ad in ads if ad is not None]

    assert len(mapped) >= len(ads) * 0.9, "more than 10% of live rows failed to map"
    for ad in mapped:
        assert ad.external_id and ad.name and ad.url.startswith("https://")
        assert ad.price is not None and ad.price_raw
        assert ad.short_description, "itemBox stopped providing a short description"


def test_sort_param_is_still_honoured(payload):
    """`order=newest_first` is what the dedup walk rests on. If Vinted renames it the
    page silently falls back to relevance sort."""
    state = flight.get(payload, "initialCatalogState") or {}
    assert state.get("filters", {}).get("sortBy") == "newest_first"


def test_catalog_filter_is_still_honoured(payload):
    state = flight.get(payload, "initialCatalogState") or {}
    assert 3580 in (state.get("filters", {}).get("catalogIds") or [])


def test_price_is_still_a_decimal_string(payload):
    """If this ever becomes a float, the Decimal path needs re-checking."""
    item = flight.items(payload)[0]["productItem"]
    assert isinstance(item["price"]["amount"], str)
    assert item["price"]["currencyCode"]


def test_catalog_tree_is_still_seedable(payload):
    """Guards `manage.py create_vinted_catalogs`: the tree ships on every catalog page."""
    from bazos.management.commands.create_vinted_catalogs import collect

    nodes = collect(payload)
    assert len(nodes) > 1000, f"only {len(nodes)} catalog nodes found"
    assert 3580 in nodes and nodes[3580][2] is not None, "laptops lost its parent"
