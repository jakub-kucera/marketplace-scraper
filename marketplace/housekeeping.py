"""Bounded growth for the two tables that have none.

Every other table here grows with the *market* — one row per listing, per price change, per
outcome. These two grow with the **clock**, whether or not anything happened:

- `StatusLog` takes INFO from three app loggers on every pass, forever.
- `QueryRun` takes one row per *attempt*, and an attempt is roughly a coin flip against
  Bazos's exit blocking, so a query that eventually succeeds can leave up to
  `MAX_BLACKLIST_RETRIES` rows. The measured rate is ~756 rows/day (5 293 over the 7 days
  to 2026-09-06), i.e. ~276 k/year on a Raspberry Pi.

Nothing pruned either before this module: outside migrations there was no `.delete()`
anywhere in the app.

**Two decisions worth not reversing by accident.**

*`QueryRun` successes and failures are pruned together, at the same age.* Keeping failures
longer is tempting — they are the interesting rows, and it would roughly halve growth — but
every historical block-rate figure is a *ratio*, and asymmetric retention silently turns old
windows into 100% failure. A number that is quietly wrong beats nothing only if you know it
is wrong, and nothing here would say so. `docs/backlog/API_CUTOVER.md` §1 is computed
exactly this way.

*`StatusLog` is not symmetric, and for the opposite reason.* It is a debugging log, not a
sample anything is measured over, so there is no ratio to distort — and a WARNING from six
weeks ago is worth keeping when the INFO around it is not. Hence two horizons.
"""
import logging

from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from marketplace.const import PRUNE_BATCH_SIZE

logger = logging.getLogger(__name__)


def _delete_in_batches(queryset, *, batch_size: int | None = None) -> int:
    """Delete `queryset` a slice at a time, returning how many rows went.

    Not one `queryset.delete()`: Django collects every pk first to resolve cascades, so a
    quarter-million-row delete is one long transaction holding locks on the table the
    scraper is still writing to. Batching keeps each transaction short.

    The slice is re-evaluated each round rather than paginated, because the rows are being
    removed underneath it — an offset would skip as much as it deleted.

    `batch_size` is read from the module at call time rather than bound as a default, so a
    test can shrink it. A default argument would capture the value at import and leave any
    batching test passing vacuously.
    """
    batch_size = batch_size if batch_size is not None else PRUNE_BATCH_SIZE
    model = queryset.model
    deleted = 0
    while True:
        pks = list(queryset.values_list("pk", flat=True)[:batch_size])
        if not pks:
            return deleted
        removed, _ = model.objects.filter(pk__in=pks).delete()
        if not removed:
            # Defensive: a filter that matches rows `delete()` will not remove would spin
            # forever otherwise. Nothing here should hit it.
            logger.warning("%s prune matched %d rows but deleted none; stopping", model.__name__, len(pks))
            return deleted
        deleted += removed


def prune_status_logs(days: int | None = None, error_days: int | None = None) -> tuple[int, int]:
    """Drop log rows past their horizon. Returns `(routine_removed, serious_removed)`.

    `days` covers everything below WARNING; `error_days` covers WARNING and above, and is
    the longer of the two — see the module docstring.
    """
    from django_db_logger.models import StatusLog

    days = days if days is not None else settings.STATUS_LOG_RETENTION_DAYS
    error_days = error_days if error_days is not None else settings.STATUS_LOG_ERROR_RETENTION_DAYS
    now = timezone.now()

    routine = _delete_in_batches(
        StatusLog.objects.filter(
            create_datetime__lt=now - timedelta(days=days), level__lt=logging.WARNING
        )
    )
    serious = _delete_in_batches(
        StatusLog.objects.filter(
            create_datetime__lt=now - timedelta(days=error_days), level__gte=logging.WARNING
        )
    )
    return routine, serious


def prune_query_runs(days: int | None = None) -> int:
    """Drop `QueryRun` rows past their horizon, successes and failures alike.

    ⚠️ This is the table every block-rate measurement is computed from. Widening the
    horizon is cheap; a row deleted is gone, and `exit_ip` is the only record of which
    egress the marketplace actually rejected.
    """
    from marketplace.models import QueryRun

    days = days if days is not None else settings.QUERY_RUN_RETENTION_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    return _delete_in_batches(QueryRun.objects.filter(run_start__lt=cutoff))
