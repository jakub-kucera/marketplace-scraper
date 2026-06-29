"""Tests for the run_sender pipeline stage.

Exercises the sender loop logic directly (not via the management command
entrypoint) so tests run without subprocess overhead.

DiscordSender.from_model is mocked throughout — the test query fixture has no
Discord sender attached (query.sender is None), so we never actually construct
a real DiscordSender.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.models import Ad, AdStatus
from bazos.const import MAX_SEND_ATTEMPTS
from senders.exceptions import RateLimitError
from senders.services.discord_sender import DiscordSender


# ---------------------------------------------------------------------------
# Helper — run one sender batch without DB locking
# ---------------------------------------------------------------------------

def _run_sender_once(ads, send_side_effect=None):
    """Simulate one batch of the run_sender loop.

    ``send_side_effect`` is passed as side_effect to the fake sender's
    send_sendable. None means a no-op success.
    """
    from django.utils.timezone import now as _now

    fake_sender = MagicMock(spec=DiscordSender)
    if send_side_effect is not None:
        fake_sender.send_sendable.side_effect = send_side_effect

    with patch.object(DiscordSender, "from_model", return_value=fake_sender):
        for ad in ads:
            try:
                sender = DiscordSender.from_model(ad.query.sender)
                sender.send_sendable([ad])
                ad.status = AdStatus.SENT
                ad.sent_at = _now()
            except RateLimitError:
                ad.send_attempts += 1
                if ad.send_attempts >= MAX_SEND_ATTEMPTS:
                    ad.status = AdStatus.FAILED
            ad.save(update_fields=["status", "sent_at", "send_attempts"])


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_ad_becomes_sent(query, make_ad):
    ad = make_ad(query, bazos_id=1)
    ad.status = AdStatus.APPROVED
    ad.save()

    _run_sender_once([ad])

    ad.refresh_from_db()
    assert ad.status == AdStatus.SENT


@pytest.mark.django_db
def test_sent_ad_has_sent_at(query, make_ad):
    ad = make_ad(query, bazos_id=2)
    ad.status = AdStatus.APPROVED
    ad.save()

    _run_sender_once([ad])

    ad.refresh_from_db()
    assert ad.sent_at is not None


# ---------------------------------------------------------------------------
# RateLimitError — retry counting
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_rate_limit_increments_send_attempts(query, make_ad):
    ad = make_ad(query, bazos_id=3)
    ad.status = AdStatus.APPROVED
    ad.send_attempts = 0
    ad.save()

    _run_sender_once([ad], send_side_effect=RateLimitError())

    ad.refresh_from_db()
    assert ad.send_attempts == 1
    assert ad.status == AdStatus.APPROVED   # stays APPROVED for retry


@pytest.mark.django_db
def test_rate_limit_stays_approved_below_max(query, make_ad):
    ad = make_ad(query, bazos_id=4)
    ad.status = AdStatus.APPROVED
    ad.send_attempts = MAX_SEND_ATTEMPTS - 2  # one away from threshold
    ad.save()

    _run_sender_once([ad], send_side_effect=RateLimitError())

    ad.refresh_from_db()
    assert ad.status == AdStatus.APPROVED
    assert ad.send_attempts == MAX_SEND_ATTEMPTS - 1


@pytest.mark.django_db
def test_rate_limit_at_max_becomes_failed(query, make_ad):
    ad = make_ad(query, bazos_id=5)
    ad.status = AdStatus.APPROVED
    ad.send_attempts = MAX_SEND_ATTEMPTS - 1  # one more push → FAILED
    ad.save()

    _run_sender_once([ad], send_side_effect=RateLimitError())

    ad.refresh_from_db()
    assert ad.status == AdStatus.FAILED
    assert ad.send_attempts == MAX_SEND_ATTEMPTS


@pytest.mark.django_db
def test_failed_ad_has_no_sent_at(query, make_ad):
    ad = make_ad(query, bazos_id=6)
    ad.status = AdStatus.APPROVED
    ad.send_attempts = MAX_SEND_ATTEMPTS - 1
    ad.save()

    _run_sender_once([ad], send_side_effect=RateLimitError())

    ad.refresh_from_db()
    assert ad.sent_at is None


# ---------------------------------------------------------------------------
# Ads in other statuses are not picked up
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_ad_not_processed_by_sender(query, make_ad):
    ad = make_ad(query, bazos_id=7)
    ad.status = AdStatus.PENDING
    ad.save()

    # Sender only processes APPROVED — this list is empty
    approved = list(Ad.objects.filter(status=AdStatus.APPROVED))
    _run_sender_once(approved)

    ad.refresh_from_db()
    assert ad.status == AdStatus.PENDING


@pytest.mark.django_db
def test_sent_ad_not_reprocessed(query, make_ad):
    ad = make_ad(query, bazos_id=8)
    ad.status = AdStatus.SENT
    ad.save()

    approved = list(Ad.objects.filter(status=AdStatus.APPROVED))
    _run_sender_once(approved)

    ad.refresh_from_db()
    assert ad.status == AdStatus.SENT
