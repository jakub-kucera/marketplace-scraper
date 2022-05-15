from time import sleep

from selenium import webdriver

from src.intervals.interval import Interval
from src.notifiers.notifier import Notifier
from src.senders.sender import Sender

from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

STATUS_UNAVAILABLE = ['Očekáváme leden 2022', 'Na objednávku – termín upřesníme']


class AlzaProductListScraper(Notifier):
    def __init__(self, sender: Sender, logger: Sender, name: str, interval: Interval, link_to_list: str):
        super().__init__(sender, logger, name)
        self.interval = interval
        self.link_to_list = link_to_list

    def check_availability(self):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.headless = True
        s = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=s, options=chrome_options)
        driver.get(self.link_to_list)

        products = driver.find_elements(by=By.CLASS_NAME, value="browsingitem")

        for product in products:
            status = product.find_element(by=By.CLASS_NAME, value="avlVal").text
            name = product.find_element(by=By.CLASS_NAME, value="name").text
            if status not in STATUS_UNAVAILABLE:
                message = f"{self.name}: AVAILABLE: {name}. STATUS: {status}"
                self.sender.send_plain(message)
                self.logger.send_plain(message)
            print(f"{status=}")
            print(f"{name=}")

    def run(self):
        while True:
            self.check_availability()

            interval = self.interval.get_next_interval()
            self.log(f"Going to sleep for {interval} seconds ({interval / 60.0} minutes).")
            sleep(interval)
            self.log("Waking up.")


