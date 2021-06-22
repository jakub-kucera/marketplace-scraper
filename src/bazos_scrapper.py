from asyncio import sleep
from typing import Optional, List

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.remote.webdriver import WebDriver

from default_config import SETTINGS
from src.discord_sender import DiscordSender
from src.product import Product
from src.query import Query


class BazosScrapper:
    def __init__(self, sender: DiscordSender):
        self.sender = sender
        self.shutdown: bool = False
        self.driver = self.create_driver()

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

    def get_page_products(self) -> List[Product]:
        product_elements = self.driver.find_elements_by_class_name("inzeraty")
        products: List[Product] = []

        for product in product_elements:
            # new_product = Product()
            header_tmp = product.find_element_by_class_name("inzeratynadpis")
            name_div = header_tmp.find_element_by_class_name("nadpis")
            name = name_div.text
            link = name_div.find_element_by_css_selector('[href]').get_attribute('href')
            description = header_tmp.find_element_by_class_name("popis").text
            price = product.find_element_by_class_name("inzeratycena").text
            location = product.find_element_by_class_name("inzeratylok").text

            new_product = Product(name=name, description=description, price=price, url=link, location=location)
            print(f"{new_product=}")
            products.append(new_product)

        return products

    async def run_query(self, query: Query) -> List[Product]:
        retrieved_products: List[Product] = []

        self.driver.get(SETTINGS.BAZOS_URL)
        self.send_query(query)

        while True:
            retrieved_products.extend(self.get_page_products())
            if not self.next_page():
                break

        return retrieved_products

    async def run(self, queries: List[Query], interval: int = 60):
        self.shutdown = False

        while not self.shutdown:

            retrieved_products: List[Product] = []
            for query in queries:
                retrieved_products.extend(await self.run_query(query))

            await self.sender.send_result(retrieved_products)
            await sleep(interval)

        self.driver.quit()
