from typing import List

from settings import SETTINGS
from src.interval.random_interval import RandomInterval
from src.notifiers.bazos_scraper import BazosScraper
from src.notifiers.notifier import Notifier
from src.query import Query
from src.senders.discord_sender import DiscordSender

pc_bazos = "https://pc.bazos.cz/pc/"  # TODO move elsewhere
gpu_bazos = "https://pc.bazos.cz/graficka/"
cpu_bazos = "https://pc.bazos.cz/procesor/"
monitors_bazos = "https://pc.bazos.cz/monitor/"
mouse_keyboard_bazos = "https://pc.bazos.cz/mys/"
headphones_bazos = "https://elektro.bazos.cz/sluchatka/"
amplifiers_bazos = "https://elektro.bazos.cz/zesilovace/"

fridge_bazos = "https://elektro.bazos.cz/lednicky/"
chairs_bazos = "https://nabytek.bazos.cz/zidle/"


def get_new_config() -> List[Notifier]:
    notifiers: List[Notifier] = \
        [
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_ALERT_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                # sender=MultiSender(senders_conditions=
                #        {
                #            d : DiscordSender(url=SETTINGS.DISCORD_BAZOS_WEBHOOK_URL, notify=True, send_empty=True),
                #            funcwork : EmailSender(sender=SETTINGS.EMAIL_SENDER, receiver=SETTINGS.EMAIL_RECEIVER)
                #        }),
                interval=RandomInterval(lower=7*60, upper=15*60),
                load_images=False,
                queries=
                [
                    # headphones
                    Query(text='Audeze', price_range=(0, 0), skip_round=False, category=headphones_bazos),
                    Query(text='beyerdynamic', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='audio technica', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='AKG', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='Sennheiser', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),

                    # amplifiers
                    Query(text='Chord Mojo', price_range=(2000, 0), skip_round=True, location=('11000', '50')),
                    Query(text='schiit', price_range=(2000, 0), skip_round=True, location=('11000', '50')),

                    # mouse
                    Query(text='mx master 3', price_range=(0, 0), skip_round=True, location=('11000', '20')),

                    # office chairs
                    Query(text='herman miller', price_range=(0, 0), skip_round=False, category=chairs_bazos),

                    # monitors
                    Query(text='', price_range=(4000, 0), skip_round=True, category=monitors_bazos, location=('11000', '70')),

                    # egpu
                    Query(text='egpu', price_range=(5000, 0), skip_round=True, category=gpu_bazos, location=('11000', '70')),

                    # raspberry pi
                    Query(text='raspberry pi', price_range=(0, 0), skip_round=True, category=pc_bazos, location=('11000', '20')),
                ]
            ),
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_OTHER_WEBHOOK_URL, notify=False),  # TODO change
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                interval=RandomInterval(lower=15 * 60, upper=45 * 60),
                load_images=False,
                queries=
                [
                    # office chairs
                    Query(text='kancelarska zidle', price_range=(0, 0), skip_round=True, category=chairs_bazos, location=('11000', '100')),
                    Query(text='kancelarske kreslo', price_range=(0, 0), skip_round=True, category=chairs_bazos, location=('11000', '100')),

                    # pc
                    Query(text='', price_range=(5000, 0), skip_round=True, category=pc_bazos, location=('11000', '70')),

                    # cpu
                    Query(text='', price_range=(5000, 0), skip_round=True, category=cpu_bazos, location=('11000', '70')),

                    # mechanical keyboard
                    Query(text='mechanicka klavesnice', price_range=(400, 0), skip_round=True, category=mouse_keyboard_bazos, location=('11000', '30')),

                    # fridge
                    Query(text='lednicka', price_range=(500, 0), skip_round=True, category=fridge_bazos, location=('11000', '30')),
                ]
            )
        ]
    return notifiers
