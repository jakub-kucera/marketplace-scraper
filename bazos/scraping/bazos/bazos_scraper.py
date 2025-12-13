import itertools
from datetime import datetime
from random import uniform
from time import sleep
from typing import Iterator, Any, Final
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
from django.utils import timezone
import requests
from requests import Response
from selenium.common.exceptions import TimeoutException

from bazos.const import BAZOS_PAGE_WAIT_TIME, BAZOS_URL, MAX_ATTEMPTS, PAGE_SIZE, BAZOS_BLACKLIST_CHECK_URL
from bazos.exceptions import BazosBlacklistedError
from bazos.models import Ad, Query, EmailPublisher, PhonePublisher
from ip_changer.tor import PROXIES


class BazosScraper:

    def __init__(self, session: requests.Session):
        self.sent_requests_count = 0
        if session:
            self.session = session
        else:
            self.session = requests.Session()
            self.session.proxies = PROXIES

    @classmethod
    def create_url_category(cls, query: Query) -> Iterator[str]:
        params = cls.get_query_url_dict(query)

        url: str = query.url
        encoded_params = urlencode(params)
        for i in itertools.count(start=0, step=PAGE_SIZE):
            yield f"{url}/{i}/?{encoded_params}"

    @classmethod
    def create_url_general(cls, query: Query) -> Iterator[str]:
        params = cls.get_query_url_dict(query)

        url: str = query.url
        for i in itertools.count(start=0, step=PAGE_SIZE):
            params['crz'] = i
            yield f"{url}?{urlencode(params)}"

    @staticmethod
    def get_query_url_dict(query: Query):
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
        date_formatted = timezone.make_aware(datetime(day=day, month=month, year=year))
        return date_formatted

    @staticmethod
    # def extract_product(product_raw) -> Product:
    def extract_product(product_raw) -> Ad:
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
        topped = 'TOP' in date_raw
        short_description = header_tmp.find(class_='popis').text.strip()
        price_raw = product_raw.find(class_='inzeratycena').text.strip()

        location_tmp = product_raw.find(class_='inzeratylok')
        location_tmp.br.replace_with(", ")
        location = location_tmp.text

        view_count_tmp = product_raw.find(class_='inzeratyview')
        view_count = view_count_tmp.text.split(' ')[0]

        actions = product_raw.find(class_='inzeratyakce')

        def get_url_query_dict_from_element_text(element_text: str) -> dict[bytes, list[bytes]]:  # TODO change
            s = actions.find('span', string=element_text).attrs['onclick']
            contents = s[s.find("(") + 1:s.find(")")]
            contents = contents.replace('\'', '')
            args = contents.split(',')
            return args[1:]
            # return actions.find('span', string=element_text).attrs['onclick']
            # return parse_qs(urlparse(actions.find('a', string=element_text).attrs['href']).query)

        # product_id_raw = parse_qs(urlparse(actions.find('a', string='Označit špatný inzerát').attrs['href']).query)
        product_id_raw = get_url_query_dict_from_element_text('Označit špatný inzerát')
        product_id = int(product_id_raw[0])
        # product_id = int(product_id_raw['idad'][0])
        assert int(bazos_id) == product_id

        # publisher_info = parse_qs(urlparse(actions.find('a', string='Ohodnotit uživatele').attrs['href']).query)
        publisher_info = get_url_query_dict_from_element_text('Ohodnotit uživatele')
        publisher_email = int(publisher_info[0])
        # publisher_email = int(publisher_info['idmail'][0])
        publisher_phone = int(publisher_info[1])
        publisher_name = str(publisher_info[2])

        email_publisher, _ = EmailPublisher.objects.get_or_create(
            bazos_id=publisher_email,
        )

        phone_publisher, _ = PhonePublisher.objects.get_or_create(
            bazos_id=publisher_phone,
        )

        # name = name.encode(encoding='UTF-8', errors='strict')
        # short_description = short_description.encode(encoding='UTF-8', errors='strict')
        # publisher_name = publisher_name.encode(encoding='UTF-8', errors='strict')
        # location = location.encode(encoding='UTF-8', errors='strict')

        # TODO check creation
        return Ad(bazos_id=bazos_id, name=name, price_raw=price_raw, url=url, location=location, publish_date=date,
                  topped=topped, short_description=short_description, email_publisher=email_publisher,
                  phone_publisher=phone_publisher, publisher_name=publisher_name, view_count=view_count)

    def get_page_products(self, response: Response | None) -> Iterator[Ad]:
        # product_elements = self.driver.find_elements(By.CLASS_NAME ,"inzeraty")
        if response is None:
            return None
        # soup = BeautifulSoup(response.text, 'html.parser', from_encoding="Windows-1250")
        # soup = BeautifulSoup(response.text, 'html.parser', from_encoding="UTF-8")
        soup = BeautifulSoup(response.text, 'html.parser')
        product_elements = soup.find_all(class_='inzeraty')

        for product_raw in product_elements:
            product = self.extract_product(product_raw)
            product.url = urljoin(response.url, product.url)
            yield product

    def run_request(self, url: str, extra_args: dict[Any, Any] = dict()) -> Response:
        response: Response | None = None
        for _ in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.session.get(url, **extra_args)
                self.sent_requests_count += 1
                break
            except (TimeoutException, URLError):  # todo correct exception
                pass
        return response

    def check_blacklisted(self, url: str = BAZOS_BLACKLIST_CHECK_URL) -> bool:
        response = self.run_request(url)
        print(f"Checking if blacklisted {response.status_code}")
        return response.status_code == 403

    def load_full_description(self, product: Ad) -> Ad:
        print(f"Loading full description for {product.url}")
        response = self.run_request(product.url)
        soup = BeautifulSoup(response.text, 'html.parser')
        full_description = soup.find(class_='popisdetail').text  # TODO FIX, CAN BE NONE?
        # full_description = unidecode(full_description)
        product.full_description = full_description
        return product

    def run_query(self, query: Query) -> Iterator[Ad]:
        if self.check_blacklisted(query.url):
            raise BazosBlacklistedError()

        if query.category or query.section:
            url_iter = self.create_url_category(query)
        else:
            url_iter = self.create_url_general(query)

        # last_top_count = query.last_top_count
        # query.last_top_count = 0

        # list through multiple pages
        for url in url_iter:
            print(f"{url=}")
            # if True: # if page contains TOP posts
            #     query.last_top_count += 1

            page_sleep_time = uniform(*BAZOS_PAGE_WAIT_TIME)
            print(f"Sleeping between pages for {page_sleep_time} seconds")
            sleep(page_sleep_time)

            # try to load page, if not possible, repeat SETTINGS.MAX_ATTEMPTS
            response = self.run_request(url)
            # extract products from 1 page
            count = 0
            for count, product in enumerate(self.get_page_products(response), start=1):
                # if query.load_full_description:
                #     product = self.load_full_description(product)
                yield product
            # TODO take a look at this, it looks like that it is no working. (have to create a new query with few Ads to repl)
            if count == 0:  # or count < 20
                break
