"""Tests for the run_filter pipeline stage.

Exercises the filter loop logic directly (not via the management command
entrypoint) so tests run without subprocess overhead.
"""
import pytest

from bazos.filters import FilterResult, PassthroughRule, RuleEngine
from bazos.models import Ad, AdStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _RejectRule:
    name = "reject_all"

    def apply(self, ad):
        return FilterResult.REJECT, "test rejection"


def _run_filter_once(ads, engine):
    """Simulate one batch of the run_filter loop (without DB locking)."""
    for ad in ads:
        result, reason = engine.apply(ad)
        ad.status = AdStatus.APPROVED if result != FilterResult.REJECT else AdStatus.REJECTED
        ad.filter_reason = reason
        ad.save(update_fields=["status", "filter_reason"])


# ---------------------------------------------------------------------------
# PENDING → APPROVED (PassthroughRule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_ad_becomes_approved(query, make_ad):
    ad = make_ad(query, bazos_id=1)
    ad.status = AdStatus.PENDING
    ad.save()

    engine = RuleEngine(rules=[PassthroughRule()])
    _run_filter_once([ad], engine)

    ad.refresh_from_db()
    assert ad.status == AdStatus.APPROVED


@pytest.mark.django_db
def test_pending_ad_has_no_filter_reason_on_approve(query, make_ad):
    ad = make_ad(query, bazos_id=1)
    ad.status = AdStatus.PENDING
    ad.save()

    engine = RuleEngine(rules=[PassthroughRule()])
    _run_filter_once([ad], engine)

    ad.refresh_from_db()
    assert ad.filter_reason is None


# ---------------------------------------------------------------------------
# PRICE_CHANGED → APPROVED (PassthroughRule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_price_changed_ad_becomes_approved(query, make_ad):
    ad = make_ad(query, bazos_id=2)
    ad.status = AdStatus.PRICE_CHANGED
    ad.save()

    engine = RuleEngine(rules=[PassthroughRule()])
    _run_filter_once([ad], engine)

    ad.refresh_from_db()
    assert ad.status == AdStatus.APPROVED


# ---------------------------------------------------------------------------
# PENDING → REJECTED (reject rule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_ad_becomes_rejected(query, make_ad):
    ad = make_ad(query, bazos_id=3)
    ad.status = AdStatus.PENDING
    ad.save()

    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once([ad], engine)

    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED


@pytest.mark.django_db
def test_rejected_ad_has_filter_reason(query, make_ad):
    ad = make_ad(query, bazos_id=4)
    ad.status = AdStatus.PENDING
    ad.save()

    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once([ad], engine)

    ad.refresh_from_db()
    assert ad.filter_reason == "test rejection"


# ---------------------------------------------------------------------------
# Ads in other statuses are not affected
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_ad_is_not_touched(query, make_ad):
    """An already-APPROVED ad must not be re-processed by the filter."""
    ad = make_ad(query, bazos_id=5)
    ad.status = AdStatus.APPROVED
    ad.save()

    # Simulate the filter loop only picking up PENDING/PRICE_CHANGED
    pending = list(Ad.objects.filter(
        status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED]
    ))
    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once(pending, engine)

    ad.refresh_from_db()
    assert ad.status == AdStatus.APPROVED   # unchanged


@pytest.mark.django_db
def test_sent_ad_is_not_touched(query, make_ad):
    ad = make_ad(query, bazos_id=6)
    ad.status = AdStatus.SENT
    ad.save()

    pending = list(Ad.objects.filter(
        status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED]
    ))
    engine = RuleEngine(rules=[_RejectRule()])
    _run_filter_once(pending, engine)

    ad.refresh_from_db()
    assert ad.status == AdStatus.SENT       # unchanged
