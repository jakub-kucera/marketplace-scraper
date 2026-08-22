"""VintedScraper — search via the `vinted-scraper` package.

Implements the `MarketplaceScraper` protocol (bazos/scraping/marketplace.py) for Vinted.
Field names and API behaviour below come from a live probe of `vinted-scraper` 4.0.0
against `vinted.cz` — see docs/refactor/STAGE8_VINTED_SPEC.md, which this module follows
exactly. Deviating from that spec without updating it there will re-open bugs it already
found (Ad.external_id overflow, decimal prices multiplying 10x through parse_price, an
uncaught detail-fetch RuntimeError truncating a scrape mid-pass).
"""
import logging
from typing import Iterator

import requests
from vinted_scraper import VintedScraper as VintedApiClient

from bazos.const import VINTED_BASE_URL, VINTED_MAX_PAGES, VINTED_PAGE_SIZE
from bazos.models import Ad, Marketplace, Query

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
        self._last_base_url: str = VINTED_BASE_URL

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
        self._last_base_url = base_url
        return client

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
            "order": "newest_first",  # mandatory — dedup assumes newest-first ordering
            "per_page": VINTED_PAGE_SIZE,
            **extra_params,
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
                yield self._map_item(item)
            if len(items) < VINTED_PAGE_SIZE:
                break
            page += 1

    @staticmethod
    def _map_item(item) -> Ad:
        return Ad(
            external_id=item.id,
            marketplace=Marketplace.VINTED.value,
            url=item.url,
            name=item.title[:120],
            price_raw=VintedScraper._format_price(item),
            location="",
            view_count=None,
            publish_date=None,
            topped=bool(item.promoted),
            short_description="",
            publisher_name="",
        )

    @staticmethod
    def _format_price(item) -> str:
        """Integer CZK only — `parse_price` strips non-digits, so a decimal point would
        silently multiply the parsed value by 10. See STAGE8_VINTED_SPEC.md §4.5.

        Uses `total_item_price` (buyer-protection fee included) rather than `price`,
        falling back to `price` when the fee isn't present.
        """
        amount = item.total_item_price if item.total_item_price is not None else item.price
        return f"{round(amount)} {item.currency}"

    def load_full_description(self, ad: Ad) -> Ad:
        """NOT a no-op — description is None on every search result.

        Two distinct, both-normal failure modes: (a) HTTP 200 with no OpenGraph tags on
        the item page -> a sparse `{'id'}`-only response, no exception (measured 5/8
        success). (b) non-200 (item sold/deleted between search and this call) ->
        RuntimeError from the library. Mode (b) is the one that matters: this is called
        with no try/except by BazosQueryRunner._handle_new_product, so letting it escape
        would abort the rest of that query's pass mid-loop over one sold listing.
        """
        client = self._client_for(self._last_base_url)
        try:
            detail = client.item(str(ad.external_id))
        except RuntimeError as e:
            logger.info("Vinted detail fetch failed for ad %s: %s", ad.external_id, e)
            return ad
        description = getattr(detail, "description", None)
        if not description:
            logger.debug("Vinted detail for ad %s carried no description", ad.external_id)
            return ad
        ad.full_description = description
        return ad

    def check_blacklisted(self) -> bool:
        return False
