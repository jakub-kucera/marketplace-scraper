import requests

from bazos.const import NEW_PRODUCT_LOAD_MAX
from bazos.models import Ad, Query
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.utils import ascii_safe
from senders.services.discord_sender import DiscordSender


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
                print(ascii_safe(f"New product {product}"))
                self.new_product_counter += 1
                self.send_to_senders(product)

            product.query = self.query
            product.save()

    def run_existing_query(self):
        for product in self.scraper.run_query(self.query):
            if not self._is_known(product):
                print(ascii_safe(f"New product {product}"))
                self.new_product_counter += 1
                product.query = self.query
                self.send_to_senders(product)
                product.save()
                if self.query.load_full_description:
                    # TODO improve by putting into some kind of queue?
                    self.scraper.load_full_description(product)
                    product.save()
            else:
                print(ascii_safe(f"Product already exists {product}"))
                if product.topped:
                    print("TOP product")
                else:
                    print("regular product, BREAKING")
                    break

    def run(self) -> int:
        if self.query.new_query:
            print(ascii_safe(f"Running NEW query {self.query}"))
            self.run_new_query()
        else:
            print(ascii_safe(f"Running EXISTING query {self.query}"))
            self.run_existing_query()

        return self.new_product_counter
