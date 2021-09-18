import asyncio
from typing import List

from src.notifiers.bazos_scraper import BazosScraper
from default_config import SETTINGS
from src.notifiers.notifier import Notifier
from src.runner import Runner
from src.senders.discord_sender import DiscordSender
from src.query import Query


def main():
    notifiers: List[Notifier] = \
        [
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True, send_empty=True),
                interval=600,
                queries=
                [
                    Query(text='Audeze', price_range=(0, 0), skip_round=False),
                    Query(text='beyerdynamic', price_range=(0, 0), skip_round=True),
                    Query(text='audio technica', price_range=(0, 0), skip_round=True),
                    Query(text='AKG', price_range=(0, 0), skip_round=True),
                    Query(text='Sennheiser', price_range=(0, 0), skip_round=True),

                    Query(text='herman miller', price_range=(0, 0), skip_round=False),
                    # Query(text='sluchatka', price_range=(0, 0), skip_round=True),
                ]
            )
        ]

    Runner.run(notifiers)


# config:
# [ notifier
#     for all:
#       List[sender]
#       reaload_time

#     specific:

# ]

if __name__ == "__main__":
    main()
