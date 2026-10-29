"""Tests for the run_filter pipeline stage.

Drives the real management command via ``--once`` (see run_filter.run_once).
These tests used to reimplement the loop body in a local ``_run_filter_once``
helper, which meant the command's own queryset — the status filter, the
``created`` ordering and the batch cap — was never executed by any test.

Operates on AdDelivery, not Ad, since the Ad/AdDelivery split moved pipeline
status there — see docs/archive/shipped/AD_DELIVERY_SPLIT.md.
"""
from unittest.mock import patch

import pytest
from django.core.management import call_command

from marketplace.filters import FilterResult, PassthroughRule, RuleEngine
from marketplace.models import AdDelivery, AdStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _RejectRule:
    name = "reject_all"

    def apply(self, delivery):
        return FilterResult.REJECT, "test rejection"


def run_filter_once(engine=None):
    """Run one real run_filter batch.

    ``engine`` optionally stands in for ``build_rule_engine``'s result, so a test
    can pin a rule outcome without having to configure a Query that produces it.
    Passing None exercises the real engine-building path end to end.
    """
    if engine is None:
        call_command("run_filter", once=True)
        return
    with patch("marketplace.management.commands.run_filter.build_rule_engine", return_value=engine):
        call_command("run_filter", once=True)


def approve_engine():
    return RuleEngine(rules=[PassthroughRule()])


def reject_engine():
    return RuleEngine(rules=[_RejectRule()])


# ---------------------------------------------------------------------------
# PENDING → APPROVED (PassthroughRule)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_delivery_becomes_approved(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=1)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    run_filter_once(approve_engine())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED


@pytest.mark.django_db
def test_pending_delivery_has_no_filter_reason_on_approve(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=1)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    run_filter_once(approve_engine())

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

    run_filter_once(approve_engine())

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

    run_filter_once(reject_engine())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.REJECTED


@pytest.mark.django_db
def test_rejected_delivery_has_filter_reason(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=4)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    run_filter_once(reject_engine())

    delivery.refresh_from_db()
    assert delivery.filter_reason == "test rejection"


# ---------------------------------------------------------------------------
# Deliveries in other statuses are not affected
#
# These no longer hand-filter the queryset: the command's own
# `.filter(status__in=[PENDING, PRICE_CHANGED])` is what is under test.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_delivery_is_not_touched(query, make_ad, make_delivery):
    """An already-APPROVED delivery must not be re-processed by the filter."""
    ad = make_ad(query, bazos_id=5)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    run_filter_once(reject_engine())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED   # unchanged


@pytest.mark.django_db
def test_sent_delivery_is_not_touched(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=6)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.SENT)

    run_filter_once(reject_engine())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SENT       # unchanged


@pytest.mark.django_db
def test_suppressed_delivery_is_not_touched(query, make_ad, make_delivery):
    """SUPPRESSED is the ignore_first_run backfill state — the filter must skip it."""
    ad = make_ad(query, bazos_id=7)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.SUPPRESSED)

    run_filter_once(reject_engine())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SUPPRESSED


# ---------------------------------------------------------------------------
# Batch cap and ordering — only reachable now that the command's own queryset
# runs. Both were previously bypassed by the hand-built delivery list.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_one_batch_processes_at_most_batch_size(query, make_ad, make_delivery, monkeypatch):
    monkeypatch.setattr("marketplace.management.commands.run_filter.FILTER_BATCH_SIZE", 3)
    for i in range(5):
        ad = make_ad(query, bazos_id=100 + i)
        ad.save()
        make_delivery(ad, query, status=AdStatus.PENDING)

    run_filter_once(approve_engine())

    assert AdDelivery.objects.filter(status=AdStatus.APPROVED).count() == 3
    assert AdDelivery.objects.filter(status=AdStatus.PENDING).count() == 2


@pytest.mark.django_db
def test_batch_takes_the_oldest_deliveries_first(query, make_ad, make_delivery, monkeypatch):
    """The queue is FIFO: the oldest PENDING deliveries are the ones a batch takes.

    Pins observable behaviour, not the `order_by` clause itself. *Deleting*
    `order_by("created")` may happen to preserve the order anyway — the (status, created)
    composite index can serve the rows already sorted, on Postgres as on SQLite — so this
    does not claim to catch that. Reversing the clause is what it catches.
    """
    from django.utils import timezone
    from datetime import timedelta

    monkeypatch.setattr("marketplace.management.commands.run_filter.FILTER_BATCH_SIZE", 2)
    base = timezone.now()
    deliveries = []
    for i in range(4):
        ad = make_ad(query, bazos_id=200 + i)
        ad.save()
        delivery = make_delivery(ad, query, status=AdStatus.PENDING)
        # `created` is auto_now_add, so it has to be set with an UPDATE.
        AdDelivery.objects.filter(pk=delivery.pk).update(created=base - timedelta(hours=i))
        deliveries.append(delivery)

    run_filter_once(approve_engine())

    # deliveries[3] is the oldest, deliveries[0] the newest.
    statuses = {}
    for d in deliveries:
        d.refresh_from_db()
        statuses[d.pk] = d.status
    assert statuses[deliveries[3].pk] == AdStatus.APPROVED
    assert statuses[deliveries[2].pk] == AdStatus.APPROVED
    assert statuses[deliveries[1].pk] == AdStatus.PENDING
    assert statuses[deliveries[0].pk] == AdStatus.PENDING


@pytest.mark.django_db
def test_once_returns_on_an_empty_queue(query):
    """--once must exit even with nothing to do, rather than sleeping forever."""
    run_filter_once(approve_engine())   # no deliveries exist; must not hang


# ---------------------------------------------------------------------------
# The real build_rule_engine path (no patched engine)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_default_query_config_approves(query, make_ad, make_delivery):
    """An unconfigured Query means "all rules", all of which pass on a plain ad."""
    ad = make_ad(query, bazos_id=8)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    run_filter_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED


@pytest.mark.django_db
def test_blocklist_keyword_rejects_through_the_real_engine(query, make_ad, make_delivery):
    """End-to-end wiring: Query.filter_blocklist → build_rule_engine → REJECTED."""
    query.filter_blocklist = ["nefunkcni"]
    query.save()
    ad = make_ad(query, bazos_id=9)
    ad.name = "Macbook nefunkcni deska"
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    run_filter_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.REJECTED
    assert delivery.filter_reason is not None
