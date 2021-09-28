from typing import List, Any

import discord_notify as dn

from src.sendables.sendable import Sendable
from src.senders.sender import Sender


class DiscordSender(Sender):

    def __init__(self, url: str, notify: bool = False):
        super().__init__(notify)
        self.notifier = dn.Notifier(url)

    def _format_product_message(self, sendable: Sendable) -> str:
        message = "@here \n" if self.notify else ""
        message += self.wrap_multi_line(sendable.message)
        message += sendable.link
        return message

    def send_sendable(self, sendables: List[Sendable]):
        # todo maybe run in parallel
        for s in sendables:
            self.notifier.send(self._format_product_message(s))

    def send_plain(self, text: str):
        self.notifier.send(text)
