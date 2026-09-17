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

from django.core.management import call_command
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Dotted paths, because that is what django-q2 persists in a `Schedule` row. Defined once
#: here so a rename breaks an import rather than silently orphaning a schedule.
SWEEP_DELISTED = "bazos.jobs.sweep_delisted"
HEARTBEAT = "bazos.jobs.heartbeat"
PRUNE_STATUS_LOGS = "bazos.jobs.prune_status_logs"
PRUNE_QUERY_RUNS = "bazos.jobs.prune_query_runs"


def sweep_delisted(limit: int | None = None) -> str:
    """Run the delisting sweep. See `bazos/delisting.py` for what it does and does not mean.

    Wraps the management command rather than reimplementing it: the command is the documented
    entry point and stays usable by hand (`--dry-run`, `--limit`) for the one-off backfill.
    """
    from io import StringIO

    out = StringIO()
    call_command("check_delisted", limit=limit, stdout=out)
    summary = out.getvalue().strip().replace("\n", " | ")
    logger.info("Delisting sweep finished: %s", summary)
    return summary


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
