import traceback
from time import sleep
from typing import List, Any
from urllib.error import HTTPError
from random import uniform

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

    def _send(self, message: str):  # TODO make thread safe
        while True:
            try:
                self.notifier.send(message)
                break
            except HTTPError as e:
                print("DiscordSender: Rate limit reached")
                sleep(uniform(0.2, 2))

    def send_sendable(self, sendables: List[Sendable]):
        # todo maybe run in parallel
        for s in sendables:
            self._send(self._format_product_message(s))

    def send_plain(self, text: str):
        if self.notify:
            text = "@here \n" + text
        self._send(text)
