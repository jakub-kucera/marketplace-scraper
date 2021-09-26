import random

from src.interval.interval import Interval


class RandomInterval(Interval):
    def __init__(self, lower: int, upper: int):
        self.lower = lower
        self.upper = upper

    def get_next_interval(self) -> int:
        return random.randint(self.lower, self.upper)
