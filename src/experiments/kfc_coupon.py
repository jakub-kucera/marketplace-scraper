from datetime import datetime
from time import sleep
from typing import List, Iterator
from urllib.error import URLError

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

from settings import SETTINGS

URL_ENTER_CODE: str = "http://mojenavstevakfc.cz"
COUPON_CODE: int = 203014171121215451


class Kfc:

    @staticmethod
    def create_driver() -> WebDriver:
        chrome_options = webdriver.ChromeOptions()
        s = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=s)

    def run(self, code: int):
        driver = self.create_driver()

        driver.get(URL_ENTER_CODE)
        driver.find_element(By.ID, "InputCouponNum").send_keys(code)
        driver.find_element(By.ID, "NextButton").click()

        containers = driver.find_elements(By.CLASS_NAME, "rbListContainer")
        print(len(containers))
        for container in containers:
            radios = container.find_elements(By.CLASS_NAME, "radioBranded")
            print(len(radios))
            radios[0].click()
        driver.find_element(By.ID, "NextButton").click()

        containers = driver.find_elements(By.CLASS_NAME, "InputRowOdd")
        containers.extend(driver.find_elements(By.CLASS_NAME, "InputRowEven"))
        for container in containers:
            container.find_elements(By.CLASS_NAME, "radioBranded")[0].click()
        driver.find_element(By.ID, "NextButton").click()

        containers = driver.find_elements(By.CLASS_NAME, "InputRowOdd")
        containers.extend(driver.find_elements(By.CLASS_NAME, "InputRowEven"))
        for container in containers:
            container.find_elements(By.CLASS_NAME, "radioBranded")[0].click()
        driver.find_element(By.ID, "NextButton").click()

        containers = driver.find_elements(By.CLASS_NAME, "InputRowOdd")
        containers.extend(driver.find_elements(By.CLASS_NAME, "InputRowEven"))
        for container in containers:
            container.find_elements(By.CLASS_NAME, "radioBranded")[1].click()
        driver.find_element(By.ID, "NextButton").click()

        # driver.find_element(By.CLASS_NAME, "textinputwrapper").send_keys(" ")
        driver.find_element(By.ID, "S081000").send_keys(" ")
        driver.find_element(By.ID, "NextButton").click()

        containers = driver.find_elements(By.CLASS_NAME, "InputRowOdd")
        containers.extend(driver.find_elements(By.CLASS_NAME, "InputRowEven"))
        for container in containers:
            container.find_elements(By.CLASS_NAME, "radioBranded")[1].click()
        driver.find_element(By.ID, "NextButton").click()

        code_text = driver.find_element(By.CLASS_NAME, "ValCode").text
        code = code_text.split(sep=': ')[-1]
        # print(f"{code=}")

        # sleep(10)
        # driver.quit()

        return int(code)


def main():
    with open("codes.txt", "a") as f:
        f.write(f"{COUPON_CODE}, ")

        for i in range(1, 100):
            kfc = Kfc()
            code = kfc.run(COUPON_CODE)
            print(f"{code=}")
            f.write(f"{code}, ")


if __name__ == "__main__":
    main()
