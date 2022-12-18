from abc import ABC

from src.models import QueryDB


class Filter(ABC):
    def __init__(self, query: QueryDB):
        self.query = query
