"""Unit tests for bazos/filters.py — FilterResult, RuleEngine, PassthroughRule,
the Stage 9 rules (PriceRangeRule, BlocklistKeywordRule, RequiredKeywordRule,
PublisherBlocklistRule, PriceDropRule), and the P17 per-query rule registry
(RULE_REGISTRY, build_rule_engine).

Rules operate on an `AdDelivery` (ad + query + pipeline status) since the Ad/AdDelivery
split — see docs/refactor/AD_DELIVERY_SPLIT_SPEC.md.
"""

import pytest

from bazos.filters import (
    DEFAULT_RULE_NAMES,
    RULE_REGISTRY,
    BlocklistKeywordRule,
    FilterResult,
    PassthroughRule,
    PriceDropRule,
    PriceRangeRule,
    PublisherBlocklistRule,
    RequiredKeywordRule,
    RuleEngine,
    build_rule_engine,
    parse_price,
)
from bazos.models import AdDelivery, AdStatus, EmailPublisher, PhonePublisher, PriceChange


# ---------------------------------------------------------------------------
# Helpers — fake rules for testing
# ---------------------------------------------------------------------------

class _ApproveRule:
    name = "approve_all"

    def apply(self, delivery):
        return FilterResult.APPROVE, None


class _RejectRule:
    name = "reject_all"

    def apply(self, delivery):
        return FilterResult.REJECT, "always rejected"


class _PassRule:
    name = "pass_all"

    def apply(self, delivery):
        return FilterResult.PASS, None


def unsaved_delivery(ad, query, status=AdStatus.PENDING):
    """An AdDelivery not persisted to the DB — enough for rules that only read
    attributes off `.ad`/`.query` without touching a reverse relation."""
    return AdDelivery(ad=ad, query=query, status=status)


# ---------------------------------------------------------------------------
# PassthroughRule
# ---------------------------------------------------------------------------

def test_passthrough_rule_approves():
    rule = PassthroughRule()
    result, reason = rule.apply(delivery=None)
    assert result == FilterResult.APPROVE


def test_passthrough_rule_has_no_reason():
    rule = PassthroughRule()
    _, reason = rule.apply(delivery=None)
    assert reason is None


def test_passthrough_rule_name():
    assert PassthroughRule.name == "passthrough"


# ---------------------------------------------------------------------------
# RuleEngine — empty rules list
# ---------------------------------------------------------------------------

def test_engine_with_no_rules_approves():
    engine = RuleEngine(rules=[])
    result, reason = engine.apply(delivery=None)
    assert result == FilterResult.APPROVE
    assert reason is None


# ---------------------------------------------------------------------------
# RuleEngine — single rule
# ---------------------------------------------------------------------------

def test_engine_approve_rule_approves():
    engine = RuleEngine(rules=[_ApproveRule()])
    result, _ = engine.apply(delivery=None)
    assert result == FilterResult.APPROVE


def test_engine_reject_rule_rejects():
    engine = RuleEngine(rules=[_RejectRule()])
    result, reason = engine.apply(delivery=None)
    assert result == FilterResult.REJECT
    assert reason == "always rejected"


def test_engine_pass_rule_defaults_to_approve():
    engine = RuleEngine(rules=[_PassRule()])
    result, reason = engine.apply(delivery=None)
    assert result == FilterResult.APPROVE
    assert reason is None


# ---------------------------------------------------------------------------
# RuleEngine — rule ordering / short-circuit
# ---------------------------------------------------------------------------

def test_engine_first_non_pass_wins_approve():
    """[pass, approve] → APPROVE from second rule."""
    engine = RuleEngine(rules=[_PassRule(), _ApproveRule()])
    result, _ = engine.apply(delivery=None)
    assert result == FilterResult.APPROVE


def test_engine_first_non_pass_wins_reject():
    """[pass, reject] → REJECT from second rule."""
    engine = RuleEngine(rules=[_PassRule(), _RejectRule()])
    result, _ = engine.apply(delivery=None)
    assert result == FilterResult.REJECT


def test_engine_reject_stops_before_approve():
    """[reject, approve] → REJECT; the approve rule is never reached."""
    call_log = []

    class _LoggingApprove:
        name = "logging_approve"

        def apply(self, delivery):
            call_log.append("approve_called")
            return FilterResult.APPROVE, None

    engine = RuleEngine(rules=[_RejectRule(), _LoggingApprove()])
    result, _ = engine.apply(delivery=None)
    assert result == FilterResult.REJECT
    assert "approve_called" not in call_log


def test_engine_multiple_pass_then_reject():
    """[pass, pass, reject] → REJECT."""
    engine = RuleEngine(rules=[_PassRule(), _PassRule(), _RejectRule()])
    result, reason = engine.apply(delivery=None)
    assert result == FilterResult.REJECT
    assert reason == "always rejected"


def test_engine_passes_reason_through():
    class _CustomRejectRule:
        name = "custom"

        def apply(self, delivery):
            return FilterResult.REJECT, "spammer detected"

    engine = RuleEngine(rules=[_CustomRejectRule()])
    _, reason = engine.apply(delivery=None)
    assert reason == "spammer detected"


# ---------------------------------------------------------------------------
# parse_price
# ---------------------------------------------------------------------------

def test_parse_price_plain():
    assert parse_price("1000 Kč") == 1000


def test_parse_price_with_thousands_separator():
    assert parse_price("1 000 Kč") == 1000


def test_parse_price_non_numeric():
    assert parse_price("Dohodou") is None


def test_parse_price_empty():
    assert parse_price("") is None


# ---------------------------------------------------------------------------
# PriceRangeRule
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_price_range_rule_passes_when_no_range_set(query, make_ad):
    query.price_lower = 0
    query.price_upper = 0
    ad = make_ad(query, bazos_id=100)
    ad.price_raw = "5000 Kč"

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS
    assert reason is None


@pytest.mark.django_db
def test_price_range_rule_rejects_below_range(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=101)
    ad.price_raw = "500 Kč"

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None


@pytest.mark.django_db
def test_price_range_rule_rejects_above_range(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=102)
    ad.price_raw = "5000 Kč"

    result, _ = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_price_range_rule_passes_inside_range(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=103)
    ad.price_raw = "1500 Kč"

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS
    assert reason is None


@pytest.mark.django_db
def test_price_range_rule_passes_non_numeric_price(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=104)
    ad.price_raw = "Dohodou"

    result, _ = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


# ---------------------------------------------------------------------------
# BlocklistKeywordRule
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_blocklist_keyword_rule_passes_when_list_empty(query, make_ad):
    query.filter_blocklist = []
    ad = make_ad(query, bazos_id=110)
    ad.name = "Broken iPhone for parts"

    result, _ = BlocklistKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_blocklist_keyword_rule_rejects_match_in_name(query, make_ad):
    query.filter_blocklist = ["broken"]
    ad = make_ad(query, bazos_id=111)
    ad.name = "Broken iPhone for parts"

    result, reason = BlocklistKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None
    assert "broken" in reason


@pytest.mark.django_db
def test_blocklist_keyword_rule_rejects_match_in_description(query, make_ad):
    query.filter_blocklist = ["cracked screen"]
    ad = make_ad(query, bazos_id=112)
    ad.short_description = "Sold as-is, cracked screen"

    result, _ = BlocklistKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_blocklist_keyword_rule_passes_no_match(query, make_ad):
    query.filter_blocklist = ["broken", "cracked screen"]
    ad = make_ad(query, bazos_id=113)
    ad.name = "Mint condition iPhone"
    ad.short_description = "Like new, no scratches"

    result, _ = BlocklistKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


# ---------------------------------------------------------------------------
# RequiredKeywordRule
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_required_keyword_rule_passes_when_list_empty(query, make_ad):
    query.filter_required = []
    ad = make_ad(query, bazos_id=120)
    ad.name = "Some random ad"

    result, _ = RequiredKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_required_keyword_rule_passes_on_name_match(query, make_ad):
    query.filter_required = ["m1", "m2"]
    ad = make_ad(query, bazos_id=121)
    ad.name = "MacBook Pro M1 16GB"

    result, _ = RequiredKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_required_keyword_rule_passes_on_description_match(query, make_ad):
    query.filter_required = ["m1"]
    ad = make_ad(query, bazos_id=122)
    ad.name = "MacBook Pro"
    ad.short_description = "Has the M1 chip"

    result, _ = RequiredKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_required_keyword_rule_rejects_no_match(query, make_ad):
    query.filter_required = ["m1", "m2"]
    ad = make_ad(query, bazos_id=123)
    ad.name = "MacBook Pro Intel"
    ad.short_description = "2019 model"

    result, reason = RequiredKeywordRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None


# ---------------------------------------------------------------------------
# PublisherBlocklistRule
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_publisher_blocklist_rule_passes_no_publishers(query, make_ad):
    ad = make_ad(query, bazos_id=130)

    result, _ = PublisherBlocklistRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_publisher_blocklist_rule_rejects_blocked_email_publisher(query, make_ad):
    publisher = EmailPublisher.objects.create(bazos_id=1, email="spam@example.com", blocked=True)
    ad = make_ad(query, bazos_id=131)
    ad.email_publisher = publisher

    result, reason = PublisherBlocklistRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None


@pytest.mark.django_db
def test_publisher_blocklist_rule_rejects_blocked_phone_publisher(query, make_ad):
    publisher = PhonePublisher.objects.create(bazos_id=2, phone="123456789", blocked=True)
    ad = make_ad(query, bazos_id=132)
    ad.phone_publisher = publisher

    result, _ = PublisherBlocklistRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_publisher_blocklist_rule_passes_non_blocked_publisher(query, make_ad):
    publisher = EmailPublisher.objects.create(bazos_id=3, email="ok@example.com", blocked=False)
    ad = make_ad(query, bazos_id=133)
    ad.email_publisher = publisher

    result, _ = PublisherBlocklistRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


# ---------------------------------------------------------------------------
# PriceDropRule
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_price_drop_rule_passes_when_not_price_changed(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=140)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_price_drop_rule_passes_when_no_price_history(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=141)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_price_drop_rule_passes_on_real_drop(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=142)
    ad.price_raw = "800 Kč"
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(ad=ad, old_price="1000 Kč", new_price="800 Kč")

    result, reason = PriceDropRule().apply(delivery)
    assert result == FilterResult.PASS
    assert reason is None


@pytest.mark.django_db
def test_price_drop_rule_rejects_price_increase(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=143)
    ad.price_raw = "1200 Kč"
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(ad=ad, old_price="1000 Kč", new_price="1200 Kč")

    result, reason = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT
    assert reason is not None


@pytest.mark.django_db
def test_price_drop_rule_rejects_unchanged_price(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=144)
    ad.price_raw = "1000 Kč"
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(ad=ad, old_price="1000 Kč", new_price="1000 Kč")

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_price_drop_rule_uses_latest_price_change(query, make_ad, make_delivery):
    """If price dropped then rose again, only the latest change should matter."""
    ad = make_ad(query, bazos_id=145)
    ad.price_raw = "1500 Kč"
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(ad=ad, old_price="2000 Kč", new_price="1000 Kč")
    PriceChange.objects.create(ad=ad, old_price="1000 Kč", new_price="1500 Kč")

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT


# ---------------------------------------------------------------------------
# RULE_REGISTRY / build_rule_engine (P17 — per-query filter rule registry)
# ---------------------------------------------------------------------------

def test_rule_registry_has_all_five_stage9_rules():
    assert set(RULE_REGISTRY) == {
        "price_range",
        "blocklist_keyword",
        "required_keyword",
        "publisher_blocklist",
        "price_drop",
    }


def test_default_rule_names_matches_registry():
    assert DEFAULT_RULE_NAMES == list(RULE_REGISTRY)


@pytest.mark.django_db
def test_build_rule_engine_empty_list_applies_all_default_rules(query):
    query.filter_rule_names = []
    engine = build_rule_engine(query)
    assert [rule.name for rule in engine.rules] == DEFAULT_RULE_NAMES


@pytest.mark.django_db
def test_build_rule_engine_subset_applies_only_named_rules(query):
    query.filter_rule_names = ["price_range"]
    engine = build_rule_engine(query)
    assert [rule.name for rule in engine.rules] == ["price_range"]


@pytest.mark.django_db
def test_build_rule_engine_subset_preserves_order(query):
    query.filter_rule_names = ["price_drop", "price_range"]
    engine = build_rule_engine(query)
    assert [rule.name for rule in engine.rules] == ["price_drop", "price_range"]


@pytest.mark.django_db
def test_build_rule_engine_unknown_name_raises(query):
    query.filter_rule_names = ["not_a_real_rule"]
    with pytest.raises(ValueError, match="not_a_real_rule"):
        build_rule_engine(query)


@pytest.mark.django_db
def test_build_rule_engine_selected_rule_still_applies(query, make_ad):
    """A query scoped to just price_range shouldn't apply blocklist_keyword."""
    query.filter_rule_names = ["price_range"]
    query.price_lower = 1000
    query.price_upper = 2000
    query.filter_blocklist = ["mint"]  # would normally reject this ad
    ad = make_ad(query, bazos_id=150)
    ad.price_raw = "1500 Kč"
    ad.name = "Mint condition laptop"

    engine = build_rule_engine(query)
    result, reason = engine.apply(unsaved_delivery(ad, query))
    assert result == FilterResult.APPROVE
    assert reason is None
