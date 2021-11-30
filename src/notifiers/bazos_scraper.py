from datetime import datetime
from time import sleep
from typing import List, Iterator
from urllib.error import URLError

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from settings import SETTINGS
from src.intervals.interval import Interval
from src.notifiers.notifier import Notifier
from src.sendables.product import Product
from src.sendables.product_database import ProductDatabase
from src.query import Query
from src.senders.sender import Sender


class BazosScraper(Notifier):
    def __init__(self, sender: Sender, logger: Sender, name: str, queries: List[Query], interval: Interval, load_images: bool = True):
        super().__init__(sender, logger, name)
        self.log("@here\nStarting")  # TODO move @here elsewhere
        self.queries: List[Query] = queries
        self.interval: Interval = interval
        self.load_images = load_images
        self.shutdown: bool = False
        self.driver: WebDriver = self.create_driver()
        self.database: ProductDatabase = ProductDatabase()

    def create_driver(self) -> WebDriver:
        chrome_options = webdriver.ChromeOptions()
        if not self.load_images:
            prefs = {"profile.managed_default_content_settings.images": 2}
            chrome_options.add_experimental_option("prefs", prefs)
        s = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=s, options=chrome_options)

    def stop(self):
        self.shutdown = True

    def send_query(self, query: Query):
        query_textbox = self.driver.find_element_by_id('hledat')
        query_textbox.send_keys(query.text)

        location_textbox = self.driver.find_element_by_id('hlokalita')
        location_textbox.send_keys(query.location[0])
        location_range_textbox = self.driver.find_element_by_name('humkreis')
        location_range_textbox.clear()
        location_range_textbox.send_keys(query.location[1])

        if query.price_range[0] > 0:
            lower_price_textbox = self.driver.find_element_by_name('cenaod')
            lower_price_textbox.send_keys(query.price_range[0])
        if query.price_range[1] > 0:
            upper_price_textbox = self.driver.find_element_by_name('cenado')
            upper_price_textbox.send_keys(query.price_range[1])

        submit_button = self.driver.find_element_by_name('Submit')
        submit_button.click()

    def next_page(self) -> bool:
        try:
            pages_div = self.driver.find_element_by_class_name('strankovani')
        except NoSuchElementException:
            return False
        next_pages_hrefs = pages_div.find_elements_by_tag_name('a')
        next_page = next_pages_hrefs[-1]

        if next_page.text == 'Další':
            self.driver.get(next_page.get_attribute('href'))
        else:
            return False

        return True

    @staticmethod
    def convert_date(date_raw: str) -> datetime:
        date = date_raw[date_raw.find("[") + 1:date_raw.find("]")]
        day, month, year = map(int, date.split('.'))
        date_formatted = datetime(day=day, month=month, year=year)
        return date_formatted

    @staticmethod
    def extract_product(product_raw: WebElement) -> Product:
        header_tmp = product_raw.find_element_by_class_name('inzeratynadpis')
        name_div = header_tmp.find_element_by_class_name('nadpis')
        date_raw = header_tmp.find_element_by_class_name('velikost10').text

        name = name_div.text
        link = name_div.find_element_by_css_selector('[href]').get_attribute('href')
        date = BazosScraper.convert_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find_element_by_class_name('popis').text
        price = product_raw.find_element_by_class_name('inzeratycena').text
        location = product_raw.find_element_by_class_name('inzeratylok').text.replace('\n', ', ')

        return Product(name=name, description=description, price=price, url=link, date=date,
                       ignore_date=ignore_date, location=location)

    def get_page_products(self) -> Iterator[Product]:
        product_elements = self.driver.find_elements_by_class_name("inzeraty")

        for product in product_elements:
            loaded_product = self.extract_product(product)
            yield loaded_product

    def run_query(self, query: Query) -> Iterator[Product]:

        self.driver.quit()
        self.driver = self.create_driver()

        url: str = SETTINGS.BAZOS_URL if len(query.category) == 0 else query.category

        while True:
            try:
                self.driver.get(url)
                self.send_query(query)
                break
            except (TimeoutException, URLError):  # todo correct exception
                self.log(f"Timeout with query: {query.text}")
                self.driver.quit()
                self.driver = self.create_driver()

        while True:
            for product in self.get_page_products():
                yield product
            if not self.next_page():
                break

    def first_run_queries(self, queries: List[Query]):
        for query in queries:
            if query.can_skip_first_round():
                counter = 0
                for product in self.run_query(query):
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
                for product in self.run_query(query):
                    if self.database.add_if_not_present(product, query):
                        new_products.append(product)
                        self.log(f"Found new product named: {product.name}")  # TODO maybe delete
                    elif not product.ignore_date:
                        break
                self.log(f"Sending {len(new_products)} products.")  # TODO maybe delete
                self.sender.send_sendable(new_products)

            interval = self.interval.get_next_interval()
            self.log(f"Going to sleep for {interval} seconds ({interval/60.0} minutes).")
            sleep(interval)
            self.log("Waking up.")

        self.driver.quit()
