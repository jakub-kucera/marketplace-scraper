"""Tests for how BazosRunner reacts to a Bazos IP block.

Context (measured from the QueryRun history of 2026-08-23): the runner used to fire a
pre-flight `check_blacklisted()` probe per query against one fixed `search.php` URL, and
treat a 403 raised by the *actual* query as a generic failure — logged, written off, and
the next query attempted on the same dead IP milliseconds later. Because the block is
path-scoped, the probe reported "clear" while the real request 403'd: every
`BazosBlacklistedError` row in that history is a run whose probe had just passed, and the
failures arrived in clusters because nothing rotated between them.

So the probe is gone and the query attempt is the probe: a 403 rotates the IP and retries,
up to MAX_BLACKLIST_RETRIES times.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.const import MAX_BLACKLIST_RETRIES
from bazos.exceptions import BazosBlacklistedError
from bazos.models import AdDelivery, AdStatus, Query, QueryRun
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.bazos_query_runner import BazosQueryRunner
from bazos.scraping.bazos_runner import BazosRunner


class StopLoop(Exception):
    """Sentinel used to escape BazosRunner.run()'s `while True` after one pass."""


def make_runner(exit_ip="185.242.6.116"):
    runner = BazosRunner.__new__(BazosRunner)
    runner.discord_loggers = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.session = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.ip_changer.get_current_ip.return_value = exit_ip
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    return runner


def run_one_pass(runner):
    with patch.object(runner, "_interruptible_sleep", side_effect=StopLoop), \
         patch.object(runner, "_sleep_between_queries"):
        with pytest.raises(StopLoop):
            runner.run()


def make_other_query(category):
    return Query.objects.create(
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


@pytest.mark.django_db
def test_blacklisted_query_rotates_ip_and_retries_the_same_query(query):
    """The whole point: a 403 must not cost the query its pass."""
    runner = make_runner()
    attempts = {"n": 0}

    def fake_run(self):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise BazosBlacklistedError()
        return 4

    with patch.object(BazosQueryRunner, "run", fake_run):
        run_one_pass(runner)

    runner.ip_changer.renew_ip_and_check_new.assert_called_once()

    runs = list(QueryRun.objects.filter(query=query).order_by("run_start"))
    assert len(runs) == 2
    assert runs[0].success is False
    assert "BazosBlacklistedError" in (runs[0].error or "")
    assert runs[1].success is True and runs[1].new_ads_count == 4


@pytest.mark.django_db
def test_durably_blacklisted_query_is_skipped_without_taking_down_the_pass(query, category):
    other_query = make_other_query(category)
    runner = make_runner()

    def fake_run(self):
        if self.query.pk == query.pk:
            raise BazosBlacklistedError()
        return 5

    with patch.object(BazosQueryRunner, "run", fake_run):
        run_one_pass(runner)

    blocked_runs = QueryRun.objects.filter(query=query)
    assert blocked_runs.count() == MAX_BLACKLIST_RETRIES
    assert not blocked_runs.filter(success=True).exists()
    # Rotation happens *between* attempts, so there is one fewer than there are attempts.
    assert runner.ip_changer.renew_ip_and_check_new.call_count == MAX_BLACKLIST_RETRIES - 1

    assert QueryRun.objects.get(query=other_query, success=True).new_ads_count == 5


@pytest.mark.django_db
def test_a_retried_new_query_still_runs_as_a_new_query(query, make_ad):
    """Regression: `run_new_query` sets `query.new_query = False` in memory *before* it
    can raise, and a failed attempt never reaches `query.save()`. Retrying with the same
    in-memory object therefore used to fall into `run_existing_query`, which bypasses both
    `ignore_first_run` (so the whole backfill goes to Discord as PENDING) and the
    NEW_PRODUCT_LOAD_MAX cap — and the eventual `query.save()` then persisted
    new_query=False, destroying the backfill state for good.
    """
    query.new_query = True
    query.ignore_first_run = True
    query.save()

    runner = make_runner()
    paths = []
    attempts = {"n": 0}

    def fake_scraper_run_query(self, q):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise BazosBlacklistedError()
        for external_id in range(100, 105):
            yield make_ad(q, external_id)

    def spy(name, original):
        def wrapper(self):
            paths.append(name)
            return original(self)
        return wrapper

    with patch.object(BazosQueryRunner, "run_new_query",
                      spy("new", BazosQueryRunner.run_new_query)), \
         patch.object(BazosQueryRunner, "run_existing_query",
                      spy("existing", BazosQueryRunner.run_existing_query)), \
         patch.object(BazosScraper, "run_query", fake_scraper_run_query):
        run_one_pass(runner)

    assert paths == ["new", "new"]
    statuses = set(AdDelivery.objects.filter(query=query).values_list("status", flat=True))
    assert statuses == {AdStatus.SUPPRESSED}


@pytest.mark.django_db
def test_failed_rotation_abandons_the_query_instead_of_burning_attempts(query):
    """`renew_ip_and_check_new` hands back the *old* IP when it gives up. Re-running the
    query against the exit that just 403'd it cannot succeed, so don't pay for it.
    """
    runner = make_runner(exit_ip="185.242.6.116")
    runner.ip_changer.renew_ip_and_check_new.return_value = "185.242.6.116"

    with patch.object(BazosQueryRunner, "run", side_effect=BazosBlacklistedError()):
        run_one_pass(runner)

    assert QueryRun.objects.filter(query=query).count() == 1
    runner.ip_changer.renew_ip_and_check_new.assert_called_once()


@pytest.mark.django_db
def test_a_non_blacklist_failure_is_not_retried(query):
    """Rotating the IP cannot fix a parse error — only a 403 earns a retry."""
    runner = make_runner()

    with patch.object(BazosQueryRunner, "run", side_effect=RuntimeError("boom")):
        run_one_pass(runner)

    assert QueryRun.objects.filter(query=query).count() == 1
    runner.ip_changer.renew_ip_and_check_new.assert_not_called()


@pytest.mark.django_db
def test_runner_never_fires_a_pre_flight_blacklist_probe(query):
    """Regression guard: the probe cost a full search request per query and lied."""
    runner = make_runner()

    with patch.object(BazosQueryRunner, "run", return_value=1), \
         patch.object(BazosScraper, "check_blacklisted") as html_check, \
         patch.object(BazosApiScraper, "check_blacklisted") as api_check:
        run_one_pass(runner)

    html_check.assert_not_called()
    api_check.assert_not_called()


@pytest.mark.django_db
def test_local_ip_is_checked_once_per_pass_not_once_per_query(query, category):
    make_other_query(category)
    runner = make_runner()

    with patch.object(BazosQueryRunner, "run", return_value=1):
        run_one_pass(runner)

    runner.ip_changer.check_ip_local.assert_called_once()


@pytest.mark.django_db
def test_local_ip_skips_the_pass_but_still_sleeps(query):
    """Must not hot-loop: a local IP means skip the queries, not skip the sleep."""
    runner = make_runner()
    runner.ip_changer.check_ip_local.return_value = True

    with patch.object(BazosQueryRunner, "run") as query_runner_run:
        run_one_pass(runner)

    query_runner_run.assert_not_called()
    assert not QueryRun.objects.exists()


@pytest.mark.django_db
def test_query_run_records_the_exit_ip(query):
    """The column that settles IP-reputation vs. sliding-window rate limiting."""
    runner = make_runner(exit_ip="185.242.6.116")

    with patch.object(BazosQueryRunner, "run", return_value=0):
        run_one_pass(runner)

    assert QueryRun.objects.get(query=query).exit_ip == "185.242.6.116"


@pytest.mark.django_db
def test_unreachable_ip_echo_service_does_not_break_the_pass(query):
    runner = make_runner()
    runner.ip_changer.get_current_ip.side_effect = OSError("no route to host")

    with patch.object(BazosQueryRunner, "run", return_value=2):
        run_one_pass(runner)

    run = QueryRun.objects.get(query=query)
    assert run.exit_ip == ""
    assert run.success is True
