from typing import List

from slack_sdk.webhook import WebhookClient

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class SlackSender(Sender):
    def __init__(self, url: str, notify: bool = False, send_empty: bool = False):
        super().__init__(notify, send_empty)
        self.notifier = WebhookClient(url)
        self.notifier.send(text="Scraper Starting")
        self.notifier.send(text="@here")
        self.notifier.send(text="@everyone")

    def send_sendable(self, sendables: List[Sendable]):
        if len(sendables) != 0:
            for s in sendables:
                # print(f"Sending {product.name=}")
                response = self.notifier.send(text=s.message)
        elif self.send_empty:
            self.notifier.send(text=self.wrap_single_line("empty"))

    def send_plain(self, text: str):
        pass

