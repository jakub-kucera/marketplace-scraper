import logging
import requests

from bazos.const import NEW_PRODUCT_LOAD_MAX
from bazos.models import Ad, Query
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)


class BazosQueryRunner:
    def __init__(self, query: Query, session: requests.Session):
        self.query = query
        self.senders = [DiscordSender.from_model(query.sender)] if query.sender else []
        self.session = session
        self.scraper = BazosScraper(session)
        self.new_product_counter = 0

    def send_to_senders(self, product: Ad):
        for sender in self.senders:
            sender.send_sendable([product])

    def _is_known(self, product: Ad) -> bool:
        return Ad.objects.filter(query=self.query, bazos_id=product.bazos_id).exists()

    def run_new_query(self):
        self.query.new_query = False

        counter = 0
        for product in self.scraper.run_query(self.query):
            if not product.topped:
                counter += 1
                if counter >= NEW_PRODUCT_LOAD_MAX:
                    break

            if not self.query.ignore_first_run:
                logger.info("New product %s", product)
                self.new_product_counter += 1
                self.send_to_senders(product)

            product.query = self.query
            product.save()

    def run_existing_query(self):
        for product in self.scraper.run_query(self.query):
            if not self._is_known(product):
                logger.info("New product %s", product)
                self.new_product_counter += 1
                product.query = self.query
                self.send_to_senders(product)
                product.save()
                if self.query.load_full_description:
                    # TODO improve by putting into some kind of queue?
                    self.scraper.load_full_description(product)
                    product.save()
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
