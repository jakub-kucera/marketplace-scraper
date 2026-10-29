"""Unit tests for bazos/geo.py — postal-code parsing, haversine, and the zip.php
geocode cache that LocationDistanceRule reads.
"""
import json
from unittest.mock import Mock

import pytest
import requests

from marketplace.geo import (
    distance_between_codes,
    ensure_postal_code,
    geocode_postal_code,
    haversine_km,
    normalize_postal_code,
    parse_postal_code,
)
from marketplace.models import PostalCode

# Real zip.php values, probed live 2026-08-30.
PRAHA = (50.087334, 14.421111)     # 110 00
BRNO = (49.195060, 16.606837)      # 602 00


def _response(payload, status_code=200):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = payload if isinstance(payload, str) else json.dumps(payload)
    return response


def _session(response=None, side_effect=None):
    session = Mock(spec=requests.Session)
    session.get = Mock(return_value=response, side_effect=side_effect)
    return session


# ---------------------------------------------------------------------------
# parse_postal_code / normalize_postal_code
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("location,expected", [
    ("Pelhřimov, 394 03", "39403"),
    ("Praha 10, 106 00", "10600"),          # the "10" in the locality must not win
    ("Praha - západ, 252 29", "25229"),
    ("Brno, 60200", "60200"),               # written without the space
    ("Slovensko, 987 65", "98765"),         # SK codes share the shape; resolution decides
    ("Praha", None),
    ("", None),
    (None, None),
    ("Praha 5, Praha, Hlavní město Praha", None),   # Sbazar: district/region, no code
])
def test_parse_postal_code(location, expected):
    assert parse_postal_code(location) == expected


def test_parse_postal_code_takes_the_last_code():
    """Bazos renders the code after the locality, so a numeric locality never wins."""
    assert parse_postal_code("123 45 Ulice, Praha 4, 140 00") == "14000"


@pytest.mark.parametrize("value,expected", [
    ("110 00", "11000"),
    ("11000", "11000"),
    ("  602 00 ", "60200"),
    ("not a code", None),
    ("", None),
    (None, None),
])
def test_normalize_postal_code(value, expected):
    assert normalize_postal_code(value) == expected


# ---------------------------------------------------------------------------
# haversine_km
# ---------------------------------------------------------------------------

def test_haversine_known_distance():
    """Praha–Brno is ~186 km great-circle; allow 2 km for the post-office coordinates."""
    assert haversine_km(*PRAHA, *BRNO) == pytest.approx(186, abs=2)


def test_haversine_is_zero_for_the_same_point():
    assert haversine_km(*PRAHA, *PRAHA) == 0


def test_haversine_is_symmetric():
    assert haversine_km(*PRAHA, *BRNO) == pytest.approx(haversine_km(*BRNO, *PRAHA))


# ---------------------------------------------------------------------------
# distance_between_codes
# ---------------------------------------------------------------------------

@pytest.fixture
def praha_and_brno(db):
    PostalCode.objects.create(code="11000", city="Praha", latitude=PRAHA[0], longitude=PRAHA[1])
    PostalCode.objects.create(code="60200", city="Brno", latitude=BRNO[0], longitude=BRNO[1])


def test_distance_between_codes(praha_and_brno):
    assert distance_between_codes("11000", "60200") == pytest.approx(186, abs=2)


def test_distance_between_codes_is_none_when_either_is_uncached(praha_and_brno):
    assert distance_between_codes("11000", "39403") is None
    assert distance_between_codes("39403", "11000") is None


def test_distance_between_identical_codes_needs_no_cache(db):
    """Short-circuited: "is this ad in my own town" must not depend on a geocode."""
    assert distance_between_codes("39403", "39403") == 0.0


# ---------------------------------------------------------------------------
# geocode_postal_code / ensure_postal_code
# ---------------------------------------------------------------------------

def test_geocode_caches_the_matching_entry(db):
    session = _session(_response([
        {"zip_code": "110 00", "city": "Praha", "post_office": "Praha 1",
         "latitude": "50.087334", "longitude": "14.421111"},
    ]))

    row = geocode_postal_code("11000", session)

    assert (row.code, row.city) == ("11000", "Praha")
    assert (row.latitude, row.longitude) == PRAHA
    assert PostalCode.objects.get(code="11000").city == "Praha"


def test_geocode_picks_the_entry_whose_code_matches(db):
    """zip.php prefix-searches codes AND city names, so the response is a list of
    neighbours; only an exact code match means "found"."""
    session = _session(_response([
        {"zip_code": "251 01", "city": "Praha - východ", "latitude": "49.9", "longitude": "14.6"},
        {"zip_code": "110 00", "city": "Praha", "latitude": "50.087334", "longitude": "14.421111"},
    ]))

    row = geocode_postal_code("11000", session)

    assert row.city == "Praha"
    assert not PostalCode.objects.filter(code="25101").exists()


def test_geocode_returns_none_when_no_entry_matches(db):
    session = _session(_response([
        {"zip_code": "251 01", "city": "Praha - východ", "latitude": "49.9", "longitude": "14.6"},
    ]))

    assert geocode_postal_code("99999", session) is None
    assert not PostalCode.objects.exists()


@pytest.mark.parametrize("response,side_effect", [
    (_response([], status_code=403), None),
    (_response("<html>nope</html>"), None),
    (None, requests.ConnectionError("tor down")),
    (None, requests.ConnectTimeout("stalled")),
])
def test_geocode_never_raises_and_caches_nothing_on_failure(db, response, side_effect):
    """It runs inside the scrape walk, whose guard catches DatabaseError only — an
    escaping requests exception would abort the query for the whole pass."""
    assert geocode_postal_code("11000", _session(response, side_effect)) is None
    assert not PostalCode.objects.exists()


def test_ensure_postal_code_uses_the_cache_without_a_request(praha_and_brno):
    session = _session()

    assert ensure_postal_code("11000", session).city == "Praha"
    session.get.assert_not_called()


def test_ensure_postal_code_geocodes_a_miss(db):
    session = _session(_response([
        {"zip_code": "394 03", "city": "Pelhřimov", "latitude": "49.43", "longitude": "15.22"},
    ]))

    assert ensure_postal_code("39403", session).city == "Pelhřimov"
    session.get.assert_called_once()


def test_ensure_postal_code_ignores_an_empty_code(db):
    session = _session()

    assert ensure_postal_code(None, session) is None
    assert ensure_postal_code("", session) is None
    session.get.assert_not_called()


def test_geocode_swallows_a_non_requests_exception(db):
    """`requests.RequestException` is not the only way this can blow up — a mocked
    transport, a DB error on the write — and none of them may reach the scrape walk."""
    assert geocode_postal_code("11000", _session(side_effect=RuntimeError("boom"))) is None
    assert not PostalCode.objects.exists()


# ---------------------------------------------------------------------------
# QueryRunner integration — a new ad's code is resolved before its delivery exists
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_scraper_geocodes_a_new_ads_postal_code(query, make_ad):
    from unittest.mock import patch

    from marketplace.scraping.query_runner import QueryRunner

    product = make_ad(query, bazos_id=111)
    product.location = "Pelhřimov, 394 03"
    session = _session(_response([
        {"zip_code": "394 03", "city": "Pelhřimov", "latitude": "49.43", "longitude": "15.22"},
    ]))
    runner = QueryRunner(query, session)

    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    assert PostalCode.objects.get(code="39403").city == "Pelhřimov"


@pytest.mark.django_db
def test_scraper_makes_no_geocode_request_for_a_cached_code(query, make_ad, praha_and_brno):
    from unittest.mock import patch

    from marketplace.scraping.query_runner import QueryRunner

    product = make_ad(query, bazos_id=111)
    product.location = "Brno, 602 00"
    session = _session()
    runner = QueryRunner(query, session)

    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    session.get.assert_not_called()


# ---------------------------------------------------------------------------
# ScrapeRunner — query centres are geocoded without anyone running a command
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_pass_geocodes_a_query_filter_centre(query):
    """A centre is typed into the admin, so unlike an ad's code it has no creation moment
    to be resolved at — without this the filter silently PASSes everything."""
    from unittest.mock import patch

    from marketplace.scraping.runner import ScrapeRunner

    query.filter_location_center = "11000"
    query.filter_location_radius = 10
    query.save()
    session = _session(_response([
        {"zip_code": "110 00", "city": "Praha", "latitude": "50.087334", "longitude": "14.421111"},
    ]))
    with patch.object(ScrapeRunner, "__init__", lambda self: None):
        runner = ScrapeRunner()
    runner.ip_changer = Mock(session=session)

    runner._ensure_filter_centres([query])

    assert PostalCode.objects.get(code="11000").city == "Praha"


@pytest.mark.django_db
def test_pass_skips_queries_with_no_centre(query):
    from unittest.mock import patch

    from marketplace.scraping.runner import ScrapeRunner

    session = _session()
    with patch.object(ScrapeRunner, "__init__", lambda self: None):
        runner = ScrapeRunner()
    runner.ip_changer = Mock(session=session)

    runner._ensure_filter_centres([query])

    session.get.assert_not_called()
