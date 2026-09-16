"""Zboží.cz — suggest, product, and price history.

Every endpoint here is measured in `docs/research/marketplaces/ZBOZI_API.md`, and all
three are **robots-allowed** for `User-agent: *` (§4). `search` is the exception and is
gated; see `ReferenceProvider.search`.

This is an **unsupported private API** — the website's own XHR surface, not a product.
`refprice/tests/test_zbozi_contract.py` is the weekly live check that it still parses,
in the spirit of `contract-check.yml`. It is the mitigation; optimism is not.
"""
import datetime as dt
import logging
import urllib.parse

import requests

from refprice.providers.base import (
    Candidate,
    NotPermitted,
    PricePoint,
    RefProductFacts,
    register,
)

logger = logging.getLogger(__name__)

BASE = "https://www.zbozi.cz"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
#: connect/read. Measured latencies are 50-160 ms; this is for a stalled socket, which is
#: what an unreachable host looks like rather than a refused connection.
TIMEOUT = (10, 20)

#: The 261-byte field list. `$all$` returns 29.4 KB of the same product.
FILTER_FIELDS = (
    "displayName,displayNameExt,normalizedName,minPrice,medianPrice,maxPrice,shopCount,"
    "productNo,releaseDateUTC,vendorName,categoryId,rootCategoryId,id,availability,url"
)

MAX_CANDIDATES = 8


def _czk(hundredths: object) -> int | None:
    """Hundredths of CZK -> whole CZK. The one place this conversion happens."""
    if hundredths is None or not isinstance(hundredths, (int, float)):
        return None
    return round(hundredths / 100)


def _date(timestamp: object) -> dt.date | None:
    if not isinstance(timestamp, (int, float)) or not timestamp:
        return None
    return dt.datetime.fromtimestamp(timestamp, dt.UTC).date()


@register
class ZboziProvider:
    name = "zbozi"

    def __init__(self) -> None:
        # Its own session, deliberately not the scraper's Tor one: Zbozi does not block,
        # and CZ sites 403 Tor exits widely. Same call VintedScraper makes.
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    # -- suggest ------------------------------------------------------------

    def suggest(self, phrase: str) -> list[Candidate]:
        # `?phrase=`, not `?q=`: the latter is what `Disallow: /*?q=` matches. The missing
        # trailing slash is load-bearing too — `/suggestV2/?phrase=` 404s.
        url = f"{BASE}/suggestV2?phrase={urllib.parse.quote(phrase)}"
        payload = self._get(url)
        if not payload:
            return []

        seen: set[str] = set()
        candidates: list[Candidate] = []
        for item in payload.get("suggestProductItems") or []:
            slug = item.get("normalizedName")
            if not slug or slug in seen:
                # Variants of one product repeat their parent slug many times over.
                continue
            seen.add(slug)
            candidates.append(
                Candidate(slug=slug, name=item.get("sentence") or slug,
                          image_url=item.get("imageUrl") or None)
            )
            if len(candidates) >= MAX_CANDIDATES:
                break
        return candidates

    # -- product ------------------------------------------------------------

    def fetch(self, slug: str) -> RefProductFacts | None:
        url = (f"{BASE}/api/v3/product/{urllib.parse.quote(slug)}/"
               f"?filterFields={urllib.parse.quote(FILTER_FIELDS)}")
        payload = self._get(url)
        # The API answers an unknown slug with `status: 404` inside a body, so the HTTP
        # code alone is not enough to tell a miss from a hit.
        if not payload or payload.get("status") != 200:
            return None
        product = payload.get("product")
        if not product:
            return None

        return RefProductFacts(
            provider=self.name,
            product_id=str(product.get("id")),
            slug=product.get("normalizedName") or slug,
            name=product.get("displayName") or "",
            brand=product.get("vendorName") or None,
            category_id=product.get("categoryId"),
            product_no=(product.get("productNo") or None),
            min_czk=_czk(product.get("minPrice")),
            median_czk=_czk(product.get("medianPrice")),
            max_czk=_czk(product.get("maxPrice")),
            shop_count=int(product.get("shopCount") or 0),
            availability=product.get("availability") or "unknown",
            release_date=_date(product.get("releaseDateUTC")),
            url=product.get("url") or None,
        )

    # -- history ------------------------------------------------------------

    def history(self, product_id: str, months_back: int = 13) -> list[PricePoint]:
        url = f"{BASE}/api/v3/pricetrend/product-v3/{urllib.parse.quote(str(product_id))}"
        # min/median/max in the browser's body are client-side hints only — the series is
        # byte-identical without them, so there is nothing to supply.
        payload = self._post(url, {"monthsBack": months_back})
        if not payload:
            return []

        points = []
        for raw in payload.get("pricePoints") or []:
            when = _date(raw.get("date"))
            if when is None:
                continue
            points.append(
                PricePoint(
                    date=when,
                    min_czk=_czk(raw.get("minPriceHa")),
                    median_czk=_czk(raw.get("medianPriceHa")),
                    max_czk=_czk(raw.get("maxPriceHa")),
                )
            )
        return sorted(points, key=lambda p: p.date)

    # -- search (robots-disallowed) -----------------------------------------

    def search(self, phrase: str, *, allow_disallowed: bool = False) -> list[Candidate]:
        if not allow_disallowed:
            raise NotPermitted(
                "Zbozi's free-text search is robots-disallowed (Disallow: /*?q=). "
                "Pass allow_disallowed=True to use it deliberately."
            )
        build_id = self._build_id()
        if not build_id:
            return []
        url = (f"{BASE}/_next/data/{build_id}/hledej.json"
               f"?q={urllib.parse.quote(phrase)}")
        payload = self._get(url)
        if not payload:
            return []
        products = (
            payload.get("pageProps", {}).get("data", {})
            .get("productsResults", {}).get("products") or []
        )
        return [
            Candidate(slug=p.get("normalizedName") or "", name=p.get("displayName") or "")
            for p in products[:MAX_CANDIDATES]
            if p.get("normalizedName")
        ]

    def _build_id(self) -> str | None:
        """The Next.js buildId rotates on every deploy — scrape it, never hardcode."""
        try:
            response = self.session.get(
                f"{BASE}/vyrobek/apple-iphone-13/?varianta=128-gb-cerny&noredirect=1",
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.warning("Zbozi buildId fetch failed: %s", exc)
            return None
        marker = '"buildId":"'
        start = response.text.find(marker)
        if start == -1:
            return None
        start += len(marker)
        return response.text[start:response.text.find('"', start)]

    # -- transport ----------------------------------------------------------

    def _get(self, url: str) -> dict | None:
        try:
            response = self.session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            # Every uncertain path is neutral: a transport failure means "no opinion",
            # never an exception escaping into a caller that is mid-resolution.
            logger.warning("Zbozi GET failed (%s): %s", url, exc)
            return None
        return self._body(response, url)

    def _post(self, url: str, json_body: dict) -> dict | None:
        try:
            response = self.session.post(url, json=json_body, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("Zbozi POST failed (%s): %s", url, exc)
            return None
        return self._body(response, url)

    @staticmethod
    def _body(response: requests.Response, url: str) -> dict | None:
        if response.status_code != 200:
            logger.warning("Zbozi returned HTTP %s for %s", response.status_code, url)
            return None
        try:
            return response.json()
        except ValueError:
            logger.warning("Zbozi returned non-JSON for %s", url)
            return None
