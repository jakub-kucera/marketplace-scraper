"""SbazarScraper — search via Sbazar's public JSON API.

Implements the `MarketplaceScraper` protocol (bazos/scraping/marketplace.py) for
Sbazar.cz. Every field name and limit below was measured live 2026-08-22 and is
documented in docs/research/marketplaces/SBAZAR.md §5a. This module follows
docs/archive/shipped/SBAZAR_SCRAPER.md exactly — deviating without updating that spec
will re-open bugs it already found (price-by-agreement rejecting every negotiable ad,
short_description overflowing its column, leaking the seller's real name).
"""
import logging
from datetime import datetime
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import requests
from django.utils import timezone

from bazos.const import (
    SBAZAR_BASE_URL,
    SBAZAR_DEDUP_BREAK_STREAK,
    SBAZAR_MAX_PAGES,
    SBAZAR_PAGE_SIZE,
)
from bazos.models import Ad, Marketplace, PriceType, Query

logger = logging.getLogger(__name__)

PRAGUE = ZoneInfo("Europe/Prague")


class SbazarScraper:
    """MarketplaceScraper for Sbazar.cz, backed by its public JSON API."""

    marketplace = Marketplace.SBAZAR.value

    # Not part of the MarketplaceScraper protocol — an optional extension point
    # QueryRunner.run_existing_query reads via getattr(..., 1). Sbazar's default
    # listing order is edit time, not creation time (see SBAZAR_DEDUP_BREAK_STREAK's
    # comment in bazos/const.py), so the walk needs more than one known hit before it
    # can be confident it has reached genuinely old content.
    dedup_break_streak = SBAZAR_DEDUP_BREAK_STREAK

    def __init__(self, session: requests.Session) -> None:
        self.session = session

    # ---------- protocol member 1 ----------
    def run_query(self, query: Query) -> Iterator[Ad]:
        extra_params = dict(query.extra_params)
        base_url = extra_params.pop("base_url", SBAZAR_BASE_URL)

        params: dict[str, Any] = {"limit": SBAZAR_PAGE_SIZE}
        if query.text:
            params["phrase"] = query.text
        if query.price_lower:
            params["price_from"] = query.price_lower
        if query.price_upper:
            params["price_to"] = query.price_upper
        params.update(extra_params)   # category_id comes from here

        offset = 0
        for _ in range(SBAZAR_MAX_PAGES):
            params["offset"] = offset
            payload = self._get(f"{base_url}/api/v1/items/search", params)
            results = payload.get("results") or []
            if not results:
                return
            for row in results:
                yield self._map_item(row, base_url)
            offset += len(results)
            total = (payload.get("pagination") or {}).get("total")
            if total is not None and offset >= total:
                return
            if len(results) < SBAZAR_PAGE_SIZE:
                return

    # ---------- protocol member 2 ----------
    def load_full_description(self, ad: Ad) -> Ad:
        """NOT a no-op: `description` is absent from every search result.

        Called by QueryRunner._handle_new_product with NO try/except, so an
        exception escaping here aborts the rest of that query's pass. Catch everything.
        """
        try:
            payload = self._get(f"{SBAZAR_BASE_URL}/api/v1/items/{ad.external_id}", None)
        except requests.RequestException as e:
            logger.info("Sbazar detail fetch failed for ad %s: %s", ad.external_id, e)
            return ad
        description = payload.get("description") or ""
        if not description:
            logger.debug("Sbazar detail for ad %s carried no description", ad.external_id)
            return ad
        ad.full_description = description
        ad.short_description = description[:300]      # column is 300 — see spec §6.2
        return ad

    # ---------- protocol member 3 ----------
    def check_blacklisted(self) -> bool:
        """Always False: no blocking has ever been observed on /api/, so there is no
        measured signal to detect. Do NOT invent one.

        Two consequences the spec covers deliberately: this makes the wrong-URL path in
        Query.url unreachable (spec §2.3), and the "never blocked" evidence was gathered
        over a direct connection, not through Tor (spec §1.5). If you later give this a
        real implementation, re-read both sections first.
        """
        return False

    # ---------- helpers ----------
    def _get(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        response = self.session.get(
            url,
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
                ),
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _map_item(row: dict[str, Any], base_url: str) -> Ad:
        price, price_type = SbazarScraper._price_and_type(row)
        return Ad(
            external_id=row["id"],
            marketplace=Marketplace.SBAZAR.value,
            url=f"{base_url}/inzerat/{row['seo_name']}",
            name=(row.get("name") or "")[:120],
            price_raw=SbazarScraper._format_price(row),
            price=price,
            price_type=price_type,
            location=SbazarScraper._format_location(row),
            view_count=None,                       # Sbazar exposes none — never synthesise
            publish_date=SbazarScraper._parse_date(row.get("create_date")),
            topped=bool(row.get("topped")),        # a real JSON bool, not a string
            short_description="",                  # detail-only; filled by load_full_description
            publisher_name=SbazarScraper._publisher_name(row),
        )

    @staticmethod
    def _format_price(row: dict[str, Any]) -> str:
        """MUST branch on the boolean, never on `price == 0`. See spec §6.1."""
        if row.get("price_by_agreement"):
            return "Dohodou"
        return f"{row.get('price', 0)} Kč"

    @staticmethod
    def _price_and_type(row: dict[str, Any]) -> tuple[int | None, PriceType]:
        """§6 of docs/research/PRICE_PARSING.md, measured on 4,000 live rows:
        `price_by_agreement` always implies `price == 0` (0 counter-examples), but the
        converse fails 33 times — 0.8% are genuine free giveaways, not negotiables. MUST
        branch on the boolean first, never on `price == 0` alone (same trap `_format_price`
        guards against).
        """
        if row.get("price_by_agreement"):
            return None, PriceType.NEGOTIABLE
        price = row.get("price", 0)
        if price == 0:
            return 0, PriceType.FREE
        return price, PriceType.EXACT

    @staticmethod
    def _format_location(row: dict[str, Any]) -> str:
        """`municipality` is empty in ~5% of rows; district/region never are."""
        loc = row.get("locality") or {}
        parts = [loc.get("municipality"), loc.get("district"), loc.get("region")]
        return ", ".join(p for p in parts if p)[:128]

    @staticmethod
    def _publisher_name(row: dict[str, Any]) -> str:
        """`shop_url`, NOT `shop_name` — shop_name is the seller's real full name. §6.4."""
        user_service = (row.get("user") or {}).get("user_service") or {}
        return (user_service.get("shop_url") or "")[:100]

    @staticmethod
    def _parse_date(value: str | None):
        """`create_date` is naive local time, e.g. '2026-08-22T17:16:53'. USE_TZ is True."""
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Sbazar: unparseable create_date %r", value)
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, PRAGUE)
        return parsed
