
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager


class SeleniumDriver():#ABC
    def __init__(self, load_images: bool = True, headless: bool = False):
        self.driver = None
        self.driver_service = Service(ChromeDriverManager().install())
        self.driver_chrome_options = webdriver.ChromeOptions()

        if not load_images:
            prefs = {"profile.managed_default_content_settings.images": 2}
            self.driver_chrome_options.add_experimental_option("prefs", prefs)
        self.driver_chrome_options.headless = headless

    def get_driver(self):
        if self.driver is not None:
            self.driver.quit()
            # del self.driver
        self.driver = webdriver.Chrome(service=self.driver_service, options=self.driver_chrome_options)

    def quit(self):
        if self.driver is not None:
            self.driver.quit()
            # del self.driver
        self.driver = None
