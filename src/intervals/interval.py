from abc import ABC, abstractmethod


class Interval(ABC):
    @abstractmethod
    def get_next_interval(self) -> int:
        pass
