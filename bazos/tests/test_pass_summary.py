"""Tests for the end-of-pass Discord digest.

Two halves, deliberately separate: the formatter is pure (no DB, no network), so its
layout, ordering and Discord size limit are pinned without a database; the runner half
checks only that the digest is built from the real pass results, pinned to the right
channel, and unable to take a pass down with it.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from bazos.models import Marketplace, Query
from bazos.scraping.pass_summary import (
    MAX_MESSAGE_CHARS,
    PassSummary,
    QueryResult,
    query_label,
)
from bazos.scraping.query_runner import QueryRunner
from bazos.scraping.runner import ScrapeRunner
from senders.models import Discord

START = datetime(2026, 8, 24, 12, 32, tzinfo=timezone.utc)


class StopLoop(Exception):
    """Sentinel used to escape ScrapeRunner.run()'s `while True` after one pass."""


def summary(*results: QueryResult, minutes: int = 9) -> PassSummary:
    return PassSummary(
        started=START, finished=START + timedelta(minutes=minutes), results=list(results)
    )


def found(label: str, new_ads: int, marketplace: str = Marketplace.BAZOS) -> QueryResult:
    return QueryResult(label=label, marketplace=marketplace, new_ads=new_ads, rows_seen=20)


def broke(label: str, error: str, marketplace: str = Marketplace.BAZOS, ip: str = "") -> QueryResult:
    return QueryResult(label=label, marketplace=marketplace, error=error, exit_ip=ip)


# --------------------------------------------------------------------------- formatting


def test_quiet_pass_collapses_to_one_line():
    """The overwhelmingly common pass. A table of zeroes every 15 minutes is how the
    channel gets muted — and muting it mutes the failures that share it."""
    text = summary(found("iPhone", 0), found("ThinkPad", 0)).format()

    assert text.count("\n") == 0
    assert "2 queries" in text and "no new ads" in text


def test_groups_by_marketplace_busiest_first():
    text = summary(
        found("Salomon XA Pro", 4, Marketplace.VINTED),
        found("iPhone 15 Pro", 18),
        found("Arc'teryx Beta AR", 14, Marketplace.VINTED),
        found("ThinkPad X1", 9),
    ).format()

    assert text.index("BAZOS") < text.index("VINTED")  # 27 new beats 18
    assert text.index("iPhone 15 Pro") < text.index("ThinkPad X1")
    assert text.index("Arc'teryx Beta AR") < text.index("Salomon XA Pro")
    assert "45 new" in text.splitlines()[0]


def test_failures_come_first_within_their_marketplace():
    text = summary(found("iPhone", 18), broke("Canon R6", "blacklisted after 3 attempts")).format()

    rows = [line for line in text.splitlines() if line.startswith(("  ", " FAIL"))]
    assert rows[0].startswith(" FAIL")
    assert "2 queries" in text and "1 FAILED" in text


def test_failure_row_carries_the_reason_and_exit_ip():
    text = summary(broke("Canon R6", "blacklisted after 3 attempts", ip="185.220.101.44")).format()

    assert "blacklisted after 3 attempts" in text
    assert "185.220.101.44" in text


def test_zero_result_queries_are_counted_not_listed():
    """The bulk of every pass. Listing them is what would blow the size limit."""
    text = summary(found("iPhone", 18), *[found(f"q{i}", 0) for i in range(16)]).format()

    assert "+ 16 queries, no new ads" in text
    assert "q0" not in text


def test_message_stays_under_the_discord_limit_and_says_what_it_dropped():
    text = summary(*[found(f"query number {i:03d} with a fairly long name", 5) for i in range(200)]).format()

    assert len(text) <= MAX_MESSAGE_CHARS
    assert text.splitlines()[0].endswith("1000 new")  # the header still totals everything
    assert "more rows" in text.splitlines()[-1]


def test_trimming_does_not_strand_an_empty_marketplace_header():
    text = summary(
        *[found(f"bazos query {i:03d} padded out to a good width", 5) for i in range(200)],
        found("lonely vinted query", 1, Marketplace.VINTED),
    ).format()

    assert len(text) <= MAX_MESSAGE_CHARS
    # Every group header (an unindented line below the first) must still have a row under
    # it — a "VINTED" with nothing beneath it reads as a bug in the scraper, not the digest.
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if i and line and not line.startswith(" ")]
    assert headers
    assert all(i + 1 < len(lines) and lines[i + 1].startswith(" ") for i in headers)


def test_duration_and_clock_are_rendered_in_prague_time():
    text = summary(found("iPhone", 1), minutes=9).format()

    # 12:32 UTC is 14:32 in Prague (CEST) — the wall clock the scraping happens on.
    assert text.startswith("Pass 14:32 → 14:41 (9m 00s)")


# ------------------------------------------------------------------------------- labels


@pytest.mark.django_db
def test_label_omits_the_marketplace_and_keeps_the_price_band(query):
    """The marketplace is the group header, so repeating it on every row is noise. The
    band is not noise: it is all that separates two queries watching the same search."""
    query.text = "iPhone 15 Pro"
    query.price_lower = 5000
    query.price_upper = 30000

    assert query_label(query) == "iPhone 15 Pro (5000-30000)"

    query.price_lower = 0
    assert query_label(query) == "iPhone 15 Pro (≤30000)"

    query.price_upper = 0
    assert query_label(query) == "iPhone 15 Pro"


@pytest.mark.django_db
def test_label_falls_back_to_the_category_for_a_textless_query(category):
    textless = Query.objects.create(
        text="", category=category, price_lower=0, price_upper=0,
        location_center="12345", location_radius=25,
    )

    assert query_label(textless) == str(category)


# ------------------------------------------------------------------------------- runner


def make_runner(summary_senders=None):
    runner = ScrapeRunner.__new__(ScrapeRunner)
    runner.unsafe = False
    runner.discord_loggers = []
    runner.summary_senders = summary_senders if summary_senders is not None else []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.session = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    return runner


def run_one_pass(runner):
    with patch.object(runner, "_interruptible_sleep", side_effect=StopLoop), \
         patch.object(runner, "_sleep_between_queries"):
        with pytest.raises(StopLoop):
            runner.run()


def patched_query_runner(new_ads: int):
    def fake_run(self):
        self.rows_seen_counter = 20
        return new_ads

    return patch.object(QueryRunner, "run", fake_run)


@pytest.mark.django_db
def test_pass_summary_reaches_the_pinned_sender_with_the_real_counts(query):
    sender = MagicMock()
    sender.wrap_multi_line = lambda text: f"```{text}```"
    runner = make_runner([sender])

    with patched_query_runner(new_ads=7):
        run_one_pass(runner)

    sender.send_plain.assert_called_once()
    text = sender.send_plain.call_args.args[0]
    assert text.startswith("```") and text.endswith("```")
    assert "7 new" in text


@pytest.mark.django_db
def test_a_failed_query_appears_in_the_summary(query):
    """The whole reason `_run_query_with_rotation` returns a result instead of None:
    before, every failure mode vanished before the pass could report it."""
    sender = MagicMock()
    sender.wrap_multi_line = lambda text: text
    runner = make_runner([sender])

    with patch.object(QueryRunner, "run", side_effect=ValueError("parser drift")):
        run_one_pass(runner)

    text = sender.send_plain.call_args.args[0]
    assert "FAIL" in text
    assert "ValueError: parser drift" in text


@pytest.mark.django_db
def test_a_broken_summary_webhook_does_not_fail_the_pass(query):
    """A digest that cannot send must not make a healthy pass look broken — without its
    own guard this reaches the pass-level handler and is announced as "Pass FAILED".

    Asserted on the calls rather than caplog: the `bazos` logger has propagate=False
    (settings.py), so its records never reach caplog's root-attached handler.
    """
    sender = MagicMock()
    sender.wrap_multi_line = lambda text: text
    sender.send_plain.side_effect = RuntimeError("429")
    runner = make_runner([sender])

    with patched_query_runner(new_ads=3), \
         patch.object(runner, "log") as log, \
         patch("bazos.scraping.runner.logger") as runner_logger:
        run_one_pass(runner)

    assert not [c for c in log.call_args_list if "Pass FAILED" in c.args[0]]
    runner_logger.exception.assert_called_once_with("Could not post the pass summary to Discord")


@pytest.mark.django_db
def test_no_pinned_channel_means_no_summary_and_no_error(query):
    runner = make_runner([])

    with patched_query_runner(new_ads=3):
        run_one_pass(runner)  # would raise if the empty sender list were mishandled


@pytest.mark.django_db
def test_summary_senders_never_ping(settings):
    """`for_summary` is honoured, `notify` deliberately is not: the digest fires every
    15-45 minutes and an @here that often gets the channel muted."""
    Discord.objects.create(channel_name="digest", url="https://d.co/s", notify=True, for_summary=True)
    Discord.objects.create(channel_name="ads", url="https://d.co/a", notify=True)
    settings.IP_CHANGER_TYPE = "DUMMY"

    with patch("bazos.scraping.runner.DummyIPChanger"):
        runner = ScrapeRunner()

    assert len(runner.summary_senders) == 1
    assert runner.summary_senders[0].notify is False
