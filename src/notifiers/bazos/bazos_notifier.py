from time import sleep
from typing import List

from settings import SETTINGS
from src.intervals.interval import Interval
from src.notifiers.bazos.bazos_scraper import BazosScraper
from src.notifiers.notifier import Notifier
from src.query import Query
from src.sendables.product import Product
from src.sendables.product_database import ProductDatabase
from src.senders.sender import Sender


class BazosNotifier(Notifier):
    def __init__(self, sender: Sender, logger: Sender, name: str, queries: List[Query], interval: Interval):
        super().__init__(sender, logger, name)
        self.scraper = BazosScraper()
        self.log("@here\nStarting")  # TODO move @here elsewhere
        self.queries: List[Query] = queries
        self.interval: Interval = interval
        self.shutdown: bool = False
        self.database: ProductDatabase = ProductDatabase()

    def stop(self):
        self.shutdown = True

    def first_run_queries(self, queries: List[Query]):
        for query in queries:
            if query.can_skip_first_round():
                counter = 0
                for product in self.scraper.query(query):
                    self.database.add_if_not_present(product, query)
                    if not product.ignore_date:
                        counter += 1
                    if counter >= SETTINGS.NEW_PRODUCT_LOAD_MAX:
                        break

    def run(self):
        self.first_run_queries(self.queries)

        self.shutdown = False
        while not self.shutdown:
            for query in self.queries:
                new_products: List[Product] = []
                for product in self.scraper.query(query):
                    if self.database.add_if_not_present(product, query):
                        new_products.append(product)
                        self.log(f"Found new product named: {product.name}")  # TODO maybe delete
                    elif not product.ignore_date:
                        break
                self.log(f"Sending {len(new_products)} products.")  # TODO maybe delete
                self.sender.send_sendable(new_products)

            interval = self.interval.get_next_interval()
            self.log(f"Going to sleep for {interval} seconds ({interval / 60.0} minutes).")
            sleep(interval)
            self.log("Waking up.")
