from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from src.sendables.sendable import Sendable


class Product(BaseModel, Sendable):
    name: str
    price: str  # todo change to Optional[int]
    url: str
    location: str
    date: datetime
    ignore_date: bool
    description: str

    @staticmethod  # todo each scrapper to have its own converter
    def convert_price(original: str) -> Optional[int]:
        digit_part = original.split()[0]
        if digit_part.isnumeric():
            price = int(digit_part)
            return price if price > 1 else None
        return None

    @property
    def message(self):
        return self.name + '\n' + \
               self.price + '\n' + \
               self.location + '\n' + \
               self.description

    @property
    def link(self):
        return self.url

    def compare_custom(self, other) -> bool:
        """
        Compare two products. Description is not compare, because of different formatting.
        """
        return self.name == other.name and \
               self.price == other.price and \
               self.url == other.url and \
               self.location == other.location and \
               self.date == other.date and \
               self.ignore_date == other.ignore_date

    # @validator('url')
    # def url_valid(cls, value: str):
    #     try:
    #         request = requests.head(value)
    #     except ConnectionError:
    #         raise ValueError
    #     assert request.status_code < 400
    #     assert validators.url(value)
    #     return value

