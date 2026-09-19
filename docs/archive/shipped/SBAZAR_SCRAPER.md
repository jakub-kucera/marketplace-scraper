---
title: "Stage 10 — `SbazarScraper`: implementation spec"
status: shipped
updated: 2026-09-18
verified: 2026-09-18
shipped_in: 0030
---

# Stage 10 — `SbazarScraper`: implementation spec

> **Audited against the code 2026-09-18.** The §6 traps, the §1 endpoint rules and the §11 dedup
> fix all still match `bazos/scraping/sbazar/sbazar_scraper.py`; this is the trap list CLAUDE.md
> sends you to and it is still good. Four things have moved underneath it since 2026-08-23:
>
> - **§6.2 is now a stale *reason*, not a stale instruction.** `Ad.short_description` was widened
>   from `CharField(max_length=300)` to a `TextField` in migration `0035` (a Bazos listing
>   overflowed it and wedged a query for two hours), so an overflow can no longer raise
>   `DataError`. The code still slices `[:300]`, which is now a display choice rather than an
>   overflow guard.
> - **The mapper also sets `Ad.price` and `Ad.price_type`** via `_price_and_type` (P22, migration
>   `0032`), which did not exist when §3.1's code block was written. It branches on
>   `price_by_agreement` first for exactly the §6.1 reason.
> - **§2.3's rationale names APIs that were deleted.** `renew_ip_bazos_ok`,
>   `check_bazos_blacklisted` and the pre-flight `blacklist_check(query.url)` are all gone; there
>   is no pre-flight probe at all now, the query attempt is the probe. The `Query.url` Sbazar
>   branch §2.3 asks for is in the model and still correct, and the §7.9 test still guards it.
> - Class and file names moved (2026-08-23, commit `0a91b9a`): `BazosRunner` is now
>   `ScrapeRunner` in `bazos/scraping/runner.py`, and `BazosQueryRunner` is now `QueryRunner` in
>   `bazos/scraping/query_runner.py`. Read the old names below as the new ones.
>
> **Follow this document literally.** Every field name, endpoint, type and limit below was
> measured live on 2026-08-22 against the real Sbazar API and is recorded in
> [`SBAZAR.md`](../../research/marketplaces/SBAZAR.md). **Do not substitute values from
> memory, and do not "improve" the field mapping.** The traps in §6 are real bugs that were
> already found — if you deviate, you will re-introduce them.
>
> Price semantics are measured across all four marketplaces in
> [`PRICE_PARSING.md`](../../research/PRICE_PARSING.md) — read §6 before touching `_format_price`.
>
> If something here contradicts what you believe about Sbazar, **this document wins**.
> If something here contradicts the actual code you are editing, **stop and report it** — do not
> guess.

---

## 0. What you are building, in one paragraph

A new class `SbazarScraper` that satisfies the existing `MarketplaceScraper` protocol
(`bazos/scraping/marketplace.py`, 4 members) by calling Sbazar's public JSON API. It yields
unsaved `Ad` objects. **It does not save anything, does not send anything, and does not touch
`AdDelivery`** — `BazosQueryRunner` already owns persistence and delivery creation. Copy the
shape of `bazos/scraping/vinted/vinted_scraper.py`; it is the closest working example.

**Do not write a migration for `Ad`.** No `Ad` column changes are needed. The only migration is
the one Django generates for the new `Marketplace` choice (§2).

---

## 1. The API — verified, use exactly these

Base URL: `https://www.sbazar.cz`

| Purpose | Request |
|---|---|
| **Listing** | `GET /api/v1/items/search?category_id=<int>&limit=<int>&offset=<int>` |
| **Detail** | `GET /api/v1/items/<id>` |

Rules, all measured:

- **No auth.** No token, no cookie, no login, no `Referer`. Send `Accept: application/json` and a
  normal browser `User-Agent`. That is all.
- **⚠️ Detail endpoint takes NO trailing slash.** `/api/v1/items/233341956` → 200.
  `/api/v1/items/233341956/` → **404**. This will silently break everything if you add one.
- **Newest-first is the DEFAULT.** **Do not pass a sort parameter.** There is none to pass —
  verified across 666 non-promoted rows, `sorting_date` is monotonically non-increasing with zero
  violations. An unknown sort value is silently ignored, so a wrong guess fails invisibly.
- **Pagination is `limit` + `offset`** (not page numbers). The response echoes
  `{"pagination": {"limit": 1000, "offset": 0, "total": 26738}}`. Use `pagination.total` to know
  when to stop.
- `limit=1000` was served in full (1.3 MB, 1.37 s). **Use `SBAZAR_PAGE_SIZE = 100`** anyway — see
  §3. Do not use 1000 in the scraper.
- Other verified filter params: `phrase`, `price_from`, `price_to`, `category_id`.
- **Do not use the HTML site.** `https://www.sbazar.cz/<category>` redirects into a Seznam consent
  wall (`cmp.seznam.cz`, `reason=missing`). The `/api/` layer is unaffected by it. If you find
  yourself parsing HTML, you have gone wrong.

**Category ids** are the numeric prefix of the category slug: `143-notebooky` → `category_id=143`,
`22-stavebnictvi-naradi` → `category_id=22`.

### 1.1 Response shape — re-verified 2026-08-22 immediately before this spec was finalised

```bash
curl -s -H 'Accept: application/json' \
  'https://www.sbazar.cz/api/v1/items/search?category_id=143&limit=3'
```
```
TOP-LEVEL KEYS: ['pagination', 'results', 'status_code', 'status_message', 'warnings']
pagination:     {'limit': 3, 'offset': 0, 'total': 4400}
results[0]:     id=233201958 (int)
                seo_name='233201958-acer-aspire-go-15-8-gb-ram-skvely-stav'
                name='Acer Aspire Go 15 | 8 GB RAM | Skvělý stav'
                price=0 (int)          price_by_agreement=True (bool)
                topped=True (bool)     create_date='2026-08-17T20:13:31'
                locality={...}         user={'id':…, 'user_service': {'shop_url': …}}
                description            -> KEY ABSENT from listing rows
```

Three things to note from that single row:
- **The listing array key is `results`.** Not `items`, not `data`.
- **That first row is itself the §6.1 trap**: `price: 0` with `price_by_agreement: true`. If your
  `_format_price` is wrong, the very first notebook you fetch is mishandled.
- **`user_service` contained only `shop_url`** here — `shop_name` was not even present. Read
  `shop_url` and this is a non-issue; read `shop_name` and you get `None` *sometimes* and a real
  person's name other times, which is the worst of both.

---

## 1.5 ✅ Tor pre-flight — ALREADY RUN, IT PASSED. Proceed as written.

> **Result, measured 2026-08-22:** Sbazar's API returned **`200` on 3/3 requests through Tor**
> (0.34–0.47 s), via a verified Tor circuit (SOCKS exit `192.42.116.110` vs. direct
> `88.146.116.43`). **No escape hatch is needed — ignore §3.2 and use the shared session as
> written in §3.1.**
>
> For contrast, and why this check exists: **Aukro was `403 cf-mitigated: challenge` on 3/3
> through the same circuit.** The check is not a formality — one of the two candidate
> marketplaces fails it.
>
> The original instructions are kept below for the record and for the next marketplace.

<details><summary>Original pre-flight instructions (superseded by the result above)</summary>

## 1.5-orig ⚠️ STOP — do the Tor pre-flight check BEFORE writing any code

**Every measurement in this spec and in `../../research/marketplaces/SBAZAR.md` was taken over a direct
residential Czech connection. NONE of it was taken through Tor.** That matters, because the
scraper you are about to write will not run that way:

`_build_scrapers` is handed `self.ip_changer.session` (`bazos_runner.py:160`), and
`TorIPChanger.renew_session()` sets `self.session.proxies = PROXIES` (`ip_changer/tor.py:25-26`).
**So in production every Sbazar request egresses through Tor.** The "no anti-bot, no rate limits,
no blocking observed" findings do **not** transfer to that path — `../../research/marketplaces/SBAZAR.md` §9 lists rate limits
and block shape as NOT DETERMINED, and Tor exit nodes carry datacenter-grade IP reputation.

There is precedent for this going wrong: **`VintedScraper` deliberately ignores the session it is
given** and egresses from the host's real IP, because Vinted bans proxy/VPN traffic
(`vinted_scraper.py` docstring, `VINTED_SCRAPER_DESIGN.md` §2).

**Run this first. It takes one minute and it decides whether §3.1 needs an escape hatch.**

```bash
docker compose up -d tor_proxy
curl -s -o /dev/null -w 'via tor: %{http_code}\n' \
  --socks5-hostname 127.0.0.1:9050 \
  -H 'Accept: application/json' \
  'https://www.sbazar.cz/api/v1/items/search?category_id=143&limit=3'
```

| Result | What to do |
|---|---|
| **`200`** | Proceed exactly as written. Record the result in `../../research/marketplaces/SBAZAR.md` §9, replacing the NOT DETERMINED line. |
| **`403` / `429` / a challenge / a timeout** | **Do not work around it silently.** Apply the escape hatch in §3.2, and report the status code. |

Repeat the request 5 times at ~1 s spacing and record every status code — that is the burst test
`../../research/marketplaces/SBAZAR.md` §9 says was never run.

</details>

---

## 2. Step 1 — constants and the `Marketplace` choice

### 2.1 `bazos/const.py` — append

```python
SBAZAR_BASE_URL: Final[str] = "https://www.sbazar.cz"
# limit=1000 is served, but 100 keeps a single failed request cheap and stays far
# below anything that might later be rate-limited. Measured payload ~1.28 KB/item.
SBAZAR_PAGE_SIZE: Final[int] = 100
# Safety stop so a mis-specified query cannot walk a 26k-item category forever.
SBAZAR_MAX_PAGES: Final[int] = 20
```

### 2.2 `bazos/models.py` — add ONE line to `Marketplace`

```python
class Marketplace(models.TextChoices):
    BAZOS     = "bazos",     "Bazos"
    BAZOS_API = "bazos_api", "Bazos (API)"
    VINTED    = "vinted",    "Vinted"
    SBAZAR    = "sbazar",    "Sbazar"      # <-- add this line only
```

Then:
```bash
python manage.py makemigrations bazos
python manage.py migrate
```
This produces an `AlterField` on `Ad.marketplace` and `Query.marketplace`. **That is the only
migration this stage needs.** If `makemigrations` wants to change anything else, stop — something
is wrong.

### 2.3 `bazos/models.py` — extend `Query.url` (do not skip this)

`Query.url` currently special-cases **Vinted only**, then falls through to Bazos:

```python
@property
def url(self):
    if self.marketplace == Marketplace.VINTED:
        return self.extra_params.get("base_url", VINTED_BASE_URL)
    if self.section: ...
    elif self.category: ...
    return BAZOS_BASE_URL          # <-- a Sbazar query lands HERE today
```

A Sbazar `Query` has neither `section` nor `category` (§5), so **`query.url` silently returns
`BAZOS_BASE_URL` — the wrong site entirely.** Add the Sbazar branch alongside Vinted's:

```python
    if self.marketplace == Marketplace.SBAZAR:
        return self.extra_params.get("base_url", SBAZAR_BASE_URL)
```
(and import `SBAZAR_BASE_URL` from `bazos.const` next to the existing `VINTED_BASE_URL` import).

**Why bother, when nothing seems to read it?** It is a latent trap, not a live bug. The consumer is
`BazosRunner.change_ip` → `ip_changer.renew_ip_bazos_ok(query.url, …)`
(`bazos_runner.py:154`), reached only when `blacklist_check(query.url)` returns `True`. For Sbazar
that is `check_blacklisted()`, which this spec defines as always `False` (§3.1) — **so the broken
path is unreachable today**. The moment anyone gives `SbazarScraper.check_blacklisted` a real
implementation, IP rotation would start validating new exit IPs against **bazos.cz** while trying
to unblock **sbazar.cz**, and the failure would look like "IP rotation doesn't work" rather than
"wrong URL". Fix it now while it is one line.

---

## 3. Step 2 — create `bazos/scraping/sbazar/`

Create the package exactly like `bazos/scraping/vinted/`:

```
bazos/scraping/sbazar/__init__.py          (empty file)
bazos/scraping/sbazar/sbazar_scraper.py    (the code below)
```

### 3.1 `sbazar_scraper.py` — write this

```python
"""SbazarScraper — search via Sbazar's public JSON API.

Implements the `MarketplaceScraper` protocol (bazos/scraping/marketplace.py) for
Sbazar.cz. Every field name and limit below was measured live 2026-08-22 and is
documented in ../../research/marketplaces/SBAZAR.md §5a. This module follows
SBAZAR_SCRAPER.md exactly — deviating without updating that spec
will re-open bugs it already found (price-by-agreement rejecting every negotiable ad,
short_description overflowing its column, leaking the seller's real name).
"""
import logging
from typing import Any, Iterator
from zoneinfo import ZoneInfo

import requests
from django.utils import timezone

from bazos.const import SBAZAR_BASE_URL, SBAZAR_MAX_PAGES, SBAZAR_PAGE_SIZE
from bazos.models import Ad, Marketplace, Query

logger = logging.getLogger(__name__)

PRAGUE = ZoneInfo("Europe/Prague")


class SbazarScraper:
    """MarketplaceScraper for Sbazar.cz, backed by its public JSON API."""

    marketplace = Marketplace.SBAZAR.value

    def __init__(self, session: requests.Session) -> None:
        self.session = session

    # ---------- protocol member 1 ----------
    def run_query(self, query: Query) -> Iterator[Ad]:
        extra_params = dict(query.extra_params)
        base_url = extra_params.pop("base_url", SBAZAR_BASE_URL)

        params: dict[str, Any] = {"limit": SBAZAR_PAGE_SIZE}
        if query.text:
            params["phrase"] = query.text
        if query.price_lower:
            params["price_from"] = query.price_lower
        if query.price_upper:
            params["price_to"] = query.price_upper
        params.update(extra_params)   # category_id comes from here

        offset = 0
        for _ in range(SBAZAR_MAX_PAGES):
            params["offset"] = offset
            payload = self._get(f"{base_url}/api/v1/items/search", params)
            results = payload.get("results") or []
            if not results:
                return
            for row in results:
                yield self._map_item(row, base_url)
            offset += len(results)
            total = (payload.get("pagination") or {}).get("total")
            if total is not None and offset >= total:
                return
            if len(results) < SBAZAR_PAGE_SIZE:
                return

    # ---------- protocol member 2 ----------
    def load_full_description(self, ad: Ad) -> Ad:
        """NOT a no-op: `description` is absent from every search result.

        Called by BazosQueryRunner._handle_new_product with NO try/except, so an
        exception escaping here aborts the rest of that query's pass. Catch everything.
        """
        try:
            payload = self._get(f"{SBAZAR_BASE_URL}/api/v1/items/{ad.external_id}", None)
        except requests.RequestException as e:
            logger.info("Sbazar detail fetch failed for ad %s: %s", ad.external_id, e)
            return ad
        description = payload.get("description") or ""
        if not description:
            logger.debug("Sbazar detail for ad %s carried no description", ad.external_id)
            return ad
        ad.full_description = description
        ad.short_description = description[:300]      # column is 300 — see spec §6.2
        return ad

    # ---------- protocol member 3 ----------
    def check_blacklisted(self) -> bool:
        """Always False: no blocking has ever been observed on /api/, so there is no
        measured signal to detect. Do NOT invent one.

        Two consequences the spec covers deliberately: this makes the wrong-URL path in
        Query.url unreachable (spec §2.3), and the "never blocked" evidence was gathered
        over a direct connection, not through Tor (spec §1.5). If you later give this a
        real implementation, re-read both sections first.
        """
        return False

    # ---------- helpers ----------
    def _get(self, url: str, params: dict[str, Any] | None) -> dict[str, Any]:
        response = self.session.get(
            url,
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
                ),
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _map_item(row: dict[str, Any], base_url: str) -> Ad:
        return Ad(
            external_id=row["id"],
            marketplace=Marketplace.SBAZAR.value,
            url=f"{base_url}/inzerat/{row['seo_name']}",
            name=(row.get("name") or "")[:120],
            price_raw=SbazarScraper._format_price(row),
            location=SbazarScraper._format_location(row),
            view_count=None,                       # Sbazar exposes none — never synthesise
            publish_date=SbazarScraper._parse_date(row.get("create_date")),
            topped=bool(row.get("topped")),        # a real JSON bool, not a string
            short_description="",                  # detail-only; filled by load_full_description
            publisher_name=SbazarScraper._publisher_name(row),
        )

    @staticmethod
    def _format_price(row: dict[str, Any]) -> str:
        """MUST branch on the boolean, never on `price == 0`. See spec §6.1."""
        if row.get("price_by_agreement"):
            return "Dohodou"
        return f"{row.get('price', 0)} Kč"

    @staticmethod
    def _format_location(row: dict[str, Any]) -> str:
        """`municipality` is empty in ~5% of rows; district/region never are."""
        loc = row.get("locality") or {}
        parts = [loc.get("municipality"), loc.get("district"), loc.get("region")]
        return ", ".join(p for p in parts if p)[:128]

    @staticmethod
    def _publisher_name(row: dict[str, Any]) -> str:
        """`shop_url`, NOT `shop_name` — shop_name is the seller's real full name. §6.4."""
        user_service = (row.get("user") or {}).get("user_service") or {}
        return (user_service.get("shop_url") or "")[:100]

    @staticmethod
    def _parse_date(value: str | None):
        """`create_date` is naive local time, e.g. '2026-08-22T17:16:53'. USE_TZ is True."""
        if not value:
            return None
        try:
            parsed = timezone.datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Sbazar: unparseable create_date %r", value)
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, PRAGUE)
        return parsed
```

---

### 3.2 Escape hatch — ONLY if the §1.5 Tor pre-flight failed

**If the pre-flight returned `200`, skip this section entirely and change nothing.**

If Tor is blocked, do **not** add retries, do **not** rotate IPs harder, and do **not** invent a
header workaround. Follow the precedent already in the codebase: `VintedScraper` accepts the
session for factory symmetry and deliberately ignores it. Mirror that, and say why in the
docstring:

```python
class SbazarScraper:
    """...

    Deliberately ignores the `session` the runner passes in: that session is
    Tor-proxied (ip_changer/tor.py), and Sbazar's API returned <STATUS> through Tor
    on <DATE> while serving a direct connection normally. Sbazar requests therefore
    egress from the host's real IP, as VintedScraper does for the analogous reason.
    """
    marketplace = Marketplace.SBAZAR.value

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session                 # accepted for symmetry, intentionally unused
        self._own_session = requests.Session()  # direct, un-proxied
```

and use `self._own_session` in `_get`. **Fill in `<STATUS>` and `<DATE>` with what you actually
measured** — do not write a rationale you did not observe.

Then record the finding in `../../research/marketplaces/SBAZAR.md` §9 and flag it to the project owner: a
marketplace that cannot use the shared rotation stack is an operational fact worth knowing, not an
implementation detail to bury.

---

## 4. Step 3 — register the scraper

`bazos/scraping/bazos_query_runner.py`, in `_build_scrapers` — add **one line** and its import:

```python
from bazos.scraping.sbazar.sbazar_scraper import SbazarScraper
...
def _build_scrapers(session: requests.Session) -> dict[str, MarketplaceScraper]:
    return {
        Marketplace.BAZOS.value:     BazosScraper(session),
        Marketplace.BAZOS_API.value: BazosApiScraper(session),
        Marketplace.VINTED.value:    VintedScraper(session),
        Marketplace.SBAZAR.value:    SbazarScraper(session),   # <-- add
    }
```

**Do not special-case Sbazar anywhere in `BazosRunner` or `BazosQueryRunner`.** That is the whole
point of the protocol (see `CLAUDE.md`, "Adding a marketplace").

---

## 5. Step 4 — how a `Query` is configured

Sbazar searches by **`category_id`**, which the existing `Query` model has no column for. Use
`Query.extra_params` (a `JSONField`, already built for exactly this):

```python
Query.objects.create(
    marketplace=Marketplace.SBAZAR.value,
    text="",                                # optional; maps to `phrase`
    extra_params={"category_id": 22},       # 22 = stavebnictvi-naradi (tools)
    ...
)
```

Useful measured category ids: `22` tools (26,738 active), `143` notebooks (4,401),
`237` iPhone (2,282), `48` other mobiles (1,801), `437` bikes/scooters (2,659).

⚠️ **`Query.section` and `Query.category` are Bazos taxonomy FKs. Leave them null for Sbazar.**
There is a DB constraint that `section` and `category` are mutually exclusive; setting neither is
fine.

---

## 6. ⚠️ The four traps — read before writing code

These are measured bugs, not hypotheticals. Each one is silent.

### 6.1 "Price by agreement" — the one that breaks filtering
Sbazar encodes a negotiable price as **`price: 0` plus `price_by_agreement: true`**.

- `parse_price("0 Kč")` returns **`0`**, not `None`. `PriceRangeRule` would then compare `0`
  against the query's range and **reject every negotiable ad**.
- Emitting the literal string `"Dohodou"` makes `parse_price` return `None`, which is the
  documented "no parseable price" path that makes `PriceRangeRule` **PASS**. That is why
  `_format_price` returns that exact word.
- ⚠️ **`price == 0` does NOT imply by-agreement.** Re-measured 2026-08-23 over **4,000 rows**
  across categories 22/143/237/437 (`PRICE_PARSING.md` §6):

  | | Count |
  |---|---|
  | `price_by_agreement: true` | 192 (4.8%) |
  | `price == 0` | 225 |
  | → of those, by-agreement | 192 |
  | → **genuine free giveaways** | **33 (0.8%)** |
  | **by-agreement with a NON-zero price** | **0** |

  So the implication runs **one way only**: by-agreement always means `price == 0`, but `price == 0`
  means free **33 times in 4,000**. **Branch on the boolean. Never on the integer.** Branching on
  the integer converts 33 giveaways into "Dohodou" and, worse, `str(0)` → `parse_price` → `0`
  (not `None`), which makes `PriceRangeRule` **reject every negotiable ad**.

### 6.2 `short_description` overflows its column
`description` is **absent from every listing row** and only present on detail. Measured lengths:
**679**, 241, and **0** characters. The column is `CharField(max_length=300)`.
**Postgres raises `DataError`; SQLite does not — so the test suite will not catch this.** Always
slice `[:300]`.

> **⚠️ Both halves of that reasoning have since changed, 2026-09-18.** `Ad.short_description` is
> now a `TextField` (migration `0035`), so there is no column bound left to overflow, and the
> suite now runs on real Postgres rather than SQLite, so a width violation would be caught. The
> `[:300]` slice is still in the code and is fine to keep, but keep it as a deliberate choice
> about how much snippet to store, not as the guard this section describes. Note the widening
> went the other way for Bazos on purpose: truncating `short_description` silently stops
> `filter_blocklist`/`filter_required` phrases in the cut tail from matching.

Consequence to be aware of, not to fix here: `load_full_description` only runs when
`query.load_full_description` is set, so otherwise `short_description` stays `""` and the
`blocklist_keyword` / `required_keyword` rules (which match on
`f"{ad.name} {ad.short_description}"`) are weakened to title-only matching.

### 6.3 Price is an integer — do **not** copy Vinted's decimal handling
Sbazar's `price` is a plain **int in whole CZK** — **4,000/4,000 rows sampled, zero floats**
(`PRICE_PARSING.md` §6). Do not round, do not divide, do not format with decimals.
Range measured: min 0, median 1,599, max exactly 1,000,000. There is **no `currency` field** —
CZK is implied.

Neighbouring marketplaces have *different* traps and you must not cross-contaminate them
(all measured, `PRICE_PARSING.md` §2):
- **Vinted** returns floats and **72% are non-integer** — `"9902.82"` → `990282`, **100× too
  large**. The error is 10^(decimal places), not a flat 10×.
- **Aukro** returns `int` *or* `float` **unstably within one response** (`2` and `2.0` side by
  side) — so its corruption is intermittent, which is worse than consistent.
- **Zboží** returns hundredths (`292000` = 2,920 Kč).
- **Sbazar returns none of these.** `11990` means 11,990 Kč. Write no conversion at all.

### 6.4 Do not store the seller's real name
`user.user_service.shop_name` is the seller's **real full name** — personal data, and a GDPR cost
the Bazos setup deliberately avoids by only ever seeing opaque ids.
**Map `publisher_name` from `shop_url`** (an opaque handle, max 32 chars, never empty).

---

## 7. Tests

Create `bazos/tests/test_sbazar_scraper.py`. **Use recorded fixture JSON — do not hit the network
in tests.** Mirror the style of the existing Vinted tests.

Minimum cases, one per trap:

1. `_format_price({"price": 11990, "price_by_agreement": False})` == `"11990 Kč"`
2. `_format_price({"price": 0, "price_by_agreement": True})` == `"Dohodou"`, **and**
   `parse_price(...)` on that returns `None`
3. `_format_price({"price": 0, "price_by_agreement": False})` == `"0 Kč"`
   *(the giveaway case — must NOT become "Dohodou")*
4. `_format_location` with `municipality: ""` yields `"Náchod, Královéhradecký kraj"`
   *(no leading comma)*
5. `load_full_description` truncates a 679-char description to exactly 300 in
   `short_description` while `full_description` keeps all 679
6. `load_full_description` returns the ad unchanged and **raises nothing** when the HTTP call
   fails *(mock `session.get` to raise `requests.RequestException`)*
7. `_map_item` sets `view_count is None` and `publish_date` is timezone-aware
8. `_map_item` uses `shop_url`, and the resulting `publisher_name` does **not** contain the value
   of `shop_name`
9. `Query(marketplace="sbazar", extra_params={"category_id": 143}).url` starts with
   `https://www.sbazar.cz` — **not** `BAZOS_BASE_URL` (§2.3). Assert the Bazos and Vinted branches
   still return what they did before.

Then run, and all three must pass:
```bash
pytest bazos/tests/test_sbazar_scraper.py
ruff check .
mypy .
```

---

## 8. Manual verification before you call it done

```bash
python manage.py shell -c "
import requests
from bazos.scraping.sbazar.sbazar_scraper import SbazarScraper
from bazos.models import Query, Marketplace
q = Query(marketplace=Marketplace.SBAZAR.value, text='', extra_params={'category_id': 143})
ads = list(SbazarScraper(requests.Session()).run_query(q))[:5]
for a in ads:
    print(a.external_id, '|', a.price_raw, '|', a.name[:40], '|', a.location, '|', a.publish_date)
"
```

Expect: 5 rows, integer ids around 233,000,000, prices like `11990 Kč` (or `Dohodou`), a composed
location with no leading comma, and timezone-aware dates. **If `publish_date` prints `None` for
every row, `create_date` is missing from the listing payload — stop and report it**, do not
synthesise a value (`Ad.publish_date`'s help_text forbids it).

---

## 9. Explicitly out of scope

Do **not** do these in this stage, even if they seem natural:

- Any `Ad` column change, or any migration beyond §2.2's choice-list one.
- A seller/reputation model. Sbazar exposes **no ratings** (measured) — there is nothing to store.
- Anything touching Bazos, Vinted, the filter rules, the sender, or `parse_price` itself.
  **The one exception is §2.3's `Query.url` branch**, which is additive and must not change the
  Vinted or Bazos branches.
- HTML scraping, consent-cookie handling, or anything involving `cmp.seznam.cz`.
- Realised prices — Sbazar has none. That is Aukro (`../../research/marketplaces/AUKRO.md`).
- `user_id` / `users/public` endpoints — those paths were **NOT verified live**
  (`../../research/marketplaces/SBAZAR.md` §4.2) and must be probed before use.

---

## 10. Known unknowns you should not paper over

**Two unknowns, and neither should be papered over.**

**(a) Sbazar over Tor is unmeasured.** See §1.5 — this is the one that can change the design, and
it is a one-minute check. Whatever you find, write the status codes into `../../research/marketplaces/SBAZAR.md` §9 so the
next person inherits a measurement instead of this same gap.

**(b) Sbazar's ToS have never been read** (`RECOMMENDATION.md` §5). `robots.txt` is
`User-agent: * / Disallow: /` and separately `Disallow: /api/`. The project owner has stated the
posture is private, non-commercial, research-only use and has accepted that. **Do not add
commentary about it in code comments** — it is recorded in the research docs. Just build what is
specified.

---

## 11. Post-implementation fix — the dedup break assumed the wrong sort key

**Added after a code review of the first implementation caught this. It is a correctness bug, not
a style note, and it was not caught by any check in §7 — `ruff`/`mypy`/`pytest` all passed with it
in place.**

`BazosQueryRunner.run_existing_query` walks newest→oldest and stops at the first already-known,
non-topped ad, on the assumption that everything below it must be older and therefore already
seen. That assumption requires the scraper's default ordering to be by **creation** time. It is
true for Bazos and Vinted. **It is not true for Sbazar** — §1's own rule says "Newest-first is the
DEFAULT," which is correct but incomplete: newest by `sorting_date` (≈ edit time), not by
`create_date` (§5b.4 of `../../research/marketplaces/SBAZAR.md`). An already-known ad that was merely edited can resurface
above genuinely new listings created earlier in that poll's window. §2.1 of `../../research/marketplaces/SBAZAR.md` quantifies
how often: on `category_id=22`, of 666 organic rows in a 35.1h window, only 204 had a `create_date`
inside that same window — most of what sorts near the top at any moment is edit noise, not new
listings. The old break-on-first-hit logic would stop at the first such edit-bumped ad and never
see the new listings sitting below it, silently, every pass.

**The fix, generalised rather than special-cased:** `run_existing_query` now breaks after
`scraper.dedup_break_streak` **consecutive** already-known, non-topped ads, not after one. The
attribute is read via `getattr(self.scraper, "dedup_break_streak", 1)` — **not** a
`MarketplaceScraper` Protocol member, so `BazosScraper`/`BazosApiScraper`/`VintedScraper` needed no
changes and keep their exact prior behaviour (default 1 = break on the first hit). `SbazarScraper`
sets `dedup_break_streak = SBAZAR_DEDUP_BREAK_STREAK` (`bazos/const.py`, currently `40`) so the walk
tolerates a run of edit-bumped known ads instead of giving up on the first one. See that constant's
comment for how `40` was derived — **it is an estimate from `../../research/marketplaces/SBAZAR.md` §2.1's bump rate, not a
measured value like everything else in this spec**, and should be revisited from `QueryRun`
(`rows_seen_counter` vs `new_ads_count`) once a real Sbazar `Query` has run in production. Whatever
the streak, the walk is still bounded by `SBAZAR_MAX_PAGES` — a mis-tuned streak costs extra
requests, not an unbounded walk.

**Left deliberately unfixed, same root cause, lower severity:** `run_new_query`'s `new_query` backfill
takes the first `NEW_PRODUCT_LOAD_MAX` non-topped ads `run_query` yields, which for Sbazar is the
50 most-recently-*edited*, not the 50 most-recently-*created*. For the common case
(`ignore_first_run=True`, the default), this only affects which ads seed the "already known"
baseline — nothing is delivered from that first pass either way, and anything left out of the
baseline simply surfaces as "new" on the next `run_existing_query` pass, which now has the fix
above. It only matters when `ignore_first_run=False`, where it can affect which ads the first batch
of real notifications covers. Not fixed here because it would mean materialising and re-sorting the
first run's results by `publish_date` before truncating to the limit — a bigger change than this
fix, and arguably its own spec.
