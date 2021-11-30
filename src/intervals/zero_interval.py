from src.intervals.interval import Interval


class ZeroInterval(Interval):
    def get_next_interval(self) -> int:
        return 0
