import itertools
from datetime import datetime
from typing import Iterator, Any
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
import requests
from requests import Response
from selenium.common.exceptions import TimeoutException

from settings import SETTINGS
from src.models import ProductDB, QueryDB
from src.notifiers.bazos.bazos_scraper import BazosScraper
from src.notifiers.bazos.exceptions import BazosBlacklistedError

BAZOS_BASE_URL = 'https'


class BazosBazosScraperBS4DBUrl(BazosScraper):
    @staticmethod
    def create_url_category(query: QueryDB) -> Iterator[str]:
        url: str = query.category

        price_lower = '' if query.price_lower == 0 else query.price_lower
        price_upper = '' if query.price_upper == 0 else query.price_upper

        params = {
            'hledat': query.text,
            # 'rubriky': 'elektro',
            'hlokalita': query.location_center,
            'humkreis': str(query.location_radius),
            'cenaod': price_lower,
            'cenado': price_upper,
            'Submit': 'Hledat',
            # 'kitx': 'ano'
        }
        encoded_params = urlencode(params)

        for i in itertools.count(start=0, step=20):
            yield f"{url}{i}/?{encoded_params}"

    @staticmethod
    def create_url_general(query: QueryDB) -> Iterator[str]:
        url: str = SETTINGS.BAZOS_URL

        price_lower = '' if query.price_lower == 0 else query.price_lower
        price_upper = '' if query.price_upper == 0 else query.price_upper

        params = {
            'hledat': query.text,
            # 'rubriky': 'elektro',
            'hlokalita': query.location_center,
            'humkreis': str(query.location_radius),
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
    # def extract_product(product_raw) -> Product:
    def extract_product(product_raw) -> ProductDB:
        header_tmp = product_raw.find(class_="inzeratynadpis")
        name_div = header_tmp.find(class_='nadpis')
        date_raw = header_tmp.find(class_='velikost10').text

        name = name_div.text
        name = ' '.join(name.split())
        url = name_div.select_one('a[href]').get('href')
        parsed_url_path = urlparse(url).path.split("/")
        bazos_id = parsed_url_path[2]
        # link = urljoin(BAZOS_BASE_URL, link)
        date = BazosBazosScraperBS4DBUrl.convert_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find(class_='popis').text
        price = product_raw.find(class_='inzeratycena').text.strip()

        location_tmp = product_raw.find(class_='inzeratylok')
        location_tmp.br.replace_with(", ")
        location = location_tmp.text

        return ProductDB(bazos_id=bazos_id, name=name, price=price, url=url, location=location, publish_date=date,
                         ignore_date=ignore_date, description=description)

        # return Product(name=name, description=description, price=price, url=url, date=date,
        #                ignore_date=ignore_date, location=location)

    # def get_page_products(self, response: Response | None) -> Iterator[Product]:
    def get_page_products(self, response: Response | None) -> Iterator[ProductDB]:
        # product_elements = self.driver.find_elements(By.CLASS_NAME ,"inzeraty")
        if response is None:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        product_elements = soup.find_all(class_='inzeraty')

        for product_raw in product_elements:
            product = self.extract_product(product_raw)
            product.url = urljoin(response.url, product.url)
            yield product

    def run_request(self, url: str, extra_args: dict[Any, Any] = dict()) -> Response:
        response: Response | None = None
        for _ in range(1, SETTINGS.MAX_ATTEMPTS + 1):
            try:
                # self.driver.get(url)
                response = requests.get(url, **extra_args)
                break
            except (TimeoutException, URLError):  # todo correct exception
                pass
        return response

    def check_blacklisted(self) -> bool:
        response = self.run_request(SETTINGS.BAZOS_URL)
        return not response.ok

    # def run_query(self, query: Query) -> Iterator[Product]:
    def run_query(self, query: QueryDB) -> Iterator[ProductDB]:
        if self.check_blacklisted():  # TODO only check for the single HTTP code
            raise BazosBlacklistedError()

        if len(query.category) > 0:
            url_iter = self.create_url_category(query)
        else:
            url_iter = self.create_url_general(query)

        # last_top_count = query.last_top_count
        # query.last_top_count = 0

        # list through multiple pages
        for url in url_iter:

            # if True: # if page contains TOP posts
            #     query.last_top_count += 1

            print(f"{url=}")
            # try to load page, if not possible, repeat SETTINGS.MAX_ATTEMPTS
            response = self.run_request(url)
            # extract products from 1 page
            count = 0
            for count, product in enumerate(self.get_page_products(response), start=1):
                yield product
            if count == 0:  # or count < 20
                break
