from typing import List

import discord
from discord.ext import commands
from discord.ext.commands import Context

from src.bazos_scraper import BazosScraper
from default_config import SETTINGS
from src.discord_sender import DiscordSender
from src.query import Query

intents = discord.Intents.default()
intents.members = True
discord_bot = commands.Bot(command_prefix='!', intents=intents)


@discord_bot.event
async def on_ready():
    print("Discord bot ready")


@discord_bot.command(name='start')
async def start_bot(ctx: Context):

    await ctx.send("starting")
    await ctx.send(f"Sent by user: {ctx.message.author.id}")
    await ctx.send(f"Sent into : {ctx.message.channel.id}")

    sender = DiscordSender(ctx=ctx)
    scrapper = BazosScraper(sender=sender)
    queries: List[Query] =\
        [
            Query(text='Audeze', price_range=(0, 0), skip_round=False),
            Query(text='beyerdynamic', price_range=(0, 0), skip_round=True),
            Query(text='audio technica', price_range=(0, 0), skip_round=True),
            Query(text='AKG', price_range=(0, 0), skip_round=True),
            Query(text='Sennheiser', price_range=(0, 0), skip_round=True),
            # Query(text='sluchatka', price_range=(0, 0), skip_round=True),
        ]
    await scrapper.run(queries, interval=600)
    # await scrapper.run(queries)


# @discord_bot.command(name='stop')
# async def stop_bot(ctx: Context):
#     session_scrapper = sessions.get(ctx.message.author.id)
#     if session_scrapper is None:
#         await ctx.send("Scrapper wasn't running for this user.")
#     else:
#         await ctx.send("stopping")
#         session_scrapper.stop()
#         sessions[ctx.message.author.id] = None

if __name__ == "__main__":
    discord_bot.run(SETTINGS.DISCORD_TOKEN)

