"""`compare_bazos_scrapers` timed out three weeks running (2026-10-02, -09, -16): it walked
five arbitrary enabled queries to full depth on both transports, and neither Bazos scraper
has a page cap. A parity check only needs the newest window, compared like for like.
"""
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command

from bazos.const import COMPARE_MAX_ADS
from bazos.models import Marketplace, Query

COMMAND = "bazos.management.commands.compare_bazos_scrapers"


class _EndlessScraper:
    """Yields ads newest-first forever, counting how many the caller actually pulled."""

    def __init__(self, newest: int, skip: frozenset[int] = frozenset()):
        self.newest, self.skip, self.pulled = newest, skip, 0
        self.sent_requests_count = 0

    def run_query(self, query):
        external_id = self.newest
        while True:
            if external_id not in self.skip:
                self.pulled += 1
                if self.pulled > 10 * COMPARE_MAX_ADS:
                    raise AssertionError("walked far past the window - no bound")
                yield SimpleNamespace(external_id=str(external_id))
            external_id -= 1


def _run(html, api, **options) -> str:
    out = StringIO()
    with (
        patch(f"{COMMAND}.build_ip_changer", return_value=SimpleNamespace(session=object())),
        patch(f"{COMMAND}.with_rotation", side_effect=lambda changer, fetch, what: fetch(None)),
        patch(f"{COMMAND}.BazosScraper", return_value=html),
        patch(f"{COMMAND}.BazosApiScraper", return_value=api),
    ):
        call_command("compare_bazos_scrapers", stdout=out, **options)
    return out.getvalue()


def _query(text: str, marketplace: str, enabled: bool = True) -> Query:
    return Query.objects.create(text=text, marketplace=marketplace, enabled=enabled,
                                price_lower=0, price_upper=0)


@pytest.mark.django_db
def test_each_walk_stops_at_the_window():
    _query("macbook", Marketplace.BAZOS)
    html, api = _EndlessScraper(10_000), _EndlessScraper(10_000)

    _run(html, api)

    assert html.pulled == api.pulled == COMPARE_MAX_ADS


@pytest.mark.django_db
def test_the_window_edge_is_not_reported_as_drift():
    """The API skipped one id, so its window reaches one id deeper. That extra id is the
    edge of the window, not something only the API sees."""
    _query("macbook", Marketplace.BAZOS)
    missing = 10_000 - 7

    output = _run(_EndlessScraper(10_000), _EndlessScraper(10_000, skip=frozenset({missing})))

    assert "only_html=1 only_api=0" in output
    assert str(missing) in output


@pytest.mark.django_db
def test_only_enabled_bazos_queries_are_compared_in_a_stable_order():
    first = _query("thinkpad", Marketplace.BAZOS_API)
    _query("iphone", Marketplace.VINTED)
    _query("ipad", Marketplace.SBAZAR)
    _query("pixel", Marketplace.BAZOS, enabled=False)
    second = _query("macbook", Marketplace.BAZOS)

    output = _run(_EndlessScraper(10_000), _EndlessScraper(10_000))

    headers = [line for line in output.splitlines() if line.startswith("--- Query")]
    assert headers == [f"--- Query {first.pk}: {first} ---", f"--- Query {second.pk}: {second} ---"]
