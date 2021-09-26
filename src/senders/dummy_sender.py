from typing import List

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class DummySender(Sender):
    def __init__(self, notify: bool = False, send_empty: bool = False):
        super().__init__(notify, send_empty)

    def _format_product_message(self, sendable: Sendable) -> str:
        return sendable.message + '\n'

    def send_sendable(self, sendables: List[Sendable]):
        if len(sendables) != 0:
            for s in sendables:
                print(self._format_product_message(s))
        elif self.send_empty:
            print("empty")

    def send_plain(self, text: str):
        print(text)

