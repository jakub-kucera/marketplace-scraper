from typing import List

from slack_sdk.webhook import WebhookClient


class SlackSender(Sender):
    def __init__(self, url: str, notify: bool = False):
        super().__init__(notify)
        self.notifier = WebhookClient(url)

    def _format_product_message(self, sendable: Sendable) -> str:
        return sendable.message

    def send_sendable(self, sendables: List[Sendable]):
        for s in sendables:
            response = self.notifier.send(text=self._format_product_message(s))

    def send_plain(self, text: str):
        self.notifier.send(text=text)

