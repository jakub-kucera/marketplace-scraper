"""Rung 2's gate: does this candidate actually describe the same product?

Runs over the **whole** suggestion list, never rank 0. Measured (`ZBOZI_API.md` §5):
top-1 was wrong or empty in 8 of 17 live archetypes, while the right answer usually sat
further down — the Samsung S10 at rank 3, a real MacBook at rank 6.

The gates are the measured failure modes, one each:

- brand, against the structured `vendorName` rather than free text;
- model tokens, **prefix-tolerant** for alphanumeric codes because `DHP484` must match
  `DHP484Z`, and **exact** for bare numbers because otherwise `13` matches `1300`;
- bundles, because `DeWalt DCD796` selected a two-tool kit containing that code;
- contrast tokens the phrase did not ask for (`Tab`, `mini`, `Pro`, …), because
  `Samsung Galaxy S10` returned a Galaxy *Tab* S10 FE;
- category, because the Dell XPS trap was a laptop bag at 262 Kc;
- and `shop_count`, which declines *differently*: one merchant is `no_market`, a fact
  about the product, not a mismatch.
"""
import unicodedata
from dataclasses import dataclass

from refprice.resolution.normalize import is_model_code

#: Words that distinguish product lines. Any of these on the candidate but not in the
#: phrase means the candidate is a different member of the family.
CONTRAST_TOKENS = frozenset({
    "mini", "pro", "max", "plus", "ultra", "lite", "fe", "air", "tab", "watch",
    "kids", "neo", "note", "duos", "xl", "se",
})

#: Czech and English bundle markers. A kit contains the member's model code, so it passes
#: every other gate.
BUNDLE_TOKENS = frozenset({"sada", "set", "kit", "sada!", "balicek", "bundle", "combo"})

#: Below this, a "price" is one merchant's asking price, not a market.
MIN_SHOPS = 2


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _tokens(text: str) -> list[str]:
    return [t for t in _fold(text).replace("/", " ").replace(",", " ").split() if t]


@dataclass(frozen=True)
class MatchSpec:
    brand: str | None
    model_tokens: frozenset[str]
    reject_tokens: frozenset[str]
    category_id: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.brand and not self.model_tokens


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str = ""
    confidence: float = 0.0
    #: True when the candidate *is* the product but has too few merchants to price.
    #: A different answer from "this is the wrong product", and callers must not merge them.
    no_market: bool = False


def spec_from_phrase(phrase: str, category_id: int | None = None) -> MatchSpec:
    tokens = _tokens(phrase)
    if not tokens:
        return MatchSpec(brand=None, model_tokens=frozenset(), reject_tokens=frozenset(),
                         category_id=category_id)
    brand, rest = tokens[0], tokens[1:]

    # When the title carries a real model code, that code *is* the identity and everything
    # else in the title is the seller's prose. Without one ("Apple iPhone 13"), every
    # remaining token has to carry weight or `iPad 13` would match.
    strong = {t for t in rest if is_model_code(t)}
    required = strong or set(rest)

    return MatchSpec(
        brand=brand,
        model_tokens=frozenset(required),
        # Only contrast words the phrase did *not* ask for. Asking for "iPhone 13 Pro"
        # must not reject a Pro.
        reject_tokens=frozenset(CONTRAST_TOKENS - set(tokens)),
        category_id=category_id,
    )


#: A prefix match needs this many characters on both sides to mean anything. Measured
#: live 2026-09-16: without a floor, `K5` matched the `K` of "Kärcher **K** 4 Compact"
#: and baselined a K5 pressure washer against a K4.
MIN_PREFIX = 3


def _token_matches(required: str, candidate_tokens: list[str]) -> tuple[bool, bool]:
    """(matched, exactly). Prefix tolerance applies to model codes, not to bare numbers."""
    if required in candidate_tokens:
        return True, True
    if required.isdigit():
        # `13` must not match `1300`.
        return False, False
    for token in candidate_tokens:
        # The useful direction is the candidate *extending* what was asked for
        # (`DHP484` -> `DHP484Z`). The reverse is allowed too, but both need real length.
        if len(required) >= MIN_PREFIX and token.startswith(required):
            return True, False
        if len(token) >= MIN_PREFIX and required.startswith(token):
            return True, False
    return False, False


def validate(facts, spec: MatchSpec) -> Verdict:
    if spec.is_empty:
        return Verdict(False, "no usable search phrase")

    candidate_tokens = _tokens(facts.name)
    brand_tokens = _tokens(facts.brand or "")

    if spec.brand and spec.brand not in brand_tokens and spec.brand not in candidate_tokens:
        return Verdict(False, f"brand mismatch: wanted {spec.brand!r}, got {facts.brand!r}")

    bundle_hit = BUNDLE_TOKENS & set(candidate_tokens)
    if bundle_hit or "+" in (facts.name or ""):
        return Verdict(False, f"bundle/kit, not the item: {facts.name!r}")

    contrast_hit = spec.reject_tokens & set(candidate_tokens)
    if contrast_hit:
        return Verdict(False, f"different product line: {sorted(contrast_hit)}")

    exact_hits = 0
    for required in spec.model_tokens:
        matched, exactly = _token_matches(required, candidate_tokens)
        if not matched:
            return Verdict(False, f"missing model token {required!r} in {facts.name!r}")
        exact_hits += exactly

    if spec.category_id is not None and facts.category_id is not None:
        if facts.category_id != spec.category_id:
            return Verdict(
                False,
                f"category mismatch: wanted {spec.category_id}, got {facts.category_id}",
            )

    if facts.shop_count < MIN_SHOPS:
        # The product is right; the price is not a market price. Declining here with a
        # distinct flag is what lets a caller say "this is old" rather than "no idea".
        return Verdict(False, f"only {facts.shop_count} merchant(s)", no_market=True)

    total = len(spec.model_tokens) or 1
    # Exact model-code agreement is worth more than prefix agreement, and a thicker
    # market is worth more than a thin one — both cap out well below certainty.
    confidence = 0.55 + 0.35 * (exact_hits / total) + min(facts.shop_count, 20) / 20 * 0.10
    return Verdict(True, "", confidence=round(min(confidence, 0.99), 3))
