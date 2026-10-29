"""Tests for `manage.py geocode_postal_codes` — which codes it decides are missing, and
the circuit rotation that keeps one blocked exit IP from failing the whole backfill.
"""
import json
from io import StringIO
from unittest.mock import Mock, patch

import pytest
import requests
from django.core.management import call_command

from marketplace.const import MAX_BLACKLIST_RETRIES
from marketplace.models import Ad, PostalCode


def _response(payload, status_code=200):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.text = payload if isinstance(payload, str) else json.dumps(payload)
    return response


BLOCK = _response(
    '{"error_code":"403","message":"You don\'t have permission to access this server. '
    'IP: 37.114.63.5"}',
    status_code=403,
)
PELHRIMOV = _response([
    {"zip_code": "394 03", "city": "Pelhřimov", "latitude": "49.43", "longitude": "15.22"},
])


class FakeChanger:
    """An IPChanger whose every rotation hands back a session with a new scripted reply."""

    def __init__(self, responses, can_rotate=True):
        self._responses = list(responses)
        self.can_rotate = can_rotate
        self.rotations = 0
        self.session = self._next_session()

    def _next_session(self):
        response = self._responses.pop(0) if self._responses else BLOCK
        session = Mock(spec=requests.Session)
        session.get = Mock(return_value=response)
        return session

    def rotate_circuit(self) -> bool:
        self.rotations += 1
        if not self.can_rotate:
            return False
        self.session = self._next_session()
        return True


@pytest.fixture
def no_pacing():
    with patch("marketplace.geo.sleep"):
        yield


def _run(changer, *args):
    out = StringIO()
    with patch(
        "marketplace.management.commands.geocode_postal_codes.Command._ip_changer",
        return_value=changer,
    ):
        call_command("geocode_postal_codes", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


@pytest.mark.django_db
def test_rotates_past_a_blocked_exit_and_succeeds(no_pacing):
    """A block is a property of the exit IP, not the code — so without rotating, the first
    blocked circuit fails every remaining lookup identically (0/40, measured live)."""
    changer = FakeChanger([BLOCK, BLOCK, PELHRIMOV])

    output = _run(changer, "--codes", "394 03")

    assert PostalCode.objects.get(code="39403").city == "Pelhřimov"
    assert changer.rotations == 2
    assert "Geocoded 1/1" in output


@pytest.mark.django_db
def test_gives_up_after_the_retry_budget(no_pacing):
    changer = FakeChanger([BLOCK] * (MAX_BLACKLIST_RETRIES + 2))

    _run(changer, "--codes", "39403")

    assert not PostalCode.objects.exists()
    assert changer.rotations == MAX_BLACKLIST_RETRIES


@pytest.mark.django_db
def test_stops_rotating_on_a_transport_with_one_egress(no_pacing):
    """DummyIPChanger has no second circuit to offer, so retrying only re-asks the same IP."""
    changer = FakeChanger([BLOCK], can_rotate=False)

    _run(changer, "--codes", "39403")

    assert changer.rotations == 1


@pytest.mark.django_db
def test_dry_run_makes_no_requests(query, no_pacing):
    query.filter_location_center = "11000"
    query.filter_location_radius = 10
    query.save()
    changer = FakeChanger([PELHRIMOV])

    output = _run(changer, "--dry-run")

    assert "missing: 11000" in output
    assert not PostalCode.objects.exists()
    changer.session.get.assert_not_called()


@pytest.mark.django_db
def test_collects_codes_from_ads_and_query_centres(query, make_ad, no_pacing):
    query.filter_location_center = "11000"
    query.filter_location_radius = 10
    query.save()
    ad = make_ad(query, 1)
    ad.location = "Pelhřimov, 394 03"
    ad.save()

    output = _run(FakeChanger([]), "--dry-run")

    assert "2 codes referenced, 2 not yet geocoded" in output
    assert "missing: 11000" in output
    assert "missing: 39403" in output


@pytest.mark.django_db
def test_skips_codes_already_cached(query, make_ad, no_pacing):
    PostalCode.objects.create(code="39403", city="Pelhřimov", latitude=49.43, longitude=15.22)
    ad = make_ad(query, 1)
    ad.location = "Pelhřimov, 394 03"
    ad.save()

    output = _run(FakeChanger([]), "--dry-run")

    assert "1 codes referenced, 0 not yet geocoded" in output


@pytest.mark.django_db
def test_reports_unparseable_explicit_codes(no_pacing):
    err = StringIO()
    with patch(
        "marketplace.management.commands.geocode_postal_codes.Command._ip_changer",
        return_value=FakeChanger([]),
    ):
        call_command("geocode_postal_codes", "--codes", "Praha", stdout=StringIO(), stderr=err)

    assert "Praha" in err.getvalue()
    assert not Ad.objects.exists()
