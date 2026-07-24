from typing import Final

APPLE_PHONES_TABLETS_BAZOS = "https://mobil.bazos.cz/apple/"
PC_BAZOS = "https://pc.bazos.cz/pc/"
LAPTOP_BAZOS = "https://pc.bazos.cz/notebook/"
GPU_BAZOS = "https://pc.bazos.cz/graficka/"
CPU_BAZOS = "https://pc.bazos.cz/procesor/"
MONITORS_BAZOS = "https://pc.bazos.cz/monitor/"
MOUSE_KEYBOARD_BAZOS = "https://pc.bazos.cz/mys/"
HEADPHONES_BAZOS = "https://elektro.bazos.cz/sluchatka/"
AMPLIFIERS_BAZOS = "https://elektro.bazos.cz/zesilovace/"
FRIDGE_BAZOS = "https://elektro.bazos.cz/lednicky/"
CHAIRS_BAZOS = "https://nabytek.bazos.cz/zidle/"


PAGE_SIZE: Final[int] = 20

BAZOS_BASE_URL: Final[str] = "https://bazos.cz"
BAZOS_URL: Final[str] = "https://bazos.cz/search.php"
BAZOS_BLACKLIST_CHECK_URL: Final[str] = "https://www.bazos.cz/search.php?hledat=iphone&rubriky=www&hlokalita=&humkreis=25&cenaod=&cenado=&Submit=Hledat&kitx=ano"
BAZOS_API_BASE_URL: Final[str] = "https://www.bazos.cz/api/v1"
# Server-enforced hard cap on `ads.php`'s `limit` param, confirmed live —
# see docs/bazos-api/BAZOS_HIDDEN_API_RESEARCH.md §4.0. Requesting more is
# silently clamped back down to this value.
API_PAGE_SIZE: Final[int] = 210

NEW_PRODUCT_LOAD_MAX: Final[int] = 50

MAX_ATTEMPTS = 5

BAZOS_PAGE_WAIT_TIME: Final[tuple[int, int]] = (2, 5)

# ---------------------------------------------------------------------------
# Pipeline process constants
# ---------------------------------------------------------------------------

FILTER_BATCH_SIZE: Final[int] = 50
FILTER_POLL_INTERVAL: Final[int] = 30   # seconds

SENDER_BATCH_SIZE: Final[int] = 50
SENDER_POLL_INTERVAL: Final[int] = 10   # seconds
MAX_SEND_ATTEMPTS: Final[int] = 5
