from threading import Thread
from time import sleep
from typing import List

from src.notifiers.notifier import Notifier


class Runner:
    @staticmethod
    def run(notifiers: List[Notifier]):
        threads: List[Thread] = [Thread(target=n.run) for n in notifiers]

        for thread in threads:
            thread.start()
            sleep(0.5)

        for thread in threads:
            thread.join()
