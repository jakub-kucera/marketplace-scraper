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

from bazos.const import (
    BAZOS_BLACKLIST_CHECK_URL,
    BAZOS_DETAIL_WAIT_TIME,
    BAZOS_PAGE_WAIT_TIME,
    BAZOS_REQUEST_TIMEOUT,
    BAZOS_URL,
    MAX_ATTEMPTS,
    PAGE_SIZE,
)
from bazos.exceptions import MarketplaceBlockedError
from bazos.filters import parse_price_and_type
from bazos.models import Ad, Marketplace, Query, EmailPublisher, PhonePublisher
from ip_changer.tor import PROXIES

logger = logging.getLogger(__name__)


class BazosScraper:
    marketplace: str = Marketplace.BAZOS

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
        """Whole-site search, for a Query with neither a section nor a category.

        Uses BAZOS_URL (`/search.php`), NOT `query.url`. `query.url` falls back to
        BAZOS_BASE_URL — a bare origin with no path — and Bazos redirects
        `https://bazos.cz?hledat=...` to the homepage, dropping the query string
        entirely. The scraper then parsed a page with zero `inzeraty` elements and
        broke out of the page loop, so a section-less, category-less Query scraped
        nothing at all, silently and on every pass. Measured 2026-08-23; see
        docs/archive/shipped/E2E_REPLAY_TESTING.md §1a.

        Fixed here rather than in `Query.url` because that property is also read by
        `create_url_category` (correct today), by the runner's IP-guard calls, and
        by the Vinted/Sbazar base-URL branches.
        """
        params = cls.get_query_url_dict(query)
        for i in itertools.count(start=0, step=PAGE_SIZE):
            params['crz'] = i
            yield f"{BAZOS_URL}?{urlencode(params)}"

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
        price, price_type = parse_price_and_type(price_raw)

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
            'price': price,
            'price_type': price_type,
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
    ) -> tuple[EmailPublisher | None, PhonePublisher | None]:
        """Resolve (or create) DB publisher records. Returns ``(email_publisher, phone_publisher)``.

        A ``0`` id is Bazos's "this ad has no publisher of that kind" marker, not an
        identity — roughly 6-8%% of ads carry it on the email side, steadily across time.
        It is stored as NULL rather than as a publisher row: a shared ``bazos_id=0`` row
        would otherwise act as a hub joining every such ad into one bogus mega-seller
        (measured on the 2024-03 export: one row, 1137 ads, 671 distinct phones, which
        merged 8.3%% of all ads into a single connected component).
        """
        email_publisher = (
            EmailPublisher.objects.get_or_create(bazos_id=publisher_email)[0]
            if publisher_email
            else None
        )
        phone_publisher = (
            PhonePublisher.objects.get_or_create(bazos_id=publisher_phone)[0]
            if publisher_phone
            else None
        )
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
            marketplace=Marketplace.BAZOS,
            name=parsed['name'],
            price_raw=parsed['price_raw'],
            price=parsed['price'],
            price_type=parsed['price_type'],
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

    def run_request(self, url: str, extra_args: dict | None = None) -> Response | None:
        extra_args = {"timeout": BAZOS_REQUEST_TIMEOUT, **(extra_args or {})}
        response: Response | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self.session.get(url, **extra_args)
                self.sent_requests_count += 1
                break
            # requests.RequestException belongs here: it is NOT a URLError (verified), so
            # before this a ConnectTimeout/ConnectionError skipped the retry loop entirely
            # and escaped into the caller. Adding the timeout above without this would
            # have made that strictly more common.
            #
            # selenium's TimeoutException used to be caught here too, left over from the
            # click-driven scraper. `self.session` is a requests.Session on every path
            # (see __init__), so nothing in this loop could ever raise it.
            except (URLError, requests.RequestException) as e:
                logger.warning("Request to %s failed (attempt %d/%d): %s", url, attempt, MAX_ATTEMPTS, e)
        return response

    def check_blacklisted(self) -> bool:
        response = self.run_request(BAZOS_BLACKLIST_CHECK_URL)
        if response is None:
            logger.warning("check_blacklisted: request failed, assuming OK")
            return False
        logger.debug("check_blacklisted status=%s", response.status_code)
        return response.status_code == 403

    def load_full_description(self, product: Ad) -> Ad:
        """Paced: QueryRunner._handle_new_product calls this once per new ad with no
        delay of its own, so an N-new-ad query used to fire N detail GETs back-to-back
        straight after its listing page (15 in a row, measured 2026-08-23). Sleeping
        before the request rather than after paces it against whatever preceded it.
        """
        logger.debug("Loading full description for %s", product.url)
        sleep(uniform(*BAZOS_DETAIL_WAIT_TIME))
        response = self.run_request(product.url)
        if response is None:
            logger.warning("Failed to load full description for %s after %d attempts", product.url, MAX_ATTEMPTS)
            return product
        # Same check `run_query` makes, and it was missing here. A 403 is a *response*, so
        # `run_request` returns its body rather than retrying, and this method used to parse
        # that body as if it were a listing — `.text` on the absent `popisdetail` raised
        # AttributeError. That is not a `DatabaseError`, so it escaped
        # `_tolerating_one_bad_ad`, and not a `MarketplaceBlockedError`, so nothing rotated:
        # a single blocked detail circuit aborted the whole query for the pass, silently, on
        # any query with load_full_description=True. Roughly half of exits are blocked.
        if response.status_code == 403:
            raise MarketplaceBlockedError.from_response(response)
        soup = BeautifulSoup(response.text, 'html.parser')
        detail = soup.find(class_='popisdetail')
        if detail is None:
            # A removed listing, or a page shape this parser does not know. Returning the
            # product unchanged keeps "no description available" a normal outcome rather
            # than an exception that costs the caller its whole walk.
            logger.warning("No description block on %s (removed, or unexpected page)", product.url)
            return product
        product.full_description = detail.text
        return product

    def run_query(self, query: Query) -> Iterator[Ad]:
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
            if response.status_code == 403:
                raise MarketplaceBlockedError.from_response(response)

            products = list(self.get_page_products(response))
            yield from products
            # TODO take a look at this, it looks like that it is no working. (have to create a new query with few Ads to repl)
            if not products:
                break
