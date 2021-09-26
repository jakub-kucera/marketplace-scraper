from typing import List, Any

import discord_notify as dn

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class DiscordSender(Sender):

    def __init__(self, url: str, notify: bool = False, send_empty: bool = False):
        super().__init__(notify, send_empty)
        self.notifier = dn.Notifier(url)
        self.notifier.send("@here\nScraper Starting", True)

    def _format_product_message(self, sendable: Sendable) -> str:
        message = "@here \n" if self.notify else ""
        message += self.wrap_multi_line(sendable.message)
        message += sendable.link
        return message

    def send_sendable(self, sendables: List[Sendable]):
        # todo maybe run in parallel
        if len(sendables) != 0:
            for s in sendables:
                # print(f"Sending {product.name=}")
                self.notifier.send(self._format_product_message(s))
        elif self.send_empty:
            self.notifier.send(self.wrap_single_line("empty"))

    def send_plain(self, text: str):
        self.notifier.send(text)
