from typing import List

from settings import SETTINGS
from src.interval.random_interval import RandomInterval
from src.notifiers.bazos_scraper import BazosScraper
from src.notifiers.notifier import Notifier
from src.query import Query
from src.senders.discord_sender import DiscordSender

headphones_bazos = "https://elektro.bazos.cz/sluchatka/"  # TODO move elsewhere
monitors_bazos = "https://pc.bazos.cz/monitor/"
chairs_bazos = "https://nabytek.bazos.cz/zidle/"


def get_new_config() -> List[Notifier]:
    notifiers: List[Notifier] = \
        [
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True, send_empty=True),
                # sender=EmailSender(sender=SETTINGS.EMAIL_SENDER, receiver=SETTINGS.EMAIL_RECEIVER),
                # sender=MultiSender(senders_conditions=
                #        {
                #            d : DiscordSender(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True, send_empty=True),
                #            funcwork : EmailSender(sender=SETTINGS.EMAIL_SENDER, receiver=SETTINGS.EMAIL_RECEIVER)
                #        }),
                interval=RandomInterval(lower=8*60, upper=15*60),
                queries=
                [
                    Query(text='Audeze', price_range=(0, 0), skip_round=False, category=headphones_bazos),
                    Query(text='beyerdynamic', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '15')),
                    Query(text='audio technica', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '15')),
                    Query(text='AKG', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '15')),
                    Query(text='Sennheiser', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '15')),

                    Query(text='herman miller', price_range=(0, 0), skip_round=False, category=chairs_bazos),

                    Query(text='', price_range=(5000, 0), skip_round=True, category=monitors_bazos, location=('11000', '20')),

                    # Query(text='', price_range=(5000, 0), skip_round=False),
                    # Query(text='lednicka', price_range=(0, 100), skip_round=False, category="https://elektro.bazos.cz/lednicky/"),
                    # Query(text='lednicka', price_range=(0, 100), skip_round=False),
                    # Query(text='lednicka', price_range=(0, 100), skip_round=False, category="https://elektro.bazos.cz/lednicky/"),
                ]
            )
        ]
    return notifiers
