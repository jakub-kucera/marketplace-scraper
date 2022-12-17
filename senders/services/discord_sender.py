from time import sleep
from typing import List
from urllib.error import HTTPError, URLError
from random import uniform

import discord_notify as dn

from bazos.mixins import SendableMixin
from senders.models import Discord
from senders.services.sender import Sender


class DiscordSender(Sender):

    def __init__(self, url: str, notify: bool = False, preview_link: str = False):
        super().__init__(notify)
        self.notifier = dn.Notifier(url)
        self.preview_link = preview_link

    @classmethod
    def from_model(cls, sender: Discord):
        return cls(sender.url, sender.notify)

    def _format_link(self, link: str):
        if self.preview_link:
            return link
        else:
            return f"<{link}>"

    def _format_product_message(self, sendable: SendableMixin) -> str:
        message = "@here \n" if self.notify else ""
        message += self.wrap_multi_line(sendable.message)
        message += self._format_link(sendable.link)
        return message

    # def _format_product_message_db(self, product: ProductDB) -> str:  # TODO DE-DUPE
    #     message = "@here \n" if self.notify else ""
    #     message += self.wrap_multi_line(product.message)
    #     message += self._format_link(product.link)
    #     return message

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

    def send_sendable(self, sendables: List[SendableMixin]):
        # todo maybe run in parallel
        for s in sendables:
            self._send(self._format_product_message(s))

    # def send_product(self, products: List[ProductDB]):
    #     # todo maybe run in parallel
    #     for p in products:
    #         self._send(self._format_product_message(p))

    def send_plain(self, text: str):
        if self.notify:
            text = "@here \n" + text
        self._send(text)
