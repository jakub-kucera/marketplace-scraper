from time import sleep

from selenium import webdriver

from src.intervals.interval import Interval
from src.notifiers.notifier import Notifier
from src.senders.sender import Sender

from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By


class GreenhouseJobListScraper(Notifier):
    def __init__(self, sender: Sender, logger: Sender, name: str, interval: Interval, link_to_list: str):
        super().__init__(sender, logger, name)
        self.interval = interval
        self.link_to_list = link_to_list
        self.old_available_jobs: list[tuple[str, str]] = []
        self.first_run = True

    def check_availability(self, ):
        chrome_options = webdriver.ChromeOptions()
        chrome_options.headless = True
        s = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=s, options=chrome_options)
        driver.get(self.link_to_list)

        # driver.find_elements(by=By.CLASS_NAME, value="level-0")
        jobs = driver.find_elements(by=By.CLASS_NAME, value="opening")

        new_available_jobs: list[tuple[str, str]] = []

        for job in jobs:
            position = job.find_element(by=By.TAG_NAME, value="a").text
            location = job.find_element(by=By.CLASS_NAME, value="location").text

            new_available_jobs.append((position, location))
            print(f"{position=}")
            print(f"{location=}")

        if not self.first_run:
            self.first_run = False
            for job in new_available_jobs:
                if job not in self.old_available_jobs:
                    message = f"{self.name}: POSITION: {job[0]}. LOCATION: {job[1]}"
                    self.sender.send_plain(message)
                    self.logger.send_plain(message)
                else:
                    print("old available job")

        self.old_available_jobs = new_available_jobs

    def run(self):
        while True:
            self.check_availability()

            interval = self.interval.get_next_interval()
            self.log(f"Going to sleep for {interval} seconds ({interval / 60.0} minutes).")
            sleep(interval)
            self.log("Waking up.")


