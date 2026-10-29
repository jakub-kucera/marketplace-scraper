"""Tests for the daily digest's impure half: what it collects, when it fires, and how it
survives Discord being unavailable.

The renderer is tested separately (`test_daily_digest_render.py`); nothing here asserts on
wording. What is asserted is the three things that would make the digest actively
misleading — bait at the top of the drops list, one listing occupying half of it, and a
failed POST recorded as a failed *job* when the digest itself was fine.
"""
from datetime import datetime, time, timedelta
from unittest.mock import Mock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from marketplace.digest.collect import DROP_MAX_PCT, MAX_DROP_ROWS, collect
from marketplace.jobs import DAILY_DIGEST, SCHEDULES, ScheduleSpec, daily_digest
from marketplace.management.commands.ensure_schedules import first_run
from marketplace.models import Ad, AdDelivery, AdStatus, Marketplace, PriceChange, PriceType
from senders.exceptions import RateLimitError
from senders.models import Discord


def _ad(n, marketplace=Marketplace.BAZOS, price=50_000):
    return Ad.objects.create(
        external_id=n, marketplace=marketplace, url=f"https://pc.bazos.cz/inzerat/{n}/x.php",
        name=f"Ad {n}", price_raw=f"{price} Kč", price=price, price_type=PriceType.EXACT,
        location="Praha", short_description="x", publisher_name="x",
    )


def _change(ad, old, new, hours_ago=1):
    change = PriceChange.objects.create(
        ad=ad, old_price=f"{old} Kč", new_price=f"{new} Kč",
        old_price_amount=old, new_price_amount=new,
    )
    PriceChange.objects.filter(pk=change.pk).update(
        created=timezone.now() - timedelta(hours=hours_ago)
    )
    return change


@pytest.mark.django_db
def test_an_empty_installation_still_produces_a_digest():
    """Nothing has ever run. Every headline number has to be a number."""
    data = collect()

    assert data.found == 0 and data.notified == 0
    assert len(data.ads_values) == len(data.ads_labels)
    assert data.drops == []


@pytest.mark.django_db
def test_a_bait_drop_does_not_head_the_list():
    """Measured on production: a phone "dropped" 35 990 → 1 000. Ranking raw percentage
    puts that first every time, and the row is worth nothing."""
    _change(_ad(1), 35_990, 1_000)
    _change(_ad(2), 61_000, 47_000)

    drops = collect().drops

    assert [d.old for d in drops] == [61_000]
    assert all(d.pct <= DROP_MAX_PCT for d in drops)


@pytest.mark.django_db
def test_a_cheap_item_losing_most_of_its_price_is_not_a_find():
    """200 → 80 is 60% off and worth nothing; without a floor it outranks every real one."""
    _change(_ad(1, price=80), 200, 80)

    assert collect().drops == []


@pytest.mark.django_db
def test_one_listing_occupies_one_row_however_often_it_changes():
    """A flip-flopping seller would otherwise fill three of eight slots with one item.
    The net move — highest old to lowest new — is what gets reported."""
    ad = _ad(1)
    _change(ad, 61_000, 55_000, hours_ago=5)
    _change(ad, 55_000, 58_000, hours_ago=4)
    _change(ad, 58_000, 52_000, hours_ago=3)

    drops = collect().drops

    assert len(drops) == 1
    assert (drops[0].old, drops[0].new) == (61_000, 52_000)


@pytest.mark.django_db
def test_vinted_price_moves_are_excluded():
    """Its prices are PLN converted at a rate that moves daily, which manufactures changes
    nobody made (CROSS_MARKETPLACE_MACBOOK.md §5.4)."""
    _change(_ad(1, marketplace=Marketplace.VINTED), 61_000, 47_000)

    assert collect().drops == []


@pytest.mark.django_db
def test_a_change_older_than_the_window_is_not_todays_news():
    _change(_ad(1), 61_000, 47_000, hours_ago=30)

    assert collect().drops == []


@pytest.mark.django_db
def test_the_drops_list_is_bounded():
    for n in range(MAX_DROP_ROWS + 5):
        _change(_ad(n), 61_000, 61_000 - 1_000 * (n + 1))

    assert len(collect().drops) == MAX_DROP_ROWS


@pytest.mark.django_db
def test_headline_counts_cover_the_last_day_not_all_history(query, make_ad):
    old = make_ad(query, 1)
    old.save()
    Ad.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(days=3))
    recent = make_ad(query, 2)
    recent.save()
    AdDelivery.objects.create(ad=recent, query=query, status=AdStatus.SENT,
                              sent_at=timezone.now())

    data = collect()

    assert data.found == 1
    assert data.notified == 1


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_job_posts_to_digest_channels_only():
    Discord.objects.create(channel_name="digest", url="https://d.test/1", for_daily_digest=True)
    Discord.objects.create(channel_name="summary", url="https://d.test/2", for_summary=True)

    with patch("senders.services.discord_webhook.post_embeds") as post:
        result = daily_digest()

    assert post.call_count == 1
    assert post.call_args.args[0] == "https://d.test/1"
    assert "1 channel" in result


@pytest.mark.django_db
def test_no_configured_channel_is_reported_not_raised():
    """A misconfiguration should be legible on the Success row, not a red Failure with a
    traceback nobody can act on."""
    assert "no for_daily_digest channel" in daily_digest()


@pytest.mark.django_db
def test_discord_being_rate_limited_does_not_fail_the_job():
    """The digest was built correctly; Discord refusing it for four seconds is not a
    defect, and letting it raise would spend `max_attempts` re-running the whole
    collection for a message that is already rendered."""
    Discord.objects.create(channel_name="digest", url="https://d.test/1", for_daily_digest=True)

    with patch("senders.services.discord_webhook.post_embeds",
               side_effect=RateLimitError(retry_after=4)):
        result = daily_digest()

    assert "1 failed" in result


@pytest.mark.django_db
def test_a_broken_renderer_does_fail_the_job():
    """The other half of the same decision: a bug here is a real defect, and a `Failure`
    row with a traceback is the report we want."""
    Discord.objects.create(channel_name="digest", url="https://d.test/1", for_daily_digest=True)

    with patch("marketplace.digest.render.render", side_effect=TypeError("boom")):
        with pytest.raises(TypeError):
            daily_digest()


# ---------------------------------------------------------------------------
# 13:00
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_digest_is_scheduled_daily_at_one_in_the_afternoon():
    spec = SCHEDULES["daily-digest"]

    assert spec.func == DAILY_DIGEST
    assert spec.schedule_type == Schedule.DAILY
    assert spec.at == time(13, 0)


@pytest.mark.parametrize(
    ("now_local", "expected_day"),
    [("2026-09-21 09:00", 21), ("2026-09-21 13:00", 22), ("2026-09-21 20:00", 22)],
)
def test_the_first_run_is_the_next_one_oclock_not_tomorrow_whenever_we_deployed(
    now_local, expected_day
):
    """Without this a DAILY row means "24 h after whenever the deploy happened", which for
    something a person reads at lunch is the one thing it must not mean."""
    now = timezone.make_aware(datetime.strptime(now_local, "%Y-%m-%d %H:%M"))
    spec = ScheduleSpec(DAILY_DIGEST, Schedule.DAILY, at=time(13, 0))

    run = first_run(spec, now=now)

    assert timezone.localtime(run).hour == 13
    assert timezone.localtime(run).day == expected_day
    assert run > now


def test_a_spec_without_a_time_still_starts_immediately():
    """Every other schedule is cadence-only; anchoring them would change their meaning."""
    now = timezone.now()

    assert first_run(ScheduleSpec(DAILY_DIGEST, Schedule.WEEKLY), now=now) == now


@pytest.mark.django_db
def test_ensure_schedules_creates_the_row_at_one_and_leaves_an_edited_time_alone():
    """Editing the cadence in the admin is a feature; a deploy reverting it silently would
    make the admin control a lie."""
    call_command("ensure_schedules", stdout=Mock())
    row = Schedule.objects.get(name="daily-digest")
    assert timezone.localtime(row.next_run).hour == 13

    moved = timezone.localtime(row.next_run) + timedelta(hours=5)
    Schedule.objects.filter(pk=row.pk).update(next_run=moved)
    call_command("ensure_schedules", stdout=Mock())

    row.refresh_from_db()
    assert timezone.localtime(row.next_run).hour == 18
