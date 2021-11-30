from types import FunctionType
from typing import List, Dict, Iterator, Any, Tuple

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class MultiSender(Sender):
    def __init__(self, senders: List[Sender], notify: bool = False):
        super().__init__(notify)
        self.senders = senders

    def _format_product_message(self, sendable: Sendable) -> str:
        pass

    def send_sendable(self, sendables: List[Sendable]):
        for sender in self.senders:
            sender.send_sendable(sendables)

    def send_plain(self, text: str):
        for sender in self.senders:
            sender.send_plain(text)
