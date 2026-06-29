"""Unit tests for bazos/filters.py — FilterResult, RuleEngine, PassthroughRule.

All tests are pure (no DB access needed).
"""
import pytest

from bazos.filters import FilterResult, PassthroughRule, RuleEngine
from bazos.models import Ad


# ---------------------------------------------------------------------------
# Helpers — fake rules for testing
# ---------------------------------------------------------------------------

class _ApproveRule:
    name = "approve_all"

    def apply(self, ad):
        return FilterResult.APPROVE, None


class _RejectRule:
    name = "reject_all"

    def apply(self, ad):
        return FilterResult.REJECT, "always rejected"


class _PassRule:
    name = "pass_all"

    def apply(self, ad):
        return FilterResult.PASS, None


# ---------------------------------------------------------------------------
# PassthroughRule
# ---------------------------------------------------------------------------

def test_passthrough_rule_approves():
    rule = PassthroughRule()
    result, reason = rule.apply(ad=None)
    assert result == FilterResult.APPROVE


def test_passthrough_rule_has_no_reason():
    rule = PassthroughRule()
    _, reason = rule.apply(ad=None)
    assert reason is None


def test_passthrough_rule_name():
    assert PassthroughRule.name == "passthrough"


# ---------------------------------------------------------------------------
# RuleEngine — empty rules list
# ---------------------------------------------------------------------------

def test_engine_with_no_rules_approves():
    engine = RuleEngine(rules=[])
    result, reason = engine.apply(ad=None)
    assert result == FilterResult.APPROVE
    assert reason is None


# ---------------------------------------------------------------------------
# RuleEngine — single rule
# ---------------------------------------------------------------------------

def test_engine_approve_rule_approves():
    engine = RuleEngine(rules=[_ApproveRule()])
    result, _ = engine.apply(ad=None)
    assert result == FilterResult.APPROVE


def test_engine_reject_rule_rejects():
    engine = RuleEngine(rules=[_RejectRule()])
    result, reason = engine.apply(ad=None)
    assert result == FilterResult.REJECT
    assert reason == "always rejected"


def test_engine_pass_rule_defaults_to_approve():
    engine = RuleEngine(rules=[_PassRule()])
    result, reason = engine.apply(ad=None)
    assert result == FilterResult.APPROVE
    assert reason is None


# ---------------------------------------------------------------------------
# RuleEngine — rule ordering / short-circuit
# ---------------------------------------------------------------------------

def test_engine_first_non_pass_wins_approve():
    """[pass, approve] → APPROVE from second rule."""
    engine = RuleEngine(rules=[_PassRule(), _ApproveRule()])
    result, _ = engine.apply(ad=None)
    assert result == FilterResult.APPROVE


def test_engine_first_non_pass_wins_reject():
    """[pass, reject] → REJECT from second rule."""
    engine = RuleEngine(rules=[_PassRule(), _RejectRule()])
    result, _ = engine.apply(ad=None)
    assert result == FilterResult.REJECT


def test_engine_reject_stops_before_approve():
    """[reject, approve] → REJECT; the approve rule is never reached."""
    call_log = []

    class _LoggingApprove:
        name = "logging_approve"

        def apply(self, ad):
            call_log.append("approve_called")
            return FilterResult.APPROVE, None

    engine = RuleEngine(rules=[_RejectRule(), _LoggingApprove()])
    result, _ = engine.apply(ad=None)
    assert result == FilterResult.REJECT
    assert "approve_called" not in call_log


def test_engine_multiple_pass_then_reject():
    """[pass, pass, reject] → REJECT."""
    engine = RuleEngine(rules=[_PassRule(), _PassRule(), _RejectRule()])
    result, reason = engine.apply(ad=None)
    assert result == FilterResult.REJECT
    assert reason == "always rejected"


def test_engine_passes_reason_through():
    class _CustomRejectRule:
        name = "custom"

        def apply(self, ad):
            return FilterResult.REJECT, "spammer detected"

    engine = RuleEngine(rules=[_CustomRejectRule()])
    _, reason = engine.apply(ad=None)
    assert reason == "spammer detected"
