from typing import List

from settings import SETTINGS
from src.notifiers.bazos_scraper import BazosScraper
from src.notifiers.notifier import Notifier
from src.query import Query
from src.senders.discord_sender import DiscordSender


# creates new instance of config everytime
def get_new_config() -> List[Notifier]:
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
    return notifiers
