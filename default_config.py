from os import environ
from typing import Final

from dotenv import load_dotenv

load_dotenv()


class Settings:
    CHROMEDRIVER_PATH: Final[str] = environ.get("CHROMEDRIVER_PATH", "chromedriver")
    BAZOS_URL: Final[str] = "https://bazos.cz"

    DISCORD_TOKEN: Final[str] = environ.get("DISCORD_TOKEN", "")
    DISCORD_GUILD: Final[str] = environ.get("DISCORD_GUILD", "")
    DISCORD_BAZOS_WEBHOOK_URL: Final[str] = "https://discord.com/api/webhooks/877681569815461920/XhA3h9R6u5E6YLiQRtdA0Cgvy-ul5CCw8WiF_uwUGwkSG9Vcmy0pvxFcZ9LISnkiiomo"

    NEW_PRODUCT_LOAD_MAX: Final[int] = 50


SETTINGS = Settings()
