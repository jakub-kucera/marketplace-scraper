import itertools
from datetime import datetime
from typing import List, Iterator, Optional
from urllib.error import URLError
from urllib.parse import urlencode

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from settings import SETTINGS
from src.notifiers.bazos.bazos_scraper import BazosScraper
from src.sendables.product_old import ProductOLD
from src.query_old import QueryOLD


class BazosBazosScraperClick(BazosScraper):
    def __init__(self, load_images: bool = True):
        self.driver_service = Service(ChromeDriverManager().install())
        self.driver_chrome_options = webdriver.ChromeOptions()
        if not load_images:
            prefs = {"profile.managed_default_content_settings.images": 2}
            self.driver_chrome_options.add_experimental_option("prefs", prefs)
        # self.driver_chrome_options.headless = True
        self.driver: Optional[WebDriver] = None

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.driver is not None:
            try:
                self.driver.quit()
            except WebDriverException:
                pass

    def create_driver(self):
        # chrome_options = webdriver.ChromeOptions()
        # if not self.load_images:
        #     prefs = {"profile.managed_default_content_settings.images": 2}
        #     chrome_options.add_experimental_option("prefs", prefs)
        # s = Service(ChromeDriverManager().install())
        if self.driver is not None:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
        self.driver = webdriver.Chrome(service=self.driver_service, options=self.driver_chrome_options)

    def send_query(self, query: QueryOLD):
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

    @classmethod
    def extract_product(cls, product_raw: WebElement) -> ProductOLD:
        header_tmp = product_raw.find_element_by_class_name('inzeratynadpis')
        name_div = header_tmp.find_element_by_class_name('nadpis')
        date_raw = header_tmp.find_element_by_class_name('velikost10').text

        name = name_div.text
        link = name_div.find_element_by_css_selector('[href]').get_attribute('href')
        date = cls.convert_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find_element_by_class_name('popis').text
        price = product_raw.find_element_by_class_name('inzeratycena').text
        location = product_raw.find_element_by_class_name('inzeratylok').text.replace('\n', ', ')

        return ProductOLD(name=name, description=description, price=price, url=link, date=date,
                          ignore_date=ignore_date, location=location)

    def get_page_products(self) -> Iterator[ProductOLD]:
        product_elements = self.driver.find_elements_by_class_name("inzeraty")

        for product in product_elements:
            loaded_product = self.extract_product(product)
            yield loaded_product

    def run_query(self, query: QueryOLD) -> Iterator[ProductOLD]:

        # self.driver.quit()
        self.create_driver()

        url: str = SETTINGS.BAZOS_URL if len(query.category) == 0 else query.category

        while True:
            try:
                self.driver.get(url)
                self.send_query(query)
                break
            except (TimeoutException, URLError):  # todo correct exception
                self.log(f"Timeout with query: {query.text}")
                self.create_driver()

        while True:
            for product in self.get_page_products():
                yield product
            if not self.next_page():
                break