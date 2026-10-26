"""HTTP transport for Vinted's server-rendered catalog.

Split out of the scraper because `manage.py create_vinted_catalogs` needs the same
bootstrap-and-fetch behaviour, and because keeping it here makes the one rule that must
never be broken easy to see: **Vinted traffic does not go through Tor.**
"""
import logging
from typing import Any
from urllib.parse import urlencode

import requests
from curl_cffi import requests as curl_requests

from bazos.const import (
    VINTED_BASE_URL,
    VINTED_IMPERSONATE,
    VINTED_REQUEST_TIMEOUT,
)

logger = logging.getLogger(__name__)


class VintedClient:
    """Fetches Vinted pages as RSC flight payloads.

    ⚠️ **Builds its own session and never accepts the runner's.** Every scraper
    is handed `ip_changer.session`, which is bound to the Tor SOCKS proxy; Vinted bans
    proxy and VPN egress, so routing through it is the one change here that could get the
    host banned. `VintedScraper` keeps the runner's session for factory symmetry and hands
    it to nothing.
    """

    def __init__(self, base_url: str = VINTED_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.session: curl_requests.Session[curl_requests.Response] = curl_requests.Session(
            impersonate=VINTED_IMPERSONATE
        )
        self._bootstrapped = False

    def _get(self, url: str, headers: dict[str, str]) -> curl_requests.Response:
        """GET, failing exactly as `requests` would. curl_cffi's exceptions sit outside
        requests' hierarchy, and the runner keys on `requests.RequestException` to log a
        transport failure as a warning rather than a Sentry error; its own HTTPError also
        drops the URL from the message QueryRun groups failures by."""
        try:
            response = self.session.get(url, headers=headers, timeout=VINTED_REQUEST_TIMEOUT)
        except curl_requests.exceptions.RequestException as exc:
            raise requests.ConnectionError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            kind = "Client" if response.status_code < 500 else "Server"
            raise requests.HTTPError(
                f"{response.status_code} {kind} Error: {response.reason} for url: {response.url}"
            )
        return response

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
        self._get(
            f"{self.base_url}/",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
            },
        )
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
        response = self._get(
            url,
            headers={
                "Accept": "text/x-component",
                "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
                "RSC": "1",
            },
        )
        # ⚠️ MUST be set before reading .text. Vinted serves the payload as
        # `text/x-component` with **no charset**, and requests then falls back to
        # ISO-8859-1 for any text/* type (RFC 2616) while the bytes are UTF-8. Left to
        # itself this silently mojibakes every accented title — "Počítače" arrives as
        # "PoÄÃ­taÄe" — which would corrupt Ad.name and short_description, and with them
        # every blocklist/required keyword match. Caught only by seeding against the live
        # site; a UTF-8 fixture file cannot reproduce it.
        response.encoding = "utf-8"
        return response.text
