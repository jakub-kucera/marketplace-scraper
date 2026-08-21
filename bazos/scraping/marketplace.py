"""MarketplaceScraper protocol.

Any scraper that satisfies this interface can be plugged into
BazosQueryRunner without code changes. BazosScraper already satisfies it
implicitly — no changes to that class are needed.
"""
from typing import Iterator, Protocol

from bazos.models import Ad, Query


class MarketplaceScraper(Protocol):
    """Structural protocol for marketplace scrapers.

    Implementations: :class:`bazos.scraping.bazos.bazos_scraper.BazosScraper`
    Future:          VintedScraper (Stage 8)
    """
    marketplace: str

    def run_query(self, query: Query) -> Iterator[Ad]: ...
    def load_full_description(self, ad: Ad) -> Ad: ...
    def check_blacklisted(self) -> bool: ...
