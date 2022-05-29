from typing import List

from discord.ext.commands import Context

from src.sendables.product_old import ProductOLD


class DiscordSenderBot():

    def __init__(self, ctx: Context, send_empty: bool = False):
        self.ctx: Context = ctx
        self.send_empty: bool = send_empty

    @staticmethod
    def wrap_multi(message: str) -> str:
        return "```" + message + "```"

    @staticmethod
    def wrap_single(message: str) -> str:
        return "`" + message + "`"

    async def send_result(self, products: List[ProductOLD]):
        # todo maybe run in parallel
        if len(products) != 0:
            for product in products:
                print(f"Sending {product.name=}")
                await self.ctx.send(self.wrap_multi(str(product)) + product.url)
        elif self.send_empty:
            await self.ctx.send(self.wrap_single("empty"))
