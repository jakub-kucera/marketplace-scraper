---
title: Price parsing — measured research for P22
status: reference
updated: 2026-08-23
verified: 2026-08-23
shipped_in: 0032, 0033 (P22 was built from this)
---

# Price parsing — measured research for P22

> Written 2026-08-23. Grounds [`PROMPTS.md`](../backlog/PROMPTS.md) **P22** (`price_raw` → real integer +
> `price_type`) in measurement rather than assumption. **All four marketplaces were sampled live**
> — Bazos HTML corpus, Bazos API, Vinted, Sbazar, Aukro.
>
> ⚠️ **This document corrects an earlier version of itself.** The first draft measured only the
> Bazos HTML corpus and reported "48.8% of ads have no numeric price" as a headline. That number is
> real but **it is an artifact of one query dominating the corpus** — see §3.2. The corrected
> figure for the goods categories this project actually targets is **0–9%**.

## 1. The state this research was written against — ✅ since fixed

> **This section is historical.** P22 shipped on 2026-08-23 (migrations `0032`/`0033`), built
> from the measurements below. Everything from §2 onward is still current — it describes the
> *marketplaces*, not the schema, and the field mappings and traps are what a new scraper needs.
> Only this section went stale.

**What it looked like before P22:**

- `Ad.price_raw` was `CharField(max_length=30)` — display strings only: `"12 500 Kč"`, `"Dohodou"`.
- `parse_price` ran at *filter* time and the result was **discarded**. Nothing numeric persisted.
- `PriceChange.old_price`/`new_price` were `CharField(30)` too — price history was strings.

No median, percentile, index or margin arithmetic was possible on any price in the database.

**What exists now:**

- **`Ad.price`** — `BigIntegerField(null=True, blank=True, db_index=True)`, the parsed CZK amount.
  `BigInteger` per §9's correction, not `Integer`.
- **`Ad.price_type`** — a `PriceType` enum. Two values carry a real `Ad.price`: `EXACT` and
  **`FREE`** (a known zero — "Zdarma" — which §3.3 showed the old parser wrongly returned `None`
  for). The placeholder values (`NEGOTIATED`, `IN_TEXT`, `MAKE_OFFER`, `UNKNOWN`) leave `price`
  null.
- **`PriceChange.old_price_amount`/`new_price_amount`** — numeric price history alongside the
  original strings.
- **`parse_price_and_type()`** in `bazos/filters.py` does the work at *scrape* time and persists
  the result, per §9.1's "normalise at the scraper, not the parser" conclusion. `parse_price` is
  kept as a thin wrapper for callers that only need the amount.

`PriceRangeRule` now reads `ad.price` directly instead of re-parsing `price_raw` on every filter
pass. **`PROMPTS.md` P23 (`PriceAnomalyRule`) is unblocked** — it was the reason this research was
commissioned.

## 2. Summary — four marketplaces, four representations, three different meanings of zero

| Marketplace | `price` wire type | Non-integer? | Zero means | `parse_price` correct? |
|---|---|---|---|---|
| **Bazos (HTML)** | string `"12 500 Kč"` | never | n/a (`Zdarma` = free) | ✅ **yes** |
| **Bazos (API)** | string `"15000"` / `"Dohodou"` | never | n/a | ⚠️ works, but `price_type` is better |
| **Vinted** | **float** `9902.82` | **72%** | n/a | ❌ **off by 10^dp** |
| **Sbazar** | **int** `11990` | never | **free** (33/4,000) *or* negotiable (192/4,000) | ❌ zero-semantics |
| **Aukro** | **int *or* float, unstably** | 0% (but `2` and `2.0` coexist) | **"not offered"** | ❌ **off by 10×** |

**The single most important conclusion:** `re.sub(r"\D","",…)` is correct for **Bazos only**, and
wrong in a *different* way for each of the other three. This is not fixable with a better regex.

## 3. Bazos — HTML corpus (16,981 rows, 2024 export)

### 3.1 The five placeholders are exhaustive

| Value | Rows | Meaning | Bazos API `price_type` (§4) |
|---|---|---|---|
| `Dohodou` | 4,222 | "by agreement" | `NEGOTIATED` |
| `V textu` | 3,756 | "in the text" | `IN_TEXT` |
| `Nabídněte` | 197 | "make an offer" | `OFFERED` |
| **`Nerozhoduje`** | **93** | **"doesn't matter"** | ⚠️ **NOT OBSERVED** |
| `Zdarma` | 14 | "free" | ⚠️ **NOT OBSERVED** |

No long tail — these five account for every non-numeric value in the corpus.

### 3.2 ⚠️ The "48.8% have no price" figure is a job-ads artifact — corrected

Overall the corpus is 48.8% non-numeric. **Broken down by query, that collapses:**

| query | section | ads | no price | % |
|---|---|---|---|---|
| **3** | **`Práce` (jobs)** | **14,107** | **8,280** | **58.7%** |
| 11 | `macbook` | 1,257 | 0 | **0.0%** |
| 10 | `apple watch` | 521 | 0 | **0.0%** |
| 8 | `threadripper OR ryzen` | 77 | 0 | **0.0%** |
| 5 | `RTX 3090` | 61 | 0 | **0.0%** |
| 2 | `herman miller` | 80 | 2 | 2.5% |

**One query — section `Práce` — is 83% of the corpus and 99.98% of all placeholders.** Job ads put
the salary in the text, so `V textu`/`Dohodou` is the norm there. Every consumer-goods query is
**0.0%**. A live Bazos API sample across `notebook`/`naradi`/`kolo`/`auto` (839 ads, §4) measured
**9.2%**.

Note `MONETIZATION.md` §4.7 already killed `Práce` as a target on volume grounds — so the section
that produces almost all the placeholder noise is one the project does not care about.

**For planning P23: expect 0–10% null `price` in goods categories, not ~49%.** The earlier headline
would have led to over-engineered null handling and badly pessimistic sample-size thresholds.
*(This is the same "check the breakdown before believing a total" failure the marketplace study
recorded for Annonce — `marketplaces/RECOMMENDATION.md` §6.4.)*

### 3.3 `Zdarma` means 0, and the current parser returns `None`

`parse_price("Zdarma") -> None` today. "Free" is a **known** price of zero, not an unknown one, so a
free item is currently indistinguishable from `Dohodou` and `PriceRangeRule` passes it rather than
evaluating it. **P22 must emit `price=0, price_type=FREE`.**

### 3.4 Numeric grammar — one shape, no decimals

10 shapes, all `<space-separated digits> Kč`. Character census over the whole corpus:
- Separator is **ASCII `U+0020`**, *not* a non-breaking space.
- **No `.` or `,` anywhere.** Bazos prices are always whole numbers.
- `Kč` is the only currency token. Max length **16** vs a 30-char column.

### 3.5 Range and junk

min **1** · median **25,490** · max **1,111,111,111** · exceeding int32: **0**

Top values are junk (`1 111 111 111`, `1 000 000 000`). Two consequences:
1. `IntegerField` fits *today* with ~2× headroom, but the observed shape `9 999 999 999 Kč` permits
   10 digits (up to ~10^10), which **would** overflow int32. **Use `BigIntegerField`** — same class
   as the Vinted `external_id` overflow (`VINTED_SCRAPER.md` §2.1), which also fit until it
   didn't and **passes on SQLite while raising on Postgres**.
2. P23 must trim outliers before any mean or high percentile.

## 4. Bazos API — `price_type` mapping, measured live 2026-08-23

The API is strictly better than string-parsing, and the mapping is now confirmed:

| `price_formatted` | detail `price` | detail `price_type` |
|---|---|---|
| `15 000 Kč` | `"15000"` | **`EXACT`** |
| `Nabídněte` | `"Nabídněte"` | **`OFFERED`** |
| `Dohodou` | `"Dohodou"` | **`NEGOTIATED`** |
| `V textu` | `"V textu"` | **`IN_TEXT`** |

```bash
UA='bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0'
curl -s -A "$UA" 'https://www.bazos.cz/api/v1/ad-detail-2.php?ad_id=222703761'
#  -> "price":"Dohodou","price_type":"NEGOTIATED","currency":"CZK","price_formatted":"Dohodou"
```

Three things that matter:
- ⚠️ **`price` is a STRING even in the API, and it echoes the placeholder** rather than being null.
  You must branch on `price_type`, not attempt `int(price)`.
- ⚠️ **Bazos's enum names differ from P22's proposed names**: `OFFERED` vs `MAKE_OFFER`,
  `NEGOTIATED` vs `NEGOTIABLE`. Pick one vocabulary and map explicitly at the boundary.
- `price_type` is **detail-only** (`ad-detail-2.php`); the listing endpoint carries only
  `price_formatted`. So the API's structured price costs one call per ad unless parsed from the
  listing string.
- ⚠️ **`Zdarma` and `Nerozhoduje` were NOT observed** in the API sample, so their `price_type`
  values are unknown. Two ad ids would settle it.

Live listing sample (839 ads over `notebook`/`naradi`/`kolo`/`auto`): 9.2% non-numeric —
`V textu` 64, `Dohodou` 12, `Nabídněte` 1. Same grammar as HTML, ASCII space, `Kč` only.

## 5. Vinted — measured live 2026-08-23 (`vinted-scraper` 4.0.0, throwaway venv)

96 items, `search_text=notebook`, `order=newest_first`:

| Property | Measured |
|---|---|
| `price` type | **`float` in 96/96** |
| **non-integer values** | **69/96 = 72%** |
| currency | `CZK` in 96/96 |
| null prices | 0 |

Examples: `9902.82`, `141.47`, `848.81`, `85.0`, `250.0`.

⚠️ **The error is 10^(decimal places), not a flat 10×.** `VINTED_SCRAPER.md` §4.5 cites
`"6307.5"` → `63075` (10×), but two-decimal values are the common case:
**`"9902.82"` → `990282` — 100× too large.**

`total_item_price` is always ≥ `price` (buyer-protection fee): measured `9902.82` → `10415.96`.
`VintedScraper._format_price` already does `round(amount)` **in the scraper**, so the decimal never
reaches the database. **That is the correct pattern and this document generalises it (§7).**

⚠️ **Vinted CZK figures are FX-converted from PLN** (`VINTED_SCRAPER.md` §4.5), so they drift
with the exchange rate — see §8.

## 6. Sbazar — measured live 2026-08-23 (4,000 rows, 4 categories)

Categories `22` (tools), `143` (notebooks), `237` (iPhone), `437` (bikes), `limit=1000` each:

| Property | Measured |
|---|---|
| `price` type | **`int` in 4,000/4,000.** Never float. |
| `price_by_agreement: true` | 192 (4.8%) |
| `price == 0` | 225 |
| → of those, by-agreement | 192 |
| → **genuine free giveaways** | **33 (0.8%)** |
| **by-agreement with a non-zero price** | **0** |
| min / median / max | 0 / 1,599 / **1,000,000** |
| currency field | **none** — implied CZK |
| exceeds int32 | 0 |

**The rule, now measured on 4× more data than the Sbazar spec's original 1,000-row sample:**
`price_by_agreement == true` **always** implies `price == 0` (0 counter-examples), but the converse
fails 33 times. So:

- `price_by_agreement` ⇒ `NEGOTIABLE`, `price = None`
- `price == 0` **and not** by-agreement ⇒ **`FREE`, `price = 0`**
- **Never branch on `price == 0` alone** — it silently converts 33 giveaways into negotiables, and
  under the current parser `str(0)` → `parse_price` → `0` (not `None`), which would make
  `PriceRangeRule` **reject every negotiable ad**.

Max is exactly `1,000,000` across 4,000 rows — almost certainly a UI cap, ⚠️ not confirmed.

## 7. Aukro — measured live 2026-08-23 (60 rows + 21 detail probes)

| Property | Measured |
|---|---|
| `price.amount` type | ⚠️ **`int` 29 / `float` 31 — in the SAME response** |
| non-integer *values* | 0/60 (all whole numbers) |
| `buyNowPrice.amount` type | `float` 60/60 |
| `buyNowPrice == 0` | **59/60 — means "no buy-now offered", NOT free** |
| currency | `CZK` 60/60 |
| `price` on `BUYNOW` items | **`null`** (detail probes) |

⚠️ **The JSON type is unstable per row.** `2` and `2.0` appear side by side in one payload for the
same logical value. So "Aukro is always float" is **wrong** — it is *sometimes* float,
unpredictably, which means the corruption is intermittent:
`str(2)` → `"2"` → **2** ✅ but `str(2.0)` → `"2.0"` → **20** ❌.
An intermittent 10× error is considerably worse than a consistent one, because it survives spot
checks. Detail probes independently returned `861.0` and `3126.0`.

**Aukro has two prices whose meaning depends on `itemType`** (`BIDDING` / `BUYNOW`), and `price` is
`null` on buy-now items. A single `CharField(30)` cannot express this. **P22 is a hard prerequisite
for Aukro** (`marketplaces/AUKRO.md` §5b.3).

## 8. Cross-marketplace comparability ⚠️

Once `price` is numeric it becomes tempting to compare across marketplaces. Measured reasons not
to, without an explicit decision:

- **Vinted is FX-converted from PLN** — its CZK values move with the exchange rate.
- **Vinted's `total_item_price` includes buyer protection** while Bazos/Sbazar are seller-asking
  prices (measured `9902.82` vs `10415.96` on one item).
- **Aukro auction `price` is a current bid, not an asking price** — it rises over an auction's life
  and only becomes meaningful at `endingTime`.

A median over mixed marketplaces is **not** like-for-like. Scope P23's baseline by marketplace, or
state the assumption explicitly.

## 9. Recommended shape for P22

```python
class PriceType(models.TextChoices):
    EXACT       = "exact",       "Exact"
    NEGOTIABLE  = "negotiable",  "Dohodou / by agreement"   # Bazos API: NEGOTIATED
    IN_TEXT     = "in_text",     "V textu"                  # Bazos API: IN_TEXT
    MAKE_OFFER  = "make_offer",  "Nabídněte"                # Bazos API: OFFERED
    INDIFFERENT = "indifferent", "Nerozhoduje"              # ADD — missing from P22
    FREE        = "free",        "Zdarma / giveaway"        # price = 0, NOT None
    CURRENT_BID = "current_bid", "Auction current bid"      # ADD — Aukro; not an asking price
    UNKNOWN     = "unknown",     "Unknown"

price      = models.BigIntegerField(null=True, blank=True, db_index=True)   # §3.5
price_type = models.CharField(max_length=20, choices=PriceType.choices, default=PriceType.UNKNOWN)
```

Rules, each traceable to a measurement:
1. `Zdarma`, and Sbazar `price==0 && !by_agreement` ⇒ `price=0`, `FREE`. (§3.3, §6)
2. Sbazar `price_by_agreement` ⇒ `price=None`, `NEGOTIABLE`. **Never branch on `price==0`.** (§6)
3. Bazos placeholders ⇒ `price=None` + matching type; prefer the API's `price_type` when
   available, mapping its vocabulary explicitly. (§3.1, §4)
4. Digits present ⇒ strip ASCII spaces and ` Kč`, parse int, `EXACT`. (§3.4)
5. Unrecognised ⇒ `price=None`, `UNKNOWN`, **and log it** — it means a marketplace changed its
   vocabulary and this document no longer describes it.
6. `price=None` must keep the current PASS behaviour in `PriceRangeRule`/`PriceDropRule`.

### 9.1 The architectural conclusion — normalise at the scraper, not the parser

> A `MarketplaceScraper` knows its own price semantics. A downstream regex cannot recover them:
> the same digits mean different things on each site, **and three of the four sites encode "zero"
> differently** (Bazos `Zdarma` = free; Sbazar `0` = free *or* negotiable depending on a flag;
> Aukro `buyNowPrice: 0` = *not offered*).

Scrapers should emit `(amount: int | None, price_type)` directly; `price_raw` stays purely as the
human-readable audit trail. **`VintedScraper` already does this** (`round()` in the scraper) — that
is the pattern to generalise, not a Vinted quirk.

**Backfill:** `price_raw` is retained, so the migration is a pure re-derivation and is re-runnable.
On Bazos rows expect **~51% populated corpus-wide, but ~90–100% in goods categories** (§3.2) —
segment the check by query or it will look broken.

**`PriceChange.old_price`/`new_price`** need the same treatment in the same migration, or price
*history* stays unqueryable and `PriceDropRule` keeps re-parsing strings.

## 10. What is NOT measured

- **`price_type` for `Zdarma` and `Nerozhoduje`** on the Bazos API (§4). Two ad ids would settle it.
- **Whether Sbazar's 1,000,000 max is a real cap** or a sampling artifact (§6).
- **Aukro's `price` on ended vs live auctions** — whether an ended `BIDDING` `price` is always the
  winning bid. One sold example measured (`marketplaces/AUKRO.md` §9.7).
- **Per-category null rates** beyond the six queries in §3.2 and four categories in §6.
- **Vinted's non-CZK domains** — only `vinted.cz` was sampled; other `base_url`s may differ.

## 11. Reproduction

```bash
# §3 — Bazos HTML corpus
python3 -c "import csv,re,collections; csv.field_size_limit(10**9); \
rows=[(r['query_id'],r['price_raw']) for r in csv.DictReader(open('data_export_23_3_2024/bazos_ad.csv',encoding='utf-8-sig',newline=''),delimiter=';')]; \
print(collections.Counter(p for q,p in rows if not re.search(r'\d',p)).most_common())"

# §4 — Bazos API price_type
UA='bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0'
curl -s -A "$UA" 'https://www.bazos.cz/api/v1/ads.php?query=notebook&sort=date&limit=210'
curl -s -A "$UA" 'https://www.bazos.cz/api/v1/ad-detail-2.php?ad_id=222703761'

# §5 — Vinted (throwaway venv; brief §4d: run the library, don't trust its README)
python3 -m venv vv && ./vv/bin/pip install -q vinted-scraper
./vv/bin/python -c "from vinted_scraper import VintedScraper; \
items=VintedScraper(baseurl='https://www.vinted.cz').search({'search_text':'notebook','order':'newest_first','per_page':96}); \
print([(i.price,i.total_item_price,i.currency) for i in items[:5]])"

# §6 — Sbazar
curl -s -H 'Accept: application/json' \
  'https://www.sbazar.cz/api/v1/items/search?category_id=22&limit=1000' | \
  python3 -c "import json,sys,collections; r=json.load(sys.stdin)['results']; \
print(collections.Counter((type(x['price']).__name__, bool(x['price_by_agreement'])) for x in r))"

# §7 — Aukro
curl -s -H 'Content-Type: application/json' -H 'X-Accept-Subbrand: BAZAAR' \
  -X POST 'https://aukro.cz/backend-web/api/offers/searchItemsCommon?page=0&size=60' \
  -d '{"categorySeoUrl":"pocitace-a-hry","subbrandExclusive":false}' | \
  python3 -c "import json,sys,collections; r=json.load(sys.stdin)['content']; \
print(collections.Counter(type(x['price']['amount']).__name__ for x in r))"
```
