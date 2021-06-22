from asyncio import sleep
from typing import Optional, List

from discord.ext.commands import Context
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver

from default_config import SETTINGS
from product import Product


def wrap_multi(message: str) -> str:
    return "'''" + message + "'''"


def wrap_single(message: str) -> str:
    return "'" + message + "'"


class BazosScrapper:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.shutdown: bool = False
        self.driver = self.create_driver()

    @staticmethod
    def create_driver() -> WebDriver:
        return webdriver.Chrome(SETTINGS.CHROMEDRIVER_PATH)

    def stop(self):
        self.shutdown = True

    async def send_result(self, products: List[str]):
        if len(products) != 0:
            await self.ctx.send("Found products:")
            for product in products:
                await self.ctx.send(wrap_multi(product))
        else:
            await self.ctx.send("empty")

    def send_query(self, query: str):
        query_textbox = self.driver.find_element_by_id('hledat')
        query_textbox.send_keys(query)
        submit_button = self.driver.find_element_by_name('Submit')
        submit_button.click()

    def next_page(self) -> bool:

        pages_div = self.driver.find_element_by_class_name('strankovani')
        next_pages_hrefs = pages_div.find_elements_by_tag_name('a')
        next_page = next_pages_hrefs[-1]

        if next_page.text == 'Další':
            next_page.click()  # todo fix
        else:
            return False
        # for a in :
        #     print(a.text)
        # print("printed all")
        #
        # next_page_button = self.driver.find_element_by_link_text('Další')
        # next_page_button.click()
        # except NoSuchElementException:
        #     return False
        return True

    def get_page_products(self) -> List[Product]:
        product_elements = self.driver.find_elements_by_class_name("inzeraty")
        products: List[Product] = []

        for product in product_elements:
            # new_product = Product()
            product_header_tmp = product.find_element_by_class_name("inzeratynadpis")

            product_name = product_header_tmp.find_element_by_class_name("nadpis").text
            product_description = product_header_tmp.find_element_by_class_name("popis").text
            product_price = product.find_element_by_class_name("inzeratycena").text
            product_location = product.find_element_by_class_name("inzeratylok").text

            print("=======================")
            print(f"product_name = {product_name}")
            print(f"product_description = {product_description}")
            print(f"product_price = {product_price}")
            print(f"product_location = {product_location}")

        pass

    async def run_query(self, query: str) -> List[str]:
        retrieved_products: List[str] = []

        self.driver.get(SETTINGS.BAZOS_URL)
        self.send_query(query)

        while True:
            await sleep(5)
            retrieved_products.extend(self.get_page_products())
            if not self.next_page():
                break

        return retrieved_products

    async def run(self, queries: List[str], interval: int = 60):
        self.shutdown = False

        while not self.shutdown:

            retrieved_products: List[str] = []
            for query in queries:
                retrieved_products.extend(await self.run_query(query))

            await self.send_result(retrieved_products)
            await sleep(interval)

        self.driver.quit()
