from os import environ
from typing import Final

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BAZOS_URL: Final[str] = "https://bazos.cz/"

    DISCORD_TOKEN: Final[str] = environ.get("DISCORD_TOKEN", "")
    DISCORD_GUILD: Final[str] = environ.get("DISCORD_GUILD", "")

    DISCORD_LOGGER_WEBHOOK_URL: Final[str] = environ.get("DISCORD_LOGGER_WEBHOOK_URL", "")
    DISCORD_BAZOS_ALERT_WEBHOOK_URL: Final[str] = environ.get("DISCORD_BAZOS_ALERT_WEBHOOK_URL", "")
    DISCORD_BAZOS_THINKPAD_WEBHOOK_URL: Final[str] = environ.get("DISCORD_BAZOS_THINKPAD_WEBHOOK_URL", "")
    DISCORD_BAZOS_OTHER_WEBHOOK_URL: Final[str] = environ.get("DISCORD_BAZOS_OTHER_WEBHOOK_URL", "")
    DISCORD_BAZOS_PC_LAPTOP_WEBHOOK_URL: Final[str] = environ.get("DISCORD_BAZOS_PC_LAPTOP_WEBHOOK_URL", "")
    DISCORD_BAZOS_CHAIR_WEBHOOK_URL: Final[str] = environ.get("DISCORD_BAZOS_CHAIR_WEBHOOK_URL", "")

    EMAIL_SENDER: Final[str] = environ.get("EMAIL_SENDER", "")
    EMAIL_RECEIVER: Final[str] = environ.get("EMAIL_RECEIVER", "")

    NEW_PRODUCT_LOAD_MAX: Final[int] = 50

    MAX_ATTEMPTS = 5

    LOG_DIRECTORY_PATH: Final[str] = "logs/"


SETTINGS = Settings()
