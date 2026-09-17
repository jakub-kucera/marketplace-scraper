import logging
import socket
from secrets import token_hex

import requests
import requests_random_user_agent  # type: ignore  # side-effecting: patches requests.utils.default_user_agent
from stem import Signal
from stem.control import Controller
from django.conf import settings

from ip_changer.ip_changer import IPChanger

logger = logging.getLogger(__name__)

#: Substrings that mark a User-Agent as a phone or tablet.
#: `requests_random_user_agent` patches `requests.utils.default_user_agent` to draw from its
#: pool **per call**, so every request rolls this dice independently.
MOBILE_UA_MARKERS: tuple[str, ...] = ("Mobile", "Android", "iPhone", "iPad", "Windows Phone")


def drop_mobile_user_agents() -> int:
    """Remove phone/tablet agents from the rotation pool. Returns how many were dropped.

    **Bazos serves a different DOM to mobile User-Agents**, and `BazosScraper._parse_product`
    is written against the desktop one. Measured 2026-09-17 on one query's own listing URL,
    same circuit, seconds apart:

        desktop Chrome  -> 20 rows, 0 missing `inzeratycena`
        iPhone Safari   -> 20 rows, **20** missing `inzeratycena`
        Android Chrome  -> 20 rows, **20** missing `inzeratycena`

    The mobile markup carries price and locality inline inside `div.popis` and has no
    `inzeratycena`/`inzeratylok`/`inzeratyview`/`inzeratyakce` at all, so the first row
    raises `AttributeError` and takes the whole page with it — `run_query` does
    `list(self.get_page_products(...))`. That lands outside `_tolerating_one_bad_ad` (it
    fires while the generator is being iterated, not in the loop body) and is not a
    `MarketplaceBlockedError`, so there is no retry: the query is written off for the pass.

    2 of the pool's 62 agents are mobile, so ~3% of sessions drew an unparseable site. The
    rotation is there to vary the *fingerprint*; varying the *response shape* is an
    accident, and one this parser cannot absorb.

    Deliberately **not** fixed by teaching the parser the mobile layout: that markup has no
    `inzeratyakce`, which is the only source of `publisher_email`/`publisher_phone`, so
    parsing it would silently drop seller identity and quietly degrade `SellerAdCounts` and
    `publisher_blocklist`.
    """
    pool = requests_random_user_agent.USER_AGENTS
    desktop = [ua for ua in pool if not any(m in ua for m in MOBILE_UA_MARKERS)]
    if not desktop:
        # Refuse to empty the pool: `random.choice([])` raises IndexError inside the patched
        # `default_user_agent`, which would break every request rather than 3% of them.
        logger.error(
            "User-Agent pool is entirely mobile (%d agents); leaving it unfiltered", len(pool)
        )
        return 0
    dropped = len(pool) - len(desktop)
    # Mutate in place: the library's patch closes over this list object by name in its own
    # module, and a slice assignment updates it for any holder of a reference.
    pool[:] = desktop
    return dropped


#: How many agents the import-time filter removed. Recorded rather than logged: this runs at
#: module import, which under pytest is *collection* — before the session fixture that
#: no-ops `DatabaseLogHandler.emit` — so a log record here would try to write to a database
#: the collecting process may not have. `ScrapeRunner.__init__` reports it instead.
DROPPED_MOBILE_UA_COUNT: int = drop_mobile_user_agents()


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
