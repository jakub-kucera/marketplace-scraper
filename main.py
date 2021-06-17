from typing import Dict, Optional

import discord
from discord.ext import commands
from discord.ext.commands import Context

from default_config import SETTINGS

intents = discord.Intents.default()
intents.members = True
discord_bot = commands.Bot(command_prefix='!', intents=intents)


@discord_bot.event
async def on_ready():
    print("Discord bot ready")


@discord_bot.command(name='start', help="{chosen month} {highest allowed day}")
async def start_bot(ctx: Context, chosen_month: str, day_threshold: int):

    ctx.

    await ctx.send("starting")
    await ctx.send(f"chosen_month: {chosen_month}")
    await ctx.send(f"day_threshold: {day_threshold}")
    await ctx.send(f"Command sent by : {ctx.message.author.id}")

    try:
        scrapper = Scrapper(ctx=ctx, chosen_month=chosen_month, day_number_threshold=day_threshold, refresh_interval=5)
        sessions[ctx.message.author.id] = scrapper
        await scrapper.run()
    except Exception as e:
        await ctx.send("```" + str(e) + "```")
        raise e


@discord_bot.command(name='stop')
async def stop_bot(ctx: Context):
    session_scrapper = sessions.get(ctx.message.author.id)
    if session_scrapper is None:
        await ctx.send("Scrapper wasn't running for this user.")
    else:
        await ctx.send("stopping")
        session_scrapper.stop()
        sessions[ctx.message.author.id] = None

if __name__ == "__main__":
    discord_bot.run(SETTINGS.DISCORD_TOKEN)

