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
amplifiers_bazos = "https://elektro.bazos.cz/zesilovace/"


def get_new_config() -> List[Notifier]:
    notifiers: List[Notifier] = \
        [
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                # sender=EmailSender(sender=SETTINGS.EMAIL_SENDER, receiver=SETTINGS.EMAIL_RECEIVER),
                # sender=MultiSender(senders_conditions=
                #        {
                #            d : DiscordSender(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True, send_empty=True),
                #            funcwork : EmailSender(sender=SETTINGS.EMAIL_SENDER, receiver=SETTINGS.EMAIL_RECEIVER)
                #        }),
                interval=RandomInterval(lower=7*60, upper=15*60),
                queries=
                [
                    # headphones
                    Query(text='Audeze', price_range=(0, 0), skip_round=False, category=headphones_bazos),
                    Query(text='beyerdynamic', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='audio technica', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='AKG', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='Sennheiser', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),

                    # amplifiers
                    Query(text='', price_range=(1000, 0), skip_round=True, category=amplifiers_bazos, location=('11000', '50')),

                    # office chairs
                    Query(text='herman miller', price_range=(0, 0), skip_round=False, category=chairs_bazos),

                    # monitors
                    Query(text='', price_range=(5000, 0), skip_round=True, category=monitors_bazos, location=('11000', '70')),

                    # Query(text='lednicka', price_range=(0, 100), skip_round=False, category="https://elektro.bazos.cz/lednicky/"),
                ]
            )
        ]
    return notifiers
