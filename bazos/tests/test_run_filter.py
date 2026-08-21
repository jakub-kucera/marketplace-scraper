"""Tests for the run_filter pipeline stage.

Exercises the filter loop logic directly (not via the management command
entrypoint) so tests run without subprocess overhead. Operates on AdDelivery,
not Ad, since the Ad/AdDelivery split moved pipeline status there — see
docs/refactor/AD_DELIVERY_SPLIT_SPEC.md.
"""
import pytest

from bazos.filters import FilterResult, PassthroughRule, RuleEngine
from bazos.models import AdDelivery, AdStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _RejectRule:
    name = "reject_all"

    def apply(self, delivery):
        return FilterResult.REJECT, "test rejection"


def _run_filter_once(deliveries, engine):
    """Simulate one batch of the run_filter loop (without DB locking)."""
    for delivery in deliveries:
        result, reason = engine.apply(delivery)
        delivery.status = AdStatus.APPROVED if result != FilterResult.REJECT else AdStatus.REJECTED
        delivery.filter_reason = reason
        delivery.save(update_fields=["status", "filter_reason"])


# ---------------------------------------------------------------------------
# PENDING → APPROVED (PassthroughRule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_delivery_becomes_approved(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=1)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    engine = RuleEngine(rules=[PassthroughRule()])
    _run_filter_once([delivery], engine)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED


@pytest.mark.django_db
def test_pending_delivery_has_no_filter_reason_on_approve(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=1)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    engine = RuleEngine(rules=[PassthroughRule()])
    _run_filter_once([delivery], engine)

    delivery.refresh_from_db()
    assert delivery.filter_reason is None


# ---------------------------------------------------------------------------
# PRICE_CHANGED → APPROVED (PassthroughRule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_price_changed_delivery_becomes_approved(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=2)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PRICE_CHANGED)

    engine = RuleEngine(rules=[PassthroughRule()])
    _run_filter_once([delivery], engine)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED


# ---------------------------------------------------------------------------
# PENDING → REJECTED (reject rule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_delivery_becomes_rejected(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=3)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once([delivery], engine)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.REJECTED


@pytest.mark.django_db
def test_rejected_delivery_has_filter_reason(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=4)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once([delivery], engine)

    delivery.refresh_from_db()
    assert delivery.filter_reason == "test rejection"


# ---------------------------------------------------------------------------
# Deliveries in other statuses are not affected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_delivery_is_not_touched(query, make_ad, make_delivery):
    """An already-APPROVED delivery must not be re-processed by the filter."""
    ad = make_ad(query, bazos_id=5)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    # Simulate the filter loop only picking up PENDING/PRICE_CHANGED
    pending = list(AdDelivery.objects.filter(
        status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED]
    ))
    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once(pending, engine)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED   # unchanged


@pytest.mark.django_db
def test_sent_delivery_is_not_touched(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=6)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.SENT)

    pending = list(AdDelivery.objects.filter(
        status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED]
    ))
    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once(pending, engine)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SENT       # unchanged
