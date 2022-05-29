from time import sleep
from typing import List
from urllib.error import HTTPError, URLError
from random import uniform

import discord_notify as dn

from src.models import ProductDB
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

    def _format_product_message_db(self, product: ProductDB) -> str:
        message = "@here \n" if self.notify else ""
        message += self.wrap_multi_line(product.message)
        message += product.link
        return message

    def _send(self, message: str):  # TODO make thread safe
        while True:
            try:
                self.notifier.send(message)
                sleep(uniform(0.5, 2))
                break
            except HTTPError as e:
                print("DiscordSender: Rate limit reached")
                sleep(uniform(1, 5))
            except URLError as e:
                print("DiscordSender: Connection error")

    def send_sendable(self, sendables: List[Sendable]):
        # todo maybe run in parallel
        for s in sendables:
            self._send(self._format_product_message(s))

    def send_product(self, products: List[ProductDB]):
        # todo maybe run in parallel
        for p in products:
            self._send(self._format_product_message(p))

    def send_plain(self, text: str):
        if self.notify:
            text = "@here \n" + text
        self._send(text)
