import asyncio
from datetime import datetime
from typing import Optional, List, Set, Iterator

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from default_config import SETTINGS
from src.discord_sender import DiscordSender
from src.product import Product
from src.product_database import ProductDatabase
from src.query import Query


class BazosScraper:
    def __init__(self, sender: DiscordSender):
        self.sender = sender
        self.shutdown: bool = False
        self.driver = self.create_driver()
        self.database: ProductDatabase = ProductDatabase()

    @staticmethod
    def create_driver() -> WebDriver:
        return webdriver.Chrome(SETTINGS.CHROMEDRIVER_PATH)

    def stop(self):
        self.shutdown = True

    def send_query(self, query: Query):
        query_textbox = self.driver.find_element_by_id('hledat')
        query_textbox.send_keys(query.text)
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
            print(f"{loaded_product=}")
            yield loaded_product

    def run_query(self, query: Query) -> Iterator[Product]:
        self.driver.get(SETTINGS.BAZOS_URL)
        self.send_query(query)

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

    async def run(self, queries: List[Query], interval: int = 60):
        self.first_run_queries(queries)

        self.shutdown = False
        while not self.shutdown:
            for query in queries:
                new_products: List[Product] = []
                for product in self.run_query(query):
                    if self.database.add_if_not_present(product, query):
                        new_products.append(product)
                    elif not product.ignore_date:
                        break
                await self.sender.send_result(new_products)

            await asyncio.sleep(interval)

        self.driver.quit()
