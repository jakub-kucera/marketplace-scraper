"""MarketplaceScraper protocol.

Any scraper that satisfies this interface can be plugged into
QueryRunner without code changes. BazosScraper already satisfies it
implicitly — no changes to that class are needed.
"""
from typing import Iterator, Protocol

from bazos.models import Ad, Query


class MarketplaceScraper(Protocol):
    """Structural protocol for marketplace scrapers.

    Implementations: :class:`bazos.scraping.bazos.bazos_scraper.BazosScraper`
                     :class:`bazos.scraping.bazos.bazos_api_scraper.BazosApiScraper`
                     :class:`bazos.scraping.vinted.vinted_scraper.VintedScraper`
                     :class:`bazos.scraping.sbazar.sbazar_scraper.SbazarScraper`

    Optional extension point, not a Protocol member: a scraper may define a class
    attribute ``dedup_break_streak: int``, read via ``getattr(..., 1)`` in
    ``QueryRunner.run_existing_query``. It says how many consecutive already-known,
    non-topped ads the dedup walk tolerates before stopping — see that method's
    docstring. The default of 1 assumes the scraper's default result order is by
    creation time; ``SbazarScraper`` overrides it because Sbazar's isn't.
    """
    marketplace: str

    def run_query(self, query: Query) -> Iterator[Ad]: ...
    def load_full_description(self, ad: Ad) -> Ad: ...
    def check_blacklisted(self) -> bool: ...
