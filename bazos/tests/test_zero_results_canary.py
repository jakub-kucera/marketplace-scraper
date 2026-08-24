"""Tests for P19: the zero-results canary.

A Bazos HTML change silently zeroes the deal flow and looks identical to a quiet
market. These tests pin the counter/threshold/reset logic that tells them apart.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from bazos.models import QueryRun
from bazos.scraping.query_runner import QueryRunner
from bazos.scraping.runner import ScrapeRunner


class StopLoop(Exception):
    """Sentinel used to escape ScrapeRunner.run()'s `while True`."""


def make_runner():
    """Construct a ScrapeRunner bypassing __init__, with a no-op IP changer.

    __init__ is skipped, so the two canary counters must be initialised by hand here.
    """
    runner = ScrapeRunner.__new__(ScrapeRunner)
    runner.unsafe = False
    runner.discord_loggers = []
    runner.summary_senders = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.ip_changer.session = MagicMock()
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    return runner


def run_n_passes(runner, n):
    """Run ScrapeRunner.run() for exactly n passes, then escape the infinite loop."""
    state = {"passes": 0}

    def fake_sleep(_seconds):
        state["passes"] += 1
        if state["passes"] >= n:
            raise StopLoop

    with patch.object(runner, "_interruptible_sleep", side_effect=fake_sleep), \
         patch.object(runner, "_sleep_between_queries"):
        with pytest.raises(StopLoop):
            runner.run()


def patched_query_runner(rows_seen: int, new_ads: int):
    """Patch QueryRunner.run so every query reports the given rows / new ads.

    Only `run` is patched — `__init__` still executes for real, so `rows_seen_counter`
    exists on the instance exactly as in production.
    """
    def fake_run(self):
        self.rows_seen_counter = rows_seen
        self.new_product_counter = new_ads
        return new_ads

    return patch.object(QueryRunner, "run", fake_run)


def alerts_at(log_mock, level):
    """The canary messages logged at `level`."""
    return [
        call for call in log_mock.call_args_list
        if call.kwargs.get("level") == level and "CANARY" in call.args[0]
    ]


@pytest.mark.django_db
def test_rows_seen_counter_counts_every_parsed_row(query, make_ad):
    runner_query_runner = QueryRunner(query, MagicMock())
    ads = [make_ad(query, bazos_id=i) for i in range(1, 4)]

    with patch.object(runner_query_runner.scraper, "run_query", return_value=iter(ads)):
        runner_query_runner.run_existing_query()

    assert runner_query_runner.rows_seen_counter == 3


@pytest.mark.django_db
def test_rows_seen_counter_counts_the_row_that_breaks_dedup(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=1, topped=False)
    known.save()
    make_delivery(known, query)

    runner_query_runner = QueryRunner(query, MagicMock())
    repeat_of_known = make_ad(query, bazos_id=1, topped=False)
    extra_ads = [make_ad(query, bazos_id=2), make_ad(query, bazos_id=3)]

    with patch.object(
        runner_query_runner.scraper,
        "run_query",
        return_value=iter([repeat_of_known, *extra_ads]),
    ):
        runner_query_runner.run_existing_query()

    assert runner_query_runner.rows_seen_counter == 1


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2)
def test_alerts_after_threshold_consecutive_zero_row_passes(query):
    runner = make_runner()

    with patched_query_runner(rows_seen=0, new_ads=0):
        with patch.object(runner, "log") as log_mock:
            run_n_passes(runner, 2)

    assert len(alerts_at(log_mock, logging.ERROR)) == 1


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2)
def test_zero_row_counter_resets_after_alerting(query):
    runner = make_runner()

    with patched_query_runner(rows_seen=0, new_ads=0):
        with patch.object(runner, "log") as log_mock:
            run_n_passes(runner, 4)

    assert len(alerts_at(log_mock, logging.ERROR)) == 2


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2)
def test_a_pass_with_rows_resets_the_zero_row_counter(query):
    runner = make_runner()

    with patch.object(runner, "log") as log_mock:
        with patched_query_runner(rows_seen=0, new_ads=0):
            run_n_passes(runner, 1)
        with patched_query_runner(rows_seen=5, new_ads=1):
            run_n_passes(runner, 1)
        with patched_query_runner(rows_seen=0, new_ads=0):
            run_n_passes(runner, 1)

    assert len(alerts_at(log_mock, logging.ERROR)) == 0


@pytest.mark.django_db
@override_settings(ZERO_NEW_ADS_ALERT_THRESHOLD=3)
def test_zero_new_ads_alerts_at_its_own_threshold_and_level(query):
    runner = make_runner()

    with patched_query_runner(rows_seen=10, new_ads=0):
        with patch.object(runner, "log") as log_mock:
            run_n_passes(runner, 3)

    assert len(alerts_at(log_mock, logging.WARNING)) == 1
    assert len(alerts_at(log_mock, logging.ERROR)) == 0


@pytest.mark.django_db
@override_settings(ZERO_NEW_ADS_ALERT_THRESHOLD=3)
def test_new_ads_found_resets_the_zero_new_ads_counter(query):
    runner = make_runner()

    with patch.object(runner, "log") as log_mock:
        for rows_seen, new_ads in [(10, 0), (10, 0), (10, 4), (10, 0), (10, 0)]:
            with patched_query_runner(rows_seen=rows_seen, new_ads=new_ads):
                run_n_passes(runner, 1)

    assert len(alerts_at(log_mock, logging.WARNING)) == 0


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2, ZERO_NEW_ADS_ALERT_THRESHOLD=6)
def test_a_zero_row_pass_resets_the_zero_new_ads_counter(query):
    """A total-outage pass in the middle of a quiet-market streak breaks that streak too:
    the outage pass carries no evidence for "rows parsed but zero new ads", so it must not
    count toward it, and it must not let the streak resume from its pre-outage value either.
    """
    runner = make_runner()

    with patch.object(runner, "log") as log_mock:
        with patched_query_runner(rows_seen=10, new_ads=0):
            run_n_passes(runner, 5)
        assert runner.zero_new_ads_passes == 5

        with patched_query_runner(rows_seen=0, new_ads=0):
            run_n_passes(runner, 1)
        assert runner.zero_new_ads_passes == 0

        with patched_query_runner(rows_seen=10, new_ads=0):
            run_n_passes(runner, 1)

    assert len(alerts_at(log_mock, logging.WARNING)) == 0


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2)
def test_pass_where_every_query_failed_does_not_count_as_zero_rows(query):
    runner = make_runner()

    with patch.object(QueryRunner, "run", side_effect=RuntimeError("boom")):
        with patch.object(runner, "log") as log_mock:
            run_n_passes(runner, 3)

    assert len(alerts_at(log_mock, logging.ERROR)) == 0
    assert len(alerts_at(log_mock, logging.WARNING)) == 0


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=1)
def test_canary_never_aborts_the_pass(query):
    runner = make_runner()

    with patched_query_runner(rows_seen=0, new_ads=0):
        run_n_passes(runner, 2)

    assert QueryRun.objects.filter(query=query).count() == 2
