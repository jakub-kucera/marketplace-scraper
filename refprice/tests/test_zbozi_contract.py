"""Live contract check against the real Zboží API. Deselected by default (`-m live`).

This exists because `refprice` is built on an **unsupported private API** — the website's
own XHR surface, recovered from its JS bundles. The offline tests prove we still parse the
responses recorded on 2026-09-16; only this file proves the site still sends them. Partial
drift — one field quietly disappearing — is exactly what would otherwise surface as a
silently wrong baseline rather than as a failure.

Same reasoning and the same weekly cadence as `contract-check.yml`'s Bazos job.

Run:  pytest -m live refprice/tests/test_zbozi_contract.py
"""
import datetime as dt

import pytest

from refprice.providers.zbozi import ZboziProvider

pytestmark = pytest.mark.live

#: A current-production cordless drill: the best-covered category, in production for
#: years, so it is the least likely fixture to age out from under this test.
PHRASE = "Makita DHP484"
EXPECTED_SLUG_PREFIX = "makita-dhp484"


@pytest.fixture(scope="module")
def provider():
    return ZboziProvider()


@pytest.fixture(scope="module")
def candidates(provider):
    found = provider.suggest(PHRASE)
    if not found:
        pytest.fail(f"suggestV2 returned nothing for {PHRASE!r} — the endpoint or its "
                    f"response shape has changed (see docs/research/marketplaces/ZBOZI_API.md §3a)")
    return found


@pytest.fixture(scope="module")
def facts(provider, candidates):
    slug = next((c.slug for c in candidates if c.slug.startswith(EXPECTED_SLUG_PREFIX)),
                candidates[0].slug)
    found = provider.fetch(slug)
    if found is None:
        pytest.fail(f"/api/v3/product/{slug}/ returned nothing — endpoint or filterFields changed")
    return found


def test_suggest_still_returns_slugs(candidates):
    assert all(c.slug for c in candidates)


def test_product_still_carries_a_median_price(facts):
    """`medianPrice` is the field this project baselines on. Losing it is not survivable
    by falling back to `min` — min is the mis-paired one (ZBOZI_API.md §6)."""
    assert facts.median_czk is not None


def test_prices_are_still_in_hundredths(facts):
    """If Zbozi ever switched to whole CZK, every number would silently drop 100x.
    A drill priced under 100 Kc is the tell."""
    assert 1_000 < facts.median_czk < 50_000


def test_product_still_carries_shop_count(facts):
    """`shop_count` is what separates `matched` from `no_market`."""
    assert facts.shop_count >= 1


def test_product_still_carries_a_brand(facts):
    """Structured brand is the cheapest validation gate; free-text would not do."""
    assert facts.brand


def test_price_history_still_works(provider, facts):
    points = provider.history(facts.product_id, months_back=13)
    assert len(points) > 10, "price trend endpoint returned little or nothing"


def test_price_history_is_recent_and_ordered(provider, facts):
    points = provider.history(facts.product_id, months_back=13)
    assert points == sorted(points, key=lambda p: p.date)
    newest = points[-1].date
    assert newest > dt.date.today() - dt.timedelta(days=45), (
        f"newest price point is {newest} — the series has gone stale"
    )


def test_price_history_is_still_in_halere(provider, facts):
    points = [p for p in provider.history(facts.product_id, months_back=13) if p.median_czk]
    assert all(500 < p.median_czk < 50_000 for p in points)


def test_an_unknown_slug_is_still_a_clean_miss(provider):
    """It answers `status: 404` inside a 200 body; a change here would turn every miss
    into an exception mid-resolution."""
    assert provider.fetch("definitely-not-a-product-xyz-zzz") is None
