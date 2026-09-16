"""Unit tests for bazos/filters.py — FilterResult, RuleEngine, PassthroughRule,
the Stage 9 rules (PriceRangeRule, BlocklistKeywordRule, RequiredKeywordRule,
PublisherBlocklistRule, PriceDropRule), and the P17 per-query rule registry
(RULE_REGISTRY, build_rule_engine).

Rules operate on an `AdDelivery` (ad + query + pipeline status) since the Ad/AdDelivery
split — see docs/archive/shipped/AD_DELIVERY_SPLIT.md.
"""

from unittest.mock import patch

import pytest

from bazos.filters import (
    DEFAULT_RULE_NAMES,
    RULE_REGISTRY,
    BlocklistKeywordRule,
    FilterResult,
    LocationDistanceRule,
    PassthroughRule,
    PriceDropRule,
    PriceRangeRule,
    PublisherBlocklistRule,
    RequiredKeywordRule,
    RuleEngine,
    build_rule_engine,
    parse_price,
    parse_price_and_type,
)
from bazos.models import (
    AdDelivery,
    AdStatus,
    EmailPublisher,
    PhonePublisher,
    PostalCode,
    PriceChange,
    PriceType,
)


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
# parse_price_and_type
# ---------------------------------------------------------------------------

def test_parse_price_and_type_exact():
    assert parse_price_and_type("1 000 Kč") == (1000, PriceType.EXACT)


def test_parse_price_and_type_free_is_zero_not_none():
    """Zdarma is a KNOWN price of zero, not an unknown one — see
    docs/research/PRICE_PARSING.md §3.3."""
    assert parse_price_and_type("Zdarma") == (0, PriceType.FREE)


def test_parse_price_and_type_negotiable():
    assert parse_price_and_type("Dohodou") == (None, PriceType.NEGOTIABLE)


def test_parse_price_and_type_in_text():
    assert parse_price_and_type("V textu") == (None, PriceType.IN_TEXT)


def test_parse_price_and_type_make_offer():
    assert parse_price_and_type("Nabídněte") == (None, PriceType.MAKE_OFFER)


def test_parse_price_and_type_indifferent():
    """Missing from P22's original enum — added per the corpus measurement (93 rows)."""
    assert parse_price_and_type("Nerozhoduje") == (None, PriceType.INDIFFERENT)


def test_parse_price_and_type_unknown_logs_and_returns_none():
    """caplog can't see this — the `bazos` logger has propagate=False (settings.py), so
    records never reach caplog's root-attached handler. Assert on the call instead."""
    with patch("bazos.filters.logger.warning") as mock_warning:
        result = parse_price_and_type("Za rozumnou cenu")
    assert result == (None, PriceType.UNKNOWN)
    mock_warning.assert_called_once()


def test_parse_price_and_type_strips_whitespace():
    assert parse_price_and_type("  Zdarma  ") == (0, PriceType.FREE)


# ---------------------------------------------------------------------------
# PriceRangeRule
# ---------------------------------------------------------------------------


def vinted_row(price: str, external_id: int = 1, promoted: bool = False) -> dict:
    """A minimal but real-shaped Vinted catalog row.

    Mirrors the live payload (camelCase, decimal price STRINGS) rather than the old
    `vinted_scraper.VintedItem` dataclass, which went away with the library when Vinted
    withdrew /api/v2/catalog/items. See bazos/tests/fixtures/vinted_listing.txt for a
    captured row and docs/research/marketplaces/VINTED.md §5 for the field list.
    """
    return {
        "productItem": {
            "id": external_id,
            "title": "Item",
            "url": f"/items/{external_id}-x",
            "price": {"amount": price, "currencyCode": "CZK"},
            "isPromoted": promoted,
            "itemBox": {"firstLine": "Apple", "secondLine": "Velmi dobrý"},
        }
    }


@pytest.mark.django_db
def test_price_range_rule_passes_when_no_range_set(query, make_ad):
    query.price_lower = 0
    query.price_upper = 0
    ad = make_ad(query, bazos_id=100)
    ad.price_raw, ad.price, ad.price_type = "5000 Kč", 5000, PriceType.EXACT

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS
    assert reason is None


@pytest.mark.django_db
def test_price_range_rule_rejects_below_range(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=101)
    ad.price_raw, ad.price, ad.price_type = "500 Kč", 500, PriceType.EXACT

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None


@pytest.mark.django_db
def test_price_range_rule_rejects_above_range(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=102)
    ad.price_raw, ad.price, ad.price_type = "5000 Kč", 5000, PriceType.EXACT

    result, _ = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_price_range_rule_passes_inside_range(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=103)
    ad.price_raw, ad.price, ad.price_type = "1500 Kč", 1500, PriceType.EXACT

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS
    assert reason is None


@pytest.mark.django_db
def test_price_range_rule_passes_non_numeric_price(query, make_ad):
    query.price_lower = 1000
    query.price_upper = 2000
    ad = make_ad(query, bazos_id=104)
    ad.price_raw, ad.price, ad.price_type = "Dohodou", None, PriceType.NEGOTIABLE

    result, _ = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_price_range_rule_rejects_out_of_range_vinted_ad(query):
    """Regression: PriceRangeRule switched from parsing ad.price_raw to reading ad.price
    directly. If a marketplace scraper doesn't populate ad.price, this rule silently PASSes
    everything from it regardless of range — verify Vinted's own price population (not a
    Bazos-vocabulary re-parse) actually feeds this rule end to end."""
    from bazos.scraping.vinted.vinted_scraper import VintedScraper

    query.price_lower = 1000
    query.price_upper = 2000
    ad = VintedScraper._map_row(vinted_row(price="5990.00"), "https://www.vinted.cz")

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None


@pytest.mark.django_db
def test_price_range_rule_rejects_out_of_range_sbazar_ad(query):
    """Same regression, Sbazar side — and it must not go through the Bazos parser (which
    can't see price_by_agreement and would mishandle a real zero-price giveaway)."""
    from bazos.scraping.sbazar.sbazar_scraper import SbazarScraper

    query.price_lower = 1000
    query.price_upper = 2000
    row = {
        "id": 1, "seo_name": "x", "name": "Item", "price": 11990, "price_by_agreement": False,
        "topped": False, "create_date": "2026-08-17T20:13:31", "locality": {},
        "user": {"id": 1, "user_service": {"shop_url": "x", "shop_name": "x"}},
    }
    ad = SbazarScraper._map_item(row, "https://www.sbazar.cz")

    result, reason = PriceRangeRule().apply(unsaved_delivery(ad, query))
    assert result == FilterResult.REJECT
    assert reason is not None


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
    ad.price_raw, ad.price = "800 Kč", 800
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(
        ad=ad, old_price="1000 Kč", new_price="800 Kč", old_price_amount=1000, new_price_amount=800
    )

    result, reason = PriceDropRule().apply(delivery)
    assert result == FilterResult.PASS
    assert reason is None


@pytest.mark.django_db
def test_price_drop_rule_rejects_price_increase(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=143)
    ad.price_raw, ad.price = "1200 Kč", 1200
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(
        ad=ad, old_price="1000 Kč", new_price="1200 Kč", old_price_amount=1000, new_price_amount=1200
    )

    result, reason = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT
    assert reason is not None


@pytest.mark.django_db
def test_price_drop_rule_rejects_unchanged_price(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=144)
    ad.price_raw, ad.price = "1000 Kč", 1000
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(
        ad=ad, old_price="1000 Kč", new_price="1000 Kč", old_price_amount=1000, new_price_amount=1000
    )

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_price_drop_rule_uses_latest_price_change(query, make_ad, make_delivery):
    """If price dropped then rose again, only the latest change should matter."""
    ad = make_ad(query, bazos_id=145)
    ad.price_raw, ad.price = "1500 Kč", 1500
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(
        ad=ad, old_price="2000 Kč", new_price="1000 Kč", old_price_amount=2000, new_price_amount=1000
    )
    PriceChange.objects.create(
        ad=ad, old_price="1000 Kč", new_price="1500 Kč", old_price_amount=1000, new_price_amount=1500
    )

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT


@pytest.mark.django_db
def test_price_drop_rule_passes_when_history_unparseable(query, make_ad, make_delivery):
    """Old data or a placeholder-to-placeholder change leaves *_amount null — PASS,
    don't guess."""
    ad = make_ad(query, bazos_id=146)
    ad.price_raw = "Dohodou"
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)
    PriceChange.objects.create(ad=ad, old_price="V textu", new_price="Dohodou")

    result, _ = PriceDropRule().apply(delivery)
    assert result == FilterResult.PASS


@pytest.mark.django_db
def test_price_drop_rule_rejects_vinted_price_increase_via_query_runner(query, make_delivery):
    """Regression: the query runner propagates known_ad.price/product.price into
    PriceChange.old_price_amount/new_price_amount (query_runner.run_existing_query)
    — this only works end to end if the scraper populated .price in the first place. Drive
    it through the real VintedScraper mapping rather than constructing the PriceChange by
    hand, so a future scraper regression here fails this test too."""
    from unittest.mock import MagicMock, patch

    from bazos.scraping.query_runner import QueryRunner
    from bazos.scraping.vinted.vinted_scraper import VintedScraper

    query.marketplace = "vinted"
    query.new_query = False
    query.save()

    base = "https://www.vinted.cz"
    existing = VintedScraper._map_row(vinted_row(price="5000.00"), base)
    existing.save()
    delivery = make_delivery(existing, query, status=AdStatus.SENT)

    product = VintedScraper._map_row(vinted_row(price="7000.00"), base)

    runner = QueryRunner(query, MagicMock())
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    delivery.refresh_from_db()
    result, reason = PriceDropRule().apply(delivery)
    assert result == FilterResult.REJECT
    assert reason is not None


# ---------------------------------------------------------------------------
# RULE_REGISTRY / build_rule_engine (P17 — per-query filter rule registry)
# ---------------------------------------------------------------------------

def test_rule_registry_has_all_five_stage9_rules():
    assert {
        "price_range",
        "blocklist_keyword",
        "required_keyword",
        "publisher_blocklist",
        "price_drop",
    } <= set(RULE_REGISTRY)


def test_default_rule_names_is_every_rule_that_is_not_opt_in():
    """An *inverted* rule REJECTs anything it does not consider a deal, so it is
    registered but deliberately NOT a default — enabling one by default would mute every
    existing query. See docs/proposals/ML_PRICE_SCORING.md §1.3."""
    from bazos.filters import OPT_IN_RULE_NAMES

    assert DEFAULT_RULE_NAMES == [n for n in RULE_REGISTRY if n not in OPT_IN_RULE_NAMES]
    for name in OPT_IN_RULE_NAMES:
        assert name in RULE_REGISTRY
        assert name not in DEFAULT_RULE_NAMES


def test_price_model_is_opt_in():
    from bazos.filters import OPT_IN_RULE_NAMES

    assert "price_model" in OPT_IN_RULE_NAMES


def test_a_rule_registered_late_lands_where_it_asked_to():
    """Rules from other apps register at AppConfig.ready(), after DEFAULT_RULE_NAMES is
    built. Going through register_rule is what stops import order deciding the answer."""
    from bazos.filters import OPT_IN_RULE_NAMES, register_rule

    class Sentinel:
        name = "sentinel_opt_in_rule"

        def apply(self, delivery):
            return FilterResult.PASS, None

    try:
        register_rule(Sentinel(), opt_in=True)
        assert "sentinel_opt_in_rule" in RULE_REGISTRY
        assert "sentinel_opt_in_rule" not in DEFAULT_RULE_NAMES
    finally:
        RULE_REGISTRY.pop("sentinel_opt_in_rule", None)
        OPT_IN_RULE_NAMES.discard("sentinel_opt_in_rule")


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
    ad.price_raw, ad.price = "1500 Kč", 1500
    ad.name = "Mint condition laptop"

    engine = build_rule_engine(query)
    result, reason = engine.apply(unsaved_delivery(ad, query))
    assert result == FilterResult.APPROVE
    assert reason is None


# ---------------------------------------------------------------------------
# LocationDistanceRule — "search wide, notify near"
# ---------------------------------------------------------------------------

@pytest.fixture
def geocoded(db):
    """Praha and Brno in the PostalCode cache — ~184 km apart."""
    PostalCode.objects.create(code="11000", city="Praha", latitude=50.087334, longitude=14.421111)
    PostalCode.objects.create(code="60200", city="Brno", latitude=49.195060, longitude=16.606837)


def _near_query(query, center="110 00", radius=10):
    query.filter_location_center = center
    query.filter_location_radius = radius
    return query


@pytest.mark.django_db
def test_distance_rule_rejects_an_ad_outside_the_radius(query, make_ad, geocoded):
    ad = make_ad(query, 1)
    ad.location = "Brno, 602 00"
    delivery = unsaved_delivery(ad, _near_query(query, radius=10))

    result, reason = LocationDistanceRule().apply(delivery)

    assert result == FilterResult.REJECT
    assert reason is not None
    assert "km away (60200)" in reason
    assert "limit 10 km from 11000" in reason


@pytest.mark.django_db
def test_distance_rule_passes_an_ad_inside_the_radius(query, make_ad, geocoded):
    ad = make_ad(query, 1)
    ad.location = "Brno, 602 00"
    delivery = unsaved_delivery(ad, _near_query(query, radius=250))

    assert LocationDistanceRule().apply(delivery)[0] == FilterResult.PASS


@pytest.mark.django_db
def test_distance_rule_passes_an_ad_in_the_centre_itself(query, make_ad, geocoded):
    ad = make_ad(query, 1)
    ad.location = "Praha 1, 110 00"
    delivery = unsaved_delivery(ad, _near_query(query, radius=1))

    assert LocationDistanceRule().apply(delivery)[0] == FilterResult.PASS


@pytest.mark.django_db
def test_distance_rule_is_inactive_by_default(query, make_ad, geocoded):
    """The shipping default is blank/blank — an existing query must keep receiving
    everything, including ads from the other end of the country."""
    ad = make_ad(query, 1)
    ad.location = "Brno, 602 00"

    assert query.filter_location_center == ""
    assert query.filter_location_radius is None
    assert LocationDistanceRule().apply(unsaved_delivery(ad, query))[0] == FilterResult.PASS


@pytest.mark.django_db
@pytest.mark.parametrize("center,radius", [("110 00", None), ("", 10)])
def test_distance_rule_passes_when_only_half_configured(query, make_ad, geocoded, center, radius):
    ad = make_ad(query, 1)
    ad.location = "Brno, 602 00"
    query.filter_location_center = center
    query.filter_location_radius = radius

    assert LocationDistanceRule().apply(unsaved_delivery(ad, query))[0] == FilterResult.PASS


@pytest.mark.django_db
@pytest.mark.parametrize("location", [
    "",                                       # Vinted
    "Praha 5, Praha, Hlavní město Praha",     # Sbazar: names, no code
])
def test_distance_rule_passes_an_ad_with_no_postal_code(query, make_ad, geocoded, location):
    """No code is not "far away". This is what keeps the rule Bazos-only without it
    having to branch on marketplace."""
    ad = make_ad(query, 1)
    ad.location = location

    delivery = unsaved_delivery(ad, _near_query(query, radius=10))
    assert LocationDistanceRule().apply(delivery)[0] == FilterResult.PASS


@pytest.mark.django_db
def test_distance_rule_passes_when_the_ad_code_is_not_geocoded(query, make_ad, geocoded):
    """The window before `geocode_postal_codes` has run over pre-existing ads. An
    unresolvable code must not be able to silently mute a query."""
    ad = make_ad(query, 1)
    ad.location = "Pelhřimov, 394 03"

    delivery = unsaved_delivery(ad, _near_query(query, radius=10))
    assert LocationDistanceRule().apply(delivery)[0] == FilterResult.PASS


@pytest.mark.django_db
def test_distance_rule_passes_when_the_centre_is_not_geocoded(query, make_ad, geocoded):
    ad = make_ad(query, 1)
    ad.location = "Brno, 602 00"

    delivery = unsaved_delivery(ad, _near_query(query, center="394 03", radius=10))
    assert LocationDistanceRule().apply(delivery)[0] == FilterResult.PASS


@pytest.mark.django_db
def test_distance_rule_accepts_an_unnormalised_centre(query, make_ad, geocoded):
    """`Query.filter_location_center` is free text; only the admin form normalises it."""
    ad = make_ad(query, 1)
    ad.location = "Brno, 602 00"

    delivery = unsaved_delivery(ad, _near_query(query, center="11000", radius=10))
    assert LocationDistanceRule().apply(delivery)[0] == FilterResult.REJECT


def test_distance_rule_is_a_default_rule():
    """Safe to default because it is neutral until a query sets both fields — unlike
    price_model, which rejects out of the box."""
    assert "location_distance" in DEFAULT_RULE_NAMES
