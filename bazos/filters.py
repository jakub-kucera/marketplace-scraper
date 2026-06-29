"""Filter rule engine for the ad pipeline.

Rules are applied per-ad in the ``run_filter`` management command.
A rule returns one of three outcomes:

- ``FilterResult.APPROVE`` — the ad should be sent
- ``FilterResult.REJECT``  — the ad should be dropped (with an optional reason)
- ``FilterResult.PASS``    — this rule has no opinion; let the next rule decide

The ``RuleEngine`` applies rules in order. The first non-PASS result wins.
If every rule returns PASS, the ad is approved by default.

Stage 9 will replace ``PassthroughRule`` with real rule implementations.
"""
from enum import Enum
from typing import Protocol

from bazos.models import Ad


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
    """Default rule — approves everything.

    Used until Stage 9 introduces real rule implementations.
    """
    name = "passthrough"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        return FilterResult.APPROVE, None


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
