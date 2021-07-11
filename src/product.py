from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class Product(BaseModel):
    name: str
    price: str  # todo change to Optional[int]
    url: str
    location: str
    date: datetime
    ignore_date: bool
    description: str

    def __str__(self):
        return self.name + '\n' + \
               self.price + '\n' + \
               self.location + '\n' + \
               self.description
               # self.url + '\n' + \
               # str(self.date) + '\n' + \
               # ('ignore date' if self.ignore_date else 'dont ignore date') + '\n' + \
               # self.description

    @staticmethod  # todo each scrapper to have its own converter
    def convert_price(original: str) -> Optional[int]:
        digit_part = original.split()[0]
        if digit_part.isnumeric():
            price = int(digit_part)
            return price if price > 1 else None
        return None

    # @validator('url')
    # def url_valid(cls, value: str):
    #     try:
    #         request = requests.head(value)
    #     except ConnectionError:
    #         raise ValueError
    #     assert request.status_code < 400
    #     assert validators.url(value)
    #     return value

