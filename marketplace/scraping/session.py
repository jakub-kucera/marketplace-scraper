"""One Bazos session, and what to do when its circuit is blocked.

Two things every caller that talks to bazos.cz outside `run_scraper` needs: the `IPChanger`
the settings name, and a retry that moves to a fresh circuit when the marketplace 403s.
`check_delisted` and `geocode_postal_codes` each grew their own copy; the jobs in
`bazos/jobs.py` would have made four and five, which is where it stops being a coincidence.

**Why rotation and not backoff.** A 403 here is a property of the *exit IP*, not of the
request — roughly half of all Tor exits are blocked by Bazos, independently per destination
host. Waiting does not help; a different egress does. Rotation is a fresh SOCKS credential
and costs 0.6-1.2 s, so eight attempts are cheaper in wall clock than three with sleeps.

⚠️ **`operation` is handed the session rather than closing over one.** `rotate_circuit()`
rebuilds `changer.session`, so an operation holding the old object would retry on exactly
the circuit that was just rejected — a loop that looks like it is rotating and is not.
"""
import logging
from typing import Callable, TypeVar

import requests
from django.conf import settings

from marketplace.const import MAX_BLACKLIST_RETRIES
from marketplace.exceptions import MarketplaceBlockedError
from ip_changer.dummy import DummyIPChanger
from ip_changer.ip_changer import IPChanger
from ip_changer.tor import TorIPChanger

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AllCircuitsBlocked(RuntimeError):
    """Every attempt was 403'd, or the transport has no second egress to offer.

    A distinct exception rather than a `None` return, deliberately. Callers here return
    `None` to mean their own things — `fetch_by_ids` uses it for "no usable answer", which
    is *already* separate from "a successful response listed nothing". Folding a third
    meaning into the same value is the exact conflation that wrote 180 false removals into
    the outcome table on 2026-09-17.
    """


def build_ip_changer() -> IPChanger:
    """The same transport the scraper uses, chosen the same way `ScrapeRunner` chooses it."""
    changer_class = DummyIPChanger if settings.IP_CHANGER_TYPE == "DUMMY" else TorIPChanger
    return changer_class()


def with_rotation(
    changer: IPChanger,
    operation: Callable[[requests.Session], T],
    *,
    what: str,
    attempts: int = MAX_BLACKLIST_RETRIES,
) -> T:
    """Run `operation` against a live session, moving to a new circuit on each block.

    Raises `AllCircuitsBlocked` once the budget is spent, or as soon as `rotate_circuit()`
    reports the transport has no other egress (`DummyIPChanger` always does, which is what
    stops a dev machine re-asking the one IP it has `attempts` times).

    Anything the operation raises that is *not* a `MarketplaceBlockedError` propagates
    untouched: those are not retryable here, and swallowing one would turn a broken
    transport into a quiet empty result.
    """
    for attempt in range(1, attempts + 1):
        assert changer.session is not None
        try:
            return operation(changer.session)
        except MarketplaceBlockedError as e:
            logger.warning(
                "%s blocked on exit %s (attempt %d/%d)",
                what, e.exit_ip or "unknown", attempt, attempts,
            )
            if not changer.rotate_circuit():
                raise AllCircuitsBlocked(
                    f"{what}: blocked, and this transport has no other egress"
                ) from e
    raise AllCircuitsBlocked(f"{what}: blocked on all {attempts} circuits")
