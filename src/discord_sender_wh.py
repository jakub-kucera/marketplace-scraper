from typing import List, Optional

import discord_notify as dn

from src.product import Product


class DiscordSenderWH:

    def __init__(self, url: str, notify: bool = False, send_empty: bool = False):
        self.notifier = dn.Notifier(url)
        self.notifier.send("Scraper Starting", True)
        self.notifier.send("@here", True)
        self.notifier.send("@everyone", True)
        self.notify = notify
        self.send_empty: bool = send_empty

    @staticmethod
    def wrap_multi(message: str) -> str:
        return "```" + message + "```"

    @staticmethod
    def wrap_single(message: str) -> str:  # todo move into parent class (+ make static) + rename smth wrap_markdown_simple, +add self.send() for abstraction
        return "`" + message + "`"

    def format_product_message(self, product: Product) -> str:
        message = "@here \n" if self.notify else ""
        message += self.wrap_multi(str(product))
        message += product.url
        return message

    async def send_result(self, products: List[Product]):
        # todo maybe run in parallel
        if len(products) != 0:
            for product in products:
                print(f"Sending {product.name=}")
                self.notifier.send(self.format_product_message(product))
        elif self.send_empty:
            self.notifier.send(self.wrap_single("empty"))
