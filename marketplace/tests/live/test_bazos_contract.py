"""Live contract checks against bazos.cz. Deselected by default.

Cassettes rot silently: a green transport suite proves the code still handles the
HTML that was recorded, not that it handles bazos.cz today. In production the
zero-results canary catches the catastrophic case; this catches *partial* drift —
`view_count` quietly disappearing while everything else still parses — before it
ships.

These tests hit the network, so they are excluded from the default run and from
CI (`addopts = -m "not live"` in pytest.ini). Run them deliberately:

    pytest -m live                      # just these
    pytest -m "live or not live"        # everything

They assert on *shape*, never on values: listings change hourly, so any test that
pins an ad's name or price would be red by lunchtime. What must not change is
which fields Bazos still exposes, and that is what is compared — live parse
against the committed cassette, field for field.

Run them from a residential connection. GitHub-hosted runner IPs are refused by
Bazos; the self-hosted Pi runner is the vantage point that works.
"""
from itertools import islice
from pathlib import Path

import pytest
import requests
import vcr

from marketplace.models import Ad, Query
from marketplace.scraping.bazos.bazos_scraper import BazosScraper

pytestmark = pytest.mark.live

# The pagination cassette, because it is the complete one: it holds page 1 *and*
# the empty page 2 that terminates the walk, so the recorded parse can consume
# the same generator to exhaustion that the live parse does.
CASSETTE = (
    Path(__file__).resolve().parent.parent
    / "cassettes" / "test_bazos_scraper_transport"
    / "test_run_query_stops_after_a_page_with_no_ads.yaml"
)

# Fields the scraper is expected to populate from a Bazos *listing* page.
# full_description is excluded on purpose: it comes from the detail page.
LISTING_FIELDS = [
    "external_id", "name", "price_raw", "url", "location",
    "publish_date", "view_count", "short_description", "publisher_name",
]


def populated_fields(ad: Ad) -> set[str]:
    """Which listing fields actually carry a value. Booleans are never 'missing'."""
    populated = set()
    for field in LISTING_FIELDS:
        value = getattr(ad, field)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        populated.add(field)
    return populated


@pytest.fixture
def scraper():
    return BazosScraper(requests.Session())


@pytest.fixture
def live_query(category):
    return Query.objects.create(
        text="thinkpad x230",
        category=category,
        location_center="",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
    )


@pytest.fixture
def live_ads(scraper, live_query):
    ads = list(islice(scraper.run_query(live_query), 20))
    if not ads:
        pytest.fail(
            "live Bazos search parsed ZERO ads. Either the markup changed, or this "
            "IP is blocked. Check a browser before assuming parser drift."
        )
    return ads


@pytest.fixture
def recorded_ads(scraper, live_query):
    with vcr.use_cassette(
        str(CASSETTE), record_mode="none", decode_compressed_response=True,
        match_on=["method", "scheme", "host", "port", "path", "query"],
    ):
        return list(islice(scraper.run_query(live_query), 20))


@pytest.mark.django_db
def test_live_search_still_returns_a_full_page(live_ads):
    """A category search should still fill a page. A handful means something moved."""
    assert len(live_ads) >= 5


# How far a field's population rate may move before it counts as drift. Rates are
# compared rather than a set union: a union only fires when a field vanishes from
# *every* ad, so view_count surviving on 1 of 20 would read as healthy — which is
# not what this test claims to detect.
#
# 0.25 is deliberately loose. A field genuinely absent from a minority of live ads
# is normal on a marketplace where sellers fill in different things, and this job
# runs unattended against a site that changes hourly — a tighter bound would spend
# its credibility on false alarms. The consequence is accepted and stated: a field
# dropping from 100% to 80% passes. Total or near-total loss is what this catches.
FIELD_RATE_TOLERANCE = 0.25


def population_rates(ads: list[Ad]) -> dict[str, float]:
    """Fraction of ads carrying a value, per listing field."""
    if not ads:
        # Unreachable today (live_ads fails loudly, recorded_ads comes from a
        # committed cassette) but a ZeroDivisionError here would read as a bug in
        # the drift maths rather than as "there were no ads".
        raise AssertionError("no ads to compute population rates from")
    return {
        field: sum(1 for ad in ads if field in populated_fields(ad)) / len(ads)
        for field in LISTING_FIELDS
    }


@pytest.mark.django_db
def test_live_ads_populate_the_same_fields_as_the_cassette(live_ads, recorded_ads):
    """The drift detector: how often each field is populated, live vs recorded.

    Asserts on which fields Bazos still fills in, never on what is in them. Fires
    in both directions — a field that starts appearing is a re-record signal just
    as much as one that stops.
    """
    live = population_rates(live_ads)
    recorded = population_rates(recorded_ads)

    drifted = {
        field: f"cassette {recorded[field]:.0%} -> live {live[field]:.0%}"
        for field in LISTING_FIELDS
        if abs(live[field] - recorded[field]) > FIELD_RATE_TOLERANCE
    }

    assert not drifted, (
        f"listing field population drifted: {drifted}. "
        f"Re-record the cassettes if this is a legitimate site change."
    )


@pytest.mark.django_db
def test_live_prices_still_parse(live_ads):
    """`price_raw` -> price/price_type. Bazos has no decimals; a change breaks P22."""
    from marketplace.models import PriceType

    parsed = [ad for ad in live_ads if ad.price_type != PriceType.UNKNOWN]
    assert parsed, "no live price resolved to a known price_type"


@pytest.mark.django_db
def test_live_dates_still_parse(live_ads):
    """`extract_date` reads a "[d.m.yyyy]" fragment — a format change breaks it."""
    assert all(ad.publish_date is not None for ad in live_ads)


@pytest.mark.django_db
def test_live_publisher_ids_are_still_exposed(live_ads):
    """The `odeslatakci('rating', email, phone, name)` onclick is the only source
    of seller identity, and the whole SellerAdCounts feature rests on it."""
    identified = [ad for ad in live_ads if ad.email_publisher or ad.phone_publisher]
    assert identified


@pytest.mark.django_db
def test_live_first_page_still_returns_404_with_a_body(scraper, live_query):
    """Pins the surprise in E2E_REPLAY_TESTING.md §4.9.

    If Bazos ever starts serving a real 404 here, the scraper silently stops
    finding anything on page 1 — this is the early warning.
    """
    url = next(BazosScraper.create_url_category(live_query))
    response = scraper.run_request(url)

    assert response is not None
    assert 'class="inzeraty' in response.text, "page 1 body no longer contains listings"
