"""Candidate validation — the gate that turns a suggestion list into a match.

These tests are the measured failure archetypes from `ZBOZI_API.md` §5, and they are the
spec rather than an illustration of it. Top-1 was wrong or empty in **8 of 17** live
archetypes, while the correct answer usually sat somewhere in the list (Samsung S10 at
rank 3, a real MacBook at rank 6). So the validator runs over the whole list and its job
is as much rejecting confidently as accepting.
"""
import json
import pathlib

from refprice.providers.base import RefProductFacts
from refprice.resolution.validate import MatchSpec, spec_from_phrase, validate

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def facts_from(fixture_name: str) -> RefProductFacts:
    raw = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))["product"]
    return RefProductFacts(
        provider="zbozi", product_id=str(raw["id"]), slug=raw["normalizedName"],
        name=raw["displayName"], brand=raw.get("vendorName"),
        category_id=raw.get("categoryId"), product_no=raw.get("productNo") or None,
        min_czk=round(raw["minPrice"] / 100) if raw.get("minPrice") else None,
        median_czk=round(raw["medianPrice"] / 100) if raw.get("medianPrice") else None,
        max_czk=round(raw["maxPrice"] / 100) if raw.get("maxPrice") else None,
        shop_count=raw.get("shopCount", 0), availability=raw.get("availability", ""),
        release_date=None,
    )


def make(name, *, brand=None, shops=5, category=None, product_no=None):
    return RefProductFacts(
        provider="zbozi", product_id="1", slug="s", name=name, brand=brand,
        category_id=category, product_no=product_no, min_czk=100, median_czk=200,
        max_czk=300, shop_count=shops, availability="in_stock", release_date=None,
    )


# ---------------------------------------------------------------------------
# spec derivation
# ---------------------------------------------------------------------------

def test_the_first_token_becomes_the_brand():
    assert spec_from_phrase("Makita DHP484").brand == "makita"


def test_model_tokens_are_everything_after_the_brand():
    assert "dhp484" in spec_from_phrase("Makita DHP484").model_tokens


def test_a_model_code_makes_the_sellers_prose_optional():
    """A Czech ad title carries category words the catalogue name does not —
    "Makita DHP484Z **aku vrtacka** 18V" vs "Makita DHP484Z Li-ion 18 V". Requiring
    every token rejected the correct product outright."""
    spec = spec_from_phrase("Makita DHP484Z aku vrtacka 18V")
    assert "dhp484z" in spec.model_tokens
    assert "aku" not in spec.model_tokens
    assert "vrtacka" not in spec.model_tokens


def test_the_prose_words_really_are_tolerated_end_to_end():
    spec = spec_from_phrase("Makita DHP484Z aku vrtacka 18V")
    assert validate(facts_from("product_makita.json"), spec).accepted is True


def test_without_a_model_code_every_token_is_required():
    """`Apple iPhone 13` has no alphanumeric code, so `iphone` has to carry weight —
    otherwise an `iPad 13` would match on the number alone."""
    spec = spec_from_phrase("Apple iPhone 13")
    assert spec.model_tokens == {"iphone", "13"}
    assert validate(make("Apple iPad 13", brand="Apple"), spec).accepted is False


def test_contrast_tokens_the_phrase_did_not_ask_for_are_rejected():
    """`Samsung Galaxy S10` must not accept a `Tab`; `Apple iPhone 13` must not accept
    a `Pro`. Both were measured as live top-1 results."""
    spec = spec_from_phrase("Samsung Galaxy S10")
    assert "tab" in spec.reject_tokens
    assert "pro" in spec.reject_tokens


def test_a_contrast_token_the_phrase_asked_for_is_not_rejected():
    spec = spec_from_phrase("Apple iPhone 13 Pro")
    assert "pro" not in spec.reject_tokens


# ---------------------------------------------------------------------------
# the measured traps
# ---------------------------------------------------------------------------

def test_rejects_the_tablet_that_top_1_returns_for_galaxy_s10():
    spec = spec_from_phrase("Samsung Galaxy S10")
    verdict = validate(facts_from("product_galaxy_tab_s10_fe.json"), spec)
    assert verdict.accepted is False
    assert "tab" in verdict.reason.lower()


def test_accepts_the_real_galaxy_s10_but_for_its_thin_market():
    """The correct product exists at rank 3 — and has one merchant, so the honest answer
    is `no_market`, not a price. Two different reasons to decline, and they mean
    different things to a caller."""
    spec = spec_from_phrase("Samsung Galaxy S10")
    verdict = validate(facts_from("product_galaxy_s10.json"), spec)
    assert verdict.accepted is False
    assert verdict.no_market is True


def test_rejects_the_dewalt_two_tool_kit():
    """Measured: `DeWalt DCD796` selected `DCK266P2T sada aku DCD796 + DCF887` at
    7 785 Kc — a bundle that contains the model code, not the drill."""
    spec = spec_from_phrase("DeWalt DCD796")
    verdict = validate(facts_from("product_dewalt_kit.json"), spec)
    assert verdict.accepted is False
    assert "bundle" in verdict.reason.lower()


def test_accepts_the_dewalt_drill_itself():
    spec = spec_from_phrase("DeWalt DCD796")
    assert validate(facts_from("product_dewalt_drill.json"), spec).accepted is True


def test_accepts_the_makita_despite_the_trailing_z():
    """`DHP484` must match `DHP484Z`. Exact token equality rejected the correct product —
    the second of the two defects the live rule-only pass turned up."""
    spec = spec_from_phrase("Makita DHP484")
    assert validate(facts_from("product_makita.json"), spec).accepted is True


def test_accepts_the_iphone_13():
    spec = spec_from_phrase("Apple iPhone 13")
    assert validate(facts_from("product_iphone13.json"), spec).accepted is True


# ---------------------------------------------------------------------------
# individual gates
# ---------------------------------------------------------------------------

def test_a_different_brand_is_rejected():
    spec = spec_from_phrase("Makita DHP484")
    verdict = validate(make("Bosch DHP484", brand="Bosch"), spec)
    assert verdict.accepted is False
    assert "brand" in verdict.reason.lower()


def test_a_missing_model_token_is_rejected():
    spec = spec_from_phrase("Makita DHP484")
    assert validate(make("Makita DDF482", brand="Makita"), spec).accepted is False


def test_a_short_model_name_does_not_prefix_match_a_longer_family():
    """Found live 2026-09-16: `Karcher K5` matched "Kärcher **K** 4 Compact" because `K5`
    starts with `K`, and baselined a K5 against a K4. A prefix match needs real length."""
    spec = spec_from_phrase("Karcher K5")
    verdict = validate(make("Kärcher K 4 Compact vysokotlaky cistic", brand="Kärcher"), spec)
    assert verdict.accepted is False


def test_the_matching_k5_is_still_accepted():
    spec = spec_from_phrase("Karcher K5")
    assert validate(make("Kärcher K5 1.180.580.0", brand="Kärcher"), spec).accepted is True


def test_a_numeric_token_must_match_exactly_not_by_prefix():
    """Prefix tolerance exists for alphanumeric model codes. Applying it to bare numbers
    would let `13` match `1300`, which is how a phone becomes a washing machine."""
    spec = spec_from_phrase("Apple iPhone 13")
    assert validate(make("Apple iPhone 1300", brand="Apple"), spec).accepted is False


def test_one_shop_is_reported_as_no_market_not_as_a_mismatch():
    spec = spec_from_phrase("Makita DHP484")
    verdict = validate(make("Makita DHP484Z", brand="Makita", shops=1), spec)
    assert verdict.accepted is False
    assert verdict.no_market is True


def test_two_shops_is_enough():
    spec = spec_from_phrase("Makita DHP484")
    assert validate(make("Makita DHP484Z", brand="Makita", shops=2), spec).accepted is True


def test_a_category_hint_rejects_an_accessory():
    """The Dell XPS trap: rank 0 was a laptop *bag* at 262 Kc."""
    spec = MatchSpec(brand="dell", model_tokens=frozenset({"xps", "9310"}),
                     reject_tokens=frozenset(), category_id=111)
    verdict = validate(make("DELL XPS 13 9310", brand="Dell", category=999), spec)
    assert verdict.accepted is False
    assert "category" in verdict.reason.lower()


def test_no_category_hint_means_the_category_gate_is_skipped():
    spec = MatchSpec(brand="dell", model_tokens=frozenset({"xps"}),
                     reject_tokens=frozenset(), category_id=None)
    assert validate(make("DELL XPS 13", brand="Dell", category=999), spec).accepted is True


def test_an_accepted_verdict_carries_a_confidence():
    spec = spec_from_phrase("Makita DHP484")
    verdict = validate(facts_from("product_makita.json"), spec)
    assert 0.0 < verdict.confidence <= 1.0


def test_an_exact_model_code_scores_above_a_prefix_match():
    spec = spec_from_phrase("Makita DHP484Z")
    exact = validate(make("Makita DHP484Z", brand="Makita"), spec).confidence
    spec_loose = spec_from_phrase("Makita DHP484")
    loose = validate(make("Makita DHP484Z", brand="Makita"), spec_loose).confidence
    assert exact > loose


def test_an_empty_spec_accepts_nothing():
    """A phrase that normalised to nothing must not match the entire catalogue."""
    spec = spec_from_phrase("")
    assert validate(make("Anything At All", brand="Any"), spec).accepted is False
