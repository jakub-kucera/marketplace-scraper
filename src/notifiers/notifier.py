from abc import abstractmethod, ABC

from src.senders.sender import Sender


class Notifier(ABC):
    def __init__(self, sender: Sender, logger: Sender, name: str):
        self.sender = sender
        self.logger = logger
        self.name = name

    @abstractmethod
    def run(self):
        pass

    def log(self, text: str):  # maybe make Logger class that wraps Sender
        # self.logger.send_plain(f"{self.name}: {text}")
        for line in text.split(sep='\n'):
            self.logger.send_plain(f"{self.name}: {line}")
        #     self.logger.send_plain(f"\t {line}")
