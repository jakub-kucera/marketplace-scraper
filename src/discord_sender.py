from typing import List, Optional

from discord.ext.commands import Context

from src.product import Product


class DiscordSender:

    def __init__(self, ctx: Context, send_empty: bool = False):
        self.ctx: Context = ctx
        self.send_empty: bool = send_empty

    @staticmethod
    def wrap_multi(message: str) -> str:
        return "```" + message + "```"

    @staticmethod
    def wrap_single(message: str) -> str:
        return "`" + message + "`"

    async def send_result(self, products: List[Product]):
        if len(products) != 0:
            await self.ctx.send("Found products:")
            for product in products:
                await self.ctx.send(self.wrap_multi(str(product)))
                await self.ctx.send(product.url)
        elif self.send_empty:
            await self.ctx.send(self.wrap_single("empty"))
