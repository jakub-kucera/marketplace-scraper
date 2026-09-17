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
# Rows per catalog page. No longer a request parameter: `per_page` was retired with the
# v2 API and the server-rendered page is fixed at 96 (measured 2026-09-16). Kept only as
# the "short page means the last page" sentinel in the pagination loop.
VINTED_PAGE_SIZE: Final[int] = 96
# Vinted serves at most 10 pages for any query — `total_entries` is capped at 960 for a
# broad search, while a narrow one reports its true count (measured: 151 over 2 pages).
# So this is the server's own ceiling, not an arbitrary safety bound.
VINTED_MAX_PAGES: Final[int] = 10
# A browser User-Agent is mandatory, not cosmetic: without one the request is served a
# DataDome interstitial instead of the page. With one, 10 back-to-back catalog fetches
# measured clean (VINTED.md §10). Deliberately a fixed string rather than
# requests-random-user-agent — Vinted fingerprints, and a UA that changes per request
# while the session cookie does not is a worse signal than a boring constant one.
VINTED_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
# (connect, read). Generous on read because a catalog page is ~800 KB gzipped that
# decompresses to ~7 MB; connect stays short because, unlike Bazos, this never goes
# through Tor and so never pays for circuit construction.
VINTED_REQUEST_TIMEOUT: Final[tuple[float, float]] = (10.0, 30.0)
# Currency for the price_from/price_to bounds. Must accompany them or they are ignored.
# Follows the domain — .cz/CZK, .sk/EUR, .pl/PLN — so a Query with a non-.cz `base_url`
# in extra_params needs this overridden there too.
VINTED_CURRENCY: Final[str] = "CZK"
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
#
# Sized against a measured block rate, not intuition. Somewhere around half of Tor exits
# are 403'd by Bazos — 5/12 and 8/14 in two probes on 2026-08-29, and the QueryRun history
# implies ~48% — and IsolateDestAddr draws an independent exit per destination host, so
# every attempt is an independent ~coin flip. At 3 attempts that left ~14% of query-passes
# with nothing at all, matching that history exactly (1428/1654 = 86.3% eventual success
# over 2026-08-24..29, which is 1 - 0.5^3). 8 takes the expected loss to ~1%. The spread
# between those samples is the reason for the margin: 8 stays near 1% anywhere in it,
# where 6 would be ~2% at the bad end. It is only affordable because a rotation is now a
# SOCKS-credential swap costing ~1 s rather than a 10-50 s NEWNYM round trip; raising it
# on the old rotation would have added minutes to every blocked query. Pass wall clock
# *falls* despite the higher ceiling, for the same reason.
MAX_BLACKLIST_RETRIES: Final[int] = 8

# ---------------------------------------------------------------------------
# Pipeline process constants
# ---------------------------------------------------------------------------

FILTER_BATCH_SIZE: Final[int] = 50
FILTER_POLL_INTERVAL: Final[int] = 30   # seconds

SENDER_BATCH_SIZE: Final[int] = 50
SENDER_POLL_INTERVAL: Final[int] = 10   # seconds
MAX_SEND_ATTEMPTS: Final[int] = 5

# ---------------------------------------------------------------------------
# Price scoring (docs/proposals/ML_PRICE_SCORING.md §5)
# ---------------------------------------------------------------------------

# Compute and store scores but never reject on them. The default is ON, not a flag someone
# has to remember to set: precision cannot be measured until P24 (delisting) exists, so the
# thresholds below are a defensible starting point, not a calibrated one.
PRICE_MODEL_SHADOW_MODE: Final[bool] = True
# z <= -2 means ~44% below prediction for an unknown private seller but ~14% for a 50-ad
# dealer. That asymmetry is the point -- it is one standard of evidence, not one percentage.
PRICE_MODEL_Z_THRESHOLD: Final[float] = -2.0
# The z-score alone answers "cheap for THIS seller", which a systematically expensive shop
# can satisfy while still being above market. Requiring both makes a deal mean cheap on
# both bases.
PRICE_MODEL_MIN_DISCOUNT_PCT: Final[float] = 10.0

# ---------------------------------------------------------------------------
# Postal-code geocoding (bazos/geo.py)
# ---------------------------------------------------------------------------

# Bazos's own geocoder, confirmed live both directions (docs/research/bazos-api/HIDDEN_API.md
# §3.1/§6.4d). Used only to fill the PostalCode cache — a code is looked up once, ever.
BAZOS_ZIP_API_URL: Final[str] = f"{BAZOS_API_BASE_URL}/zip.php"
# Pacing between geocode lookups, for the backfill command that walks hundreds of them in a
# row. The scraper's own per-ad lookups are already spaced by the walk around them.
GEOCODE_WAIT_TIME: Final[tuple[float, float]] = (1.0, 3.0)

# ---------------------------------------------------------------------------
# Comparables (bazos/comparables.py)
# ---------------------------------------------------------------------------

# How far back a listing still counts as a comparable. Long enough that a thin spec bucket
# (two M4 Max MacBooks on the whole site, measured 2026-09-15) has anything in it at all,
# short enough that a price from a different market moment does not set the bar.
COMPARABLE_MAX_AGE_DAYS: Final[int] = 90
# Cap on rows read for one bucket. The notification only shows a count and a span, and the
# appraisal report is meant to be read — neither wants an unbounded list, and this keeps the
# query cost of `Ad.message` bounded regardless of how popular a configuration is.
COMPARABLE_MAX_ROWS: Final[int] = 60

# ---------------------------------------------------------------------------
# Delisting sweep (bazos/delisting.py, `manage.py check_delisted`)
# ---------------------------------------------------------------------------

# `ads.php?ad_id[]=` accepts this many ids in one request and silently omits the ones that
# no longer exist — the absence IS the signal (HIDDEN_API.md §3.1, §4.0's measured cap).
DELIST_BATCH_SIZE: Final[int] = 210

# How often an ad is re-checked, by age. The hazard of a listing selling is front-loaded, so
# resolution is spent where the events are. This is the whole cost model: flat hourly checks
# over ~20k live Bazos ads would be ~3 300 requests/day — roughly three times the entire
# current scrape — while the schedule below covers the same ads for ~33/day, because
# `ceil(20000/210)` is only 96 requests for a *complete* sweep.
#
# (max_age_days, recheck_interval_days) — first matching row wins, so keep it ascending.
DELIST_SCHEDULE: Final[tuple[tuple[int, int], ...]] = (
    (3, 1),    # < 3 days old  -> daily
    (14, 3),   # 3-14 days     -> every 3 days
    (60, 7),   # 14-60 days    -> weekly
)
# Past this, stop checking and leave `removed_at` NULL. That is a **censored observation**,
# not "still for sale": Bazos listings expire on their own, so beyond this horizon a
# disappearance says more about the clock than about a buyer.
DELIST_MAX_AGE_DAYS: Final[int] = DELIST_SCHEDULE[-1][0]

# Ads that were notified or scored get checked one tier faster: they are few, and they are
# the ones whose outcome calibrates something. Everything else still gets watched, because
# without the un-notified ads there is no baseline to compare "sold fast" against.
DELIST_PRIORITY_SPEEDUP: Final[int] = 2

# Pacing between batches. Each request is ~200x cheaper per ad than a per-ad detail call,
# but PROXY_ROTATION.md §5.1 names detail-endpoint volume as the ban vector, so the sweep
# stays paced like every other Bazos path.
DELIST_WAIT_TIME: Final[tuple[float, float]] = (2.0, 5.0)


# ---------------------------------------------------------------------------
# Housekeeping (bazos/housekeeping.py, `manage.py prune_logs`)
# ---------------------------------------------------------------------------

# Rows per DELETE. Django resolves cascades by collecting every pk first, so one unbounded
# delete over a quarter-million rows is a single long transaction holding locks on a table
# the scraper is still writing to.
PRUNE_BATCH_SIZE: Final[int] = 5_000
