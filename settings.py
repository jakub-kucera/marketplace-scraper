from os import environ
from typing import Final

from dotenv import load_dotenv

load_dotenv()


class Settings:
    CHROMEDRIVER_PATH: Final[str] = environ.get("CHROMEDRIVER_PATH", "chromedriver")
    BAZOS_URL: Final[str] = "https://bazos.cz"

    DISCORD_TOKEN: Final[str] = environ.get("DISCORD_TOKEN", "")
    DISCORD_GUILD: Final[str] = environ.get("DISCORD_GUILD", "")
    DISCORD_BAZOS_WEBHOOK_URL: Final[str] = environ.get("DISCORD_BAZOS_WEBHOOK_URL", "")
    DISCORD_LOGGER_WEBHOOK_URL: Final[str] = environ.get("DISCORD_LOGGER_WEBHOOK_URL", "")

    EMAIL_SENDER: Final[str] = environ.get("EMAIL_SENDER", "")
    EMAIL_RECEIVER: Final[str] = environ.get("EMAIL_RECEIVER", "")

    NEW_PRODUCT_LOAD_MAX: Final[int] = 50

    LOG_DIRECTORY_PATH: Final[str] = "logs/"


SETTINGS = Settings()
