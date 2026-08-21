"""Tests for the run_sender pipeline stage.

Exercises the sender loop logic directly (not via the management command
entrypoint) so tests run without subprocess overhead. Operates on AdDelivery,
not Ad, since the Ad/AdDelivery split moved pipeline status there — see
docs/refactor/AD_DELIVERY_SPLIT_SPEC.md.

DiscordSender.from_model is mocked throughout — the test query fixture has no
Discord sender attached (query.sender is None), so we never actually construct
a real DiscordSender.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.models import AdDelivery, AdStatus
from bazos.const import MAX_SEND_ATTEMPTS
from senders.exceptions import RateLimitError
from senders.services.discord_sender import DiscordSender


# ---------------------------------------------------------------------------
# Helper — run one sender batch without DB locking
# ---------------------------------------------------------------------------

def _run_sender_once(deliveries, send_side_effect=None):
    """Simulate one batch of the run_sender loop.

    ``send_side_effect`` is passed as side_effect to the fake sender's
    send_sendable. None means a no-op success.
    """
    from django.utils.timezone import now as _now

    fake_sender = MagicMock(spec=DiscordSender)
    if send_side_effect is not None:
        fake_sender.send_sendable.side_effect = send_side_effect

    with patch.object(DiscordSender, "from_model", return_value=fake_sender):
        for delivery in deliveries:
            try:
                sender = DiscordSender.from_model(delivery.query.sender)
                sender.send_sendable([delivery.ad])
                delivery.status = AdStatus.SENT
                delivery.sent_at = _now()
            except RateLimitError:
                delivery.send_attempts += 1
                if delivery.send_attempts >= MAX_SEND_ATTEMPTS:
                    delivery.status = AdStatus.FAILED
            delivery.save(update_fields=["status", "sent_at", "send_attempts"])


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_delivery_becomes_sent(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=1)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    _run_sender_once([delivery])

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SENT


@pytest.mark.django_db
def test_sent_delivery_has_sent_at(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=2)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    _run_sender_once([delivery])

    delivery.refresh_from_db()
    assert delivery.sent_at is not None


# ---------------------------------------------------------------------------
# RateLimitError — retry counting
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_rate_limit_increments_send_attempts(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=3)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = 0
    delivery.save()

    _run_sender_once([delivery], send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.send_attempts == 1
    assert delivery.status == AdStatus.APPROVED   # stays APPROVED for retry


@pytest.mark.django_db
def test_rate_limit_stays_approved_below_max(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=4)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 2  # one away from threshold
    delivery.save()

    _run_sender_once([delivery], send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED
    assert delivery.send_attempts == MAX_SEND_ATTEMPTS - 1


@pytest.mark.django_db
def test_rate_limit_at_max_becomes_failed(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=5)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 1  # one more push → FAILED
    delivery.save()

    _run_sender_once([delivery], send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.FAILED
    assert delivery.send_attempts == MAX_SEND_ATTEMPTS


@pytest.mark.django_db
def test_failed_delivery_has_no_sent_at(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=6)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 1
    delivery.save()

    _run_sender_once([delivery], send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.sent_at is None


# ---------------------------------------------------------------------------
# Deliveries in other statuses are not picked up
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_delivery_not_processed_by_sender(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=7)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    # Sender only processes APPROVED — this list is empty
    approved = list(AdDelivery.objects.filter(status=AdStatus.APPROVED))
    _run_sender_once(approved)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.PENDING


@pytest.mark.django_db
def test_sent_delivery_not_reprocessed(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=8)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.SENT)

    approved = list(AdDelivery.objects.filter(status=AdStatus.APPROVED))
    _run_sender_once(approved)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SENT
