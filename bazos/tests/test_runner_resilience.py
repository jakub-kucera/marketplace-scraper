"""A broken transport must not take the scraper daemon down with it.

On 2026-08-23 a ConnectTimeout from the icanhazip lookup escaped ScrapeRunner.run() and
killed the process. `run_scraper`'s outer loop did restart it — but that rebuilds
ScrapeRunner, which resets the canary streak counters, so parser drift interrupted by a
single crash could never reach its alert threshold.

See test_bad_ad_tolerance.py for the same shape one level down: a single unusable listing
taking out a whole query walk.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings

from bazos.exceptions import MarketplaceBlockedError
from bazos.models import QueryRun
from bazos.scraping.query_runner import QueryRunner
from bazos.scraping.runner import ScrapeRunner


class StopLoop(Exception):
    """Sentinel used to escape ScrapeRunner.run()'s `while True`."""


def make_runner(unsafe=False):
    runner = ScrapeRunner.__new__(ScrapeRunner)
    runner.unsafe = unsafe
    runner.discord_loggers = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.session = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.ip_changer.get_current_ip.return_value = "1.2.3.4"
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    return runner


def run_n_passes(runner, n):
    state = {"passes": 0}

    def fake_sleep(_seconds):
        state["passes"] += 1
        if state["passes"] >= n:
            raise StopLoop

    with patch.object(runner, "_interruptible_sleep", side_effect=fake_sleep), \
         patch.object(runner, "_sleep_between_queries"):
        with pytest.raises(StopLoop):
            runner.run()
    return state["passes"]


# --- the pass-level guard --------------------------------------------------

@pytest.mark.django_db
def test_a_failed_egress_lookup_skips_the_pass_instead_of_killing_the_runner(query):
    """`check_ip_local` raising must not escape run(). Skipping is also the *right*
    answer: if we cannot see our own egress the transport is down.
    """
    runner = make_runner()
    runner.ip_changer.check_ip_local.side_effect = requests.exceptions.ConnectTimeout("boom")

    with patch.object(QueryRunner, "run") as query_runner_run:
        assert run_n_passes(runner, 2) == 2  # it slept and came back, twice

    query_runner_run.assert_not_called()
    assert not QueryRun.objects.exists()


@pytest.mark.django_db
@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2)
def test_a_crashing_pass_does_not_reset_the_canary_streak(query):
    """The reason this is worth guarding rather than leaving to run_scraper's restart:
    a rebuilt ScrapeRunner starts both streak counters at zero, so drift interrupted by
    one crash could never reach its threshold.
    """
    runner = make_runner()
    runner.zero_rows_passes = 1

    runner.ip_changer.check_ip_local.side_effect = requests.exceptions.ConnectTimeout("boom")
    run_n_passes(runner, 1)

    assert runner.zero_rows_passes == 1


@pytest.mark.django_db
def test_unsafe_mode_still_crashes(query):
    """`--unsafe` is documented as crash-fast; the new guard must not neuter it."""
    runner = make_runner(unsafe=True)
    runner.ip_changer.check_ip_local.side_effect = requests.exceptions.ConnectTimeout("boom")

    with patch.object(runner, "_interruptible_sleep"), \
         patch.object(runner, "_sleep_between_queries"):
        with pytest.raises(requests.exceptions.ConnectTimeout):
            runner.run()


@pytest.mark.django_db
def test_a_failed_rotation_does_not_cost_other_queries_their_turn(query, category):
    from bazos.models import Query

    other = Query.objects.create(
        text="thinkpad", category=category, location_center="12345", location_radius=25,
        price_lower=0, price_upper=0, new_query=False, ignore_first_run=True,
        load_full_description=False,
    )
    runner = make_runner()
    runner.ip_changer.renew_ip_and_check_new.side_effect = requests.exceptions.ConnectTimeout("boom")

    def fake_run(self):
        if self.query.pk == query.pk:
            raise MarketplaceBlockedError()
        return 7

    with patch.object(QueryRunner, "run", fake_run):
        run_n_passes(runner, 1)

    assert QueryRun.objects.get(query=other, success=True).new_ads_count == 7
