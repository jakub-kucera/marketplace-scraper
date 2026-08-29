import logging
import socket
from secrets import token_hex

import requests
import requests_random_user_agent  # type: ignore  # noqa: F401 (side-effecting import: patches requests.Session UA)
from stem import Signal
from stem.control import Controller
from django.conf import settings

from ip_changer.ip_changer import IPChanger

logger = logging.getLogger(__name__)


def tor_proxies(circuit_id: str | None = None) -> dict[str, str]:
    """SOCKS proxy dict for the Tor container, optionally pinned to one circuit.

    Tor keys stream isolation on the SOCKS credentials (`IsolateSOCKSAuth`, on by
    default), so a username it has not seen before is served by a brand-new circuit with
    a new exit node — built on demand, in well under a second. That is the whole
    mechanism behind `TorIPChanger.rotate_circuit`, and it needs no control-port signal.

    Passing no `circuit_id` shares the unauthenticated default circuit, which is what the
    scrapers' own no-session fallback and `compare_bazos_scrapers` want: they are not
    rotating anything.
    """
    credentials = f"{circuit_id}:x@" if circuit_id else ""
    url = f"socks5h://{credentials}{settings.TOR_PROXY_IP}:9050"
    return {"http": url, "https": url}


PROXIES = tor_proxies()


class TorIPChanger(IPChanger):
    def __init__(self):
        # Before super(), which calls renew_session().
        self.circuit_id = token_hex(8)
        super().__init__()

    def renew_session(self):
        self.session = requests.Session()
        self.session.proxies = tor_proxies(self.circuit_id)

    def rotate_circuit(self) -> bool:
        """Draw a fresh circuit by asking Tor for one under a credential it has not seen.

        Measured on the Pi 2026-08-29: a fresh SOCKS username gets a new exit in
        0.6-1.2 s. The NEWNYM loop this replaced cost 10-50 s for a *worse* answer — it
        signalled the control port, slept `NEWNYM_WAIT_SECONDS` for the rate limit, then
        re-read icanhazip to prove the exit had changed. Under `IsolateDestAddr` that
        proof is about the icanhazip circuit and says nothing about the marketplace's,
        so the budget bought a check that could not be right (see
        `IPChanger.get_current_ip`).

        A random token rather than a counter so a restarted process cannot land back on
        a circuit it just abandoned.

        Always True: this is local state, and Tor builds the circuit lazily on the next
        request. A circuit that cannot be built surfaces there, as a request failure.
        """
        self.circuit_id = token_hex(8)
        self.renew_session()
        logger.info("Rotated to Tor circuit %s", self.circuit_id)
        return True

    def renew_ip(self):
        """Signal NEWNYM: a new identity for *every* circuit at once.

        Nothing calls this. It is kept as the coarse manual reset — `rotate_circuit` is
        per-session and cannot help if Tor's guards themselves are the problem — but
        don't read its existence as evidence the retry path signals the control port; it
        does not, deliberately.
        """
        address = socket.gethostbyname(settings.TOR_PROXY_IP)
        with Controller.from_port(address=address, port=9051) as controller:
            controller.authenticate(password=settings.TOR_PROXY_PASSWORD)
            controller.signal(Signal.NEWNYM)
