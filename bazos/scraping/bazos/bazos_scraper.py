import itertools
import logging
from datetime import datetime
from random import uniform
from time import sleep
from typing import Iterator
from urllib.error import URLError
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup
from django.utils import timezone
import requests
from requests import Response
from selenium.common.exceptions import TimeoutException

from bazos.const import BAZOS_PAGE_WAIT_TIME, MAX_ATTEMPTS, PAGE_SIZE, BAZOS_BLACKLIST_CHECK_URL
from bazos.exceptions import BazosBlacklistedError
from bazos.models import Ad, Query, EmailPublisher, PhonePublisher
from ip_changer.tor import PROXIES

logger = logging.getLogger(__name__)


class BazosScraper:
    marketplace = "bazos"

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
    def _parse_action_args(actions, element_text: str) -> list:
        s = actions.find('span', string=element_text).attrs['onclick']
        contents = s[s.find("(") + 1:s.find(")")]
        contents = contents.replace('\'', '')
        return contents.split(',')[1:]

    @staticmethod
    def _parse_product(product_raw) -> dict:
        """Pure HTML parsing — no DB access. Returns a dict of all Ad fields plus
        raw publisher IDs (``publisher_email``, ``publisher_phone``, ``publisher_name``).
        """
        header_tmp = product_raw.find(class_="inzeratynadpis")
        name_div = header_tmp.find(class_='nadpis')
        date_raw = header_tmp.find(class_='velikost10').text

        name = name_div.text
        name = ' '.join(name.split())
        url = name_div.select_one('a[href]').get('href')
        parsed_url_path = urlparse(url).path.split("/")
        bazos_id = parsed_url_path[2]
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

        product_id_raw = BazosScraper._parse_action_args(actions, 'Označit špatný inzerát')
        product_id = int(product_id_raw[0])
        assert int(bazos_id) == product_id

        publisher_info = BazosScraper._parse_action_args(actions, 'Ohodnotit uživatele')
        publisher_email = int(publisher_info[0])
        publisher_phone = int(publisher_info[1])
        publisher_name = str(publisher_info[2])

        return {
            'external_id': bazos_id,
            'name': name,
            'price_raw': price_raw,
            'url': url,
            'location': location,
            'publish_date': date,
            'topped': topped,
            'short_description': short_description,
            'view_count': view_count,
            'publisher_email': publisher_email,
            'publisher_phone': publisher_phone,
            'publisher_name': publisher_name,
        }

    @staticmethod
    def _resolve_publishers(
        publisher_email: int, publisher_phone: int
    ) -> tuple["EmailPublisher", "PhonePublisher"]:
        """Resolve (or create) DB publisher records. Returns ``(email_publisher, phone_publisher)``."""
        email_publisher, _ = EmailPublisher.objects.get_or_create(bazos_id=publisher_email)
        phone_publisher, _ = PhonePublisher.objects.get_or_create(bazos_id=publisher_phone)
        return email_publisher, phone_publisher

    @staticmethod
    def extract_product(product_raw) -> Ad:
        """Parse an ad element and resolve its publisher records. Composes
        :meth:`_parse_product` (pure) and :meth:`_resolve_publishers` (DB).
        """
        parsed = BazosScraper._parse_product(product_raw)
        email_publisher, phone_publisher = BazosScraper._resolve_publishers(
            parsed['publisher_email'], parsed['publisher_phone']
        )
        return Ad(
            external_id=parsed['external_id'],
            marketplace="bazos",
            name=parsed['name'],
            price_raw=parsed['price_raw'],
            url=parsed['url'],
            location=parsed['location'],
            publish_date=parsed['publish_date'],
            topped=parsed['topped'],
            short_description=parsed['short_description'],
            email_publisher=email_publisher,
            phone_publisher=phone_publisher,
            publisher_name=parsed['publisher_name'],
            view_count=parsed['view_count'],
        )

    def get_page_products(self, response: Response | None) -> Iterator[Ad]:
        if response is None:
            return
        soup = BeautifulSoup(response.text, 'html.parser')
        product_elements = soup.find_all(class_='inzeraty')

        for product_raw in product_elements:
            product = self.extract_product(product_raw)
            product.url = urljoin(response.url, product.url)
            yield product

    def run_request(self, url: str, extra_args: dict | None = None) -> Response:
        extra_args = extra_args or {}
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
        if response is None:
            logger.warning("check_blacklisted: request failed, assuming OK")
            return False
        logger.debug("check_blacklisted status=%s", response.status_code)
        return response.status_code == 403

    def load_full_description(self, product: Ad) -> Ad:
        logger.debug("Loading full description for %s", product.url)
        response = self.run_request(product.url)
        soup = BeautifulSoup(response.text, 'html.parser')
        full_description = soup.find(class_='popisdetail').text  # TODO FIX, CAN BE NONE?
        product.full_description = full_description
        return product

    def run_query(self, query: Query) -> Iterator[Ad]:
        if self.check_blacklisted(query.url):
            raise BazosBlacklistedError()

        if query.category or query.section:
            url_iter = self.create_url_category(query)
        else:
            url_iter = self.create_url_general(query)

        for url in url_iter:
            logger.debug("Fetching page url=%s", url)

            page_sleep_time = uniform(*BAZOS_PAGE_WAIT_TIME)
            logger.debug("Sleeping between pages for %.1f s", page_sleep_time)
            sleep(page_sleep_time)

            response = self.run_request(url)
            if response is None:
                logger.warning("Failed to load %s after %d attempts, stopping query", url, MAX_ATTEMPTS)
                break

            products = list(self.get_page_products(response))
            yield from products
            # TODO take a look at this, it looks like that it is no working. (have to create a new query with few Ads to repl)
            if not products:
                break
