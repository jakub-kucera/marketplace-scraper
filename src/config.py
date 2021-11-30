from typing import List

from settings import SETTINGS
from src.intervals.random_interval import RandomInterval
from src.notifiers.alza_product_list_scraper import AlzaProductListScraper
from src.notifiers.bazos_scraper import BazosScraper
from src.notifiers.cinemacity_scraper import CinemaCityScraper
from src.notifiers.datart_product_list_scraper import DatartProductListScraper
from src.notifiers.greenhouse_list_scraper import GreenhouseJobListScraper
from src.notifiers.notifier import Notifier
from src.query import Query
from src.senders.discord_sender import DiscordSender

pc_bazos = "https://pc.bazos.cz/pc/"  # TODO move elsewhere
laptop_bazos = "https://pc.bazos.cz/notebook/"
gpu_bazos = "https://pc.bazos.cz/graficka/"
cpu_bazos = "https://pc.bazos.cz/procesor/"
monitors_bazos = "https://pc.bazos.cz/monitor/"
mouse_keyboard_bazos = "https://pc.bazos.cz/mys/"
headphones_bazos = "https://elektro.bazos.cz/sluchatka/"
amplifiers_bazos = "https://elektro.bazos.cz/zesilovace/"
apple_phones_bazos = "https://mobil.bazos.cz/apple/"

fridge_bazos = "https://elektro.bazos.cz/lednicky/"
chairs_bazos = "https://nabytek.bazos.cz/zidle/"


def get_new_config() -> List[Notifier]:
    notifiers: List[Notifier] = \
        [
            # AlzaProductListScraper(
            #     sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_ALERT_WEBHOOK_URL, notify=True),
            #     logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
            #     name="AlzaScraper",
            #     interval=RandomInterval(lower=2*60, upper=7*60),
            #     link_to_list="https://alza.cz/iphone-13-pro/18892048.htm"
            # ),
            DatartProductListScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_ALERT_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                name="DatartScraper",
                interval=RandomInterval(lower=1*60, upper=3*60),
                link_to_list="https://www.datart.cz/iphone-13-pro.html"
            ),
            GreenhouseJobListScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_ALERT_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                name="GreenhouseScraper",
                interval=RandomInterval(lower=6 * 60 * 60, upper=15 * 60 * 60),
                link_to_list="https://boards.greenhouse.io/purestorage/"
            ),
            CinemaCityScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_ALERT_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                name="CinemaCity",
                interval=RandomInterval(lower=5*60, upper=15*60),
                start_day=1, end_day=30
            ),
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_ALERT_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                name="BazosScraper_alerts",
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
                    Query(text='AirPods Max', price_range=(0, 0), skip_round=False, category=headphones_bazos),
                    Query(text='Focal', price_range=(0, 0), skip_round=False, category=headphones_bazos),
                    Query(text='Dan Clark', price_range=(0, 0), skip_round=False, category=headphones_bazos),
                    Query(text='beyerdynamic', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='audio technica', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='HiFiMAN', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='AKG', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='Sennheiser', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='Sony', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),
                    Query(text='Bose', price_range=(1000, 0), skip_round=True, category=headphones_bazos, location=('11000', '50')),

                    # amplifiers
                    Query(text='Chord Mojo', price_range=(2000, 0), skip_round=True, location=('11000', '50')),
                    Query(text='schiit', price_range=(2000, 0), skip_round=True, location=('11000', '50')),

                    # mouse
                    Query(text='mx master 3', price_range=(0, 0), skip_round=True, category=mouse_keyboard_bazos, location=('11000', '20')),
                    Query(text='apple magic trackpad', price_range=(0, 0), skip_round=True, category=mouse_keyboard_bazos, location=('11000', '20')),

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
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_THINKPAD_WEBHOOK_URL, notify=True),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                name="BazosScraper_thinkpad",
                interval=RandomInterval(lower=10 * 60, upper=25 * 60),
                load_images=False,
                queries=
                [
                    Query(text='thinkpad', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '20')),
                    Query(text='dell latitude', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '20')),
                ]
            ),
            BazosScraper(
                sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_OTHER_WEBHOOK_URL, notify=False),
                logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
                name="BazosScraper_other",
                interval=RandomInterval(lower=15 * 60, upper=45 * 60),
                load_images=False,
                queries=
                [
                    # iphone
                    Query(text='iphone 13', price_range=(8000, 0), skip_round=True, category=apple_phones_bazos, location=('11000', '30')),

                    # laptop
                    Query(text='', price_range=(1000, 0), skip_round=True, category=laptop_bazos, location=('11000', '50')),

                    # pc
                    Query(text='', price_range=(5000, 0), skip_round=True, category=pc_bazos, location=('11000', '50')),

                    # cpu
                    Query(text='', price_range=(5000, 0), skip_round=True, category=cpu_bazos, location=('11000', '70')),

                    # mechanical keyboard
                    Query(text='mechanicka klavesnice', price_range=(400, 0), skip_round=True, category=mouse_keyboard_bazos, location=('11000', '30')),

                    # headphones
                    Query(text='', price_range=(4000, 0), skip_round=True, category=headphones_bazos, location=('11000', '70')),
                    Query(text='AirPods Pro', price_range=(1000, 0), skip_round=False, category=headphones_bazos, location=('11000', '30')),

                    # fridge
                    Query(text='lednicka', price_range=(500, 0), skip_round=True, category=fridge_bazos, location=('11000', '30')),

                    # office chair
                    Query(text='kancelarska zidle', price_range=(0, 0), skip_round=True, category=chairs_bazos, location=('11000', '100')),
                    Query(text='kancelarske kreslo', price_range=(0, 0), skip_round=True, category=chairs_bazos, location=('11000', '100')),
                ]
            ),
            # BazosScraper(
            #     sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_CHAIR_WEBHOOK_URL, notify=False),
            #     logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
            #     name="BazosScraper_chair",
            #     interval=RandomInterval(lower=15 * 60, upper=45 * 60),
            #     load_images=False,
            #     queries=
            #     [
            #
            #     ]
            # ),
            # BazosScraper(
            #     sender=DiscordSender(url=SETTINGS.DISCORD_BAZOS_PC_LAPTOP_WEBHOOK_URL, notify=False),
            #     logger=DiscordSender(url=SETTINGS.DISCORD_LOGGER_WEBHOOK_URL),
            #     name="BazosScraper_pc_laptop",
            #     interval=RandomInterval(lower=15 * 60, upper=45 * 60),
            #     load_images=False,
            #     queries=
            #     [
            #
            #     ]
            # )
        ]
    return notifiers
