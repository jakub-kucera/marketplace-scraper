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
# see docs/research/bazos-api/HIDDEN_API.md §4.0. Requesting more is
# silently clamped back down to this value.
API_PAGE_SIZE: Final[int] = 210

NEW_PRODUCT_LOAD_MAX: Final[int] = 50

MAX_ATTEMPTS = 5

VINTED_BASE_URL: Final[str] = "https://www.vinted.cz"
# Server-enforced hard cap on the search `per_page` param, confirmed live —
# see docs/archive/shipped/VINTED_SCRAPER.md §3. Requesting more (e.g. 200) is
# silently clamped back down to this value.
VINTED_PAGE_SIZE: Final[int] = 96
# Safety bound on run_query's page loop, so a misbehaving response (e.g. one
# that never returns a short page) cannot page forever.
VINTED_MAX_PAGES: Final[int] = 20
# A new_query backfill can fire up to NEW_PRODUCT_LOAD_MAX unpaced item() detail
# requests in a row — the exact kind of burst VINTED_SCRAPER_DESIGN.md §1a measured
# tripping the Cloudflare/DataDome session-cookie bootstrap. Search itself doesn't need
# this (6 rapid searches measured clean, no 429 — see VINTED_SCRAPER.md §9); only
# the detail-fetch burst does.
VINTED_DETAIL_WAIT_TIME: Final[tuple[float, float]] = (0.5, 1.5)

SBAZAR_BASE_URL: Final[str] = "https://www.sbazar.cz"
# limit=1000 is served, but 100 keeps a single failed request cheap and stays far
# below anything that might later be rate-limited. Measured payload ~1.28 KB/item.
SBAZAR_PAGE_SIZE: Final[int] = 100
# Safety stop so a mis-specified query cannot walk a 26k-item category forever.
SBAZAR_MAX_PAGES: Final[int] = 20
# How many consecutive already-known, non-topped ads QueryRunner.run_existing_query
# tolerates before stopping (see SbazarScraper.dedup_break_streak). Sbazar's default
# ordering is sorting_date (~= edit time), not creation time, so an old already-known ad
# can resurface above genuinely new listings just because it was edited — see
# docs/research/marketplaces/SBAZAR.md §5b.4 and docs/archive/shipped/SBAZAR_SCRAPER.md §11.
# NOT a measured value (unlike the constants above): derived from SBAZAR.md §2.1's
# bump rate for the busiest measured category (tools, ~19 bumps/hour) over the longest
# poll gap (90 min, night-doubled INTERVAL_UPPER), ~28 in the worst case, rounded up with
# margin. Revisit using QueryRun.rows_seen/new_ads_count once a real Sbazar Query has run.
SBAZAR_DEDUP_BREAK_STREAK: Final[int] = 40

BAZOS_PAGE_WAIT_TIME: Final[tuple[int, int]] = (2, 5)
# (connect, read) for every Bazos HTTP call. Same reasoning as IP_LOOKUP_TIMEOUT: these go
# through Tor, where an unreachable host is a stalled socket rather than a refused
# connection, and run_request carried no timeout at all — a single hung GET stalled the
# pass with nothing to interrupt it. Connect is generous because it covers circuit build.
BAZOS_REQUEST_TIMEOUT: Final[tuple[float, float]] = (20.0, 30.0)
# Pacing for `load_full_description`. Unpaced before this, so a query finding N new ads
# fired N back-to-back detail GETs immediately after its listing page — a 15-new-ad
# `Práce` pass on 2026-08-23 sent 15 in a row. Bursts, not steady volume, are what the
# QueryRun history correlates with 403s.
BAZOS_DETAIL_WAIT_TIME: Final[tuple[float, float]] = (1.0, 3.0)
# Pacing between queries inside one scraper pass. There was no gap at all: the runner
# went straight from one query's last request to the next query's first. Unprefixed
# because ScrapeRunner applies it to every marketplace, unlike the BAZOS_*/VINTED_* waits
# above, which each belong to one scraper.
QUERY_WAIT_TIME: Final[tuple[float, float]] = (5.0, 15.0)
# How many times a query is attempted before it is written off for this pass. Attempts
# after the first are preceded by an IP rotation. The attempt itself is the blacklist
# probe — see ScrapeRunner._run_query_with_rotation for why there is no separate one.
MAX_BLACKLIST_RETRIES: Final[int] = 3

# ---------------------------------------------------------------------------
# Pipeline process constants
# ---------------------------------------------------------------------------

FILTER_BATCH_SIZE: Final[int] = 50
FILTER_POLL_INTERVAL: Final[int] = 30   # seconds

SENDER_BATCH_SIZE: Final[int] = 50
SENDER_POLL_INTERVAL: Final[int] = 10   # seconds
MAX_SEND_ATTEMPTS: Final[int] = 5
