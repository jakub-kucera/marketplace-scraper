import logging
import requests

from bazos.const import NEW_PRODUCT_LOAD_MAX
from bazos.models import Ad, AdStatus, Marketplace, PriceChange, Query
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.marketplace import MarketplaceScraper

logger = logging.getLogger(__name__)


def _build_scrapers(session: requests.Session) -> dict[str, MarketplaceScraper]:
    """Return the registry of available scrapers, keyed by marketplace name.

    Add new entries here when new marketplaces are implemented (Stage 8+).

    Marketplace.BAZOS_API (BazosApiScraper, see docs/bazos-api/BAZOS_HIDDEN_API_RESEARCH.md)
    is registered for validation only — no production Query currently uses it,
    so the normal run_scraper loop is unaffected. Compare it against Marketplace.BAZOS
    with `python manage.py compare_bazos_scrapers`.
    """
    return {
        Marketplace.BAZOS.value: BazosScraper(session),
        Marketplace.BAZOS_API.value: BazosApiScraper(session),
        # Marketplace.VINTED.value: VintedScraper(session),   # Stage 8
    }


class BazosQueryRunner:
    def __init__(self, query: Query, session: requests.Session):
        self.query = query
        self.session = session
        scrapers = _build_scrapers(session)
        self.scraper: MarketplaceScraper = scrapers[query.marketplace]
        self.new_product_counter = 0

    def _get_known(self, product: Ad) -> Ad | None:
        return Ad.objects.filter(
            query=self.query,
            marketplace=product.marketplace,
            external_id=product.external_id,
        ).first()

    def _handle_new_product(self, product: Ad):
        logger.info("New product %s", product)
        self.new_product_counter += 1
        product.status = AdStatus.PENDING
        product.save()
        if self.query.load_full_description:
            self.scraper.load_full_description(product)
            product.save()

    def run_new_query(self):
        self.query.new_query = False

        counter = 0
        for product in self.scraper.run_query(self.query):
            if not product.topped:
                counter += 1
                if counter >= NEW_PRODUCT_LOAD_MAX:
                    break

            product.query = self.query
            if self.query.ignore_first_run:
                product.status = AdStatus.SUPPRESSED
                product.save()
            else:
                self._handle_new_product(product)

    def run_existing_query(self):
        for product in self.scraper.run_query(self.query):
            existing = self._get_known(product)
            if existing is None:
                product.query = self.query
                self._handle_new_product(product)
            else:
                if existing.price_raw != product.price_raw:
                    logger.info(
                        "Price changed for ad %d: %s -> %s", existing.pk, existing.price_raw, product.price_raw
                    )
                    PriceChange.objects.create(
                        ad=existing,
                        old_price=existing.price_raw,
                        new_price=product.price_raw,
                    )
                    existing.price_raw = product.price_raw
                    existing.status = AdStatus.PRICE_CHANGED
                    existing.save(update_fields=["price_raw", "status"])
                logger.debug("Product already exists %s", existing)
                if product.topped:
                    logger.debug("TOP product — continuing")
                else:
                    logger.debug("Regular product — breaking")
                    break

    def run(self) -> int:
        if self.query.new_query:
            logger.info("Running NEW query %s", self.query)
            self.run_new_query()
        else:
            logger.info("Running EXISTING query %s", self.query)
            self.run_existing_query()

        return self.new_product_counter
