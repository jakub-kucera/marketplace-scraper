from abc import ABC, abstractmethod
from typing import Iterator

from src.query import Query
from src.sendables.product import Product


class Scraper(ABC):
    @abstractmethod
    def run_query(self, query: Query) -> Iterator[Product]:
        pass
