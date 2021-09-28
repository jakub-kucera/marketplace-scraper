from abc import abstractmethod, ABC

from src.senders.sender import Sender


class Notifier(ABC):
    def __init__(self, sender: Sender, logger: Sender):
        self.sender = sender
        self.logger = logger

    @abstractmethod
    def run(self):
        pass

    def log(self, text: str):
        self.logger.send_plain(text)
