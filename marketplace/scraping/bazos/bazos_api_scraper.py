"""BazosApiScraper — search via Bazos's hidden mobile JSON API.

Alternate implementation of the `MarketplaceScraper` protocol, sitting next to
`BazosScraper` for validation (see docs/research/bazos-api/HIDDEN_API.md).
Registered in `QueryRunner._build_scrapers()` under the `bazos_api` key —
no existing `Query` row uses that marketplace value, so this is inert for the
production `run_scraper` loop until a `Query` is deliberately switched over.

Uses the same `Query` fields as `BazosScraper` (text, section/category,
price_lower/upper, location_center/radius) — no model changes required.
"""
import logging
from datetime import datetime
from random import uniform
from time import sleep
from typing import Iterator

import requests
from django.utils import timezone
from requests import Response

from marketplace.const import (
    API_PAGE_SIZE,
    BAZOS_API_BASE_URL,
    BAZOS_DETAIL_WAIT_TIME,
    BAZOS_PAGE_WAIT_TIME,
    BAZOS_REQUEST_TIMEOUT,
    MAX_ATTEMPTS,
    PAGINATION_PROGRESS_LOG_INTERVAL,
)
from marketplace.exceptions import MarketplaceBlockedError
from marketplace.filters import parse_price_and_type
from marketplace.models import Ad, Marketplace, PriceType, Query
from marketplace.scraping.bazos.bazos_scraper import BazosScraper
from marketplace.scraping.bazos.user_agent import default_user_agent
from ip_changer.tor import PROXIES

logger = logging.getLogger(__name__)

#: `ad-detail-2.php`'s own `price_type` vocabulary, measured live 2026-08-23 (see
#: docs/research/PRICE_PARSING.md §4) — differs from PriceType's names
#: (NEGOTIATED/OFFERED here vs NEGOTIABLE/MAKE_OFFER there), so the mapping is explicit
#: rather than assumed. "Zdarma"/"Nerozhoduje" were NOT observed in the live sample, so
#: their API price_type strings are unknown and deliberately absent here — an
#: unrecognised value falls back to the listing-parsed price_type instead of guessing.
_API_PRICE_TYPE_MAP: dict[str, str] = {
    "EXACT": PriceType.EXACT,
    "NEGOTIATED": PriceType.NEGOTIABLE,
    "OFFERED": PriceType.MAKE_OFFER,
    "IN_TEXT": PriceType.IN_TEXT,
}


def _to_bool(value) -> bool:
    """Listing payloads encode `topped` as the string "true"/"false"; detail
    payloads use a real JSON boolean. Handle both.
    """
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _parse_listing_date(date_raw: str) -> datetime:
    naive = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
    return timezone.make_aware(naive)


def parse_listing_item(item: dict) -> dict:
    """Pure parsing of one `ads.php` listing entry, as `Ad` field values.

    Thin payload — no description, images, GPS or publisher ids, and no structured price
    (HIDDEN_API.md §5.1). `price_formatted` follows the same string grammar as the HTML
    scraper (§4), so it is parsed the same way; `load_full_description` upgrades this to the
    API's own `price_type` when the detail call happens.

    **Module-level, not a method**, because two callers outside this class need it —
    `bazos/enrichment.py` parses seller-inventory rows with it — and a `@staticmethod`
    reached through the class disappears the moment a test patches `BazosApiScraper`, taking
    the parsing with it and yielding a `MagicMock` where an int should be.
    """
    price_raw = item["price_formatted"]
    price, price_type = parse_price_and_type(price_raw)
    return {
        "external_id": int(item["id"]),
        "name": item["title"],
        "price_raw": price_raw,
        "price": price,
        "price_type": price_type,
        "url": item["url"],
        "location": item["locality"],
        "publish_date": _parse_listing_date(item["from"]),
        "topped": _to_bool(item.get("topped", False)),
        "view_count": int(item["views"]),
    }


class BazosApiScraper:
    marketplace: str = Marketplace.BAZOS_API

    def __init__(self, session: requests.Session):
        self.sent_requests_count = 0
        if session:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.proxies = PROXIES
        # Not stored on self.session.headers: the session is shared with
        # BazosScraper (same Tor identity), and requests_random_user_agent
        # patches Session-level UA rotation for the HTML scraper — mutating
        # shared session headers here would leak into its requests too.
        self._user_agent = default_user_agent()

    @staticmethod
    def _build_query_params(query: Query) -> dict:
        params: dict = {"sort": "date"}
        if query.text:
            params["query"] = query.text
        if query.section_id:
            params["section"] = query.section.bazos_id
        if query.category_id:
            params["category"] = query.category.bazos_id
        if query.price_lower:
            params["price_from"] = query.price_lower
        if query.price_upper:
            params["price_to"] = query.price_upper
        if query.location_center:
            params["zip_code"] = query.location_center
            params["distance"] = query.location_radius
        return params

    @staticmethod
    def extract_product(item: dict) -> Ad:
        parsed = parse_listing_item(item)
        return Ad(
            external_id=parsed["external_id"],
            marketplace=Marketplace.BAZOS_API,
            name=parsed["name"],
            price_raw=parsed["price_raw"],
            price=parsed["price"],
            price_type=parsed["price_type"],
            url=parsed["url"],
            location=parsed["location"],
            publish_date=parsed["publish_date"],
            topped=parsed["topped"],
            short_description="",  # not present in the thin listing payload
            view_count=parsed["view_count"],
            publisher_name="",  # only known after load_full_description
        )

    def run_request(self, url: str, params: dict | None = None) -> Response | None:
        params = params or {}
        response: Response | None = None
        for _ in range(MAX_ATTEMPTS):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers={"User-Agent": self._user_agent},
                    timeout=BAZOS_REQUEST_TIMEOUT,
                )
                self.sent_requests_count += 1
                break
            except requests.exceptions.RequestException:
                logger.warning("BazosApiScraper request failed, retrying: %s", url)
        return response

    def _fetch_page(self, params: dict, offset: int) -> tuple[list[dict], int | None]:
        page_params = {**params, "limit": API_PAGE_SIZE, "offset": offset}
        response = self.run_request(f"{BAZOS_API_BASE_URL}/ads.php", params=page_params)
        if response is None:
            logger.warning("BazosApiScraper: no response fetching offset=%d, stopping query", offset)
            return [], None
        if response.status_code in (403, 429):
            raise MarketplaceBlockedError.from_response(response)
        if response.status_code != 200:
            logger.warning("BazosApiScraper: status=%d fetching offset=%d, stopping query", response.status_code, offset)
            return [], None
        total_header = response.headers.get("x-total-count")
        total = int(total_header) if total_header is not None else None
        return response.json(), total

    def fetch_by_ids(self, external_ids: list[int]) -> dict[int, dict] | None:
        """Bulk-fetch listings by id. Missing ids are simply absent from the result.

        That absence is the whole delisting signal: `ads.php` silently omits ids it no
        longer has rather than erroring (HIDDEN_API.md §3.1), so one request answers "which
        of these 210 are still up" and returns their current `price_formatted` and `views`
        for free.

        ⚠️ **`None` and `{}` mean opposite things, and conflating them destroys data.**

        - `{}` — a successful response that listed none of these ids. Every one is gone.
        - `None` — no usable answer: the request failed, timed out, or came back unparseable.
          The caller must record nothing.

        Returning `{}` for a failed request is exactly the bug this signature now prevents:
        a cold Tor circuit made `run_request` exhaust its retries, which read as "all 210 of
        these are gone" and wrote false removals into the only outcome data the project has.

        ⚠️ **A successful response is a third case, and it is the one that actually corrupted
        the table.** `ads.php` pages this endpoint at 30 rows when no `limit` is sent, so a
        210-id batch came back HTTP 200, well-formed and 30 rows long, and `apply_batch` read
        the 180 absent ids as removals - 19 008 rows written, 56% of a random re-checked
        sample of 200 still live (measured 2026-09-19). Neither `None` nor `{}` covers it:
        the request succeeds, it just answers a narrower question than the caller asked.
        Nothing in the payload distinguishes "truncated" from "gone", so the only defence is
        never to ask for more than one page - hence the guard rather than a post-hoc check.

        Raises `MarketplaceBlockedError` on a 403/429 so the caller can rotate.
        """
        if not external_ids:
            return {}
        if len(external_ids) > API_PAGE_SIZE:
            # `DELIST_BATCH_SIZE == API_PAGE_SIZE` is the only thing making every caller safe
            # today, and nothing pins the two together. Fail loudly rather than come back
            # silently short, which this caller writes as removals.
            raise ValueError(
                f"{len(external_ids)} ids exceeds one page of {API_PAGE_SIZE}; "
                "the response would truncate and read as removals"
            )
        response = self.run_request(
            f"{BAZOS_API_BASE_URL}/ads.php",
            params={"ad_id[]": [str(i) for i in external_ids], "limit": API_PAGE_SIZE},
        )
        if response is None:
            logger.warning("Bulk id fetch failed after %d attempts", MAX_ATTEMPTS)
            return None
        if response.status_code in (403, 429):
            raise MarketplaceBlockedError.from_response(response)
        if response.status_code != 200:
            logger.warning("Bulk id fetch returned status=%d", response.status_code)
            return None
        try:
            rows = response.json()
        except ValueError:
            logger.warning("Bulk id fetch returned non-JSON")
            return None
        if not isinstance(rows, list):
            logger.warning("Bulk id fetch returned %s, not a list", type(rows).__name__)
            return None
        return {int(row["id"]): row for row in rows if isinstance(row, dict) and "id" in row}

    def fetch_publisher_listings(self, param: str, publisher_id: int) -> list[dict] | None:
        """One seller's current active inventory. `param` is "email_id" or "phone_id".

        Undocumented but confirmed working (HIDDEN_API.md §6.4g). Thin listing payloads, the
        same shape `run_query` yields, so `parse_listing_item` reads them unchanged.

        Capped at `API_PAGE_SIZE` — one request. A seller with more listings than that is a
        dealer, and the first 210 already answer every question worth asking about one; a
        pagination loop here would turn an on-demand lookup into a crawl.

        `None` means no usable answer; `[]` means the seller genuinely has nothing listed.
        """
        response = self.run_request(
            f"{BAZOS_API_BASE_URL}/ads.php",
            params={param: publisher_id, "limit": API_PAGE_SIZE, "offset": 0},
        )
        if response is None:
            logger.warning("Publisher listing fetch failed after %d attempts", MAX_ATTEMPTS)
            return None
        if response.status_code in (403, 429):
            raise MarketplaceBlockedError.from_response(response)
        if response.status_code != 200:
            logger.warning("Publisher listing fetch returned status=%d", response.status_code)
            return None
        try:
            rows = response.json()
        except ValueError:
            logger.warning("Publisher listing fetch returned non-JSON")
            return None
        if not isinstance(rows, list):
            logger.warning("Publisher listing fetch returned %s, not a list", type(rows).__name__)
            return None
        return [row for row in rows if isinstance(row, dict)]

    def fetch_ratings(self, param: str, publisher_id: int) -> list[dict] | None:
        """One seller's whole rating history. `param` is "email_id" or "phone_id".

        Public, unauthenticated, and **unpaginated** — HIDDEN_API.md §6.4b: one request
        returns everything. Every id it needs is already stored on `EmailPublisher` /
        `PhonePublisher`, so the back catalogue is enrichable with no discovery step.

        ⚠️ Each entry carries the *reviewer's* real `name`, `phone` and `message`. Nothing
        here filters that — this is the transport, and it returns what the endpoint said.
        `bazos/ratings.py` is where the decision to keep only counts is enforced, and the
        raw entries must not be persisted on the way past.

        Same `None` vs `[]` contract as `fetch_by_ids`: `None` is "no usable answer",
        `[]` is "this seller genuinely has no ratings". Conflating them would record a
        well-reviewed seller as unrated on a single failed request.
        """
        response = self.run_request(
            f"{BAZOS_API_BASE_URL}/ratings.php", params={param: publisher_id}
        )
        if response is None:
            logger.warning("Ratings fetch failed after %d attempts", MAX_ATTEMPTS)
            return None
        if response.status_code in (403, 429):
            raise MarketplaceBlockedError.from_response(response)
        if response.status_code != 200:
            logger.warning("Ratings fetch returned status=%d", response.status_code)
            return None
        try:
            rows = response.json()
        except ValueError:
            logger.warning("Ratings fetch returned non-JSON")
            return None
        if not isinstance(rows, list):
            logger.warning("Ratings fetch returned %s, not a list", type(rows).__name__)
            return None
        return [row for row in rows if isinstance(row, dict)]

    def check_blacklisted(self) -> bool:
        response = self.run_request(f"{BAZOS_API_BASE_URL}/ads.php", params={"query": "iphone", "limit": 1, "offset": 0})
        if response is None:
            logger.warning("check_blacklisted: request failed, assuming OK")
            return False
        logger.debug("check_blacklisted status=%s", response.status_code)
        return response.status_code in (403, 429)

    def load_full_description(self, product: Ad) -> Ad:
        """Paced for the same reason as BazosScraper.load_full_description: one call per
        new ad, no delay of its own in the caller.
        """
        logger.debug("Loading full description for ad %s", product.external_id)
        sleep(uniform(*BAZOS_DETAIL_WAIT_TIME))
        response = self.run_request(f"{BAZOS_API_BASE_URL}/ad-detail-2.php", params={"ad_id": product.external_id})
        if response is None:
            logger.warning(
                "Failed to load detail for ad %s after %d attempts", product.external_id, MAX_ATTEMPTS
            )
            return product
        if response.status_code == 410:
            logger.info("Ad %s no longer available (410 deleted)", product.external_id)
            return product
        # Raised rather than folded into the `!= 200` branch below: a block is retryable on
        # a different circuit and every other path in this class treats it that way, while
        # "unexpected status" is not. Returning the product unchanged for a 403 would report
        # "this ad has no description" for an ad nobody actually looked at.
        if response.status_code in (403, 429):
            raise MarketplaceBlockedError.from_response(response)
        if response.status_code != 200:
            logger.warning("Unexpected status=%d loading detail for ad %s", response.status_code, product.external_id)
            return product

        data = response.json()
        product.full_description = data.get("description")

        api_price_type = data.get("price_type")
        if api_price_type in _API_PRICE_TYPE_MAP:
            # `price` is a string even here, and for non-EXACT types it just echoes the
            # placeholder ("Dohodou", not a number or null) — only int() it for EXACT, and
            # even then defensively: a malformed/missing value must not raise and abort
            # the pass (see _handle_new_product's docstring on load_full_description
            # exceptions) — fall back to the listing-parsed price/price_type instead.
            if api_price_type == "EXACT":
                try:
                    product.price = int(data["price"])
                    product.price_type = PriceType.EXACT
                except (KeyError, TypeError, ValueError):
                    logger.warning(
                        "Bazos API price_type=EXACT but price=%r isn't a plain int for ad %s — "
                        "keeping listing-parsed price=%s",
                        data.get("price"), product.external_id, product.price,
                    )
            else:
                product.price_type = _API_PRICE_TYPE_MAP[api_price_type]
                product.price = None
        elif api_price_type:
            logger.warning(
                "Unrecognised Bazos API price_type=%r for ad %s — keeping listing-parsed price_type=%s",
                api_price_type, product.external_id, product.price_type,
            )

        product.email_publisher, product.phone_publisher = BazosScraper._resolve_publishers(
            int(data.get("email_id") or 0), int(data.get("phone_id") or 0)
        )
        return product

    def run_query(self, query: Query) -> Iterator[Ad]:
        params = self._build_query_params(query)
        offset = 0
        page_num = 0
        while True:
            page_num += 1
            if page_num % PAGINATION_PROGRESS_LOG_INTERVAL == 0:
                logger.info("Query %s: still paginating, page %d, offset=%d", query.pk, page_num, offset)

            items, total = self._fetch_page(params, offset)
            if not items:
                logger.info("Query %s: pagination stopped after %d page(s) (empty page)", query.pk, page_num)
                break

            yield from (self.extract_product(item) for item in items)

            offset += len(items)
            if total is not None and offset >= total:
                logger.info("Query %s: pagination stopped after %d page(s) (offset %d >= total %d)",
                             query.pk, page_num, offset, total)
                break

            page_sleep_time = uniform(*BAZOS_PAGE_WAIT_TIME)
            logger.debug("Sleeping between pages for %.1f s", page_sleep_time)
            sleep(page_sleep_time)
