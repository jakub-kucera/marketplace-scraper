"""Tests for the run_sender pipeline stage.

Drives the real management command via ``--once`` (see run_sender.run_once).
These tests used to reimplement the loop body in a local ``_run_sender_once``
helper, which meant the command's own queryset — the APPROVED filter, the
``created`` ordering and the batch cap — was never executed by any test.

Operates on AdDelivery, not Ad, since the Ad/AdDelivery split moved pipeline
status there — see docs/archive/shipped/AD_DELIVERY_SPLIT.md.

DiscordSender.from_model is patched throughout, so no webhook is ever built and
nothing reaches the network.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command

from bazos.models import AdDelivery, AdStatus
from bazos.const import MAX_SEND_ATTEMPTS
from senders.exceptions import RateLimitError
from senders.models import Discord
from senders.services.discord_sender import DiscordSender


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def query_has_a_sender(query):
    """The shared `query` fixture leaves `sender` null, which every other test can
    ignore — this module cannot. run_once now fails a delivery whose query has no
    webhook (Query.sender is SET_NULL), so without this the tests below would assert
    against that path instead of the one they are about.
    """
    query.sender = Discord.objects.create(channel_name="fixture", url="https://discord.test/fixture")
    query.save()
    return query


def run_sender_once(send_side_effect=None):
    """Run one real run_sender batch. Returns the stand-in sender for assertions.

    ``send_side_effect`` is passed as side_effect to the fake sender's
    send_sendable. None means a no-op success.
    """
    fake_sender = MagicMock(spec=DiscordSender)
    if send_side_effect is not None:
        fake_sender.send_sendable.side_effect = send_side_effect

    with patch.object(DiscordSender, "from_model", return_value=fake_sender) as from_model:
        call_command("run_sender", once=True)
    fake_sender.from_model = from_model
    return fake_sender


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_approved_delivery_becomes_sent(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=1)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    run_sender_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SENT


@pytest.mark.django_db
def test_sent_delivery_has_sent_at(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=2)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    run_sender_once()

    delivery.refresh_from_db()
    assert delivery.sent_at is not None


@pytest.mark.django_db
def test_sender_is_handed_the_ad(query, make_ad, make_delivery):
    """The sender receives the Ad (the Sendable), not the AdDelivery."""
    ad = make_ad(query, bazos_id=3)
    ad.save()
    make_delivery(ad, query, status=AdStatus.APPROVED)

    fake_sender = run_sender_once()

    fake_sender.send_sendable.assert_called_once()
    (sendables,), _ = fake_sender.send_sendable.call_args
    assert [s.pk for s in sendables] == [ad.pk]


@pytest.mark.django_db
def test_sender_is_built_from_the_querys_discord_config(query, make_ad, make_delivery):
    """`select_related("query__sender")` must reach the right Discord row."""
    discord = Discord.objects.create(channel_name="deals", url="https://discord.test/hook")
    query.sender = discord
    query.save()
    ad = make_ad(query, bazos_id=4)
    ad.save()
    make_delivery(ad, query, status=AdStatus.APPROVED)

    fake_sender = run_sender_once()

    fake_sender.from_model.assert_called_once_with(discord)


# ---------------------------------------------------------------------------
# RateLimitError — retry counting
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_rate_limit_increments_send_attempts(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=5)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = 0
    delivery.save()

    run_sender_once(send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.send_attempts == 1
    assert delivery.status == AdStatus.APPROVED   # stays APPROVED for retry


@pytest.mark.django_db
def test_rate_limit_stays_approved_below_max(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=6)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 2  # one away from threshold
    delivery.save()

    run_sender_once(send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED
    assert delivery.send_attempts == MAX_SEND_ATTEMPTS - 1


@pytest.mark.django_db
def test_rate_limit_at_max_becomes_failed(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=7)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 1  # one more push → FAILED
    delivery.save()

    run_sender_once(send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.FAILED
    assert delivery.send_attempts == MAX_SEND_ATTEMPTS


@pytest.mark.django_db
def test_failed_delivery_has_no_sent_at(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=8)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 1
    delivery.save()

    run_sender_once(send_side_effect=RateLimitError())

    delivery.refresh_from_db()
    assert delivery.sent_at is None


# ---------------------------------------------------------------------------
# Deliveries in other statuses are not picked up
#
# These no longer hand-filter the queryset: the command's own
# `.filter(status=APPROVED)` is what is under test.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pending_delivery_not_processed_by_sender(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=9)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.PENDING)

    fake_sender = run_sender_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.PENDING
    fake_sender.send_sendable.assert_not_called()


@pytest.mark.django_db
def test_sent_delivery_not_reprocessed(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=10)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.SENT)

    fake_sender = run_sender_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.SENT
    fake_sender.send_sendable.assert_not_called()


@pytest.mark.django_db
def test_rejected_delivery_not_processed_by_sender(query, make_ad, make_delivery):
    ad = make_ad(query, bazos_id=11)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.REJECTED)

    fake_sender = run_sender_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.REJECTED
    fake_sender.send_sendable.assert_not_called()


# ---------------------------------------------------------------------------
# Batch cap — only reachable now that the command's own queryset runs
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_one_batch_sends_at_most_batch_size(query, make_ad, make_delivery, monkeypatch):
    monkeypatch.setattr("bazos.management.commands.run_sender.SENDER_BATCH_SIZE", 3)
    for i in range(5):
        ad = make_ad(query, bazos_id=100 + i)
        ad.save()
        make_delivery(ad, query, status=AdStatus.APPROVED)

    run_sender_once()

    assert AdDelivery.objects.filter(status=AdStatus.SENT).count() == 3
    assert AdDelivery.objects.filter(status=AdStatus.APPROVED).count() == 2


@pytest.mark.django_db
def test_once_returns_on_an_empty_queue(query):
    """--once must exit even with nothing to do, rather than sleeping forever."""
    run_sender_once()   # no deliveries exist; must not hang


# ---------------------------------------------------------------------------
# Missing sender — Query.sender is SET_NULL
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_delivery_without_a_sender_fails_instead_of_crashing(query, make_ad, make_delivery):
    """Deleting a Discord row must not wedge the sender.

    `Query.sender` is SET_NULL, so the query survives its webhook. Before the guard
    this raised AttributeError inside the atomic block — the batch rolled back with
    the rows still APPROVED, and the next poll crashed on the same ones.
    """
    query.sender = None
    query.save()
    ad = make_ad(query, bazos_id=200)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    fake_sender = run_sender_once()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.FAILED
    fake_sender.send_sendable.assert_not_called()


@pytest.mark.django_db
def test_a_senderless_delivery_does_not_block_the_rest_of_the_batch(make_ad, make_delivery, category):
    """The unsendable row is terminal, so later deliveries still go out this pass."""
    from bazos.models import Query

    orphaned = Query.objects.create(text="orphan", category=category, sender=None)
    discord = Discord.objects.create(channel_name="deals", url="https://discord.test/hook")
    wired = Query.objects.create(text="wired", category=category, sender=discord)

    bad_ad = make_ad(orphaned, bazos_id=201)
    bad_ad.save()
    good_ad = make_ad(wired, bazos_id=202)
    good_ad.save()
    bad = make_delivery(bad_ad, orphaned, status=AdStatus.APPROVED)
    good = make_delivery(good_ad, wired, status=AdStatus.APPROVED)

    run_sender_once()

    bad.refresh_from_db()
    good.refresh_from_db()
    assert bad.status == AdStatus.FAILED
    assert good.status == AdStatus.SENT
