"""Task functions for the django-q2 cluster, and the schedules that drive them.

A task here is a thin, importable callable — django-q2 stores a *dotted path*, so a task must
stay importable at that path or its schedule silently stops firing. Renaming one of these is
a migration, not a refactor.

Two rules this module keeps:

- **A task returns a short string and lets exceptions escape.** django-q2 records the return
  value on `Success` and the traceback on `Failure`, so the admin becomes the run log for
  free. Swallowing an exception to "be safe" would turn a failure into a green row, which is
  the one thing a run log must never do.
- **Nothing here holds the Tor session open across tasks.** Each task builds what it needs
  and drops it, so the single worker's serialisation (`Q_CLUSTER["workers"] = 1`) is the
  only concurrency control required — see JOB_QUEUE.md §2.
"""
import logging
from dataclasses import dataclass

from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

logger = logging.getLogger(__name__)

#: Dotted paths, because that is what django-q2 persists in a `Schedule` row. Defined once
#: here so a rename breaks an import rather than silently orphaning a schedule.
SWEEP_DELISTED = "bazos.jobs.sweep_delisted"
HEARTBEAT = "bazos.jobs.heartbeat"
PRUNE_STATUS_LOGS = "bazos.jobs.prune_status_logs"
PRUNE_QUERY_RUNS = "bazos.jobs.prune_query_runs"


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
#
# Declared here rather than in the management command so another app can contribute one
# without `bazos` importing it. `refprice` already registers a filter rule this way; a
# schedule is the same seam for the same reason — deleting that app must break nothing here.

@dataclass(frozen=True)
class ScheduleSpec:
    func: str
    schedule_type: str
    minutes: int | None = None
    kwargs: dict | None = None


#: name -> spec. Cadence is editable in the admin afterwards; this only declares the row.
SCHEDULES: dict[str, ScheduleSpec] = {
    "delisting-sweep": ScheduleSpec(
        SWEEP_DELISTED,
        Schedule.DAILY,
        # Daily is the right resolution: `removed_at` is stamped when the sweep notices, so
        # finer cadence buys precision the question ("how many days to disappear") cannot
        # use, at a linear cost in requests.
        #
        # No `limit` in kwargs, which is what puts the task in chunked mode: it works a
        # slice, yields the single worker, and re-enqueues itself while ads remain due. A
        # backlog run as one task would make every other job wait for the whole backfill.
    ),
    "cluster-heartbeat": ScheduleSpec(HEARTBEAT, Schedule.MINUTES, minutes=60),
    # Weekly, not daily: both prunes are by age, so running more often deletes the same rows
    # a few days earlier at the cost of a long DELETE competing with the scraper for locks.
    "prune-status-logs": ScheduleSpec(PRUNE_STATUS_LOGS, Schedule.WEEKLY),
    "prune-query-runs": ScheduleSpec(PRUNE_QUERY_RUNS, Schedule.WEEKLY),
}


def register_schedule(name: str, spec: ScheduleSpec) -> None:
    """Add a schedule from another app, at that app's `AppConfig.ready()`.

    Mutating the registry rather than importing into it is what keeps the dependency
    pointing inward — `bazos` never has to know which other apps exist. Registering twice is
    a no-op so a double `ready()` (Django calls it once, test harnesses are less reliable)
    cannot produce two rows for one job.
    """
    SCHEDULES.setdefault(name, spec)


def sweep_delisted(limit: int | None = None, rounds_left: int | None = None) -> str:
    """Run the delisting sweep. See `bazos/delisting.py` for what it does and does not mean.

    Wraps the management command rather than reimplementing it: the command is the documented
    entry point and stays usable by hand (`--dry-run`, `--limit`) for the one-off backfill.

    **Two modes, chosen by `limit`.**

    - `limit` given — do exactly that much and stop. The explicit one-off.
    - `limit` omitted — work in chunks of `DELIST_CHUNK_SIZE` and **re-enqueue itself** while
      ads remain due. This is what the schedule uses.

    Chunking is not throughput tuning; it is what stops a backfill monopolising the cluster.
    `Q_CLUSTER["workers"] = 1` is a correctness constraint (the Tor session is not safe for
    concurrent callers), so *every* other job waits behind this one. A ~29 000-ad backlog run
    as a single task means an admin-triggered lookup sits behind the whole thing; run as
    chunks, it waits about a minute.

    No offset is threaded through, and that is deliberate: a swept ad has `last_seen_at`
    stamped, so it drops out of `due_for_check()` on its own. Paginating instead would skip
    exactly as many rows as the previous chunk removed from the result set.

    **Two independent stops**, because a re-enqueueing task that cannot finish is a loop that
    looks like progress: the round budget, and "this chunk cleared nothing". The second is
    the one that matters — a chunk whose every batch was blocked leaves its ads due, and
    without it the job would re-queue itself against a marketplace that is refusing us.
    """
    from io import StringIO

    from django_q.tasks import async_task

    from bazos.const import DELIST_CHUNK_SIZE, DELIST_MAX_CHUNK_ROUNDS
    from bazos.delisting import due_for_check

    one_off = limit is not None
    chunk = limit if one_off else DELIST_CHUNK_SIZE
    rounds_left = DELIST_MAX_CHUNK_ROUNDS if rounds_left is None else rounds_left

    due_before = 0 if one_off else due_for_check().count()

    out = StringIO()
    call_command("check_delisted", limit=chunk, stdout=out)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("Delisting sweep finished: %s", summary)

    if one_off:
        return summary

    due_after = due_for_check().count()
    if due_after == 0:
        return f"{summary} | nothing left due"
    if due_after >= due_before:
        # Every batch was skipped — blocked circuits, or a transport that cannot answer.
        # Re-queueing would spend the round budget asking the same question.
        logger.warning("Delisting chunk cleared nothing; %d still due", due_after)
        return f"{summary} | {due_after} still due, chunk made no progress — stopping"
    if rounds_left <= 1:
        return f"{summary} | {due_after} still due, round budget spent — stopping"

    async_task(SWEEP_DELISTED, rounds_left=rounds_left - 1)
    return f"{summary} | {due_after} still due, next chunk queued"


def heartbeat() -> str:
    """Prove the cluster is alive, so silence becomes a signal.

    Moving every scheduled job behind one `qcluster` process concentrates failure: if it
    dies, everything stops and nothing says so. That is the same shape as the Vinted outage
    that ran unnoticed for eight days, and the per-query failure alert does not cover it —
    it only fires when a *pass* runs and fails.

    This is deliberately trivial. It exists so that the absence of a recent `Success` row,
    or of this line in the log channel, is itself evidence.
    """
    now = timezone.now()
    logger.info("Job cluster heartbeat at %s", now.isoformat(timespec="seconds"))
    return f"alive at {now:%Y-%m-%d %H:%M:%S}"


# ---------------------------------------------------------------------------
# Housekeeping — the two tables that grow with the clock, not with the market
# ---------------------------------------------------------------------------

def prune_status_logs(days: int | None = None, error_days: int | None = None) -> str:
    """Drop log rows past their horizon. See `bazos/housekeeping.py` for the two horizons."""
    from bazos.housekeeping import prune_status_logs as prune

    routine, serious = prune(days, error_days)
    logger.info("Pruned %d routine and %d warning+ log rows", routine, serious)
    return f"deleted {routine} routine, {serious} warning+"


def prune_query_runs(days: int | None = None) -> str:
    """Drop `QueryRun` rows past their horizon.

    ⚠️ This is the table every block-rate measurement is computed from, and a deleted row is
    gone — `exit_ip` is the only record of which egress the marketplace actually rejected.
    """
    from bazos.housekeeping import prune_query_runs as prune

    deleted = prune(days)
    logger.info("Pruned %d query runs", deleted)
    return f"deleted {deleted} query runs"
