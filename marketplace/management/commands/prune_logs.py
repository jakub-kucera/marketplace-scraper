"""Drop log and run-history rows past their retention horizon.

The counterpart to `bazos.jobs.prune_status_logs` / `prune_query_runs` — same functions,
runnable by hand. `--dry-run` reports what would go without deleting anything, which is the
mode to use before widening a horizon downwards.

See `bazos/housekeeping.py` for why QueryRun successes and failures share one horizon while
StatusLog's routine and serious rows do not.
"""
from django.core.management.base import BaseCommand

from marketplace.housekeeping import prune_query_runs, prune_status_logs


class Command(BaseCommand):
    help = "Delete StatusLog and QueryRun rows past their retention horizon."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None,
                            help="StatusLog horizon for rows below WARNING (default: setting).")
        parser.add_argument("--error-days", type=int, default=None,
                            help="StatusLog horizon for WARNING and above (default: setting).")
        parser.add_argument("--query-run-days", type=int, default=None,
                            help="QueryRun horizon (default: setting).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would be deleted; delete nothing.")

    def handle(self, *args, **options):
        if options["dry_run"]:
            self._report_counts(options)
            return

        routine, serious = prune_status_logs(options["days"], options["error_days"])
        runs = prune_query_runs(options["query_run_days"])

        self.stdout.write(self.style.SUCCESS(
            f"Deleted {routine} routine log rows, {serious} warning+ log rows, {runs} query runs"
        ))

    def _report_counts(self, options) -> None:
        """Counts only — deliberately a separate path rather than a flag threaded through
        the prune functions, so there is no branch inside the thing that deletes."""
        import logging
        from datetime import timedelta

        from django.conf import settings
        from django.utils import timezone
        from django_db_logger.models import StatusLog

        from marketplace.models import QueryRun

        now = timezone.now()
        days = options["days"] or settings.STATUS_LOG_RETENTION_DAYS
        error_days = options["error_days"] or settings.STATUS_LOG_ERROR_RETENTION_DAYS
        run_days = options["query_run_days"] or settings.QUERY_RUN_RETENTION_DAYS

        routine = StatusLog.objects.filter(
            create_datetime__lt=now - timedelta(days=days), level__lt=logging.WARNING
        ).count()
        serious = StatusLog.objects.filter(
            create_datetime__lt=now - timedelta(days=error_days), level__gte=logging.WARNING
        ).count()
        runs = QueryRun.objects.filter(run_start__lt=now - timedelta(days=run_days)).count()

        self.stdout.write(
            f"Would delete {routine} routine log rows (>{days}d), "
            f"{serious} warning+ log rows (>{error_days}d), "
            f"{runs} query runs (>{run_days}d)"
        )
        self.stdout.write(self.style.WARNING("Dry run — nothing was deleted."))
