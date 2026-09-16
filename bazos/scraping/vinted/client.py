"""HTTP transport for Vinted's server-rendered catalog.

Split out of the scraper because `manage.py create_vinted_catalogs` needs the same
bootstrap-and-fetch behaviour, and because keeping it here makes the one rule that must
never be broken easy to see: **Vinted traffic does not go through Tor.**
"""
import logging
from typing import Any
from urllib.parse import urlencode

import requests

from bazos.const import (
    VINTED_BASE_URL,
    VINTED_REQUEST_TIMEOUT,
    VINTED_USER_AGENT,
)

logger = logging.getLogger(__name__)


class VintedClient:
    """Fetches Vinted pages as RSC flight payloads.

    ⚠️ **Builds its own `requests.Session` and never accepts the runner's.** Every scraper
    is handed `ip_changer.session`, which is bound to the Tor SOCKS proxy; Vinted bans
    proxy and VPN egress, so routing through it is the one change here that could get the
    host banned. `VintedScraper` keeps the runner's session for factory symmetry and hands
    it to nothing.
    """

    def __init__(self, base_url: str = VINTED_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self._bootstrapped = False

    # ---------- session ----------
    def bootstrap(self) -> None:
        """One GET of the site root, which sets the anonymous session cookies.

        Vinted hands out `access_token_web` (a 24 h JWT), `refresh_token_web` and
        `anon_id` in a single hop — no JS, no cookie solving, no headless browser. Cached
        for the life of the client.

        Deliberately no retry loop: "cannot reach Vinted at all" is a genuine query
        failure and belongs on `QueryRun` via the runner's per-query handler, which is a
        different thing from the per-ad failures `load_full_description` swallows.
        """
        if self._bootstrapped:
            return
        response = self.session.get(
            f"{self.base_url}/",
            headers={
                "User-Agent": VINTED_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
            },
            timeout=VINTED_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        self._bootstrapped = True
        logger.debug("Vinted session bootstrapped against %s", self.base_url)

    # ---------- fetching ----------
    def get_flight(self, path: str, params: Any = None) -> str:
        """Fetch `path` and return the raw RSC flight payload.

        The `RSC: 1` header is what makes the server skip the HTML shell and return the
        payload directly — the same request the site's own client-side navigation makes.
        It saves a parsing step; it does not save bytes (~800 KB gzipped either way).

        `params` is a sequence of pairs, not a dict: Vinted repeats `catalog[]` and
        `brand_ids[]`, which a dict cannot express.
        """
        self.bootstrap()
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(list(params))}"
        response = self.session.get(
            url,
            headers={
                "User-Agent": VINTED_USER_AGENT,
                "Accept": "text/x-component",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                "RSC": "1",
            },
            timeout=VINTED_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        # ⚠️ MUST be set before reading .text. Vinted serves the payload as
        # `text/x-component` with **no charset**, and requests then falls back to
        # ISO-8859-1 for any text/* type (RFC 2616) while the bytes are UTF-8. Left to
        # itself this silently mojibakes every accented title — "Počítače" arrives as
        # "PoÄÃ­taÄe" — which would corrupt Ad.name and short_description, and with them
        # every blocklist/required keyword match. Caught only by seeding against the live
        # site; a UTF-8 fixture file cannot reproduce it.
        response.encoding = "utf-8"
        return response.text
