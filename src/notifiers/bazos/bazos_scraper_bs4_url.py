import itertools
from datetime import datetime
from typing import List, Iterator, Optional
from urllib.error import URLError
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
import requests
from requests import Response
import requests_random_user_agent
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException

from settings import SETTINGS
from src.notifiers.bazos.scraper import Scraper
from src.sendables.product import Product
from src.query import Query

BAZOS_BASE_URL = 'https'


class BazosScraperBS4Url(Scraper):
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
    def extract_product(product_raw) -> Product:
        header_tmp = product_raw.find(class_="inzeratynadpis")
        name_div = header_tmp.find(class_='nadpis')
        date_raw = header_tmp.find(class_='velikost10').text

        name = name_div.text
        name = ' '.join(name.split())
        url = name_div.select_one('a[href]').get('href')
        # link = urljoin(BAZOS_BASE_URL, link)
        date = BazosScraperBS4Url.convert_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find(class_='popis').text
        price = product_raw.find(class_='inzeratycena').text.strip()

        location_tmp = product_raw.find(class_='inzeratylok')
        location_tmp.br.replace_with(", ")
        location = location_tmp.text

        return Product(name=name, description=description, price=price, url=url, date=date,
                       ignore_date=ignore_date, location=location)

    def get_page_products(self, response: Response | None) -> Iterator[Product]:
        # product_elements = self.driver.find_elements(By.CLASS_NAME ,"inzeraty")
        if response is None:
            return None
        soup = BeautifulSoup(response.text, 'html.parser')
        product_elements = soup.find_all(class_='inzeraty')

        for product_raw in product_elements:
            product = self.extract_product(product_raw)
            product.url = urljoin(response.url, product.url)
            yield product

    def run_query(self, query: Query) -> Iterator[Product]:
        if len(query.category) > 0:
            url_iter = self.create_url_category(query)
        else:
            url_iter = self.create_url_general(query)
        response: Response | None = None
        # list through multiple pages
        for url in url_iter:  # todo rename, smth get_product_page
            print(f"{url=}")
            # try to load page, if not possible, repeat SETTINGS.MAX_ATTEMPTS
            for _ in range(1, SETTINGS.MAX_ATTEMPTS + 1):
                try:
                    # self.driver.get(url)
                    response = requests.get(url)
                    break
                except (TimeoutException, URLError):  # todo correct exception
                    pass

            # extract products from 1 page
            count = 0
            for count, product in enumerate(self.get_page_products(response), start=1):
                yield product
            if count == 0:  # or count < 20
                break
#
# same_products=[Product(name='MacBook Pro 13" 2020 i5 256GB 8GB Touch Bar, jako nový', price='21 000 Kč', url='https://pc.bazos.cz/inzerat/152356925/macbook-pro-13-2020-i5-256gb-8gb-touch-bar-jako-novy.php', location='Praha 6, 160 00', date=datetime.datetime(2022, 5, 15, 0, 0), ignore_date=True, description='Prodám Apple MacBook Pro ročník 2020, 13" displej, stříbrný. Model A2289, MXK32CZ/A MacBook Pro 13" 2020 Intel i5 Quad Core 1,4 GHz 256 GB SSD 8 GB RAM Displej 13,3" Retina 2560x1600 Touch Bar Touch ID Baterie 201 cyklů V super stavu, ž ...'),
#                Product(name='MacBook Pro 13" 2020 i5 256GB 8GB Touch Bar, jako nový', price='  21 000 Kč', url='/inzerat/152356925/macbook-pro-13-2020-i5-256gb-8gb-touch-bar-jako-novy.php', location='Praha 6160 00', date=datetime.datetime(2022, 5, 15, 0, 0), ignore_date=True, description='Prodám Apple MacBook Pro ročník 2020, 13" displej, stříbrný.\r\nModel A2289, MXK32CZ/A\r\n\r\nMacBook Pro 13" 2020\r\nIntel i5 Quad Core 1,4 GHz\r\n256 GB SSD\r\n8 GB RAM\r\nDisplej 13,3" Retina 2560x1600\r\nTouch Bar\r\nTouch ID\r\nBaterie 201 cyklů\r\n\r\nV super stavu, ž ...')]
#
# same_products=[Product(name='Hodinky APPLE Watch 6 44mm modré', price='5 800 Kč', url='https://ostatni.bazos.cz/inzerat/151963126/hodinky-apple-watch-6-44mm-modre.php', location='Praha 10, 100 00', date=datetime.datetime(2022, 5, 3, 0, 0), ignore_date=False, description='Prodám modré hodinky apple watch 6, velikost 44 mm. Zakoupené 9.6.2021. Kompletní balení.'),
#                Product(name='Hodinky APPLE Watch 6   44mm modré', price='5 800 Kč', url='https://ostatni.bazos.cz/inzerat/151963126/hodinky-apple-watch-6-44mm-modre.php', location='Praha 10100 00', date=datetime.datetime(2022, 5, 3, 0, 0), ignore_date=False, description='Prodám modré hodinky apple watch 6, velikost 44 mm. Zakoupené 9.6.2021. Kompletní balení. \r\n')]


# Product(name='MacBook Pro 13" 2020 i5 256GB 8GB Touch Bar, jako nový', price='21 000 Kč', url='https://pc.bazos.cz/inzerat/152356925/macbook-pro-13-2020-i5-256gb-8gb-touch-bar-jako-novy.php', location='Praha 6, 160 00', date=datetime.datetime(2022, 5, 15, 0, 0), ignore_date=True, description='Prodám Apple MacBook Pro ročník 2020, 13" displej, stříbrný. Model A2289, MXK32CZ/A MacBook Pro 13" 2020 Intel i5 Quad Core 1,4 GHz 256 GB SSD 8 GB RAM Displej 13,3" Retina 2560x1600 Touch Bar Touch ID Baterie 201 cyklů V super stavu, ž ...')
# Product(name='MacBook Pro 13" 2020 i5 256GB 8GB Touch Bar, jako nový', price='21 000 Kč', url='https://pc.bazos.cz/inzerat/152356925/macbook-pro-13-2020-i5-256gb-8gb-touch-bar-jako-novy.php', location='Praha 6160 00', date=datetime.datetime(2022, 5, 15, 0, 0), ignore_date=True, description='Prodám Apple MacBook Pro ročník 2020, 13" displej, stříbrný.\r\nModel A2289, MXK32CZ/A\r\n\r\nMacBook Pro 13" 2020\r\nIntel i5 Quad Core 1,4 GHz\r\n256 GB SSD\r\n8 GB RAM\r\nDisplej 13,3" Retina 2560x1600\r\nTouch Bar\r\nTouch ID\r\nBaterie 201 cyklů\r\n\r\nV super stavu, ž ...')]
