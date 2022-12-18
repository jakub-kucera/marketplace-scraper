from abc import ABC, abstractmethod
from datetime import datetime

import pytz


class IntervalMultiplier(ABC):
    def get_current_multiplier(self) -> float:
        pass

    def multiply(self, interval_sec: float | int) -> float:
        return self.get_current_multiplier() * interval_sec


class NoMultiplier(IntervalMultiplier):
    def get_current_multiplier(self) -> float:
        return 1.0


class NightMultiplier(IntervalMultiplier):
    def get_current_multiplier(self) -> float:
        now = datetime.now(tz=pytz.timezone('Europe/Prague'))  # not used, because not the same TZ handling
        now_dt = datetime(now.year, now.month, now.day, now.hour, now.minute, now.second, tzinfo=pytz.timezone('Europe/Prague'))
        morning = datetime(now.year, now.month, now.day, 6, 0, 0, tzinfo=pytz.timezone('Europe/Prague'))
        evening = datetime(now.year, now.month, now.day, 22, 0, 0, tzinfo=pytz.timezone('Europe/Prague'))
        # if morning < now < evening:
        if morning < now_dt < evening:
            return 1.0
        return 2.0
