from datetime import timedelta

from settings import SETTINGS
from src.models import QueryDB, ProductDB, session
from src.notifiers.bazos.bazos_scraper import BazosScraper
from src.senders.discord_sender import DiscordSender


class BazosQueryRunner:
    def __init__(self, query: QueryDB):
        self.query = query
        # self.senders = [DiscordSender(s.url, s.notify) for s in query.bazos_senders]
        # self.senders = [DiscordSender(query.discord_sender.url, query.discord_sender.notify)]
        self.senders = [DiscordSender.from_db(query.discord_sender)]
        self.scraper = BazosScraper()

    def send_to_senders(self, product: ProductDB):
        for sender in self.senders:
            sender.send_product([product])
            # sender.send_sendable(product)

    def get_sleep_length(self, query: QueryDB):
        pass

    def run_new_query(self):
        self.query.new_query = False

        counter = 0
        for product in self.scraper.run_query(self.query):

            # only load limited amount of products, to prevent hitting limits with broad queries
            if not product.ignore_date:
                counter += 1
                if counter >= SETTINGS.NEW_PRODUCT_LOAD_MAX:
                    break

            # if product.do_send:
            #     product.do_send = False
            #     self.send_to_senders(product)
            if not self.query.ignore_first_run:
                print(f"New product {product}")
                self.send_to_senders(product)

            self.query.products.append(product)
            session.add(product)

        pass

    def run_existing_query(self):
        for product in self.scraper.run_query(self.query):
            # matching_products = db.execute(select(ProductDB).filter(ProductDB.query_id == product.query_id).filter(ProductDB.bazos_id == product.bazos_id))
            matching_products = session.query(ProductDB)\
                .filter(ProductDB.query_id == self.query.id)\
                .filter(ProductDB.bazos_id == product.bazos_id)\
                .count()
            if matching_products == 0:  # is new
                print(f"New product {product}")
                self.query.products.append(product)
                self.send_to_senders(product)
                session.add(product)
            else:
                print(f"Product already exists {product}")
                if product.ignore_date:
                    print(f"TOP product")
                else:
                    print(f"regular product, BREAKING")
                    break

            # if product.do_send:
            #     product.do_send = False
            #     self.send_to_senders(product)

    def run(self):
        # self.query.set_next_runtime(timedelta(minutes=10))
        interval = self.query.get_next_interval()
        print(f"next interval will be: {interval}")
        self.query.set_next_runtime(timedelta(minutes=interval))
        if self.query.new_query:
            print(f"Running NEW query {self.query}")
            return self.run_new_query()
        else:
            print(f"Running EXISTING query {self.query}")
            return self.run_existing_query()

