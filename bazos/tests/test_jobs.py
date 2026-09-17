"""Tests for the django-q2 task layer and its schedules.

The risks here are not in the library, so these do not test django-q2. They test the two
things that are ours and that fail *silently*:

- a schedule pointing at a dotted path that no longer imports (a rename looks like a
  refactor and stops the job forever, with no error anywhere), and
- `ensure_schedules` clobbering a cadence someone edited in the admin, which would make the
  admin control a lie.
"""
from importlib import import_module
from io import StringIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django_q.models import Schedule

from bazos.const import DELIST_MAX_CHUNK_ROUNDS
from bazos.jobs import (
    COMPARE_BAZOS_SCRAPERS,
    FETCH_FULL_DESCRIPTION,
    GEOCODE_POSTAL_CODE,
    REFRESH_AD,
    HEARTBEAT,
    PRUNE_QUERY_RUNS,
    PRUNE_STATUS_LOGS,
    RESCORE_ADS,
    SCHEDULES,
    SCORE_AD,
    SWEEP_DELISTED,
    SYNC_VINTED_CATALOGS,
    heartbeat,
)


def resolve(dotted: str):
    module_path, _, attribute = dotted.rpartition(".")
    return getattr(import_module(module_path), attribute)


# ---------------------------------------------------------------------------
# The dotted paths django-q2 persists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dotted",
    [
        SWEEP_DELISTED, HEARTBEAT, PRUNE_STATUS_LOGS, PRUNE_QUERY_RUNS,
        SCORE_AD, RESCORE_ADS, SYNC_VINTED_CATALOGS, COMPARE_BAZOS_SCRAPERS,
        GEOCODE_POSTAL_CODE, FETCH_FULL_DESCRIPTION, REFRESH_AD,
    ],
)
def test_every_task_path_resolves(dotted):
    """django-q2 stores the path as a string, so a rename fails at *run* time, in a worker,
    as a Failure row nobody is watching. Resolve them here instead."""
    assert callable(resolve(dotted))


def test_every_scheduled_path_resolves():
    for name, spec in SCHEDULES.items():
        assert callable(resolve(spec.func)), f"schedule {name} points at an unimportable path"


# ---------------------------------------------------------------------------
# ensure_schedules
# ---------------------------------------------------------------------------

def run_ensure():
    out = StringIO()
    call_command("ensure_schedules", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_creates_every_schedule():
    report = run_ensure()

    assert Schedule.objects.count() == len(SCHEDULES)
    for name in SCHEDULES:
        assert Schedule.objects.filter(name=name).exists()
        assert name in report


@pytest.mark.django_db
def test_is_idempotent():
    run_ensure()
    first = list(Schedule.objects.values_list("pk", flat=True))

    run_ensure()

    assert list(Schedule.objects.values_list("pk", flat=True)) == first


@pytest.mark.django_db
def test_does_not_overwrite_a_cadence_edited_in_the_admin():
    """Editing cadence in the admin is the whole reason for the queue; a deploy silently
    reverting that edit would make the page a control that does nothing."""
    run_ensure()
    schedule = Schedule.objects.get(name="cluster-heartbeat")
    schedule.minutes = 5
    schedule.save()

    run_ensure()

    schedule.refresh_from_db()
    assert schedule.minutes == 5


@pytest.mark.django_db
def test_repoints_a_schedule_whose_task_was_renamed():
    """The dotted path is ours to own — a stale one fails silently in a worker."""
    run_ensure()
    Schedule.objects.filter(name="delisting-sweep").update(func="bazos.jobs.gone_away")

    report = run_ensure()

    assert Schedule.objects.get(name="delisting-sweep").func == SWEEP_DELISTED
    assert "repointed" in report


@pytest.mark.django_db
def test_schedules_repeat_forever():
    """`repeats=-1`. A schedule that counts down to zero stops without ever erroring."""
    run_ensure()

    assert set(Schedule.objects.values_list("repeats", flat=True)) == {-1}


# ---------------------------------------------------------------------------
# The tasks themselves
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_heartbeat_returns_a_recorded_summary():
    """django-q2 stores the return value on the Success row, which is what makes the admin
    a run log — so a task that returns nothing is a blank row."""
    assert "alive at" in heartbeat()


@pytest.mark.django_db
def test_sweep_returns_the_command_summary(make_ad, query):
    from bazos.jobs import sweep_delisted

    result = sweep_delisted(limit=0)

    assert "due" in result


@pytest.mark.django_db
def test_prune_tasks_return_what_they_deleted():
    """A blank Success row is a run log that does not log anything."""
    from bazos.jobs import prune_query_runs, prune_status_logs

    assert "deleted" in prune_status_logs()
    assert "query runs" in prune_query_runs()


@pytest.mark.django_db
def test_a_failing_task_raises_rather_than_returning_quietly(monkeypatch):
    """A swallowed exception becomes a green Success row, which is the one thing a run log
    must never do."""
    from bazos import jobs

    def boom(*args, **kwargs):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(jobs, "call_command", boom)

    with pytest.raises(RuntimeError):
        jobs.sweep_delisted()


# ---------------------------------------------------------------------------
# Cluster configuration — the constraint that is not a tuning choice
# ---------------------------------------------------------------------------

def test_the_cluster_runs_exactly_one_worker():
    """JOB_QUEUE.md §2: the shared requests.Session and its Tor circuit are not safe for
    concurrent callers. Raising this needs the `requires_bazos_session` lock first, so it is
    pinned here rather than left to whoever next tunes throughput."""
    from django.conf import settings

    assert settings.Q_CLUSTER["workers"] == 1


def test_retry_exceeds_timeout():
    """Otherwise django-q2 re-queues a task that is still running, underneath itself."""
    from django.conf import settings

    # `settings.Q_CLUSTER` is typed as a plain mapping, so the values arrive as `object`.
    retry = cast(int, settings.Q_CLUSTER["retry"])
    timeout = cast(int, settings.Q_CLUSTER["timeout"])

    assert retry > timeout


def test_missed_schedules_do_not_replay():
    """catch_up=False: a schedule missed during downtime fires once on return and skips to
    the next future slot, rather than replaying every occurrence it slept through."""
    from django.conf import settings

    assert settings.Q_CLUSTER["catch_up"] is False


# ---------------------------------------------------------------------------
# The chunked sweep — the prerequisite for every interactive job
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_an_explicit_limit_runs_once_and_never_re_enqueues(monkeypatch):
    """`limit` given is the one-off: do exactly that much and stop."""
    from bazos import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))

    jobs.sweep_delisted(limit=5)

    assert queued == []


@pytest.mark.django_db
def test_a_chunk_that_leaves_work_queues_the_next_one(monkeypatch, make_ad):
    from bazos import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))
    # 3 due before the chunk, 1 after: progress was made and work remains.
    counts = iter([3, 1])
    monkeypatch.setattr(jobs, "call_command", lambda *a, **kw: None)
    monkeypatch.setattr(
        "bazos.delisting.due_for_check",
        lambda *a, **kw: _CountOnly(next(counts)),
    )

    result = jobs.sweep_delisted()

    assert len(queued) == 1
    assert queued[0][1]["rounds_left"] == DELIST_MAX_CHUNK_ROUNDS - 1
    assert "next chunk queued" in result


@pytest.mark.django_db
def test_a_chunk_that_clears_nothing_stops_instead_of_looping(monkeypatch):
    """The stop that matters. A chunk whose every batch was blocked leaves its ads due, so
    without this the job re-queues itself against a marketplace that is refusing us — a loop
    that looks like progress."""
    from bazos import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))
    counts = iter([3, 3])
    monkeypatch.setattr(jobs, "call_command", lambda *a, **kw: None)
    monkeypatch.setattr(
        "bazos.delisting.due_for_check", lambda *a, **kw: _CountOnly(next(counts))
    )

    result = jobs.sweep_delisted()

    assert queued == []
    assert "made no progress" in result


@pytest.mark.django_db
def test_the_round_budget_is_a_backstop_for_slow_progress(monkeypatch):
    """Separate from the no-progress stop: this covers a sweep that clears *some* ads every
    round but never finishes."""
    from bazos import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))
    counts = iter([3, 2])
    monkeypatch.setattr(jobs, "call_command", lambda *a, **kw: None)
    monkeypatch.setattr(
        "bazos.delisting.due_for_check", lambda *a, **kw: _CountOnly(next(counts))
    )

    result = jobs.sweep_delisted(rounds_left=1)

    assert queued == []
    assert "round budget spent" in result


class _CountOnly:
    """`due_for_check()` returns a QuerySet; the chunk logic only ever counts it."""

    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


# ---------------------------------------------------------------------------
# Price scoring
# ---------------------------------------------------------------------------

@pytest.fixture
def saved_ad(db):
    """`make_ad` returns an *unsaved* Ad and takes a query it no longer stores; these tasks
    take a pk, so they need a row."""
    from bazos.models import Ad, Marketplace

    def _factory(external_id=901):
        return Ad.objects.create(
            external_id=external_id, marketplace=Marketplace.BAZOS,
            url=f"https://pc.bazos.cz/inzerat/{external_id}/test.php",
            name="MacBook Pro 14 M1", price_raw="31 000 Kč", price=31000,
            location="Praha, 110 00", short_description="", publisher_name="Seller",
        )
    return _factory


@pytest.mark.django_db
def test_score_ad_reports_no_model_separately_from_a_decline(saved_ad):
    """Three outcomes, not two. "No registered model claims this ad" and "a model looked
    and had no opinion" are different facts, and only one of them is worth revisiting."""
    from bazos import jobs

    ad = saved_ad()

    with patch("bazos.pricing.scoring.score_ad", return_value=None):
        assert "no model claims it" in jobs.score_ad(ad.pk)

    declined = SimpleNamespace(
        declined_reason="damage words", model_name="macbook", predicted=None, discount_pct=None
    )
    with patch("bazos.pricing.scoring.score_ad", return_value=declined):
        assert "declined" in jobs.score_ad(ad.pk)

    scored = SimpleNamespace(
        declined_reason=None, model_name="macbook", predicted=31000, discount_pct=-12.0
    )
    with patch("bazos.pricing.scoring.score_ad", return_value=scored):
        assert "31000" in jobs.score_ad(ad.pk)


@pytest.mark.django_db
def test_score_ad_forces_a_refresh(saved_ad):
    """The freshness check keys on the ARTIFACT version, so a row written by older code
    short-circuits and comes back unchanged. The only reason to ask for one ad by hand is
    that the stored answer is suspect."""
    from bazos import jobs

    ad = saved_ad()
    with patch("bazos.pricing.scoring.score_ad", return_value=None) as predict:
        jobs.score_ad(ad.pk)

    assert predict.call_args.kwargs["refresh"] is True


@pytest.mark.django_db
def test_rescore_omits_model_when_not_given():
    """`--model` defaults to None in the command; passing it explicitly is harmless, but
    passing a *different* falsy value would silently narrow the backfill to nothing."""
    from bazos import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.rescore_ads()

    assert "model" not in call.call_args.kwargs
    assert call.call_args.kwargs["missing_features"] is False


@pytest.mark.django_db
def test_the_admin_action_queues_one_task_per_ad(saved_ad, monkeypatch):
    from django.contrib import admin as dj_admin
    from django.contrib.messages import INFO
    from django.test import RequestFactory

    from bazos.jobs import SCORE_AD
    from bazos.models import Ad

    first, second = saved_ad(901), saved_ad(902)
    model_admin = dj_admin.site._registry[Ad]
    captured: list[tuple[int, str]] = []
    monkeypatch.setattr(
        model_admin, "message_user",
        lambda req, msg, level=INFO, **kw: captured.append((level, msg)),
    )

    with patch("bazos.admin.async_task") as async_task, \
         patch("bazos.pricing.scoring.score_ad") as predict:
        model_admin.score_selected_ads(
            RequestFactory().post("/admin/bazos/ad/"),
            Ad.objects.filter(pk__in=[first.pk, second.pk]),
        )

    assert {call.args for call in async_task.call_args_list} == {
        (SCORE_AD, first.pk), (SCORE_AD, second.pk)
    }
    predict.assert_not_called()
    assert "Queued 2" in captured[0][1]


@pytest.mark.django_db
def test_vinted_catalog_sync_wraps_the_command():
    """The report is the point: `catalog_ids` live in a JSONField and are not an FK, so a
    retired node fails as an empty result rather than as an error."""
    from bazos import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.sync_vinted_catalogs()

    assert call.call_args.args[0] == "create_vinted_catalogs"


@pytest.mark.django_db
def test_scraper_parity_check_wraps_the_command():
    """The standing drift check for P21a's cutover: `BazosApiScraper` is registered but no
    Query selects it, so nothing would notice if it stopped agreeing with the HTML scraper."""
    from bazos import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.compare_bazos_scrapers(limit=3)

    assert call.call_args.args[0] == "compare_bazos_scrapers"
    assert call.call_args.kwargs["limit"] == 3


@pytest.mark.django_db
def test_parity_check_omits_limit_when_not_given():
    """`--limit` defaults to 5 in the command; passing None would override that with None."""
    from bazos import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.compare_bazos_scrapers()

    assert "limit" not in call.call_args.kwargs


# ---------------------------------------------------------------------------
# Geocoding one code on demand
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_an_already_cached_code_makes_no_request():
    """The common case when the action runs over a selection. A no-op that says so beats
    one that looks like a lookup."""
    from bazos import jobs
    from bazos.models import PostalCode

    PostalCode.objects.create(code="11000", city="Praha 1", latitude=50.08, longitude=14.42)

    with patch("bazos.geo.geocode_postal_code") as geocode:
        result = jobs.geocode_postal_code("110 00")

    geocode.assert_not_called()
    assert "already cached" in result


@pytest.mark.django_db
def test_an_unparseable_code_is_reported_not_raised():
    """A code the parser cannot read is a data problem to report, not a transport failure to
    retry — and a Failure row would say the wrong thing about it."""
    from bazos import jobs

    with patch("bazos.geo.geocode_postal_code") as geocode:
        result = jobs.geocode_postal_code("not a code")

    geocode.assert_not_called()
    assert "not a usable postal code" in result


@pytest.mark.django_db
def test_zip_php_not_knowing_a_code_is_distinct_from_being_blocked():
    """`None` from the geocoder is a real answer about the code. Being blocked raises, so
    the run log can tell "there is no such place" from "we could not ask"."""
    from bazos import jobs

    with patch("bazos.geo.geocode_postal_code", return_value=None), \
         patch("bazos.scraping.session.build_ip_changer"), \
         patch("bazos.scraping.session.with_rotation", side_effect=lambda c, op, **kw: op(None)):
        result = jobs.geocode_postal_code("99999")

    assert "unresolved" in result


@pytest.mark.django_db
def test_the_query_action_skips_queries_with_no_centre(query, monkeypatch):
    from django.contrib import admin as dj_admin
    from django.contrib.messages import INFO
    from django.test import RequestFactory

    from bazos.jobs import GEOCODE_POSTAL_CODE
    from bazos.models import Query

    query.filter_location_center = "11000"
    query.save()
    model_admin = dj_admin.site._registry[Query]
    captured: list[tuple[int, str]] = []
    monkeypatch.setattr(
        model_admin, "message_user",
        lambda req, msg, level=INFO, **kw: captured.append((level, msg)),
    )

    with patch("bazos.admin.async_task") as async_task:
        model_admin.geocode_filter_centres(
            RequestFactory().post("/admin/bazos/query/"), Query.objects.all()
        )

    assert [call.args for call in async_task.call_args_list] == [(GEOCODE_POSTAL_CODE, "11000")]
    assert "Queued 1" in captured[0][1]


@pytest.mark.django_db
def test_an_empty_detail_fetch_is_reported_not_raised(saved_ad):
    """A 410 on the API path, or a detail page carrying nothing. The request worked and the
    answer was "nothing here", so a Failure row would misdescribe it."""
    from bazos import jobs

    ad = saved_ad()
    with patch("bazos.enrichment.fetch_full_description", side_effect=lambda a, s: a), \
         patch("bazos.scraping.session.build_ip_changer"), \
         patch("bazos.scraping.session.with_rotation", side_effect=lambda c, op, **kw: op(None)):
        result = jobs.fetch_full_description(ad.pk)

    assert "no description returned" in result
