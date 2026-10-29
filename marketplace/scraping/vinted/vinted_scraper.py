"""VintedScraper — reads Vinted's server-rendered catalog pages.

Implements the `MarketplaceScraper` protocol (bazos/scraping/marketplace.py). Vinted
withdrew the anonymous `/api/v2/catalog/items` endpoint around 2026-09-08 and every query
had been failing since; the catalog page now server-renders the full result set as a
Next.js RSC payload, and that is what this reads. Every field name, limit and trap below
was measured live on 2026-09-16 and is written up in
docs/research/marketplaces/VINTED.md, which this module follows. The implementation plan
is docs/backlog/VINTED_REWRITE.md.
"""
import logging
from decimal import Decimal, InvalidOperation
from random import uniform
from time import sleep
from typing import Any, Iterator
from urllib.parse import urljoin, urlparse

import requests

from marketplace.const import (
    VINTED_BASE_URL,
    VINTED_CURRENCY,
    VINTED_DETAIL_WAIT_TIME,
    VINTED_MAX_PAGES,
    VINTED_PAGE_SIZE,
)
from marketplace.models import Ad, Marketplace, PriceType, Query
from marketplace.scraping.vinted import flight
from marketplace.scraping.vinted.client import VintedClient

logger = logging.getLogger(__name__)

CATALOG_PATH = "/catalog"

#: extra_params keys that become repeated `<name>[]` query parameters.
LIST_PARAMS = {
    "catalog_ids": "catalog[]",
    "brand_ids": "brand_ids[]",
    "brand_collection_ids": "brand_collection_ids[]",
    "status_ids": "status_ids[]",
}


class VintedScraper:
    """MarketplaceScraper for Vinted, reading the catalog page's RSC payload.

    ⚠️ Accepts the runner's `session` and deliberately does not use it. Every scraper is
    handed `ip_changer.session`, which is bound to the Tor SOCKS proxy, and Vinted bans
    proxy/VPN egress — so `VintedClient` builds its own. The parameter stays for factory
    symmetry with `_build_scrapers`.
    """

    marketplace = Marketplace.VINTED.value

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session          # intentionally unused — see the class docstring
        self._clients: dict[str, VintedClient] = {}

    def _client_for(self, base_url: str) -> VintedClient:
        client = self._clients.get(base_url)
        if client is None:
            client = VintedClient(base_url)
            self._clients[base_url] = client
        return client

    @staticmethod
    def _base_url_from_ad(ad: Ad) -> str:
        """Derive the client's base URL from the ad's own URL rather than from whatever
        `run_query` last used — correct regardless of how the scraper registry is cached.
        """
        parsed = urlparse(ad.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    # ---------- protocol member 1 ----------
    def run_query(self, query: Query) -> Iterator[Ad]:
        extra_params = dict(query.extra_params or {})
        base_url = extra_params.pop("base_url", VINTED_BASE_URL)
        client = self._client_for(base_url)
        params = self._search_params(query, extra_params)

        checked_echo = False
        for page in range(1, VINTED_MAX_PAGES + 1):
            payload = flight.decode(client.get_flight(CATALOG_PATH, params + [("page", page)]))
            rows = flight.items(payload)
            if not rows:
                # The only trustworthy block signal: there is no status code or error body
                # to key on, and the string "datadome" appears on healthy pages too, so
                # "did anything parse" is the check. VINTED.md §10.
                logger.info("Vinted: no rows on page %d for query %s — stopping", page, query)
                return

            if not checked_echo:
                self._warn_on_param_mismatch(payload, query, params)
                checked_echo = True

            for row in rows:
                ad = self._map_row(row, base_url)
                if ad is not None:
                    yield ad

            if len(rows) < VINTED_PAGE_SIZE:
                return
            pagination = flight.get(payload, "pagination") or {}
            total_pages = pagination.get("total_pages")
            if isinstance(total_pages, int) and page >= total_pages:
                return

    @staticmethod
    def _search_params(query: Query, extra_params: dict[str, Any]) -> list[tuple[str, Any]]:
        """Build the query string as a list of pairs — `catalog[]` repeats, so a dict
        cannot express it.

        ⚠️ `order=newest_first` is mandatory: Vinted's default sort is relevance, and
        `run_existing_query`'s dedup walk assumes newest-first ordering. Measured
        chronological for non-promoted rows (VINTED.md §7).

        ⚠️ `per_page` is deliberately absent — it was retired with the v2 API and the page
        is fixed at 96.
        """
        params: list[tuple[str, Any]] = [("order", "newest_first")]
        if query.text:
            params.append(("search_text", query.text))

        for key, name in LIST_PARAMS.items():
            values = extra_params.pop(key, None) or []
            if isinstance(values, (str, int)):      # tolerate a scalar typed into the admin
                values = [values]
            params.extend((name, value) for value in values)

        currency = extra_params.pop("currency", VINTED_CURRENCY)
        if query.price_lower:
            params.append(("price_from", query.price_lower))
        if query.price_upper:
            params.append(("price_to", query.price_upper))
        if query.price_lower or query.price_upper:
            # Without it the bounds are ignored. Note they filter on `price` (ex-fee),
            # which is also what _map_row stores — see VINTED.md §6b.
            params.append(("currency", currency))

        # Anything left is passed through verbatim, so a new Vinted filter can be used
        # from the admin before this module knows about it.
        params.extend((key, value) for key, value in extra_params.items())
        return params

    @staticmethod
    def _warn_on_param_mismatch(payload: str, query: Query, params: list[tuple[str, Any]]) -> None:
        """Unknown query params are dropped silently, so assert on the echo.

        This is the canary for Vinted renaming a parameter. Without it, a renamed `order`
        degrades to relevance sort and quietly breaks the dedup walk with no error
        anywhere — which is close to how the endpoint withdrawal went unnoticed for eight
        days.
        """
        state = flight.get(payload, "initialCatalogState")
        filters = (state or {}).get("filters") if isinstance(state, dict) else None
        if not isinstance(filters, dict):
            logger.warning("Vinted: no initialCatalogState in the payload for query %s", query)
            return

        if filters.get("sortBy") != "newest_first":
            logger.warning(
                "Vinted: asked for order=newest_first but the page reports sortBy=%r "
                "(query %s) — the dedup walk assumes newest-first ordering",
                filters.get("sortBy"), query,
            )
        sent_catalogs = {str(value) for name, value in params if name == "catalog[]"}
        echoed = {str(value) for value in (filters.get("catalogIds") or [])}
        if sent_catalogs and sent_catalogs != echoed:
            logger.warning(
                "Vinted: sent catalog ids %s but the page reports %s (query %s)",
                sorted(sent_catalogs), sorted(echoed), query,
            )
        if query.text and filters.get("query") != query.text:
            logger.warning(
                "Vinted: sent search_text %r but the page reports %r (query %s)",
                query.text, filters.get("query"), query,
            )

    # ---------- mapping ----------
    @classmethod
    def _map_row(cls, row: dict[str, Any], base_url: str) -> Ad | None:
        """One search row -> an unsaved `Ad`, or None when the row is unusable.

        Returns None rather than raising: this runs inside `run_query`'s generator, and an
        exception here would truncate the rest of the query's pass — the same failure
        `load_full_description` catches one method over.
        """
        item = row.get("productItem") if isinstance(row.get("productItem"), dict) else None
        if not item:
            logger.warning("Vinted: row carried no productItem")
            return None

        external_id, title, url = item.get("id"), item.get("title"), item.get("url")
        if not isinstance(external_id, int) or not title or not url:
            logger.warning("Vinted: skipping row missing id/title/url (id=%s)", external_id)
            return None

        amount, currency = cls._price(item)
        if amount is None:
            logger.warning("Vinted: skipping row %s with no usable price", external_id)
            return None

        return Ad(
            external_id=external_id,
            marketplace=Marketplace.VINTED.value,
            # The URL is relative now ("/items/1001…-slug"), unlike the old API's absolute
            # one — urljoin also keeps an absolute value working if that ever changes back.
            url=urljoin(base_url + "/", url),
            name=title[:120],
            price_raw=f"{amount} {currency}",
            price=amount,
            price_type=PriceType.FREE if amount == 0 else PriceType.EXACT,
            short_description=cls._short_description(item),
            location="",            # Vinted is shipping-first and exposes none
            view_count=None,        # served only to the item's owner
            publish_date=None,      # ⚠️ no absolute date exists anywhere — never synthesise
            topped=bool(item.get("isPromoted")),
            publisher_name="",
        )

    @staticmethod
    def _price(item: dict[str, Any]) -> tuple[int | None, str]:
        """`price` — the seller's asking price, **excluding** Buyer Protection.

        ⚠️ Deliberately NOT `totalItemPrice`. Vinted's own `price_from`/`price_to` filter
        works on `price`, so storing the all-in figure made a `price_upper=5000` query
        return rows whose stored price was up to 5268 — which `price_range` then rejected.
        Measured: `price + serviceFee == totalItemPrice` on 96/96 rows, with the fee an
        exact `18 CZK + 5%`, so the all-in number stays derivable. See VINTED.md §6b.

        ⚠️ `amount` is a decimal STRING ("17999.00"). `parse_price` strips non-digits, so
        letting a decimal point through would silently multiply by 10.
        """
        price = item.get("price")
        if not isinstance(price, dict):
            return None, ""
        raw, currency = price.get("amount"), price.get("currencyCode")
        if raw is None or not currency:
            return None, ""
        try:
            return int(Decimal(str(raw)).to_integral_value()), currency
        except (InvalidOperation, ValueError):
            logger.warning("Vinted: unparseable price %r", raw)
            return None, ""

    @staticmethod
    def _short_description(item: dict[str, Any]) -> str:
        """`itemBox` -> "Apple MacBook Pro 2019 · Velmi dobrý".

        The shipped scraper stored "" here, which silently disabled `blocklist_keyword`
        and `required_keyword` on Vinted — both match `name + short_description`. Measured
        96/96 coverage of both lines.

        ⚠️ Not `accessibilityLabel`, which is richer but embeds both prices: it would then
        change whenever the price does, and `run_existing_query` compares `price_raw` by
        string. It also just repeats the title.
        """
        box = item.get("itemBox")
        if not isinstance(box, dict):
            return ""
        parts = [box.get("firstLine"), box.get("secondLine")]
        return " · ".join(p for p in parts if p and p != "$undefined")[:300]

    # ---------- protocol member 2 ----------
    def load_full_description(self, ad: Ad) -> Ad:
        """Fetch the item page for its description and structured specs.

        ⚠️ Called by `QueryRunner._handle_new_product` with no try/except, and
        `_tolerating_one_bad_ad` catches only `DatabaseError` — so anything escaping here
        aborts the rest of that query's pass. A listing sold or deleted between the search
        and this call is routine on a resale marketplace, so everything is caught.

        Paced before the request: a `new_query` backfill calls this up to
        NEW_PRODUCT_LOAD_MAX times with no delay of its own.
        """
        sleep(uniform(*VINTED_DETAIL_WAIT_TIME))
        try:
            payload = flight.decode(
                self._client_for(self._base_url_from_ad(ad)).get_flight(urlparse(ad.url).path)
            )
        except Exception as exc:                      # noqa: BLE001 — see the docstring
            logger.info("Vinted detail fetch failed for ad %s: %s", ad.external_id, exc)
            return ad

        description = self._description(payload)
        if description:
            ad.full_description = description
        else:
            logger.debug("Vinted detail for ad %s carried no description", ad.external_id)

        attributes = self._attributes(payload)
        if attributes:
            ad.attributes = attributes
        return ad

    @staticmethod
    def _description(payload: str) -> str:
        """From the schema.org `Product` JSON-LD — present on 3/3 items probed, against
        the old library's OpenGraph scrape at 5/8.

        ⚠️ Only the description is taken. `offers.price` here is in the **seller's**
        currency (a .cz listing returned 2500 PLN while its listing row showed converted
        CZK), so a price read from this page would be wrong and would register as a price
        change on the next pass.
        """
        json_ld = flight.get(payload, "jsonLd")
        if isinstance(json_ld, dict):
            description = json_ld.get("description")
            if isinstance(description, str) and description.strip():
                return description.strip()
        return ""

    @staticmethod
    def _attributes(payload: str) -> dict[str, str]:
        """The typed spec list -> `Ad.attributes`, verbatim.

        ⚠️ Every code the page offers is kept — no allow-list. The set is
        category-dependent (a phone carries different codes from a laptop) and an unknown
        code costs nothing, whereas filtering drops data nothing can recover later.

        ⚠️ `upload_date` lands here as the relative string Vinted renders ("před hodinou")
        and is NOT parsed into `Ad.publish_date`; `status` here is the item-page condition
        id, which is a different namespace from the `status_ids[]` filter value.
        """
        found: dict[str, str] = {}
        for block in flight.iter_values(payload, "attributes"):
            if not isinstance(block, list):
                continue
            for attribute in block:
                if not isinstance(attribute, dict):
                    continue
                code, data = attribute.get("code"), attribute.get("data")
                if not code or not isinstance(data, dict):
                    continue
                value = data.get("value")
                if value not in (None, "", "$undefined"):
                    found[str(code)] = str(value)
        return found

    # ---------- protocol member 3 ----------
    def check_blacklisted(self) -> bool:
        """Always False: no block signal has ever been observed on these pages, so there
        is nothing measured to detect. Nothing in production calls this."""
        return False
