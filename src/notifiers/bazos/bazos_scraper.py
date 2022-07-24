import itertools
from datetime import datetime
from typing import Iterator, Any, Final
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
import requests
from requests import Response
from selenium.common.exceptions import TimeoutException

from settings import SETTINGS
from src.models import ProductDB, QueryDB
from src.notifiers.bazos.exceptions import BazosBlacklistedError

PAGE_SIZE: Final[int] = 20


class BazosScraper:

    def __init__(self):
        self.sent_requests_count = 0

    @classmethod
    def create_url_category(cls, query: QueryDB) -> Iterator[str]:
        params = cls.get_query_url_dict(query)

        url: str = query.category
        encoded_params = urlencode(params)
        for i in itertools.count(start=0, step=PAGE_SIZE):
            yield f"{url}{i}/?{encoded_params}"

    @classmethod
    def create_url_general(cls, query: QueryDB) -> Iterator[str]:
        params = cls.get_query_url_dict(query)

        url: str = SETTINGS.BAZOS_URL
        for i in itertools.count(start=0, step=PAGE_SIZE):
            params['crz'] = i
            yield f"{url}?{urlencode(params)}"

    @staticmethod
    def get_query_url_dict(query: QueryDB):
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
        return params

    @staticmethod
    def extract_date(date_raw: str) -> datetime:
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
        # link = urljoin('https', link)
        date = BazosScraper.extract_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find(class_='popis').text
        price = product_raw.find(class_='inzeratycena').text.strip()

        location_tmp = product_raw.find(class_='inzeratylok')
        location_tmp.br.replace_with(", ")
        location = location_tmp.text

        view_count_tmp = product_raw.find(class_='inzeratyview')
        view_count = view_count_tmp.text.split(' ')[0]

        actions = product_raw.find(class_='inzeratyakce')

        def get_url_query_dict_from_element_text(element_text: str) -> dict[bytes, list[bytes]]:  # TODO change
            return parse_qs(urlparse(actions.find('a', string=element_text).attrs['href']).query)

        # product_id_raw = parse_qs(urlparse(actions.find('a', string='Označit špatný inzerát').attrs['href']).query)
        product_id_raw = get_url_query_dict_from_element_text('Označit špatný inzerát')
        product_id = int(product_id_raw['idad'][0])
        assert int(bazos_id) == product_id

        # publisher_info = parse_qs(urlparse(actions.find('a', string='Ohodnotit uživatele').attrs['href']).query)
        publisher_info = get_url_query_dict_from_element_text('Ohodnotit uživatele')
        publisher_email = int(publisher_info['idmail'][0])
        publisher_phone = int(publisher_info['idphone'][0])
        publisher_name = publisher_info['jmeno'][0]

        return ProductDB(bazos_id=bazos_id, name=name, price=price, url=url, location=location, publish_date=date,
                         ignore_date=ignore_date, description=description, publisher_email_id=publisher_email,
                         publisher_phone_id=publisher_phone, publisher_name=publisher_name, view_count=view_count)

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
                self.sent_requests_count += 1
                break
            except (TimeoutException, URLError):  # todo correct exception
                pass
        return response

    def check_blacklisted(self) -> bool:
        response = self.run_request(SETTINGS.BAZOS_URL)
        return response.status_code == 403

    def load_full_description(self, product: ProductDB) -> ProductDB:
        response = self.run_request(product.url)
        soup = BeautifulSoup(response.text, 'html.parser')
        full_description = soup.find(class_='popisdetail').text
        # full_description = unidecode(full_description)
        product.full_description = full_description
        return product

    def run_query(self, query: QueryDB) -> Iterator[ProductDB]:
        if self.check_blacklisted():
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
                if query.load_full_description:
                    product = self.load_full_description(product)
                yield product
            if count == 0:  # or count < 20
                break
