"""The Zboží provider, against responses recorded from the live API on 2026-09-16.

Endpoint shapes and the reasoning behind each field are in
`docs/research/marketplaces/ZBOZI_API.md`. Nothing here touches the network; the live
contract test that guards drift is `test_zbozi_contract.py`.

The single most important assertion in this file is the unit conversion. Zboží reports
**hundredths of CZK** under two different spellings — `medianPrice` on a product and
`medianPriceHa` on a trend — and `parse_price` in `bazos/filters.py` strips non-digits,
so an unconverted value lands in the database 100x too large.
"""
import datetime as dt
import json
import pathlib
from unittest.mock import MagicMock

import pytest
import requests

from refprice.providers.base import Candidate, NotPermitted, PricePoint, RefProductFacts
from refprice.providers.zbozi import ZboziProvider

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def stub(provider, payload, status=200):
    """Point the provider's session at a canned payload."""
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = payload
    provider.session = MagicMock(spec=requests.Session)
    provider.session.get.return_value = response
    provider.session.post.return_value = response
    return provider.session


@pytest.fixture()
def provider():
    return ZboziProvider()


# ---------------------------------------------------------------------------
# suggest
# ---------------------------------------------------------------------------

def test_suggest_returns_candidates(provider):
    stub(provider, fixture("suggest_makita.json"))
    candidates = provider.suggest("Makita DHP484")
    assert candidates
    assert all(isinstance(c, Candidate) for c in candidates)


def test_suggest_reads_the_slug_the_product_endpoint_takes(provider):
    stub(provider, fixture("suggest_makita.json"))
    assert provider.suggest("Makita DHP484")[0].slug == "makita-dhp484z-li-ion-18-v"


def test_suggest_keeps_the_display_name(provider):
    stub(provider, fixture("suggest_makita.json"))
    assert provider.suggest("Makita DHP484")[0].name == "Makita DHP484Z Li-ion 18 V"


def test_suggest_deduplicates_repeated_slugs(provider):
    """Variants collapse to one slug — `apple-iphone-13` appears many times over."""
    stub(provider, fixture("suggest_iphone13.json"))
    slugs = [c.slug for c in provider.suggest("Apple iPhone 13")]
    assert len(slugs) == len(set(slugs))


def test_suggest_returns_empty_when_nothing_matches(provider):
    """Measured: spec noise empties the result. That is a normal answer, not an error."""
    stub(provider, fixture("suggest_empty.json"))
    assert provider.suggest("Lenovo ThinkPad T480") == []


def test_suggest_uses_the_phrase_parameter_not_q(provider):
    """`?q=` is the robots-disallowed spelling; `?phrase=` is not (ZBOZI_API.md §4)."""
    session = stub(provider, fixture("suggest_makita.json"))
    provider.suggest("Makita DHP484")
    url = session.get.call_args.args[0]
    assert "phrase=" in url
    assert "?q=" not in url


def test_suggest_has_no_trailing_slash_before_the_query(provider):
    """Measured: `/suggestV2/?phrase=` is a 404, `/suggestV2?phrase=` is a 200."""
    session = stub(provider, fixture("suggest_makita.json"))
    provider.suggest("x")
    assert "/suggestV2?" in session.get.call_args.args[0]


def test_suggest_declines_gracefully_on_a_transport_error(provider):
    provider.session = MagicMock(spec=requests.Session)
    provider.session.get.side_effect = requests.ConnectionError("no route")
    assert provider.suggest("anything") == []


# ---------------------------------------------------------------------------
# fetch — and the x100 trap
# ---------------------------------------------------------------------------

def test_fetch_returns_facts(provider):
    stub(provider, fixture("product_makita.json"))
    assert isinstance(provider.fetch("makita-dhp484z-li-ion-18-v"), RefProductFacts)


def test_fetch_converts_hundredths_to_whole_czk(provider):
    """`medianPrice: 381300` is 3 813 Kc. This is the assertion that matters most here.

    Derived from the fixture rather than hardcoded: these are live prices and they move,
    so a literal would rot the moment the fixtures are refreshed — and it would rot into
    a *failing* test about the wrong thing, hiding the conversion it exists to guard.
    """
    raw = fixture("product_makita.json")["product"]
    stub(provider, fixture("product_makita.json"))
    facts = provider.fetch("makita-dhp484z-li-ion-18-v")
    assert facts.median_czk == round(raw["medianPrice"] / 100)
    assert facts.min_czk == round(raw["minPrice"] / 100)
    assert facts.max_czk == round(raw["maxPrice"] / 100)
    # and the absolute sanity check the ratio alone would not give: a cordless drill
    # costs thousands, not hundreds of thousands.
    assert 1_000 < facts.median_czk < 20_000


def test_fetch_reads_identity_fields(provider):
    stub(provider, fixture("product_makita.json"))
    facts = provider.fetch("makita-dhp484z-li-ion-18-v")
    assert facts.product_id == "5325309"
    assert facts.name == "Makita DHP484Z Li-ion 18 V"
    assert facts.brand == "Makita"
    assert facts.category_id == 2543
    assert facts.provider == "zbozi"


def test_fetch_reads_the_manufacturer_part_number(provider):
    """`productNo` is the identifier HEUREKA_ZBOZI.md concluded did not exist."""
    stub(provider, fixture("product_galaxy_s10.json"))
    assert provider.fetch("samsung-galaxy-s10-g973f").product_no == "SM-G973FZWDXEZ"


def test_fetch_leaves_product_no_none_when_absent(provider):
    stub(provider, fixture("product_makita.json"))
    assert provider.fetch("makita-dhp484z-li-ion-18-v").product_no is None


def test_fetch_reads_shop_count(provider):
    stub(provider, fixture("product_makita.json"))
    assert provider.fetch("makita-dhp484z-li-ion-18-v").shop_count == 41


def test_fetch_surfaces_a_thin_market(provider):
    """A discontinued phone keeps its catalogue entry and one stale offer."""
    stub(provider, fixture("product_galaxy_s10.json"))
    assert provider.fetch("samsung-galaxy-s10-g973f").shop_count == 1


def test_fetch_parses_the_release_date(provider):
    stub(provider, fixture("product_makita.json"))
    facts = provider.fetch("makita-dhp484z-li-ion-18-v")
    assert isinstance(facts.release_date, dt.date)


def test_fetch_returns_none_for_an_unknown_slug(provider):
    """A 200 body carrying `status: 404` — the API does not use the HTTP code alone."""
    stub(provider, fixture("product_404.json"))
    assert provider.fetch("definitely-not-a-product-xyz") is None


def test_fetch_returns_none_on_a_transport_error(provider):
    provider.session = MagicMock(spec=requests.Session)
    provider.session.get.side_effect = requests.Timeout("slow")
    assert provider.fetch("anything") is None


def test_fetch_trims_the_payload_with_filterfields(provider):
    """29 KB to 261 B. The difference between cheap to run and not."""
    session = stub(provider, fixture("product_makita.json"))
    provider.fetch("makita-dhp484z-li-ion-18-v")
    assert "filterFields=" in session.get.call_args.args[0]


def test_fetch_uses_the_robots_allowed_api_path(provider):
    session = stub(provider, fixture("product_makita.json"))
    provider.fetch("x")
    assert "/api/v3/product/" in session.get.call_args.args[0]


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

def test_history_returns_price_points(provider):
    stub(provider, fixture("pricetrend_makita.json"))
    points = provider.history("5325309", months_back=13)
    assert points and all(isinstance(p, PricePoint) for p in points)


def test_history_converts_halere_to_whole_czk(provider):
    raw = {p["date"]: p for p in fixture("pricetrend_makita.json")["pricePoints"]}
    points = provider.history("5325309", months_back=13) if stub(
        provider, fixture("pricetrend_makita.json")) else []
    for point in points:
        source = raw[int(dt.datetime.combine(point.date, dt.time(), dt.UTC).timestamp())]
        assert point.min_czk == round(source["minPriceHa"] / 100)


def test_history_medians_stay_in_a_plausible_band(provider):
    """A cordless drill trades in the low thousands; ~300 000 would be unconverted."""
    stub(provider, fixture("pricetrend_makita.json"))
    medians = [p.median_czk for p in provider.history("5325309", months_back=13) if p.median_czk]
    assert all(1_000 < m < 20_000 for m in medians)


def test_history_preserves_the_mis_paired_minimum_rather_than_hiding_it(provider):
    """The Makita series contains a ~484 Kc `min` — a mis-paired accessory offer, and the
    concrete reason this project baselines on `median`. The provider must not quietly
    filter it: that is the consumer's judgement to make, with the evidence in front of it."""
    stub(provider, fixture("pricetrend_makita.json"))
    mins = [p.min_czk for p in provider.history("5325309", months_back=13) if p.min_czk]
    assert min(mins) < 1_000
    medians = [p.median_czk for p in provider.history("5325309", months_back=13) if p.median_czk]
    assert min(medians) > 1_000


def test_history_is_sorted_oldest_first(provider):
    stub(provider, fixture("pricetrend_iphone13.json"))
    dates = [p.date for p in provider.history("6712579", months_back=13)]
    assert dates == sorted(dates)


def test_history_dates_are_dates(provider):
    stub(provider, fixture("pricetrend_makita.json"))
    assert isinstance(provider.history("5325309", months_back=13)[0].date, dt.date)


def test_history_posts_only_months_back(provider):
    """The price hints the browser sends are client-side only — the series is identical
    without them, so sending a min/median/max we may not have is pointless."""
    session = stub(provider, fixture("pricetrend_makita.json"))
    provider.history("5325309", months_back=13)
    assert session.post.call_args.kwargs["json"] == {"monthsBack": 13}


def test_history_returns_empty_on_a_transport_error(provider):
    provider.session = MagicMock(spec=requests.Session)
    provider.session.post.side_effect = requests.ConnectionError("down")
    assert provider.history("5325309", months_back=13) == []


def test_history_captures_the_real_depreciation(provider):
    """The iPhone 13 median fell ~38% over 13 months. If the series parses, this holds."""
    stub(provider, fixture("pricetrend_iphone13.json"))
    points = [p for p in provider.history("6712579", months_back=13) if p.median_czk]
    assert points[-1].median_czk < points[0].median_czk * 0.8


# ---------------------------------------------------------------------------
# search — separated from suggest because its compliance posture differs
# ---------------------------------------------------------------------------

def test_search_is_refused_by_default(provider):
    """`?q=` is robots-disallowed. Reaching it must be a deliberate, per-call decision."""
    with pytest.raises(NotPermitted):
        provider.search("Bosch GSB 18-2-LI")


def test_search_is_allowed_when_explicitly_opted_in(provider):
    stub(provider, {"pageProps": {"data": {"productsResults": {"products": []}}}})
    assert provider.search("Bosch GSB 18-2-LI", allow_disallowed=True) == []


# ---------------------------------------------------------------------------
# transport posture
# ---------------------------------------------------------------------------

def test_it_builds_its_own_unproxied_session(provider):
    """Zbozi does not block, and CZ sites 403 Tor exits widely. Same call VintedScraper
    makes when it ignores the session it is handed."""
    assert isinstance(provider.session, requests.Session)
    assert not provider.session.proxies


def test_every_request_carries_a_timeout(provider):
    session = stub(provider, fixture("product_makita.json"))
    provider.fetch("x")
    assert session.get.call_args.kwargs["timeout"]


def test_it_satisfies_the_reference_provider_protocol(provider):
    from refprice.providers.base import ReferenceProvider
    assert isinstance(provider, ReferenceProvider)


def test_it_is_registered():
    from refprice.providers.base import PROVIDER_REGISTRY
    assert PROVIDER_REGISTRY["zbozi"] is ZboziProvider
