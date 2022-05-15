from time import sleep

from selenium import webdriver

from src.intervals.interval import Interval
from src.intervals.random_interval import RandomInterval
from src.notifiers.notifier import Notifier
from src.senders.console_sender import ConsoleSender
from src.senders.sender import Sender

from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

CINEMA_LIST_DAY = "https://www.cinemacity.cz/imax#/buy-tickets-by-cinema?in-cinema=1052"


class CinemaCityScraper(Notifier):
    def __init__(self, sender: Sender, logger: Sender, name: str, interval: Interval, start_day: int, end_day: int):
        super().__init__(sender, logger, name)
        self.interval = interval
        self.start_day = start_day
        self.end_day = end_day

    @staticmethod
    def create_url(day: int):
        return f"{CINEMA_LIST_DAY}&at=2021-12-{day:02}"

    def check_availability(self):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.headless = True
        s = Service(ChromeDriverManager().install())

        for day in range(self.start_day, self.end_day):
            driver = webdriver.Chrome(service=s, options=chrome_options)
            driver.get(self.create_url(day))
            alerts = driver.find_elements(By.CLASS_NAME, "alert-warning")
            if len(alerts) == 0:
                self.start_day = day+1
                message = f"{self.name}: New screenings on {day}.12.2021"
                self.logger.send_plain(message)
                self.sender.send_plain(message)
            print(f"2021-12-{day}: alerts: {len(alerts)}")

    def run(self):
        while True:
            self.check_availability()

            interval = self.interval.get_next_interval()
            self.log(f"Going to sleep for {interval} seconds ({interval / 60.0} minutes).")
            sleep(interval)
            self.log("Waking up.")
