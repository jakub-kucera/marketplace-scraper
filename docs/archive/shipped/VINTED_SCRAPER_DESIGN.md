---
title: Stage 8 Design Notes — VintedScraper & Multi-Marketplace Queries
status: shipped
updated: 2026-09-18
verified: 2026-09-18
shipped_in: 0029
---

# Stage 8 Design Notes — VintedScraper & Multi-Marketplace Queries

> **✅ Built 2026-08-22** (migration `0029`) — this is the design that preceded it, kept for the
> decision log. The executable version is [VINTED_SCRAPER.md](VINTED_SCRAPER.md);
> the stage entry is [PIPELINE_REFACTOR.md](PIPELINE_REFACTOR.md) Stage 8.
>
> **⛔ Correction, audited 2026-09-18: §1a is NOT the durable part any more, and must not be
> checked against the code.** The `vinted-scraper` library whose `VintedItem` model §1a
> enumerates is gone from `pyproject.toml`; Vinted withdrew the anonymous
> `/api/v2/catalog/items` endpoint around 2026-09-08 and the scraper was rebuilt on the catalog
> page's Next.js RSC payload (commit `4cf35ec`, 2026-09-16), which names every field
> differently. The live field list is
> [`VINTED.md`](../../research/marketplaces/VINTED.md), measured 2026-09-16.
>
> §1c's `total_item_price` recommendation was also **reversed**: the code stores `price`
> (ex-fee), because Vinted's own `price_from`/`price_to` filter keys on `price` and storing the
> all-in figure made bounded queries return rows the `price_range` rule then rejected.
>
> What survives as the durable part is **§3 to §5**: the `Query` model analysis and the Option C
> decision. `extra_params` is still how a Vinted query is configured, and §3's
> "a separate `VintedCategory` model would be needed" has since shipped as the
> marketplace-agnostic `MarketplaceCategory` (migration `0043`).

> **⚠️ §1 and §2 rewritten from a live probe, 2026-08-21.** Everything in those two sections
> was previously *asserted from the package README, never run*. It has now been measured
> against `vinted.cz` with `vinted-scraper` **4.0.0**, and **four of the original claims were
> wrong** — including the one the whole design rested on ("description is already in search
> results, so `load_full_description` is a no-op"). It is not. Details inline below; the
> superseded claims are struck through rather than deleted so the delta is visible.
>
> §3–§5 (the `Query` model analysis and the Option C decision) were **not** affected by the
> probe and stand unchanged.

---

## 1. Library choice

**Package**: [`vinted-scraper`](https://pypi.org/project/vinted-scraper/) by Giglium
**Version**: **`4.0.0`** — ~~`3.1.1`~~. 4.0.0 is current as of 2026-08-21 and is what the probe
below used. A `^3.1.1` constraint in `pyproject.toml` would resolve to `3.1.x` and **not** get
this API — pin `^4.0.0`.
**Transport**: **`httpx`**, not `requests`. This is a new dependency for this repo and it is
also the concrete reason the library cannot accept the Tor session (see §2).

```python
from vinted_scraper import VintedScraper

scraper = VintedScraper("https://www.vinted.cz")
items = scraper.search({"search_text": "macbook", "order": "newest_first", "per_page": 96})
# → List[VintedItem]     ✅ confirmed live
```

The library manages session cookies automatically. No BeautifulSoup — the API returns JSON.
`VintedWrapper` is the same API returning raw `dict`s instead of typed models; `VintedScraper`
(typed) is the one to use. `AsyncVintedScraper` exists if concurrency is ever wanted
(`BACKLOG_IDEAS.md` #2).

### 1a. Measured `VintedItem` fields — search endpoint (probed 2026-08-21)

`search()` returns 28 attributes. These are the ones that matter, with **real values** from
`{"search_text": "macbook"}` against `vinted.cz`:

| `VintedItem` field | Example value | maps to `Ad` field |
|---|---|---|
| `id` | `9561743808` | `external_id` |
| `title` | `'Apple MacBook Pro 15” (2016) \| 16 GB RAM…'` | `name` |
| `price` | `5990.0` (float — the model flattens the raw `{"amount","currency_code"}` dict) | `price_raw` (format as string) |
| `currency` | `'CZK'` | — (used for formatting) |
| `total_item_price` | `6307.5` | ⚠️ see §1c — this is what a buyer actually pays |
| `service_fee` | `317.5` | — |
| `url` | full absolute URL | `url` |
| `promoted` | `True` / `False` | **`topped`** ✅ — the concept exists after all |
| `status` | `'Velmi dobrý'` | item condition — no `Ad` column today |
| `brand_title` | `'Apple'` | — |
| `favourite_count` | `90` | — (closest thing to interest signal) |
| `photo` / `photos` | dict / list, incl. `url` + `thumbnails[]` | thumbnail is **free here** — relevant to P16 |
| `user` | `VintedUser(id, login, business, profile_url, photo)` | see §1d |
| `description` | **`None`** | ⚠️ **not populated in search** — see §1b |
| `view_count` | **`0` on every row** | `view_count` — present but always zero, treat as unavailable |
| — | **no date field of any kind** in the payload | `publish_date` — genuinely unavailable ⚠️ |

~~`description` maps to `short_description` from search results.~~ It does not.

### 1b. ⚠️ `load_full_description` is NOT a no-op — the original design's central error

The doc previously said the description "is already in search results", making
`load_full_description` a no-op. **Measured: `description` is `None` on every search result.**

A detail call `scraper.item(str(item_id))` does return a description — but it is scraping
**OpenGraph meta tags off the item page**, not an API, and it is **unreliable**:

```
probed 8 consecutive item() calls on live ids:
  description present on 5/8
  the other 3 returned literally {'id'} — no exception, no error, just nothing
```

Consequences for the implementation:

1. `load_full_description` must actually make a request (one per ad), so the Vinted path costs
   the same as the Bazos HTML path, not zero.
2. It must **tolerate a missing description silently** — a `{'id'}`-only response is normal,
   not an error. Do not raise, do not retry in a loop.
3. `Ad.short_description` will be **empty for every Vinted ad**, since the only description
   source is the detail call and that text belongs in `full_description`. This matters because
   `BlocklistKeywordRule` / `RequiredKeywordRule` match on
   `f"{ad.name} {ad.short_description}"` — **on Vinted they effectively match on the title
   alone.** Given §1e below, that is a real filtering weakness, not a cosmetic one.

### 1c. ⚠️ Cross-border results and converted prices — unanticipated, and it matters

A `macbook` search on **`vinted.cz`** returns mostly **Polish** listings with prices converted
into CZK. Measured, 5 of the first 6 newest results:

```
price=1385.41 CZK  conversion={'seller_price': '245.0', 'seller_currency': 'PLN',
                               'buyer_currency': 'CZK', 'fx_rounded_rate': '5.65',
                               'fx_markup_rate': '0.012'}
```

Three implications the design never considered:

- **Prices are non-round floats** (`1385.41`), because they are FX conversions. `Ad.price_raw`
  is a `CharField(max_length=30)`, so formatting must be decided explicitly, and P22's
  integer-price work has to cope with a decimal source on this marketplace.
- **`price` excludes buyer protection; `total_item_price` includes it** (5990.0 vs 6307.5, ~5%).
  For a deal-hunting use case `total_item_price` is the honest number. **Decide deliberately.**
- **The item may ship from another country.** Distance/travel-cost scoring
  (`BACKLOG_IDEAS.md` #10) is meaningless here, which that idea already anticipated
  ("gate the rule on `marketplace`") — this is the live confirmation.

### 1d. Seller identity is *better* than Bazos, not absent

The original table said publisher info is "not available". Measured: every item carries
`user` → `VintedUser(id=199717601, login='kristyna_cerhova', business=False, profile_url=...)`.

That is a **stable, non-opaque seller id plus a business/dealer flag** — strictly better than
Bazos's opaque `email_id`/`phone_id` pairing, and it makes `SellerAdCounts`-style analysis
trivial on this marketplace. There is still no email/phone, so
`EmailPublisher`/`PhonePublisher` stay `null` and `PublisherBlocklistRule` cannot fire.

**Out of scope for the first implementation** — it needs a new model (`VintedSeller` or a
generic `Publisher`) and a decision about GDPR retention (`MONETIZATION.md` §6.1's retention
rule applies: `login` and `profile_url` are personal data). Record it, don't build it yet.

### 1e. Search relevance is loose

`{"search_text": "macbook"}` returned **`'Torebka Mango'`** (a Mango handbag) inside the first
6 newest results. Vinted's text match is much fuzzier than Bazos's. `RequiredKeywordRule` is
therefore close to mandatory on Vinted queries — note it in the admin `help_text` for
`extra_params`.

---

## 2. Behavioural differences from BazosScraper

Corrected against the probe. Changed rows are marked ⚠️.

| Concern | BazosScraper | VintedScraper |
|---|---|---|
| Transport | HTML + BeautifulSoup over `requests` | ⚠️ REST JSON via `vinted-scraper`, which uses **`httpx`** |
| Session management | Caller passes `requests.Session` | Library manages cookies internally |
| Tor / IP rotation | Required — Bazos bans IPs | **Must NOT use** — Vinted bans proxies/VPNs |
| `check_blacklisted()` | Real HTTP 403 probe | Always returns `False` (no equivalent) |
| `load_full_description()` | Fetches a second detail page | ⚠️ **Also fetches** — one `item()` call per ad, OpenGraph-scraped, **succeeds ~5/8 of the time**. Not a no-op. Two failure modes: a sparse `{'id'}` dict on 200, **and a raised `RuntimeError` on non-200** (sold/deleted listing). Both must be caught — see the spec §4.6. |
| Pagination | Manual URL construction, stop on empty page | ⚠️ `per_page`, **server-capped at 96** (asked 200, got 96) |
| Ordering | Newest-first by default | ⚠️ **Must pass `order: "newest_first"` explicitly** — default order is relevance, which silently breaks the dedup walk |
| Publisher tracking | `EmailPublisher` / `PhonePublisher` FKs | ⚠️ Both FKs `null`, but a real `user` object exists — see §1d |
| "topped" ads | `topped=True` if promoted | ⚠️ **`promoted` exists** and behaves the same way — maps directly to `topped` |
| Rate limiting | Bazos 403s a blocked IP | ⚠️ 6 rapid searches: **all 200, ~0.30s each, no 429.** No aggressive limiting observed at this volume |
| `publish_date` | parsed from listing | ⚠️ **No date field exists at all** — see the spec's NOT NULL handling |

### Tor implications

`BazosRunner` passes `self.ip_changer.session` into `BazosQueryRunner`, which forwards it to the
scraper. `VintedScraper` builds its own `httpx` client, so the passed `session` argument must be
ignored — meaning **Vinted requests egress from the host's real IP**, not through Tor. That is
intended (Vinted bans proxy traffic), but it should be a conscious decision, not an accident.

Note the class-name collision this creates: the library's class is *also* called
`VintedScraper`. Alias it on import — the spec mandates
`from vinted_scraper import VintedScraper as VintedApiClient`.

---

## 3. The Query model problem

### The core issue

A single `Query` row does not cleanly serve both marketplaces. Field-by-field breakdown:

| `Query` field | Bazos | Vinted |
|---|---|---|
| `text` | keyword search | `search_text` — **same** ✅ |
| `section` FK → `Section` | Bazos subdomain (`pc.bazos.cz`) | **no equivalent** |
| `category` FK → `Category` | Bazos category ID + URL slug | **completely different taxonomy** — Vinted uses `catalog_ids` integers |
| `price_lower` / `price_upper` | CZK price range | `price_from` / `price_to` — **same semantics** ✅ |
| `location_center` / `location_radius` | Bazos PSČ + km | Vinted search API **does not support location filtering** |
| `url` property | computed from `section`/`category` | needs to return `https://www.vinted.cz` |
| `load_full_description` | triggers second page fetch | meaningless for Vinted |

#### The category problem in detail

- **Bazos `Category`**: `bazos_id` integer + `url` slug + `Section` FK. Fully Bazos-specific.
- **Vinted categories**: `catalog_ids` (e.g. `1194`, `1206`...) — completely different integer IDs with no Section equivalent. A separate `VintedCategory` model would be needed for proper admin lookup, and would need to be seeded from Vinted's API.

---

## 4. Options considered

### Option A — Single model, nullable cross-marketplace fields *(simplest)*

Keep one `Query`. Accept that `section` / `category` are `null` for Vinted queries.
Add `vinted_catalog_ids = JSONField(default=list)` for Vinted category filtering.
`location_*` fields are silently ignored by `VintedScraper`.
`url` property returns `https://www.vinted.cz` when `marketplace="vinted"`.

**Pros**: No model restructure. One small migration.  
**Cons**: Admin shows half-empty fields for Vinted queries. Bazos-specific constraints look wrong for Vinted rows.

---

### Option B — Abstract base + per-marketplace subclasses *(cleanest OOP)*

Make `Query` an abstract base. Add `BazosQuery` and `VintedQuery` subclasses using Django multi-table inheritance.

**Pros**: Perfect separation, no nullable mismatches.  
**Cons**: Large refactor, breaks all existing FK relations to `Query`, breaks admin, breaks runner dispatch. Not worth it for two marketplaces.

---

### Option C — Single model + `extra_params` JSONField *(recommended)*

Keep one `Query` table. Add a single `extra_params = JSONField(default=dict)`.
Each scraper reads what it needs from it:

```python
# BazosScraper reads nothing from extra_params (uses section/category FKs as before)

# VintedScraper builds its search params:
params = {
    "search_text": query.text,
    "price_from": query.price_lower or None,
    "price_to": query.price_upper or None,
    **query.extra_params,   # e.g. {"catalog_ids": [1194], "order": "newest_first"}
}
```

`section` / `category` FKs stay Bazos-only; they are simply `null` for Vinted queries.
The existing constraint `not_section_or_not_category` already allows both to be `null`,
so Vinted queries satisfy it naturally without any constraint changes.

`url` property gains a short override:

```python
@property
def url(self):
    if self.marketplace == "vinted":
        return "https://www.vinted.cz"
    if self.section:
        return self.section.full_url
    elif self.category:
        return self.category.full_url
    return BAZOS_BASE_URL
```

**Pros**: One migration (add `extra_params` JSONField). No model restructure. Admin stays usable. `extra_params` maps directly to `vinted-scraper`'s search dict.  
**Cons**: `extra_params` is untyped — callers must know valid keys per marketplace. Document in admin help_text.

---

## 5. Decision

**Proceed with Option C.**

Migration adds `extra_params = JSONField(default=dict, blank=True)` to `Query`.
A `VintedCategory` model can be added later as a proper lookup for admin autocomplete if needed.


---

## 6. Files to create / modify

Corrected 2026-08-21 — the original table predated the `Marketplace` enum (`03b3546`) and the
`check_blacklisted` rework (`2fb37f8`), and its migration number was stale by six.

| File | Change |
|---|---|
| `bazos/scraping/vinted/__init__.py` | [NEW] empty |
| `bazos/scraping/vinted/vinted_scraper.py` | [NEW] `VintedScraper` implementing `MarketplaceScraper` |
| `bazos/models.py` | ⚠️ **uncomment `Marketplace.VINTED`** (line ~45) — missing from the original table; add `extra_params` to `Query`; update the `url` property |
| `bazos/models.py` | ⚠️ make `Ad.view_count` / `Ad.publish_date` nullable — see the spec; without this every Vinted ad raises `IntegrityError` on save |
| `bazos/migrations/00NN_…` | [NEW] ⚠️ next free number is **`0026`** (latest is `0025_drop_sentinel_publishers.py`), not `0019` — **verify at write time** |
| `bazos/scraping/bazos_query_runner.py` | uncomment the `Marketplace.VINTED.value` line in `_build_scrapers` |
| `bazos/admin.py` | `QueryAdmin`: expose `extra_params` (with `help_text`), confirm `marketplace` in `list_display` |
| `pyproject.toml` | ⚠️ add `vinted-scraper = "^4.0.0"` — **not** `^3.1.1`; pulls in `httpx` |
| `bazos/tests/test_vinted_scraper.py` | [NEW] ⚠️ flat path, matching the other 20 test files — **not** `bazos/scraping/vinted/tests/` |

---

## 7. Open questions — ✅ all three answered by the 2026-08-21 probe

- [x] **Czech vs Slovak domain.** Per-query, in `extra_params["base_url"]`, defaulting to
  `https://www.vinted.cz`. The probe settles the argument: `vinted.cz` already returns
  cross-border (Polish) inventory with FX-converted prices (§1c), so the domain selects
  *pricing currency and buyer context*, not *seller geography*. That is a per-query concern,
  not a global setting. P3 already specifies `extra_params["base_url"]` — it is the right call.

- [x] **"Bumped" listings.** `promoted` is a real boolean on every search result and behaves
  exactly like Bazos's `topped`: with `order=newest_first`, promoted items appear
  **interleaved out of chronological order** (measured: index 7 of 8 was the promoted one).
  So map `promoted → Ad.topped` and reuse `run_existing_query`'s existing logic unchanged —
  `continue` past known topped ads, `break` on the first known non-topped one. **No
  Vinted-specific variant is needed**, provided `order: "newest_first"` is always sent.

- [x] **Rate limiting.** No `429`, but **not entirely clean either** — corrected after further
  probing. 6 back-to-back searches all returned HTTP 200 in ~0.30s with no backoff, so at this
  project's volume (one search per query per pass) the existing runner sleep is sufficient and
  **no bespoke backoff is needed**.

  ⚠️ However, after ~30 requests in one session the **session-cookie bootstrap failed** with
  `RuntimeError: Cannot fetch session cookie from https://www.vinted.cz`, succeeding immediately
  on retry. Response headers show **Cloudflare (`__cf_bm`) and DataDome** in front of the site,
  so this is intermittent anti-bot challenge rather than a rate-limit counter. The library
  already retries the cookie fetch 3× internally.

  Operational consequence: `VintedApiClient(base_url)` **can raise**, so expect occasional
  failed `QueryRun` rows on Vinted queries that are not bugs. Handling is specified in
  [`VINTED_SCRAPER.md`](VINTED_SCRAPER.md) §4.2.

---

## 8. Reproducing the probe

```bash
python3 -m venv /tmp/vintedenv && /tmp/vintedenv/bin/pip install vinted-scraper
/tmp/vintedenv/bin/python - <<'PY'
from vinted_scraper import VintedScraper
s = VintedScraper("https://www.vinted.cz")
items = s.search({"search_text": "macbook", "order": "newest_first", "per_page": 8})
for x in items:
    print(x.id, x.promoted, x.price, x.currency, repr(x.description), x.view_count, x.title[:40])
print(s.item(str(items[0].id)).json_data.keys())   # OpenGraph only, often just {'id'}
PY
```

Re-run this before implementing if more than a few weeks have passed — it is an unofficial API
with no stability guarantee, and 4.0.0 landed after this doc's original 3.1.1 claim.
