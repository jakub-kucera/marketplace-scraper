from os import environ
from typing import Final

from dotenv import load_dotenv

load_dotenv()


class Settings:
    BAZOS_URL: Final[str] = "https://bazos.cz/search.php"

    # DISCORD_LOGGER_WEBHOOK_URL: Final[str] = environ.get("DISCORD_LOGGER_WEBHOOK_URL", "")

    # EMAIL_SENDER: Final[str] = environ.get("EMAIL_SENDER", "")
    # EMAIL_RECEIVER: Final[str] = environ.get("EMAIL_RECEIVER", "")

    NEW_PRODUCT_LOAD_MAX: Final[int] = 50

    MAX_ATTEMPTS = 5

    LOG_DIRECTORY_PATH: Final[str] = "logs/"

    BAZOS_PAGE_WAIT_TIME: Final[tuple[int, int]] = (2, 5)

    TOR_PROXY_IP = environ.get("TOR_PROXY_IP", "localhost")
    TOR_PROXY_PASSWORD = environ.get("TOR_PROXY_PASSWORD", "root")

    LOCAL_IP_SUBNET = environ.get("LOCAL_IP_SUBNET", "146.70.111.0/24")


SETTINGS = Settings()
