from abc import ABC, abstractmethod
from typing import Iterator

from src.query_old import QueryOLD
from src.sendables.product_old import ProductOLD


class BazosScraper(ABC):
    @abstractmethod
    def run_query(self, query: QueryOLD) -> Iterator[ProductOLD]:
        pass
