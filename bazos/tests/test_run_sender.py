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


# ---------------------------------------------------------------------------
# Rate limiting is backpressure, not failure
# ---------------------------------------------------------------------------

def _rate_limited(retry_after):
    from senders.exceptions import RateLimitError

    return RateLimitError(retry_after=retry_after)


@pytest.mark.django_db
def test_a_retry_after_does_not_spend_the_failure_budget(query, make_ad, make_delivery):
    """Discord saying "wait 2s" is flow control. Charging it to MAX_SEND_ATTEMPTS is how
    65 deliveries were marked permanently FAILED inside about a second each."""
    ad = make_ad(query, bazos_id=300)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    run_sender_once(send_side_effect=_rate_limited(2.0))

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.APPROVED, "must stay queued, not fail"
    assert delivery.send_attempts == 0, "backpressure is not an attempt"


@pytest.mark.django_db
def test_a_refusal_with_no_retry_after_does_spend_it(query, make_ad, make_delivery):
    """That is the case the budget exists for: refused, and we cannot tell for how long."""
    ad = make_ad(query, bazos_id=301)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)

    run_sender_once(send_side_effect=_rate_limited(None))

    delivery.refresh_from_db()
    assert delivery.send_attempts == 1
    assert delivery.status == AdStatus.APPROVED


@pytest.mark.django_db
def test_one_rate_limited_channel_does_not_block_the_others(make_ad, make_delivery, category):
    """Discord rate-limits per webhook, and the batch is the oldest N by `created`. A burst
    on one channel must not fill the batch with rows nobody can send."""
    from unittest.mock import MagicMock

    from bazos.models import Query
    from senders.services.discord_sender import DiscordSender

    busy_channel = Discord.objects.create(channel_name="busy", url="https://discord.test/busy")
    calm_channel = Discord.objects.create(channel_name="calm", url="https://discord.test/calm")
    busy_q = Query.objects.create(text="busy", category=category, sender=busy_channel,
                                  price_lower=0, price_upper=0, new_query=False)
    calm_q = Query.objects.create(text="calm", category=category, sender=calm_channel,
                                  price_lower=0, price_upper=0, new_query=False)

    busy_deliveries = []
    for i in range(3):                       # oldest in the queue, all for the busy channel
        ad = make_ad(busy_q, bazos_id=400 + i)
        ad.save()
        busy_deliveries.append(make_delivery(ad, busy_q, status=AdStatus.APPROVED))
    calm_ad = make_ad(calm_q, bazos_id=500)
    calm_ad.save()
    calm_delivery = make_delivery(calm_ad, calm_q, status=AdStatus.APPROVED)

    def per_channel(sendables):
        # The fake sender is shared, so route on the ad that reached it.
        if sendables[0].external_id < 500:
            raise _rate_limited(5.0)

    fake = MagicMock(spec=DiscordSender)
    fake.send_sendable.side_effect = per_channel
    with patch.object(DiscordSender, "from_model", return_value=fake):
        call_command("run_sender", once=True)

    calm_delivery.refresh_from_db()
    assert calm_delivery.status == AdStatus.SENT, "the calm channel must still go out"
    for d in busy_deliveries:
        d.refresh_from_db()
        assert d.status == AdStatus.APPROVED
        assert d.send_attempts == 0


@pytest.mark.django_db
def test_a_cooling_channel_is_excluded_from_the_next_batch(query, make_ad, make_delivery):
    """Excluded in the queryset, not skipped in Python — otherwise a burst fills the batch."""
    from unittest.mock import MagicMock

    from bazos.management.commands.run_sender import Command
    from senders.services.discord_sender import DiscordSender

    ad = make_ad(query, bazos_id=600)
    ad.save()
    make_delivery(ad, query, status=AdStatus.APPROVED)

    command = Command()
    fake = MagicMock(spec=DiscordSender)
    fake.send_sendable.side_effect = _rate_limited(30.0)
    with patch.object(DiscordSender, "from_model", return_value=fake):
        command.run_once()                       # trips the cooldown
        fake.send_sendable.side_effect = None
        handled = command.run_once()             # ...second pass must not even select it

    assert handled == 0
    assert fake.send_sendable.call_count == 1


@pytest.mark.django_db
def test_a_permanent_failure_is_announced_to_the_logging_channel(query, make_ad, make_delivery):
    """A lost notification used to be silent — 65 accumulated before anyone noticed."""
    from unittest.mock import MagicMock

    from senders.services.discord_sender import DiscordSender

    Discord.objects.create(channel_name="log", url="https://discord.test/log", for_logging=True)
    ad = make_ad(query, bazos_id=700)
    ad.save()
    delivery = make_delivery(ad, query, status=AdStatus.APPROVED)
    delivery.send_attempts = MAX_SEND_ATTEMPTS - 1
    delivery.save()

    fake = MagicMock(spec=DiscordSender)
    fake.send_sendable.side_effect = _rate_limited(None)
    with patch.object(DiscordSender, "from_model", return_value=fake):
        call_command("run_sender", once=True)

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.FAILED
    fake.send_plain.assert_called_once()
    assert "permanently failed" in fake.send_plain.call_args[0][0]
