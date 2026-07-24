"""Filter rule engine for the ad pipeline.

Rules are applied per-ad in the ``run_filter`` management command.
A rule returns one of three outcomes:

- ``FilterResult.APPROVE`` — the ad should be sent
- ``FilterResult.REJECT``  — the ad should be dropped (with an optional reason)
- ``FilterResult.PASS``    — this rule has no opinion; let the next rule decide

The ``RuleEngine`` applies rules in order. The first non-PASS result wins.
If every rule returns PASS, the ad is approved by default.

Stage 9 rules below are combined into the ``RuleEngine`` used by ``run_filter``.
"""
import re
from enum import Enum
from typing import Protocol

from bazos.models import Ad, AdStatus, Query


class FilterResult(Enum):
    APPROVE = "approve"
    REJECT  = "reject"
    PASS    = "pass"   # neutral — let the next rule decide


class FilterRule(Protocol):
    """Structural protocol every filter rule must satisfy."""
    name: str

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        """Return (result, reason). reason is None unless result is REJECT."""
        ...


class PassthroughRule:
    """Approves everything. Useful as a no-op RuleEngine baseline (e.g. in tests)."""
    name = "passthrough"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        return FilterResult.APPROVE, None


def parse_price(price_raw: str) -> int | None:
    """Parse a Bazos price string (e.g. "1 000 Kč") into an int amount.

    Returns None if the string has no digits (e.g. "Dohodou", "V textu").
    """
    digits = re.sub(r"\D", "", price_raw)
    return int(digits) if digits else None


class PriceRangeRule:
    """Rejects ads priced outside the query's price_lower/price_upper range.

    PASSes when the query has no range set (0-0, the "no filter" convention —
    see PROMPTS.md P7) or when the price can't be parsed as a number.
    """
    name = "price_range"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        query = ad.query
        if query.price_lower == 0 and query.price_upper == 0:
            return FilterResult.PASS, None
        price = parse_price(ad.price_raw)
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

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        blocklist = ad.query.filter_blocklist
        if not blocklist:
            return FilterResult.PASS, None
        haystack = f"{ad.name} {ad.short_description}".lower()
        for phrase in blocklist:
            if phrase.lower() in haystack:
                return FilterResult.REJECT, f"blocklisted keyword: {phrase}"
        return FilterResult.PASS, None


class RequiredKeywordRule:
    """Rejects ads whose name/short_description contains none of the query's
    required keywords. PASSes when the query's filter_required is empty.
    """
    name = "required_keyword"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        required = ad.query.filter_required
        if not required:
            return FilterResult.PASS, None
        haystack = f"{ad.name} {ad.short_description}".lower()
        if any(phrase.lower() in haystack for phrase in required):
            return FilterResult.PASS, None
        return FilterResult.REJECT, "missing required keyword"


class PublisherBlocklistRule:
    """Rejects ads from a blocked email or phone publisher."""
    name = "publisher_blocklist"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        if ad.email_publisher_id and ad.email_publisher.blocked:
            return FilterResult.REJECT, "blocked email publisher"
        if ad.phone_publisher_id and ad.phone_publisher.blocked:
            return FilterResult.REJECT, "blocked phone publisher"
        return FilterResult.PASS, None


class PriceDropRule:
    """For PRICE_CHANGED ads only: rejects re-notifications where the price
    didn't actually drop (e.g. it rose, or the reported string round-trips to
    the same number). PASSes for ads not currently in PRICE_CHANGED, or when
    there's no parseable price history to compare against.
    """
    name = "price_drop"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        if ad.status != AdStatus.PRICE_CHANGED:
            return FilterResult.PASS, None
        latest_change = ad.price_history.order_by("-created").first()
        if latest_change is None:
            return FilterResult.PASS, None
        old_price = parse_price(latest_change.old_price)
        new_price = parse_price(latest_change.new_price)
        if old_price is None or new_price is None:
            return FilterResult.PASS, None
        if new_price >= old_price:
            return FilterResult.REJECT, f"price did not drop ({old_price} -> {new_price})"
        return FilterResult.PASS, None


class RuleEngine:
    """Applies a list of :class:`FilterRule` objects in order.

    The first rule that returns ``APPROVE`` or ``REJECT`` terminates
    evaluation. If all rules return ``PASS``, the ad is approved by default.
    """

    def __init__(self, rules: list[FilterRule]) -> None:
        self.rules = rules

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        for rule in self.rules:
            result, reason = rule.apply(ad)
            if result != FilterResult.PASS:
                return result, reason
        return FilterResult.APPROVE, None


RULE_REGISTRY: dict[str, FilterRule] = {
    "price_range": PriceRangeRule(),
    "blocklist_keyword": BlocklistKeywordRule(),
    "required_keyword": RequiredKeywordRule(),
    "publisher_blocklist": PublisherBlocklistRule(),
    "price_drop": PriceDropRule(),
}
DEFAULT_RULE_NAMES: list[str] = list(RULE_REGISTRY)


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
