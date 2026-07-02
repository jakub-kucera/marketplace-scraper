import logging
import requests

from bazos.const import NEW_PRODUCT_LOAD_MAX
from bazos.models import Ad, AdStatus, Query
from bazos.scraping.bazos.bazos_scraper import BazosScraper

logger = logging.getLogger(__name__)


class BazosQueryRunner:
    def __init__(self, query: Query, session: requests.Session):
        self.query = query
        self.session = session
        self.scraper = BazosScraper(session)
        self.new_product_counter = 0

    def _is_known(self, product: Ad) -> bool:
        return Ad.objects.filter(
            query=self.query,
            marketplace=product.marketplace,
            external_id=product.external_id,
        ).exists()

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
            if not self._is_known(product):
                product.query = self.query
                self._handle_new_product(product)
            else:
                logger.debug("Product already exists %s", product)
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
