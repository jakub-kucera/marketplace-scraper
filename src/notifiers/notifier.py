from abc import abstractmethod, ABC

from src.senders.sender import Sender


class Notifier(ABC):
    def __init__(self, sender: Sender):
        self.sender = sender

    @abstractmethod
    def run(self):
        pass
