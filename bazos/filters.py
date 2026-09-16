"""Filter rule engine for the ad pipeline.

Rules are applied per-delivery in the ``run_filter`` management command.
A rule returns one of three outcomes:

- ``FilterResult.APPROVE`` — the ad should be sent
- ``FilterResult.REJECT``  — the ad should be dropped (with an optional reason)
- ``FilterResult.PASS``    — this rule has no opinion; let the next rule decide

The ``RuleEngine`` applies rules in order. The first non-PASS result wins.
If every rule returns PASS, the ad is approved by default.

Stage 9 rules below are combined into the ``RuleEngine`` used by ``run_filter``.
"""
import logging
import re
from enum import Enum
from typing import Protocol

from django.conf import settings

from bazos.const import (
    PRICE_MODEL_MIN_DISCOUNT_PCT,
    PRICE_MODEL_SHADOW_MODE,
    PRICE_MODEL_Z_THRESHOLD,
)
from bazos.geo import distance_between_codes, normalize_postal_code, parse_postal_code
from bazos.models import AdDelivery, AdStatus, PriceType, Query

logger = logging.getLogger(__name__)


class FilterResult(Enum):
    APPROVE = "approve"
    REJECT  = "reject"
    PASS    = "pass"   # neutral — let the next rule decide


class FilterRule(Protocol):
    """Structural protocol every filter rule must satisfy."""
    name: str

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        """Return (result, reason). reason is None unless result is REJECT."""
        ...


class PassthroughRule:
    """Approves everything. Useful as a no-op RuleEngine baseline (e.g. in tests)."""
    name = "passthrough"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        return FilterResult.APPROVE, None


#: Bazos's four placeholder strings with no numeric value at all — "Zdarma" is a fifth
#: placeholder-shaped string but is handled separately below, since unlike these four it
#: resolves to a real price of 0, not None. Exhaustive against the measured corpus — see
#: docs/research/PRICE_PARSING.md §3.1. Only the string keys are Bazos-specific;
#: this is shared by both BazosScraper (HTML) and BazosApiScraper's listing parse, since the
#: API's `price_formatted` follows the same grammar (§4).
_PLACEHOLDER_TYPES: dict[str, PriceType] = {
    "Dohodou": PriceType.NEGOTIABLE,
    "V textu": PriceType.IN_TEXT,
    "Nabídněte": PriceType.MAKE_OFFER,
    "Nerozhoduje": PriceType.INDIFFERENT,
}


def parse_price_and_type(price_raw: str) -> tuple[int | None, PriceType]:
    """Parse a Bazos price string (e.g. "1 000 Kč", "Dohodou") into (amount, price_type).

    Rules, each traceable to a measurement in PRICE_PARSING.md §3:
    - "Zdarma" (free) -> (0, FREE) — a known price of zero, not an unknown one.
    - The other four placeholders -> (None, matching type).
    - Digits present -> strip everything but digits, parse as int, EXACT.
    - Anything else -> (None, UNKNOWN), logged: an unrecognised value means Bazos changed
      its price vocabulary and this parser no longer describes it.
    """
    stripped = price_raw.strip()
    if stripped == "Zdarma":
        return 0, PriceType.FREE
    if stripped in _PLACEHOLDER_TYPES:
        return None, _PLACEHOLDER_TYPES[stripped]
    digits = re.sub(r"\D", "", stripped)
    if digits:
        return int(digits), PriceType.EXACT
    logger.warning("Unrecognised Bazos price string: %r", price_raw)
    return None, PriceType.UNKNOWN


def parse_price(price_raw: str) -> int | None:
    """Parse a Bazos price string (e.g. "1 000 Kč") into an int amount.

    Returns None if the string has no digits (e.g. "Dohodou", "V textu"), and 0 for
    "Zdarma" (free is a known zero price, not an unknown one). Thin wrapper over
    parse_price_and_type, kept for callers that only need the amount.
    """
    amount, _ = parse_price_and_type(price_raw)
    return amount


class PriceRangeRule:
    """Rejects ads priced outside the query's price_lower/price_upper range.

    PASSes when the query has no range set (0-0, the "no filter" convention —
    see PROMPTS.md P7) or when `ad.price is None` — an unparseable/placeholder price
    (Dohodou, V textu, ...), or a marketplace scraper that hasn't been wired to populate
    it yet. Note FREE is NOT covered by that PASS: it carries a real `price=0`, so a free
    ad IS evaluated against the range (and rejected whenever price_lower > 0) — that's the
    intended behaviour (PRICE_PARSING.md §3.3), not an oversight.
    """
    name = "price_range"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        query = delivery.query
        if query.price_lower == 0 and query.price_upper == 0:
            return FilterResult.PASS, None
        price = delivery.ad.price
        if price is None:
            return FilterResult.PASS, None
        if price < query.price_lower or price > query.price_upper:
            return FilterResult.REJECT, f"price {price} outside range {query.price_lower}-{query.price_upper}"
        return FilterResult.PASS, None


class BlocklistKeywordRule:
    """Rejects ads whose name/short_description contains a blocklisted phrase.

    PASSes when the query's filter_blocklist is empty.
    """
    name = "blocklist_keyword"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        blocklist = delivery.query.filter_blocklist
        if not blocklist:
            return FilterResult.PASS, None
        haystack = f"{delivery.ad.name} {delivery.ad.short_description}".lower()
        for phrase in blocklist:
            if phrase.lower() in haystack:
                return FilterResult.REJECT, f"blocklisted keyword: {phrase}"
        return FilterResult.PASS, None


class RequiredKeywordRule:
    """Rejects ads whose name/short_description contains none of the query's
    required keywords. PASSes when the query's filter_required is empty.
    """
    name = "required_keyword"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        required = delivery.query.filter_required
        if not required:
            return FilterResult.PASS, None
        haystack = f"{delivery.ad.name} {delivery.ad.short_description}".lower()
        if any(phrase.lower() in haystack for phrase in required):
            return FilterResult.PASS, None
        return FilterResult.REJECT, "missing required keyword"


class PublisherBlocklistRule:
    """Rejects ads from a blocked email or phone publisher."""
    name = "publisher_blocklist"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        ad = delivery.ad
        if ad.email_publisher_id and ad.email_publisher.blocked:
            return FilterResult.REJECT, "blocked email publisher"
        if ad.phone_publisher_id and ad.phone_publisher.blocked:
            return FilterResult.REJECT, "blocked phone publisher"
        return FilterResult.PASS, None


class PriceDropRule:
    """For PRICE_CHANGED ads only: rejects re-notifications where the price
    didn't actually drop (e.g. it rose, or round-trips to the same number).
    PASSes for ads not currently in PRICE_CHANGED, or when there's no parsed
    price history to compare against.
    """
    name = "price_drop"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        if delivery.status != AdStatus.PRICE_CHANGED:
            return FilterResult.PASS, None
        latest_change = delivery.ad.price_history.order_by("-created").first()
        if latest_change is None:
            return FilterResult.PASS, None
        old_price = latest_change.old_price_amount
        new_price = latest_change.new_price_amount
        if old_price is None or new_price is None:
            return FilterResult.PASS, None
        if new_price >= old_price:
            return FilterResult.REJECT, f"price did not drop ({old_price} -> {new_price})"
        return FilterResult.PASS, None


class LocationDistanceRule:
    """Rejects ads further than `query.filter_location_radius` km from `filter_location_center`.

    This is the "search wide, notify near" rule. The marketplace-side location params
    (`Query.location_center`/`location_radius`) decide what gets scraped and are binary and
    server-side; a query that wants to watch the whole country cannot use them to keep the
    Discord channel local. This one runs after the scrape, over the same ads, so both are
    expressible at once.

    Distance is straight-line between two post offices (`bazos/geo.py`), not driving
    distance, and the ad's real position is somewhere inside its postal area — so treat the
    radius as approximate and do not tune it in single km.

    PASSes — never rejects — when:
    - the query has not set both a centre and a radius (**the default**, so an existing
      query keeps receiving everything),
    - the ad's location string carries no postal code, which is every Sbazar and Vinted ad
      (that is the gate on marketplace: an ad with no code is not a distant ad),
    - either code is missing from the `PostalCode` cache — a code is normally geocoded when
      its first ad is scraped, so this is the window before `manage.py geocode_postal_codes`
      has been run over ads that predate the feature.

    "Unknown location" therefore means "send it", matching the permissive-when-unset
    convention of the keyword rules. The opposite would let a geocoding outage silently
    mute a query.
    """
    name = "location_distance"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        query = delivery.query
        radius = query.filter_location_radius
        center = normalize_postal_code(query.filter_location_center)
        if center is None or radius is None:
            return FilterResult.PASS, None
        ad_code = parse_postal_code(delivery.ad.location)
        if ad_code is None:
            return FilterResult.PASS, None
        distance = distance_between_codes(center, ad_code)
        if distance is None:
            logger.info(
                "Distance filter inactive for ad %s: %s or %s is not geocoded",
                delivery.ad_id, center, ad_code,
            )
            return FilterResult.PASS, None
        if distance > radius:
            # One decimal, not zero: rounding 10.4 to "10 km away, limit 10 km" reads as
            # a bug in the rule rather than a listing just outside the radius.
            return FilterResult.REJECT, (
                f"{distance:.1f} km away ({ad_code}), limit {radius} km from {center}"
            )
        return FilterResult.PASS, None


class PriceModelRule:
    """Rejects ads that a price model does NOT consider a deal.

    Inverted relative to the other rules on purpose. The others answer "is there a reason to
    drop this?"; this one answers "is there a reason to *send* this?", so on a query that
    enables it the channel only ever sees listings the model flagged. That is what makes a
    dedicated alert query work -- `Query.sender` is per query, so routing deals to one channel
    and everything else to another is not expressible any other way.

    Always persists the score before deciding (P23 step 4: a rule that only returns
    APPROVE/REJECT/PASS throws away the interesting number).

    PASSes -- deliberately, never rejects -- when:
    - shadow mode is on (the shipping default; see `PRICE_MODEL_SHADOW_MODE`),
    - no registered model claims the ad,
    - the model declined (missing artifact, incomplete specs, damage words, non-EXACT price).

    A model that cannot score must not be able to silently drop everything, so every
    uncertain path is neutral rather than rejecting. Design: docs/proposals/ML_PRICE_SCORING.md
    """
    name = "price_model"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        # Imported lazily: bazos.pricing imports bazos.models, and filters.py is imported at
        # app-load time by callers that must not pay for the pricing package.
        from bazos.pricing.scoring import score_ad

        try:
            score = score_ad(delivery.ad)
        except Exception:
            # Scoring is an enhancement, not a gate. A bug here must not stop the pipeline
            # filtering everything else, so this is one of the few places a bare except is
            # the right call -- it is logged with a traceback and degrades to PASS.
            logger.exception("Price scoring failed for ad %s; passing", delivery.ad_id)
            return FilterResult.PASS, None

        if score is None or score.z_score is None or score.discount_pct is None:
            return FilterResult.PASS, None
        if getattr(settings, "PRICE_MODEL_SHADOW_MODE", PRICE_MODEL_SHADOW_MODE):
            return FilterResult.PASS, None

        z_limit = self._threshold(
            delivery.query, "filter_price_model_z",
            "PRICE_MODEL_Z_THRESHOLD", PRICE_MODEL_Z_THRESHOLD,
        )
        pct_limit = self._threshold(
            delivery.query, "filter_price_model_min_discount",
            "PRICE_MODEL_MIN_DISCOUNT_PCT", PRICE_MODEL_MIN_DISCOUNT_PCT,
        )
        if score.z_score <= z_limit and score.discount_pct >= pct_limit:
            return FilterResult.PASS, None
        # The thresholds are in the reason, not just the measurements: while these are being
        # calibrated the useful question about a rejection is "by how much did it miss, and
        # against what bar", and `filter_reason` is the only place that survives.
        return FilterResult.REJECT, (
            f"not a deal: {score.discount_pct:+.1f}% vs predicted {score.predicted}, "
            f"z={score.z_score:+.2f} (limits z<={z_limit:g}, discount>={pct_limit:g}%)"
        )

    @staticmethod
    def _threshold(query: Query, field: str, setting_name: str, default: float) -> float:
        """Per-query override, else the global setting, else the shipped constant.

        The query field wins even when it is *more permissive* than the global — that is
        the point of it. `None` means "not set", which is why these columns are nullable
        rather than defaulted: a query that has never been tuned must be indistinguishable
        from one tuned back to the default value.
        """
        override = getattr(query, field, None)
        if override is not None:
            return override
        return getattr(settings, setting_name, default)


class RuleEngine:
    """Applies a list of :class:`FilterRule` objects in order.

    The first rule that returns ``APPROVE`` or ``REJECT`` terminates
    evaluation. If all rules return ``PASS``, the ad is approved by default.
    """

    def __init__(self, rules: list[FilterRule]) -> None:
        self.rules = rules

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        for rule in self.rules:
            result, reason = rule.apply(delivery)
            if result != FilterResult.PASS:
                return result, reason
        return FilterResult.APPROVE, None


RULE_REGISTRY: dict[str, FilterRule] = {
    "price_range": PriceRangeRule(),
    "blocklist_keyword": BlocklistKeywordRule(),
    "required_keyword": RequiredKeywordRule(),
    "publisher_blocklist": PublisherBlocklistRule(),
    "price_drop": PriceDropRule(),
    "location_distance": LocationDistanceRule(),
    "price_model": PriceModelRule(),
}
#: Rules that are registered but NOT applied unless a query names them. These are the
#: *inverted* ones — they answer "is there a reason to send this?" rather than "is there a
#: reason to drop it?" — so switching one on by default would mute every existing query.
#: Opt in per query via `Query.filter_rule_names`, which is the case P17's registry was
#: built for.
OPT_IN_RULE_NAMES: set[str] = {"price_model"}

DEFAULT_RULE_NAMES: list[str] = [n for n in RULE_REGISTRY if n not in OPT_IN_RULE_NAMES]


def register_rule(rule: FilterRule, *, opt_in: bool = False) -> None:
    """Add a rule from another app, at that app's `AppConfig.ready()`.

    The registry is mutated rather than imported into, so `bazos` never has to know which
    other apps exist and stays deletable-independent of them. Registering *through* this
    function rather than assigning into `RULE_REGISTRY` directly is what keeps
    `DEFAULT_RULE_NAMES` correct: it is a list built at import time, and a rule added
    afterwards would otherwise be included or excluded purely by import order.
    """
    if rule.name in RULE_REGISTRY:
        return
    RULE_REGISTRY[rule.name] = rule
    if opt_in:
        OPT_IN_RULE_NAMES.add(rule.name)
    else:
        DEFAULT_RULE_NAMES.append(rule.name)


def build_rule_engine(query: Query) -> RuleEngine:
    """Build a RuleEngine from a query's `filter_rule_names`.

    An empty list means "all default rules" — the same permissive-when-empty
    convention already used for `filter_blocklist`/`filter_required`.
    """
    names = query.filter_rule_names or DEFAULT_RULE_NAMES
    try:
        rules = [RULE_REGISTRY[name] for name in names]
    except KeyError as e:
        raise ValueError(
            f"Unknown filter rule name {e.args[0]!r} in Query {query.pk}.filter_rule_names "
            f"(known rules: {DEFAULT_RULE_NAMES})"
        ) from e
    return RuleEngine(rules)
