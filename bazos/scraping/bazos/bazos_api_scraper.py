"""BazosApiScraper — search via Bazos's hidden mobile JSON API.

Alternate implementation of the `MarketplaceScraper` protocol, sitting next to
`BazosScraper` for validation (see docs/bazos-api/BAZOS_HIDDEN_API_RESEARCH.md).
Registered in `BazosQueryRunner._build_scrapers()` under the `bazos_api` key —
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

from bazos.const import (
    API_PAGE_SIZE,
    BAZOS_API_BASE_URL,
    BAZOS_PAGE_WAIT_TIME,
    MAX_ATTEMPTS,
)
from bazos.exceptions import BazosBlacklistedError
from bazos.models import Ad, Marketplace, Query
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.bazos.user_agent import default_user_agent
from ip_changer.tor import PROXIES

logger = logging.getLogger(__name__)


def _to_bool(value) -> bool:
    """Listing payloads encode `topped` as the string "true"/"false"; detail
    payloads use a real JSON boolean. Handle both.
    """
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


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
    def _parse_listing_date(date_raw: str) -> datetime:
        naive = datetime.strptime(date_raw, "%Y-%m-%d %H:%M:%S")
        return timezone.make_aware(naive)

    @staticmethod
    def _parse_listing_item(item: dict) -> dict:
        """Pure parsing of one `ads.php` listing entry — thin payload, no
        description/images/GPS/publisher ids (see §5.1 of the research doc).
        """
        return {
            "external_id": int(item["id"]),
            "name": item["title"],
            "price_raw": item["price_formatted"],
            "url": item["url"],
            "location": item["locality"],
            "publish_date": BazosApiScraper._parse_listing_date(item["from"]),
            "topped": _to_bool(item.get("topped", False)),
            "view_count": int(item["views"]),
        }

    @staticmethod
    def extract_product(item: dict) -> Ad:
        parsed = BazosApiScraper._parse_listing_item(item)
        return Ad(
            external_id=parsed["external_id"],
            marketplace=Marketplace.BAZOS_API,
            name=parsed["name"],
            price_raw=parsed["price_raw"],
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
                response = self.session.get(url, params=params, headers={"User-Agent": self._user_agent})
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
        if response.status_code != 200:
            logger.warning("BazosApiScraper: status=%d fetching offset=%d, stopping query", response.status_code, offset)
            return [], None
        total_header = response.headers.get("x-total-count")
        total = int(total_header) if total_header is not None else None
        return response.json(), total

    def check_blacklisted(self, url: str = "") -> bool:
        response = self.run_request(f"{BAZOS_API_BASE_URL}/ads.php", params={"query": "iphone", "limit": 1, "offset": 0})
        if response is None:
            logger.warning("check_blacklisted: request failed, assuming OK")
            return False
        logger.debug("check_blacklisted status=%s", response.status_code)
        return response.status_code in (403, 429)

    def load_full_description(self, product: Ad) -> Ad:
        logger.debug("Loading full description for ad %s", product.external_id)
        response = self.run_request(f"{BAZOS_API_BASE_URL}/ad-detail-2.php", params={"ad_id": product.external_id})
        if response is None:
            logger.warning(
                "Failed to load detail for ad %s after %d attempts", product.external_id, MAX_ATTEMPTS
            )
            return product
        if response.status_code == 410:
            logger.info("Ad %s no longer available (410 deleted)", product.external_id)
            return product
        if response.status_code != 200:
            logger.warning("Unexpected status=%d loading detail for ad %s", response.status_code, product.external_id)
            return product

        data = response.json()
        product.full_description = data.get("description")

        email_id = data.get("email_id")
        phone_id = data.get("phone_id")
        if email_id and phone_id:
            product.email_publisher, product.phone_publisher = BazosScraper._resolve_publishers(
                int(email_id), int(phone_id)
            )
        return product

    def run_query(self, query: Query) -> Iterator[Ad]:
        if self.check_blacklisted():
            raise BazosBlacklistedError()

        params = self._build_query_params(query)
        offset = 0
        while True:
            items, total = self._fetch_page(params, offset)
            if not items:
                break

            yield from (self.extract_product(item) for item in items)

            offset += len(items)
            if total is not None and offset >= total:
                break

            page_sleep_time = uniform(*BAZOS_PAGE_WAIT_TIME)
            logger.debug("Sleeping between pages for %.1f s", page_sleep_time)
            sleep(page_sleep_time)
