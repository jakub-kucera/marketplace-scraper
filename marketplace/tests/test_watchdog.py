from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from marketplace.const import WATCHDOG_FILTER_SILENCE, WATCHDOG_SCRAPER_SILENCE, WATCHDOG_SENDER_SILENCE
from marketplace.jobs import PIPELINE_WATCHDOG, SCHEDULES, pipeline_watchdog
from marketplace.models import AdDelivery, AdStatus, QueryRun
from marketplace.watchdog import find_stalls
from senders.models import Discord

MINUTE = timedelta(minutes=1)


@pytest.fixture
def now():
    return timezone.now()


def _run(query, started, success=True):
    return QueryRun.objects.create(query=query, run_start=started, success=success)


def _delivery(make_ad, make_delivery, query, external_id, status, created, sent_at=None):
    ad = make_ad(query, external_id)
    ad.save()
    delivery = make_delivery(ad, query, status=status)
    AdDelivery.objects.filter(pk=delivery.pk).update(created=created, sent_at=sent_at)
    return delivery


# ---------------------------------------------------------------------------
# scraper
# ---------------------------------------------------------------------------

def test_a_recent_success_is_healthy(query, now):
    _run(query, now - WATCHDOG_SCRAPER_SILENCE + MINUTE)

    assert find_stalls(now) == []


def test_only_failed_runs_since_the_threshold_is_a_scraper_stall(query, now):
    """A blocked or crashing scraper still writes QueryRun rows - they just never succeed."""
    _run(query, now - WATCHDOG_SCRAPER_SILENCE - MINUTE)
    _run(query, now - 10 * MINUTE, success=False)

    stalls = find_stalls(now)

    assert len(stalls) == 1 and "scraper" in stalls[0]


def test_no_run_at_all_is_a_scraper_stall(query, now):
    assert ["scraper" in s for s in find_stalls(now)] == [True]


def test_nothing_enabled_means_nothing_to_watch(query, now):
    query.enabled = False
    query.save()

    assert find_stalls(now) == []


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------

def test_an_old_pending_delivery_is_a_filter_stall(query, now, make_ad, make_delivery):
    _run(query, now)
    _delivery(make_ad, make_delivery, query, 1, AdStatus.PENDING, now - 2 * MINUTE)
    _delivery(make_ad, make_delivery, query, 2, AdStatus.PENDING, now - WATCHDOG_FILTER_SILENCE - MINUTE)

    stalls = find_stalls(now)

    assert len(stalls) == 1 and "filter" in stalls[0]


def test_a_fresh_pending_delivery_is_just_the_queue(query, now, make_ad, make_delivery):
    _run(query, now)
    _delivery(make_ad, make_delivery, query, 1, AdStatus.PENDING, now - WATCHDOG_FILTER_SILENCE + MINUTE)
    _delivery(make_ad, make_delivery, query, 2, AdStatus.REJECTED, now - 30 * WATCHDOG_FILTER_SILENCE)

    assert find_stalls(now) == []


# ---------------------------------------------------------------------------
# sender
# ---------------------------------------------------------------------------

def test_approved_waiting_with_nothing_sent_lately_is_a_sender_stall(query, now, make_ad, make_delivery):
    _run(query, now)
    _delivery(make_ad, make_delivery, query, 1, AdStatus.SENT, now - 3 * WATCHDOG_SENDER_SILENCE,
              sent_at=now - WATCHDOG_SENDER_SILENCE - MINUTE)
    _delivery(make_ad, make_delivery, query, 2, AdStatus.APPROVED, now - 5 * MINUTE)

    stalls = find_stalls(now)

    assert len(stalls) == 1 and "sender" in stalls[0]


def test_a_sender_that_is_still_sending_is_healthy(query, now, make_ad, make_delivery):
    """APPROVED rows waiting behind a Discord rate limit are backpressure, not a stall."""
    _run(query, now)
    _delivery(make_ad, make_delivery, query, 1, AdStatus.SENT, now - MINUTE, sent_at=now - MINUTE)
    _delivery(make_ad, make_delivery, query, 2, AdStatus.APPROVED, now - 3 * WATCHDOG_SENDER_SILENCE)

    assert find_stalls(now) == []


def test_a_quiet_market_is_not_a_sender_stall(query, now, make_ad, make_delivery):
    _run(query, now)
    _delivery(make_ad, make_delivery, query, 1, AdStatus.SENT, now - 10 * WATCHDOG_SENDER_SILENCE,
              sent_at=now - 10 * WATCHDOG_SENDER_SILENCE)

    assert find_stalls(now) == []


# ---------------------------------------------------------------------------
# the job
# ---------------------------------------------------------------------------

def test_the_job_posts_each_stall_to_the_logging_channels(query):
    Discord.objects.create(channel_name="log", url="https://d.test/1", for_logging=True)
    Discord.objects.create(channel_name="ads", url="https://d.test/2")
    fake = MagicMock()

    with patch("marketplace.jobs.DiscordSender.from_model", return_value=fake) as from_model:
        summary = pipeline_watchdog()

    assert [c.args[0].channel_name for c in from_model.call_args_list] == ["log"]
    assert "scraper" in fake.send_plain.call_args.args[0]
    assert "1 stall" in summary


def test_a_healthy_pipeline_posts_nothing(query):
    _run(query, timezone.now())
    Discord.objects.create(channel_name="log", url="https://d.test/1", for_logging=True)

    with patch("marketplace.jobs.DiscordSender.from_model") as from_model:
        summary = pipeline_watchdog()

    from_model.assert_not_called()
    assert summary == "healthy"


def test_a_refusing_webhook_does_not_fail_the_job(query):
    Discord.objects.create(channel_name="log", url="https://d.test/1", for_logging=True)
    fake = MagicMock()
    fake.send_plain.side_effect = RuntimeError("429")

    with patch("marketplace.jobs.DiscordSender.from_model", return_value=fake):
        assert "1 stall" in pipeline_watchdog()


def test_the_watchdog_is_scheduled_hourly():
    spec = SCHEDULES["pipeline-watchdog"]

    assert spec.func == PIPELINE_WATCHDOG and spec.minutes == 60
