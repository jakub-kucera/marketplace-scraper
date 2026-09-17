"""Per-query failure alerting — the gap that let Vinted die quietly for eight days.

The zero-results canary aggregates over *successful* queries only, so a query that fails
every attempt contributes nothing to it: it simply stops appearing in the numerator while the
healthy queries keep the numbers looking normal. Between 2026-09-08 and 09-16 every Vinted
query returned 404 and neither canary fired.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from bazos.scraping.pass_summary import QueryResult
from bazos.scraping.runner import ScrapeRunner


def make_runner():
    runner = ScrapeRunner.__new__(ScrapeRunner)
    runner.unsafe = False
    runner.discord_loggers = []
    runner.summary_senders = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    runner.query_failure_streaks = {}
    return runner


def failed(error="RuntimeError: 404"):
    return QueryResult(label="q", marketplace="vinted", error=error)


def ok(rows_seen=20, new_ads=1):
    return QueryResult(label="q", marketplace="vinted", rows_seen=rows_seen, new_ads=new_ads)


def alerts(log_mock):
    return [
        call for call in log_mock.call_args_list
        if call.kwargs.get("level") == logging.ERROR and "CANARY" in call.args[0]
    ]


def run_passes(runner, query, results):
    """Feed one query's per-pass outcomes through the streak checker."""
    with patch.object(runner, "log") as log_mock:
        for result in results:
            runner._check_query_failure_streaks([(query, result)])
    return log_mock


# ---------------------------------------------------------------------------

@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=3)
def test_alerts_after_threshold_consecutive_failures(query):
    runner = make_runner()

    log_mock = run_passes(runner, query, [failed(), failed(), failed()])

    assert len(alerts(log_mock)) == 1


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=3)
def test_does_not_alert_below_the_threshold(query):
    runner = make_runner()

    log_mock = run_passes(runner, query, [failed(), failed()])

    assert alerts(log_mock) == []


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=3)
def test_one_success_resets_the_streak(query):
    """The ~50% Tor block rate means isolated failures are normal; only a run of them is
    evidence of something broken."""
    runner = make_runner()

    log_mock = run_passes(runner, query, [failed(), failed(), ok(), failed(), failed()])

    assert alerts(log_mock) == []
    assert runner.query_failure_streaks[query.pk] == 2


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=2)
def test_alert_names_the_query_and_the_error(query):
    """An alert you have to go digging to act on is most of the way to being ignored."""
    runner = make_runner()

    log_mock = run_passes(runner, query, [failed("RuntimeError: endpoint 404"), failed("RuntimeError: endpoint 404")])

    message = alerts(log_mock)[0].args[0]
    assert str(query) in message
    assert "endpoint 404" in message
    assert "2 consecutive passes" in message


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=2)
def test_repeats_every_threshold_passes_rather_than_every_pass(query):
    """Matches the zero-results canary: reset after alerting, so a permanently broken query
    is reported periodically instead of shouting on every pass."""
    runner = make_runner()

    log_mock = run_passes(runner, query, [failed()] * 6)

    assert len(alerts(log_mock)) == 3


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=2)
def test_streaks_are_tracked_per_query(query, category):
    """One dead marketplace must not be masked by another query's health, which is exactly
    the aggregation flaw this exists to cover."""
    from bazos.models import Query

    other = Query.objects.create(text="healthy", category=category, location_radius=25)
    runner = make_runner()

    with patch.object(runner, "log") as log_mock:
        for _ in range(2):
            runner._check_query_failure_streaks([(query, failed()), (other, ok())])

    assert len(alerts(log_mock)) == 1
    assert other.pk not in runner.query_failure_streaks


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=3)
def test_a_query_that_stops_running_is_forgotten(query, category):
    """A disabled query must not resume its streak weeks later against a different world."""
    from bazos.models import Query

    other = Query.objects.create(text="other", category=category, location_radius=25)
    runner = make_runner()

    with patch.object(runner, "log"):
        runner._check_query_failure_streaks([(query, failed())])
        assert query.pk in runner.query_failure_streaks
        # Next pass: `query` is disabled, so it is not among the outcomes.
        runner._check_query_failure_streaks([(other, ok())])

    assert query.pk not in runner.query_failure_streaks


@pytest.mark.django_db
@override_settings(QUERY_FAILURE_ALERT_THRESHOLD=3)
def test_a_healthy_query_leaves_no_state(query):
    runner = make_runner()

    run_passes(runner, query, [ok(), ok(), ok()])

    assert runner.query_failure_streaks == {}
