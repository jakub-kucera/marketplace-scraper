from src.intervals.interval import Interval


class ConstInterval(Interval):
    def __init__(self, interval_length: int):
        self.interval_length = interval_length

    def get_next_interval(self) -> int:
        return self.interval_length
