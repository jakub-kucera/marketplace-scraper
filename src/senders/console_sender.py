from typing import List

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class ConsoleSender(Sender):
    def _format_product_message(self, sendable: Sendable) -> str:
        pass

    def send_sendable(self, sendables: List[Sendable]):
        pass

    def send_plain(self, text: str):
        pass
