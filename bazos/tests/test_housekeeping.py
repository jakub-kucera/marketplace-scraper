"""Tests for `bazos/housekeeping.py` and `manage.py prune_logs`.

Deletion is the one operation here with no undo, so these pin the *boundaries* — what
survives, not just what goes — and the two retention asymmetries, which are decisions rather
than parameters.
"""
import logging
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models import QuerySet
from django.utils import timezone
from django_db_logger.models import StatusLog
from model_bakery import baker

from bazos.housekeeping import prune_query_runs, prune_status_logs
from bazos.models import QueryRun


@pytest.fixture
def make_log():
    def _factory(days_ago: int, level: int = logging.INFO):
        row = StatusLog.objects.create(logger_name="bazos", level=level, msg="x")
        # create_datetime is auto_now_add, so it can only be moved afterwards.
        StatusLog.objects.filter(pk=row.pk).update(
            create_datetime=timezone.now() - timedelta(days=days_ago)
        )
        return row
    return _factory


@pytest.fixture
def make_run(query):
    def _factory(days_ago: int, success: bool = True):
        return baker.make(
            QueryRun,
            query=query,
            run_start=timezone.now() - timedelta(days=days_ago),
            success=success,
        )
    return _factory


# ---------------------------------------------------------------------------
# StatusLog — two horizons
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_routine_rows_past_the_horizon_go(make_log):
    old = make_log(days_ago=40)
    recent = make_log(days_ago=5)

    routine, _ = prune_status_logs(days=30, error_days=180)

    assert routine == 1
    assert not StatusLog.objects.filter(pk=old.pk).exists()
    assert StatusLog.objects.filter(pk=recent.pk).exists()


@pytest.mark.django_db
def test_a_warning_outlives_an_info_of_the_same_age(make_log):
    """The asymmetry is the point: a StatusLog is a debugging log, not a sample anything is
    measured over, so there is no ratio to distort by keeping the serious rows longer."""
    info = make_log(days_ago=40, level=logging.INFO)
    warning = make_log(days_ago=40, level=logging.WARNING)
    error = make_log(days_ago=40, level=logging.ERROR)

    prune_status_logs(days=30, error_days=180)

    assert not StatusLog.objects.filter(pk=info.pk).exists()
    assert StatusLog.objects.filter(pk__in=[warning.pk, error.pk]).count() == 2


@pytest.mark.django_db
def test_a_warning_past_its_own_longer_horizon_does_go(make_log):
    warning = make_log(days_ago=200, level=logging.WARNING)

    _, serious = prune_status_logs(days=30, error_days=180)

    assert serious == 1
    assert not StatusLog.objects.filter(pk=warning.pk).exists()


@pytest.mark.django_db
def test_horizons_default_to_the_settings(make_log, settings):
    settings.STATUS_LOG_RETENTION_DAYS = 1
    settings.STATUS_LOG_ERROR_RETENTION_DAYS = 1
    make_log(days_ago=3)

    routine, _ = prune_status_logs()

    assert routine == 1


# ---------------------------------------------------------------------------
# QueryRun — deliberately ONE horizon
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_old_runs_go_and_recent_ones_stay(make_run):
    old = make_run(days_ago=120)
    recent = make_run(days_ago=10)

    assert prune_query_runs(days=90) == 1
    assert not QueryRun.objects.filter(pk=old.pk).exists()
    assert QueryRun.objects.filter(pk=recent.pk).exists()


@pytest.mark.django_db
def test_failures_are_not_kept_longer_than_successes(make_run):
    """Deliberate, and the opposite call from StatusLog. Every block-rate figure this
    project quotes is a *ratio* over this table; retaining failures longer would silently
    turn old windows into 100% failure, and nothing would say so.
    """
    failed = make_run(days_ago=120, success=False)
    succeeded = make_run(days_ago=120, success=True)

    prune_query_runs(days=90)

    assert not QueryRun.objects.filter(pk__in=[failed.pk, succeeded.pk]).exists()


@pytest.mark.django_db
def test_deletion_batches_rather_than_collecting_every_pk(make_run, monkeypatch):
    """One unbounded delete over a quarter-million rows is a single long transaction
    holding locks on a table the scraper writes to every pass.

    Asserts the number of DELETEs, not just the outcome: counting deleted rows alone passes
    identically whether or not any batching happens.
    """
    from bazos import housekeeping

    monkeypatch.setattr(housekeeping, "PRUNE_BATCH_SIZE", 2)
    for _ in range(5):
        make_run(days_ago=120)

    real_delete = QuerySet.delete
    calls = []

    def counting_delete(self):
        calls.append(len(self.query.where.children))
        return real_delete(self)

    monkeypatch.setattr(QuerySet, "delete", counting_delete)

    assert prune_query_runs(days=90) == 5
    assert not QueryRun.objects.exists()
    # 5 rows at 2 per batch: two full batches, one partial.
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def run_prune(**kwargs):
    out = StringIO()
    call_command("prune_logs", stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
def test_dry_run_reports_without_deleting(make_log, make_run):
    make_log(days_ago=40)
    make_run(days_ago=120)

    report = run_prune(dry_run=True, days=30, query_run_days=90)

    assert "Would delete" in report
    assert StatusLog.objects.count() == 1
    assert QueryRun.objects.count() == 1


@pytest.mark.django_db
def test_the_command_deletes_both_tables(make_log, make_run):
    make_log(days_ago=40)
    make_run(days_ago=120)

    report = run_prune(days=30, error_days=180, query_run_days=90)

    assert "Deleted 1 routine log rows" in report
    assert "1 query runs" in report
    assert not StatusLog.objects.exists()
    assert not QueryRun.objects.exists()
