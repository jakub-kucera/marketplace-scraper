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
from typing import cast

import pytest
from django.core.management import call_command
from django_q.models import Schedule

from bazos.const import DELIST_MAX_CHUNK_ROUNDS
from bazos.jobs import (
    HEARTBEAT,
    PRUNE_QUERY_RUNS,
    PRUNE_STATUS_LOGS,
    SCHEDULES,
    SWEEP_DELISTED,
    heartbeat,
)


def resolve(dotted: str):
    module_path, _, attribute = dotted.rpartition(".")
    return getattr(import_module(module_path), attribute)


# ---------------------------------------------------------------------------
# The dotted paths django-q2 persists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dotted", [SWEEP_DELISTED, HEARTBEAT, PRUNE_STATUS_LOGS, PRUNE_QUERY_RUNS]
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
