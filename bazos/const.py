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
BAZOS_BLACKLIST_CHECK_URL: Final[str] = "https://mobil.bazos.cz/apple/"

NEW_PRODUCT_LOAD_MAX: Final[int] = 50

MAX_ATTEMPTS = 5

BAZOS_PAGE_WAIT_TIME: Final[tuple[int, int]] = (2, 5)
