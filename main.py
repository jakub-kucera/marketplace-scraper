from typing import Dict, Optional

import discord
from discord.ext import commands
from discord.ext.commands import Context

from bazos_scrapper import BazosScrapper
from default_config import SETTINGS

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

    scrapper = BazosScrapper(ctx=ctx)
    await scrapper.run(queries=['sennheiser'])


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

