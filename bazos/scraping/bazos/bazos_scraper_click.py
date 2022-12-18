from datetime import datetime
from random import uniform
from time import sleep
from typing import List, Iterator, Optional
from urllib.error import URLError
from urllib.parse import urlencode, urlparse, parse_qs

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager



class BazosScraperClick(BazosScraper):
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

    def send_query(self, query: QueryDB):
        query_textbox = self.driver.find_element(By.ID, 'hledat')
        query_textbox.send_keys(query.text)

        location_textbox = self.driver.find_element(By.ID, 'hlokalita')
        location_textbox.send_keys(query.location_center)
        location_range_textbox = self.driver.find_element(By.NAME, 'humkreis')
        location_range_textbox.clear()
        location_range_textbox.send_keys(query.location_radius)

        if query.price_lower > 0:
            lower_price_textbox = self.driver.find_element(By.NAME, 'cenaod')
            lower_price_textbox.send_keys(query.price_lower)
        if query.price_upper > 0:
            upper_price_textbox = self.driver.find_element(By.NAME, 'cenado')
            upper_price_textbox.send_keys(query.price_upper)

        submit_button = self.driver.find_element(By.NAME, 'Submit')
        submit_button.click()

    def next_page(self) -> bool:
        try:
            pages_div = self.driver.find_element(By.CLASS_NAME,'strankovani')
        except NoSuchElementException:
            return False
        next_pages_hrefs = pages_div.find_elements(By.TAG_NAME, 'a')
        next_page = next_pages_hrefs[-1]

        if next_page.text == 'Další':
            self.driver.get(next_page.get_attribute('href'))
            return True
        return False

    @staticmethod
    def convert_date(date_raw: str) -> datetime:
        date = date_raw[date_raw.find("[") + 1:date_raw.find("]")]
        day, month, year = map(int, date.split('.'))
        date_formatted = datetime(day=day, month=month, year=year)
        return date_formatted

    @classmethod
    def extract_product(cls, product_raw: WebElement) -> ProductDB:

        header_tmp = product_raw.find_element(By.CLASS_NAME, 'inzeratynadpis')
        header_tmp = product_raw.find_element(By.CLASS_NAME, 'inzeratynadpis')
        name_div = header_tmp.find_element(By.CLASS_NAME, 'nadpis')
        date_raw = header_tmp.find_element(By.CLASS_NAME, 'velikost10').text
        name = name_div.text
        url = name_div.find_element(By.CSS_SELECTOR, '[href]').get_attribute('href')
        parsed_url_path = urlparse(url).path.split("/")
        bazos_id = parsed_url_path[2]

        date = cls.convert_date(date_raw)
        ignore_date = 'TOP' in date_raw
        description = header_tmp.find_element(By.CLASS_NAME, 'popis').text
        price = product_raw.find_element(By.CLASS_NAME, 'inzeratycena').text

        location = product_raw.find_element(By.CLASS_NAME, 'inzeratylok').text.replace('\n', ', ')

        view_count_tmp = product_raw.find_element(By.CLASS_NAME, 'inzeratyview')
        view_count = view_count_tmp.text.split(' ')[0]  # TODO NEW

        actions = product_raw.find_element(By.CLASS_NAME, 'inzeratyakce')

        # def get_url_query_dict_from_element_text(element_text: str) -> dict[bytes, list[bytes]]:  # TODO change
        #     # actions.find_element(By.TAG_NAME, 'a', string=element_text).get_attribute("href")
        #     action_link = actions.find_element(By.XPATH, f"//*[text()='{element_text}']").get_attribute("href")
        #     return parse_qs(urlparse(bytes(action_link, encoding='utf-8')).query)
        #
        # product_id_raw = get_url_query_dict_from_element_text('Označit špatný inzerát')
        # product_id = int(product_id_raw['idad'][0])
        # assert int(bazos_id) == product_id
        #
        # publisher_info = get_url_query_dict_from_element_text('Ohodnotit uživatele')
        # publisher_email = int(publisher_info['idmail'][0])
        # publisher_phone = int(publisher_info['idphone'][0])
        # publisher_name = publisher_info['jmeno'][0]

        return ProductDB(bazos_id=bazos_id, name=name, price=price, url=url, location=location, publish_date=date,
                         ignore_date=ignore_date, description=description, view_count=view_count)
        # return ProductDB(bazos_id=bazos_id, name=name, price=price, url=url, location=location, publish_date=date,
        #                  ignore_date=ignore_date, description=description, publisher_email_id=publisher_email,
        #                  publisher_phone_id=publisher_phone, publisher_name=publisher_name, view_count=view_count)
        # return ProductDB(name=name, description=description, price=price, url=url, date=date,
        #                   ignore_date=ignore_date, location=location)

    def get_page_products(self) -> Iterator[ProductDB]:
        product_elements = self.driver.find_elements(By.CLASS_NAME, "inzeraty")

        for product in product_elements:
            loaded_product = self.extract_product(product)
            # TODO get url loaded_product.url, (maybe do in extract_product)
            yield loaded_product

    def run_query(self, query: QueryDB) -> Iterator[ProductDB]:

        # TODO check blacklisted

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

            page_sleep_time = uniform(*SETTINGS.BAZOS_PAGE_WAIT_TIME)
            print(f"Sleeping between pages for {page_sleep_time} seconds")
            sleep(page_sleep_time)

            for product in self.get_page_products():
                # TODO add check, load full description
                yield product
            if not self.next_page():
                break