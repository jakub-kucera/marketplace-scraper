"""Tests for P18: QueryRun rows must survive a failing query.

Covers:
- QueryRun is persisted immediately, before the query actually runs.
- A raising query records success=False + error, and run_end is still set.
- A raising query does not abort the rest of the pass — later queries still run.
- A succeeding query records success=True with no error.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.exceptions import MarketplaceBlockedError
from bazos.models import Query, QueryRun
from bazos.scraping.query_runner import QueryRunner
from bazos.scraping.runner import ScrapeRunner


class StopLoop(Exception):
    """Sentinel used to escape ScrapeRunner.run()'s `while True` after one pass."""


def make_runner():
    """Construct a ScrapeRunner bypassing __init__, with a no-op IP changer."""
    runner = ScrapeRunner.__new__(ScrapeRunner)
    runner.unsafe = False
    runner.discord_loggers = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.ip_changer.session = MagicMock()
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    return runner


def run_one_pass(runner):
    """Run ScrapeRunner.run() for exactly one pass, then escape the infinite loop."""
    with patch.object(runner, "_interruptible_sleep", side_effect=StopLoop), \
         patch.object(runner, "_sleep_between_queries"):
        with pytest.raises(StopLoop):
            runner.run()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "exc",
    [RuntimeError("boom"), MarketplaceBlockedError()],
    ids=["exception-with-message", "bare-blacklisted-error"],
)
def test_failing_query_still_produces_queryrun_row_with_error(query, exc):
    """`str(e)` is empty for `MarketplaceBlockedError()` raised with no args — the exact
    shape of the exception that actually fires in production (bazos_scraper.py,
    bazos_api_scraper.py). error must stay non-empty and name the exception type either way.

    A blacklisted query is retried (see test_runner_blacklist.py), so it leaves one
    row per attempt; every one of them must carry the error.
    """
    runner = make_runner()

    with patch.object(QueryRunner, "run", side_effect=exc):
        run_one_pass(runner)

    runs = list(QueryRun.objects.filter(query=query))
    assert runs
    for run in runs:
        assert run.success is False
        assert run.error
        assert type(exc).__name__ in run.error
        if str(exc):
            assert str(exc) in run.error
        assert run.run_end is not None


@pytest.mark.django_db
def test_succeeding_query_records_success(query):
    runner = make_runner()

    with patch.object(QueryRunner, "run", return_value=3):
        run_one_pass(runner)

    run = QueryRun.objects.get(query=query)
    assert run.success is True
    assert run.error is None
    assert run.new_ads_count == 3
    assert run.run_end is not None


@pytest.mark.django_db
def test_one_failing_query_does_not_abort_the_rest_of_the_pass(query, category):
    other_query = Query.objects.create(
        text="thinkpad",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
        load_full_description=False,
    )
    runner = make_runner()

    def fake_run(self):
        if self.query.pk == query.pk:
            raise RuntimeError("boom")
        return 5

    with patch.object(QueryRunner, "run", fake_run):
        run_one_pass(runner)

    failed_run = QueryRun.objects.get(query=query)
    assert failed_run.success is False
    assert failed_run.error is not None and "boom" in failed_run.error

    ok_run = QueryRun.objects.get(query=other_query)
    assert ok_run.success is True
    assert ok_run.new_ads_count == 5


@pytest.mark.django_db
def test_queryrun_is_persisted_before_the_query_executes(query):
    """The row must exist as soon as it's constructed, not only after a successful run."""
    runner = make_runner()
    seen_pk_before_run = {}

    def fake_run(self):
        seen_pk_before_run["exists"] = QueryRun.objects.filter(query=self.query).exists()
        raise RuntimeError("boom")

    with patch.object(QueryRunner, "run", fake_run):
        run_one_pass(runner)

    assert seen_pk_before_run["exists"] is True
