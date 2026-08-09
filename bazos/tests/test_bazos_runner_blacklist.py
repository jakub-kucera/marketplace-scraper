"""Tests for BazosRunner's marketplace-aware blacklist check.

Context: BazosApiScraper.check_blacklisted probes the hidden API, a separate
surface from the HTML site the generic IPChanger.check_bazos_blacklisted
check targets. A bazos_api Query's pre-flight blacklist check (and the
retry-until-clear loop on IP rotation) must be bound to the API, not the
HTML page, or it stays blind to the API being blocked.
"""
from unittest.mock import MagicMock, patch

import pytest

from bazos.exceptions import BazosBlacklistedError
from bazos.models import Marketplace, Query
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.bazos_runner import BazosRunner


def make_runner():
    runner = BazosRunner.__new__(BazosRunner)
    runner.discord_loggers = []
    runner.ip_changer = MagicMock()
    runner.ip_changer.session = MagicMock()
    return runner


@pytest.mark.django_db
def test_blacklist_checker_uses_api_scraper_for_bazos_api_query(query):
    query.marketplace = Marketplace.BAZOS_API
    query.save()
    runner = make_runner()

    with patch.object(BazosApiScraper, "check_blacklisted", return_value=True) as api_check, \
         patch.object(BazosScraper, "check_blacklisted") as html_check:
        result = runner._blacklist_checker(query)(query.url)

    assert result is True
    api_check.assert_called_once()
    html_check.assert_not_called()


@pytest.mark.django_db
def test_blacklist_checker_uses_html_scraper_for_bazos_query(query):
    assert query.marketplace == Marketplace.BAZOS
    runner = make_runner()

    with patch.object(BazosScraper, "check_blacklisted", return_value=False) as html_check, \
         patch.object(BazosApiScraper, "check_blacklisted") as api_check:
        result = runner._blacklist_checker(query)(query.url)

    assert result is False
    html_check.assert_called_once()
    api_check.assert_not_called()


@pytest.mark.django_db
def test_change_ip_exhausting_retries_raises_and_does_not_crash_run(query, category):
    """A durably-blocked bazos_api query should skip gracefully, not take down the pass."""
    query.marketplace = Marketplace.BAZOS_API
    query.enabled = True
    query.save()

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

    runner = BazosRunner.__new__(BazosRunner)
    runner.discord_loggers = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.session = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.ip_changer.renew_ip_bazos_ok.side_effect = BazosBlacklistedError("still blocked")

    class StopLoop(Exception):
        pass

    with patch.object(BazosApiScraper, "check_blacklisted", return_value=True), \
         patch.object(BazosRunner, "_interruptible_sleep", side_effect=StopLoop), \
         patch("bazos.scraping.bazos_runner.BazosQueryRunner") as mock_query_runner:
        mock_query_runner.return_value.run.return_value = 2
        with pytest.raises(StopLoop):
            runner.run()

    from bazos.models import QueryRun
    assert not QueryRun.objects.filter(query=query).exists()
    assert QueryRun.objects.filter(query=other_query, success=True).exists()
