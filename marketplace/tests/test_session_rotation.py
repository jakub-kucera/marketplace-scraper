"""Tests for `bazos/scraping/session.py`.

The risk this module carries is not "does it retry" — it is that a retry can *look* like
rotation without being one, and that exhaustion can be mistaken for a result. Both failure
modes are silent, and the second one has already cost this project 180 false removals.
"""
from unittest.mock import MagicMock

import pytest
from django.test import override_settings

from marketplace.const import MAX_BLACKLIST_RETRIES
from marketplace.exceptions import MarketplaceBlockedError
from marketplace.scraping.session import AllCircuitsBlocked, build_ip_changer, with_rotation
from ip_changer.dummy import DummyIPChanger
from ip_changer.tor import TorIPChanger


def changer_yielding(*sessions, rotates=True):
    """An IPChanger whose `session` advances on each successful `rotate_circuit()`."""
    changer = MagicMock()
    changer.session = sessions[0]
    remaining = list(sessions[1:])

    def rotate():
        if not rotates:
            return False
        if remaining:
            changer.session = remaining.pop(0)
        return True

    changer.rotate_circuit.side_effect = rotate
    return changer


# ---------------------------------------------------------------------------
# build_ip_changer
# ---------------------------------------------------------------------------

@override_settings(IP_CHANGER_TYPE="DUMMY")
def test_dummy_is_selected_for_local_development():
    assert isinstance(build_ip_changer(), DummyIPChanger)


@override_settings(IP_CHANGER_TYPE="TOR")
def test_tor_is_selected_otherwise():
    assert isinstance(build_ip_changer(), TorIPChanger)


# ---------------------------------------------------------------------------
# with_rotation
# ---------------------------------------------------------------------------

def test_a_clean_call_runs_once_and_never_rotates():
    changer = changer_yielding("session-1")

    result = with_rotation(changer, lambda session: f"ok on {session}", what="probe")

    assert result == "ok on session-1"
    changer.rotate_circuit.assert_not_called()


def test_the_operation_is_handed_the_session_it_should_use():
    """The whole point of passing the session in rather than closing over one: after a
    rotation the old object is exactly the circuit that was just rejected, so an operation
    reusing it would retry against the IP it is trying to escape."""
    changer = changer_yielding("blocked-session", "fresh-session")
    seen = []

    def operation(session):
        seen.append(session)
        if session == "blocked-session":
            raise MarketplaceBlockedError(exit_ip="1.2.3.4")
        return session

    assert with_rotation(changer, operation, what="probe") == "fresh-session"
    assert seen == ["blocked-session", "fresh-session"]


def test_exhausting_the_budget_raises_rather_than_returning_a_value():
    """`AllCircuitsBlocked`, not None. Callers here already use None for their own
    meanings — `fetch_by_ids` uses it for "no usable answer", which is itself distinct from
    "a successful response listed nothing" — and folding a third meaning into the same
    value is the conflation that wrote 180 false removals on 2026-09-17."""
    changer = changer_yielding("s")
    always_blocked = MagicMock(side_effect=MarketplaceBlockedError(exit_ip="1.2.3.4"))

    with pytest.raises(AllCircuitsBlocked):
        with_rotation(changer, always_blocked, what="probe")

    assert always_blocked.call_count == MAX_BLACKLIST_RETRIES


def test_a_transport_with_no_second_egress_stops_immediately():
    """DummyIPChanger always reports False. Without this the dev machine would re-ask the
    one IP it has `MAX_BLACKLIST_RETRIES` times and call it rotation."""
    changer = changer_yielding("s", rotates=False)
    always_blocked = MagicMock(side_effect=MarketplaceBlockedError(exit_ip="1.2.3.4"))

    with pytest.raises(AllCircuitsBlocked):
        with_rotation(changer, always_blocked, what="probe")

    assert always_blocked.call_count == 1


def test_the_attempt_budget_is_adjustable():
    changer = changer_yielding("s")
    always_blocked = MagicMock(side_effect=MarketplaceBlockedError(exit_ip="1.2.3.4"))

    with pytest.raises(AllCircuitsBlocked):
        with_rotation(changer, always_blocked, what="probe", attempts=2)

    assert always_blocked.call_count == 2


def test_any_other_exception_propagates_untouched():
    """A dead transport must not be laundered into a quiet empty result — the same reason
    `_tolerating_one_bad_ad` catches DatabaseError and nothing wider."""
    changer = changer_yielding("s")

    with pytest.raises(ConnectionError):
        with_rotation(
            changer,
            MagicMock(side_effect=ConnectionError("socket died")),
            what="probe",
        )

    changer.rotate_circuit.assert_not_called()
