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
from src.notifiers.bazos.scraper import Scraper
from src.sendables.product import Product
from src.query import Query


class BazosScraperSelUrl(Scraper):
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
        if self.driver is not None:
            try:
                self.driver.quit()
            except WebDriverException:
                pass
        # self.driver = webdriver.Chrome("/usr/bin/chromedriver", options=self.driver_chrome_options)
        self.driver = webdriver.Chrome(service=self.driver_service, options=self.driver_chrome_options)
        # self.driver = webdriver.Remote("http://selenium_chromedriver:4444/wd/hub", options=self.driver_chrome_options)
        # self.driver = webdriver.Remote("http://localhost:4444/wd/hub", options=self.driver_chrome_options)

    @staticmethod
    def create_url_category(query: Query) -> Iterator[str]:
        url: str = query.category

        price_lower = '' if query.price_range[0] == 0 else query.price_range[0]
        price_upper = '' if query.price_range[1] == 0 else query.price_range[1]

        params = {
            'hledat': query.text,
            # 'rubriky': 'elektro',
            'hlokalita': query.location[0],
            'humkreis': query.location[1],
            'cenaod': price_lower,
            'cenado': price_upper,
            'Submit': 'Hledat',
            # 'kitx': 'ano'
        }
        encoded_params = urlencode(params)

        for i in itertools.count(start=0, step=20):
            yield f"{url}{i}/?{encoded_params}"

    @staticmethod
    def create_url_general(query: Query) -> Iterator[str]:
        url: str = SETTINGS.BAZOS_URL

        price_lower = '' if query.price_range[0] == 0 else query.price_range[0]
        price_upper = '' if query.price_range[1] == 0 else query.price_range[1]

        params = {
            'hledat': query.text,
            # 'rubriky': 'elektro',
            'hlokalita': query.location[0],
            'humkreis': query.location[1],
            'cenaod': price_lower,
            'cenado': price_upper,
            'Submit': 'Hledat',
            'crz': 0
            # 'kitx': 'ano'
        }

        for i in itertools.count(start=0, step=20):
            params['crz'] = i
            encoded_params = urlencode(params)
            yield f"{url}?{encoded_params}"

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
        date = BazosScraperSelUrl.convert_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find_element_by_class_name('popis').text
        price = product_raw.find_element_by_class_name('inzeratycena').text
        location = product_raw.find_element_by_class_name('inzeratylok').text.replace('\n', ', ')

        return Product(name=name, description=description, price=price, url=link, date=date,
                       ignore_date=ignore_date, location=location)

    def get_page_products(self) -> Iterator[Product]:
        # product_elements = self.driver.find_elements(By.CLASS_NAME ,"inzeraty")
        product_elements = self.driver.find_elements_by_class_name("inzeraty")

        for product in product_elements:
            yield self.extract_product(product)

    def run_query(self, query: Query) -> Iterator[Product]:
        self.create_driver()

        if len(query.category) > 0:
            url_iter = self.create_url_category(query)
        else:
            url_iter = self.create_url_general(query)

        # list through multiple pages
        for url in url_iter:  # todo rename, smth get_product_page
            print(f"{url=}")
            # try to load page, if not possible, repeat SETTINGS.MAX_ATTEMPTS
            for _ in range(1, SETTINGS.MAX_ATTEMPTS + 1):
                try:
                    self.driver.get(url)
                    break
                except (TimeoutException, URLError):  # todo correct exception
                    self.create_driver()

            # extract products from 1 page
            count = 0
            for count, product in enumerate(self.get_page_products(), start=1):
                yield product
            if count == 0:  # or count < 20
                break
