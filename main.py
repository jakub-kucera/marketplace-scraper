import asyncio
from threading import Thread
from typing import List

import discord_notify as dn

from src.bazos_scraper import BazosScraper
from default_config import SETTINGS
from src.discord_sender_bot import DiscordSenderBot
from src.discord_sender_wh import DiscordSenderWH
from src.query import Query


def main():

    sender = DiscordSenderWH(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True, send_empty=True)
    scrapper = BazosScraper(sender=sender)
    queries: List[Query] = \
        [
            Query(text='Audeze', price_range=(0, 0), skip_round=False),
            Query(text='beyerdynamic', price_range=(0, 0), skip_round=True),
            Query(text='audio technica', price_range=(0, 0), skip_round=True),
            Query(text='AKG', price_range=(0, 0), skip_round=True),
            Query(text='Sennheiser', price_range=(0, 0), skip_round=True),



            Query(text='herman miller', price_range=(0, 0), skip_round=True),
            # Query(text='sluchatka', price_range=(0, 0), skip_round=True),
        ]
    asyncio.run(scrapper.run(queries, interval=600))


if __name__ == "__main__":
    main()

