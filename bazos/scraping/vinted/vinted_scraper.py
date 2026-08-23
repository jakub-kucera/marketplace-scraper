"""VintedScraper — search via the `vinted-scraper` package.

Implements the `MarketplaceScraper` protocol (bazos/scraping/marketplace.py) for Vinted.
Field names and API behaviour below come from a live probe of `vinted-scraper` 4.0.0
against `vinted.cz` — see docs/refactor/STAGE8_VINTED_SPEC.md, which this module follows
exactly. Deviating from that spec without updating it there will re-open bugs it already
found (Ad.external_id overflow, decimal prices multiplying 10x through parse_price, an
uncaught detail-fetch RuntimeError truncating a scrape mid-pass).
"""
import logging
from random import uniform
from time import sleep
from typing import Iterator
from urllib.parse import urlparse

import requests
from vinted_scraper import VintedScraper as VintedApiClient

from bazos.const import (
    VINTED_BASE_URL,
    VINTED_DETAIL_WAIT_TIME,
    VINTED_MAX_PAGES,
    VINTED_PAGE_SIZE,
)
from bazos.models import Ad, Marketplace, PriceType, Query

logger = logging.getLogger(__name__)


class VintedScraper:
    """MarketplaceScraper for Vinted, backed by the `vinted-scraper` package.

    Deliberately ignores the `session` the runner passes in: the library builds its own
    httpx client, and Vinted bans proxy/VPN traffic, so Vinted requests egress from the
    host's real IP rather than through Tor. See STAGE8_VINTED_DESIGN.md §2.
    """
    marketplace = Marketplace.VINTED.value

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session          # accepted for factory symmetry, intentionally unused
        self._clients: dict[str, VintedApiClient] = {}

    def _client_for(self, base_url: str) -> VintedApiClient:
        """One client per base URL, cached for the lifetime of this scraper instance.

        The library fetches a session cookie on construction, so rebuilding it per
        request would double the request count — and would re-trigger the cookie
        handshake for every ad's `load_full_description` call within a query's pass.
        Construction can raise `RuntimeError` (cookie fetch failed behind
        Cloudflare/DataDome); that is intentionally left to propagate — see `run_query`.
        """
        client = self._clients.get(base_url)
        if client is None:
            client = VintedApiClient(baseurl=base_url)
            self._clients[base_url] = client
        return client

    @staticmethod
    def _base_url_from_ad(ad: Ad) -> str:
        """Derive the client's base URL straight from the ad's own URL.

        Deliberately not "whichever base_url run_query last used": that would only be
        correct because _build_scrapers currently rebuilds every scraper fresh on each
        call, so one scraper instance never outlives one query. Reading it off the ad
        itself is correct regardless of how the registry is built or cached later.
        """
        parsed = urlparse(ad.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    def run_query(self, query: Query) -> Iterator[Ad]:
        extra_params = dict(query.extra_params)
        base_url = extra_params.pop("base_url", VINTED_BASE_URL)

        # Not caught here: "cannot reach Vinted at all" is a genuine query failure,
        # recorded on QueryRun by BazosRunner.run's per-query except-Exception. This is
        # deliberately different from load_full_description's per-ad failures below,
        # which must never abort a pass.
        client = self._client_for(base_url)

        params = {
            "search_text": query.text,
            **extra_params,
            # These two always win over extra_params, not just default it: "order" is
            # required for the dedup walk in run_existing_query (assumes newest-first),
            # and "per_page" must match VINTED_PAGE_SIZE exactly or the "short page"
            # pagination sentinel below desyncs from what the server actually returns.
            "order": "newest_first",
            "per_page": VINTED_PAGE_SIZE,
        }
        if query.price_lower:
            params["price_from"] = query.price_lower
        if query.price_upper:
            params["price_to"] = query.price_upper

        page = 1
        while page <= VINTED_MAX_PAGES:
            params["page"] = page
            items = client.search(params)
            if not items:
                break
            for item in items:
                ad = self._map_item(item)
                if ad is not None:
                    yield ad
            if len(items) < VINTED_PAGE_SIZE:
                break
            page += 1

    @staticmethod
    def _map_item(item) -> Ad | None:
        """None search-result fields are real, not hypothetical: the library types id,
        title, url, price, total_item_price and currency all Optional, and a malformed
        row is exactly the kind of thing anti-bot throttling can produce. Skip and log
        rather than raising — raising here would escape the run_query generator and
        truncate the rest of the pass, the same failure load_full_description's
        try/except was written to avoid one function over.
        """
        if item.id is None or not item.title or not item.url:
            logger.warning("Vinted: skipping search result missing id/title/url (id=%s)", item.id)
            return None
        amount = VintedScraper._price_amount(item)
        if amount is None or not item.currency:
            logger.warning("Vinted: skipping search result with no usable price (id=%s)", item.id)
            return None
        return Ad(
            external_id=item.id,
            marketplace=Marketplace.VINTED.value,
            url=item.url,
            name=item.title[:120],
            price_raw=f"{amount} {item.currency}",
            price=amount,
            price_type=PriceType.EXACT,  # Vinted has no placeholder prices — see _price_amount
            location="",
            view_count=None,
            publish_date=None,
            topped=bool(item.promoted),
            short_description="",
            publisher_name="",
        )

    @staticmethod
    def _price_amount(item) -> int | None:
        """Integer CZK only — `parse_price` strips non-digits, so a decimal point would
        silently multiply the parsed value by 10. See STAGE8_VINTED_SPEC.md §4.5.

        Uses `total_item_price` (buyer-protection fee included) rather than `price`,
        falling back to `price` when the fee isn't present. None means "no usable price"
        — `_map_item` skips the item entirely rather than persist a fabricated one.
        """
        amount = item.total_item_price if item.total_item_price is not None else item.price
        return round(amount) if amount is not None else None

    @staticmethod
    def _format_price(item) -> str | None:
        """Returns None (caller skips the item) rather than a fabricated string when
        neither price nor currency is present — `f"{amount} None"` would both look broken
        to a reader and register as a spurious price change downstream, since price
        comparison is a plain string compare (bazos_query_runner.run_existing_query).
        """
        amount = VintedScraper._price_amount(item)
        if amount is None or not item.currency:
            return None
        return f"{amount} {item.currency}"

    def load_full_description(self, ad: Ad) -> Ad:
        """NOT a no-op — description is None on every search result.

        Two distinct, both-normal failure modes: (a) HTTP 200 with no OpenGraph tags on
        the item page -> a sparse `{'id'}`-only response, no exception (measured 5/8
        success). (b) non-200 (item sold/deleted between search and this call) ->
        RuntimeError from the library. Mode (b) is the one that matters: this is called
        with no try/except by BazosQueryRunner._handle_new_product, so letting it escape
        would abort the rest of that query's pass mid-loop over one sold listing.

        Paced: a new_query backfill can call this up to NEW_PRODUCT_LOAD_MAX times in a
        row with no other delay in between (see VINTED_DETAIL_WAIT_TIME).
        """
        client = self._client_for(self._base_url_from_ad(ad))
        try:
            detail = client.item(str(ad.external_id))
        except RuntimeError as e:
            logger.info("Vinted detail fetch failed for ad %s: %s", ad.external_id, e)
            return ad
        finally:
            sleep(uniform(*VINTED_DETAIL_WAIT_TIME))
        description = getattr(detail, "description", None)
        if not description:
            logger.debug("Vinted detail for ad %s carried no description", ad.external_id)
            return ad
        ad.full_description = description
        return ad

    def check_blacklisted(self) -> bool:
        return False
