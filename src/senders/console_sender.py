from typing import List

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class ConsoleSender(Sender):
    def _format_product_message(self, sendable: Sendable) -> str:
        return sendable.message + '\n'

    def send_sendable(self, sendables: List[Sendable]):
        for s in sendables:
            print(self._format_product_message(s))

    def send_plain(self, text: str):
        print(text)
