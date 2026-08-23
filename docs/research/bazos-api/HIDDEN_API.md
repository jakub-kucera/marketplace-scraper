---
title: Bazos Hidden Mobile API — Research & Scraping Assessment
status: reference
updated: 2026-08-07
verified: 2026-07-26
---

# Bazos Hidden Mobile API — Research & Scraping Assessment

> Source: decompiled Android app `cz.ackee.bazos` **v2.19.1** (versionCode 4630),
> in `bazos_app_decomplied/`. Endpoints extracted from the Retrofit interfaces
> under `sources/cz/ackee/bazos/**/retrofit/*ApiDescription.java` and the request
> assembly in `AdRetrofitDataSource.java` / `OkHttpClientFactory.java`.
>
> **Provenance of claims:** endpoint paths, query keys, headers and the response model
> are read directly from bytecode. **Update 2026-07-19:** the key open questions
> have now been checked against the live API (direct connection, no Tor) — see
> §7 for the full probe log. Auth-free access, the real pagination cap, the
> listing-vs-detail field split, and several new endpoints are now **confirmed**,
> not inferred. Anything still unconfirmed is marked explicitly. **Update
> 2026-07-26:** issue #52's AND/OR claim probed live — see §4.1a. `OR` is a real
> boolean union operator (confirmed via near-exact union arithmetic); `AND` is not
> an operator at all, just literal text, and silently narrows results if used.
> Follow-up probe (§4.1b) also identified the actual search mechanism: plain SQL
> substring `LIKE`, not MySQL FULLTEXT boolean mode as initially suspected — no
> wildcard/`+require`/`~rank` operators work, but substring matching means Czech
> word declension is already handled for free with no special syntax needed.

---

## 1. TL;DR

Bazos ships a private, **undocumented JSON REST API at `https://www.bazos.<tld>/api/v1/`**
that the official mobile app uses for everything — search, ad detail, favourites,
posting, ratings, saved-search "agents", geocoding, taxonomy. It is served from the
same host as the website (per-country base URL: `bazos.cz`, `.sk`, `.at`, `.pl`).

**The search endpoint (`api/v1/ads.php`) is strictly better than the current HTML
scraper for our purposes** — structured JSON instead of brittle BeautifulSoup
selectors, real `limit`/`offset` pagination, an `x-total-count` header, and
server-side sorting. **Live-confirmed:** the server accepts (and silently caps)
`limit` at **210** regardless of what's requested — a ~10.5x reduction in HTTP
requests versus the app's own default page size of 20, which directly cuts scrape
time, request volume, and blacklist-trigger risk.

**Important nuance confirmed live:** the listing endpoint (`ads.php`, in both its
paged and bulk-by-id forms) returns a **thin** payload — no description, no
images, no GPS, no publisher ids, no section/category objects. All of that richer
data is **only** in the single-ad detail endpoint (`ad-detail-2.php`). See §5.1 —
this changes the request-budget math versus what the `ApiAd` model class alone
suggested.

The API also unlocks workflows the HTML scraper can't do cheaply or at all:
cheap bulk existence/price refresh, explicit sold/removed detection (HTTP 410),
a seller-reputation/rating lookup that's confirmed live and unauthenticated, and
— found by testing rather than decompiling, not something the app itself uses —
an undocumented `email_id=`/`phone_id=` filter on `ads.php` that pulls any
seller's entire current active inventory directly. See §6.4 and §8.

**Recommendation: migrate Bazos scraping to the API**, implemented as a new
`MarketplaceScraper` protocol implementation registered in
`QueryRunner._build_scrapers()`, keeping the HTML scraper as a fallback.
This fits the existing marketplace-abstraction layer with **zero pipeline changes**.

---

## 2. How the app talks to the API

### 2.1 Base URL
`RetrofitFactory.create()` builds the client with `baseUrl = country.a()`, where
`country.a()` (see `sources/kg/b.java` for CZ) returns the **site root**:

| Country | Base URL | Currency |
|---------|----------|----------|
| CZ | `https://www.bazos.cz/` | CZK |
| SK | `https://www.bazos.sk/` | EUR |
| AT | `https://www.bazos.at/` | EUR |
| PL | `https://www.bazos.pl/` | PLN |

All endpoints below are **relative to that root**, e.g.
`https://www.bazos.cz/api/v1/ads.php`.

### 2.2 Request headers (`OkHttpClientFactory.addCommonNetworkInterceptor`)
Every request gets:

| Header | Value | Needed for scraping? |
|--------|-------|----------------------|
| `User-Agent` | app UA, lowercased + diacritics stripped (e.g. `bazos/2.19.1 …`) | **Yes** — send an app-like UA (see `USER_AGENT.md`) |
| `Date` | `EEE, d MMM yyyy HH:mm:ss Z` (US locale) | Not required — omit |
| `X-DeviceId` | device GUID, **added only if present** | **Confirmed not required** for public reads (§7) |
| `token` | auth token, **added only if present** (`addTokenHeaderIfPossible`) | **No** — only for account ops |
| `Accept-Encoding` | explicitly **removed** | cosmetic; `requests` handles this transparently |

**Confirmed live (§7, 2026-07-19):** search, detail, taxonomy, geocoding,
suggestions and ratings all return normal `200` JSON with **only a `User-Agent`
header** — no `token`, no `X-DeviceId`, no cookies, direct connection (no Tor).
`guid.php` still works and returns a real GUID, but nothing in the response or in
subsequent requests required it. A 20-request rapid-fire burst against
`ads.php` returned `200` every time — no `429`/`Retry-After` observed (short-burst
result only; sustained-load behaviour is still unknown, see §7 caveats).

### 2.3 The GUID / device-id handshake
`GuidInterceptor` lazily calls **`GET api/v1/guid.php`** (returns `{ "guid": "…" }`)
the first time a device id is missing, then sends it as `X-DeviceId` on subsequent
requests. If the API rejects anonymous reads, replicate this once and reuse the GUID.

---

## 3. Full endpoint inventory

Extracted verbatim from the `*ApiDescription` interfaces. `→` shows the response type.

### 3.1 Search / browse — **the ones that matter for scraping**

| Method | Path | Params | Returns |
|--------|------|--------|---------|
| `GET` | `api/v1/ads.php` | `@QueryMap` (see §4) | **thin** `List<ApiAd>` + `x-total-count` header — confirmed |
| `GET` | `api/v1/ads.php` | `ad_id[]=…&ad_id[]=…` | bulk fetch by id — **thin** fields only, missing ids silently omitted — confirmed |
| `GET` | `api/v1/ads.php?favourite_list=true` | `offset`, `limit` | favourites (needs auth) |
| `GET` | `api/v1/ad-detail-2.php` | `ad_id`, `edit`, `password` | single ad, **rich** — full description, images[], GPS, publisher ids, `user_ads_count`/`user_reviews_count` (undocumented in the model, present on the wire) — confirmed |
| `GET` | `api/v1/ad-phone.php` | `ad_id`, `phone_id` | resolves real phone number — **auth-gated**: confirmed `403 {"error_code":"1","message":"Číslo je neověřené"}` ("number unverified") without an account |
| `GET` | `api/v1/ratings.php` | `email_id` **or** `phone_id` | seller rating history — **public, no auth, confirmed live** — see §6.4 |
| `GET` | `api/v1/suggestionsnew.php` | `limit`, `offset`, `query`, `section`, `category` | keyword suggestions **+ matched section/category ids** — confirmed |
| `GET` | `api/v1/sections.php` | `order` | `List<ApiSection>` (taxonomy) — confirmed, human-readable CZ titles + slugs |
| `GET` | `api/v1/categories.php` | `section` | `List<ApiCategory>` (taxonomy) — confirmed |
| `GET` | `api/v1/zip.php` | `query` **or** `latitude`+`longitude` | geocode / reverse-geocode — confirmed both directions |

### 3.2 Saved searches ("agents" = Bazos "hlídací pes")

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `api/v1/agents.php` | list your agents |
| `GET` | `api/v1/agent-detailnew.php?agent_id=` | agent detail |
| `POST` | `api/v1/agent-post.php` | create agent |
| `POST` | `api/v1/agent-edit.php` | update agent |
| `PUT` | `api/v1/agent-detail-put.php` | activate/deactivate |
| `DELETE`| `api/v1/agent-detail-delete.php?agent_id=` | delete |

Ads matched by an agent are pulled via `ads.php?agent_id=<id>` (see `getAgentAds`).

**Confirmed live:** `agents.php` returns the same `403 {"error_code":"1","message":"Číslo je neověřené"}`
("number unverified") as `ad-phone.php` — both require a **phone-verified, logged-in
account**, not just a token. This is a real account-creation + SMS-verification cost,
not a header you can fake; see §6.4 before deciding whether it's worth it.

### 3.3 Account / write operations (auth-gated, **not needed for scraping**)

| Method | Path | Purpose |
|--------|------|---------|
| `POST`/`@Multipart` | `api/v1/ad-insert.php` | post an ad |
| `POST`/`@Multipart` | `api/v1/ad-edit.php` | edit an ad |
| `PUT` | `api/v1/ad-activate.php` | activate ad |
| `DELETE`| `api/v1/ad-remove.php` | delete ad |
| `POST` | `api/v1/ad-top.php` | "top" (promote) an ad |
| `POST` | `api/v1/ad-mail.php` | reply to an ad by email |
| `POST` | `api/v1/ad-mark.php` | report an ad |
| `POST` | `api/v1/image-upload.php` | upload image (multipart) |
| `GET` | `api/v1/deleted-ads.php` | `email`,`phone`,`offset`,`limit` — confirmed returns `[]` (no error) for a non-matching identity; needs the *exact* owning email/phone, so it's only useful for an ad's own poster, not general scraping |
| `GET` | `api/v1/confirm-phone.php` / `POST confirm-phone-post.php?platform=android` / `PUT confirm-phone-put.php` | phone verification |
| `POST` | `api/v1/ratings-post.php` | submit a rating (write side — auth-gated; the **read** side, `GET ratings.php`, is public and moved to §3.1) |
| `POST` | `api/v1/notifications.php` | register push token |
| `POST` | `api/v1/feedback.php` | app feedback |

---

## 4. The search query map (`api/v1/ads.php`)

Built in `AdRetrofitDataSource.getFilteredAdsQueryParams()`. **These are the exact
keys** the app sends:

| Key | Source | Notes |
|-----|--------|-------|
| `limit` | page size | e.g. 20 |
| `offset` | page offset | true offset pagination (not page-number) |
| `query` | serialized search text | see §4.1 |
| `section` | section id | mutually exclusive-ish with category |
| `category` | category id | |
| `price_from` | int | |
| `price_to` | int | |
| `zip_code` | ZIP/PSČ | location centre |
| `distance` | int | radius (km) around `zip_code` |
| `latitude` / `longitude`| GPS | alternative to zip; also enables `sort=distance` |
| `type` | real-estate type | e.g. flat/house subtypes |
| `agent_id` | saved-search id | pull ads matched by an agent |
| `sort` | see §4.2 | |
| `email_id` | seller's numeric id | **undocumented — not sent by the app itself, confirmed working anyway. See §6.4g.** |
| `phone_id` | seller's numeric id | same as `email_id`, alternate identity key — §6.4g |

Response pagination total comes from the **`x-total-count` response header**
(`getTotalAdsCount`), so you know exactly how many results exist and when to stop.
Requesting `offset` past the total returns a clean `200 []` — safe loop-termination
condition, confirmed live.

### 4.0 Pagination cap — confirmed live (2026-07-19)

The app always requests `limit=20`, but the **server** — not the client — enforces
the real ceiling. Tested directly against `https://www.bazos.cz/api/v1/ads.php`:

| Requested `limit` | Items actually returned |
|---|---|
| 50 | 50 |
| 100 | 100 |
| 200 | 200 |
| **210** | **210** |
| 211 | 210 |
| 250 / 300 / 1000 / 5000 | 210 |

**The hard cap is exactly 210 items per request**, independent of what the app itself
ever asks for. Walking a query with `limit=210` instead of the app's `limit=20` is a
**~10.5x reduction in HTTP requests** for the same amount of data — directly cuts
scrape wall-clock time, Tor circuit usage, and the number of chances to trip a
blacklist. This is the single highest-leverage, purely mechanical improvement
available (§6.4 / §8).

### 4.1 `query` serialization (`bi.a.b` / `SearchOptions`) — confirmed live

- Base text is the search phrase, matched **server-side as full-text search across
  both `title` and `description`** — confirmed: a plain `query=iphone` search
  surfaced a car ad ("Karoq…") whose *description* happened to mention "SmartLink
  pro iPhone". This means `Query.text` is already doing more than a title match
  today via the HTML scraper's `hledat=` param presumably does the same, but it's
  now explicit and exploitable (see §6.4 — fewer, broader queries + this full-text
  match can replace some of the manual category/keyword fan-out).
- If **exact match** is on, the phrase is wrapped in quotes: `"phrase"` — e.g.
  `query="iphone 13"` narrowed `x-total-count` from 6984 to 989 and returned only
  literal "iPhone 13" listings. Confirmed.
- **Excluded words**: confirmed the `-word` suffix works — `query=iphone -case`
  dropped the total from 6984 to 6781 (excluding "case"-mentioning results) while
  keeping otherwise-matching ads. Space-separated, appended after the base phrase.
- Empty `SearchOptions` serializes to `""`.

### 4.1a Boolean `OR` — confirmed real, `AND` — confirmed fake (live, 2026-07-26)

Issue #52 claimed the backend supports AND/OR operators; this was never tested in
the original 2026-07-19 pass. Probed directly (no Tor, unblocked connection) against
both surfaces — `api/v1/ads.php` (`query=`) and the HTML `search.php` (`hledat=`),
which return **identical `x-total-count`/"Zobrazeno X z Y" totals** for every query
below, confirming both hit the same backend index/logic.

**`OR` is a real boolean union operator, not literal text.** Evidence — union
arithmetic matches almost exactly, which plain literal-substring matching could not
produce:

| Query | Total (API / HTML) |
|---|---|
| `iphone` | 6940 / 6940 |
| `traktor` | 11542 / 11542 |
| `iphone OR traktor` | **18481** / 18481 |
| `macbook` | 1615 / 1615 |
| `imac` | 215 / 215 |
| `macbook imac` (implicit AND, both terms) | 57 / — |
| `macbook OR imac` | **1788** / 1788 |
| `macbook OR imac OR ipad` (ipad=1072) | 2794 / — |

`iphone` + `traktor` (two unrelated categories, near-zero real overlap) sums to
18482 — the `OR` query returned 18481, essentially exact. `macbook` + `imac` −
overlap (1615 + 215 − 57 = 1773) is close to the observed 1788 (small delta
consistent with live index churn between requests, ads posted/removed mid-probe).
A literal-token reading (`query` AND `"or"` AND `imac`, all required) would predict
a tiny number, not a value exceeding either baseline — ruled out. Also confirmed:
**case-insensitive** (`or` == `OR`), works with **3+ terms**, and quoting/
parenthesizing (`"macbook" OR "imac"`, `(macbook OR imac)`) doesn't change the
result — the parser accepts but doesn't require them. `macbook|imac` (pipe, no
spaces) and `iphone&samsung` are **not** recognized — both returned 0 (treated as
literal punctuation matching nothing).

**`AND` is NOT a real operator — it's just another literal required word,
indistinguishable from the existing default multi-word behavior.** Multi-word
`query` already behaves as an implicit AND (`macbook pro` → 1101/1102, down from
`macbook` alone's 1615 — narrowing, not widening). If `AND` were parsed and
discarded as a no-op keyword, `macbook AND pro` should return ~1101 too. It
doesn't — it returns **71/72**, a 15x drop, because `AND` gets treated as a *fourth
required literal substring* ("and"/"and" must also appear in the ad text), on top
of `macbook` and `pro`. Case-insensitive same way (`and` == `AND`, both 71-ish).
`macbook & pro` (ampersand) returns 0, consistent with literal-character matching
rather than any operator.

**Bottom line for query design**: `" OR "` between terms is safe to rely on and
already reduces `Query` row sprawl exactly as issue #52 hoped — e.g. one query for
`macbook OR imac OR ipad` instead of three separate rows, confirmed to work
identically via the production HTML scraper's `hledat=` param (no API migration
needed to use this today). There is **no working AND operator** beyond the
already-existing implicit multi-word AND — don't design anything around an
explicit `AND` keyword, it silently degrades results by requiring literal "and"
text.

Probe commands (reproducible):
```bash
UA="bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0"
curl -s -D - -A "$UA" -G "https://www.bazos.cz/api/v1/ads.php" \
  --data-urlencode "limit=3" --data-urlencode "sort=date" \
  --data-urlencode "query=macbook OR imac"   # check x-total-count header

curl -s -A "Mozilla/5.0" -G "https://www.bazos.cz/search.php" \
  --data-urlencode "hledat=macbook OR imac" --data-urlencode "rubriky=www" \
  --data-urlencode "Submit=Hledat"           # check "Zobrazeno 1-20 inzerátů z N"
```

### 4.1b Search mechanism identified — plain SQL substring `LIKE`, not FULLTEXT boolean mode (live, 2026-07-26)

Follow-up probe, prompted by §4.1a's confirmed `-word`/`"phrase"` syntax initially
looking like MySQL's native `MATCH() AGAINST(... IN BOOLEAN MODE)` — tested whether
that theory holds by trying more of *that* syntax's other operators (`+word`
require, `~word` soft-rank, `word*` wildcard). **All three break the query instead
of working as documented MySQL operators would:**

| Query | Total | Expected if real MySQL boolean-mode operator |
|---|---|---|
| `macbook` (baseline) | 1615/1616 | — |
| `+macbook` (explicit require) | **0** | should equal baseline (1615) — a lone `+word` is a no-op in real boolean mode |
| `macbook ~pro` (soft negative, rank-only) | **0** | should be ≥ baseline — `~` only downranks, never excludes |
| `macbook*` / `notebook*` (wildcard) | same as bare word | should be ≥ baseline (wildcard only ever adds matches) |
| `macb*` (broader wildcard prefix) | **0** | should be > 0 — "macb" is a real prefix of real listings |

Getting **0** for `+macbook` and `~pro` — rather than the baseline count or higher —
rules out real boolean-mode semantics entirely: those operators are being searched
for as literal characters, not interpreted. The decisive test was substring
truncation:

```
macbook  → 1616
acbook   → 1616   (missing the leading "m")
macboo   → 1616   (missing the trailing "k")
```

A fragment with letters missing from *either end* returns the **exact same** count
as the full word. A real full-text/tokenized index (MySQL FULLTEXT, Sphinx, Lucene,
…) only ever matches whole indexed tokens — "acbook" was never itself a token and
could not match. Identical counts across truncations is the signature of plain
`title LIKE '%word%' OR description LIKE '%word%'` substring matching.

**Corrected model**: PHP + MySQL, but the search itself is ordinary `LIKE`-based
substring matching, not `MATCH() AGAINST()`. On top of that raw substring match, the
PHP layer hand-parses exactly the operators actually confirmed working: bare
space-separated words (ANDed, each as its own required `LIKE '%word%'`), `-word`
(→ `NOT LIKE`), `"phrase"` (exact substring), and literal `" OR "` (splits the query
into two independent searches and unions the result sets — this one has to be
app-level, since bare-substring reasoning alone can't produce a union). Nothing else
is special-cased — `*`, `+`, `~`, `&`, `|`, and the literal word `AND` all just
become part of the literal substring being matched, which is why they return 0 or
(for `AND`) a small nonzero count from matching the literal 3-character substring
"and" inside unrelated words (brand names, "handmade", etc.), not from any real
conjunction logic.

**Practical implications**:
- **No useful new operators exist beyond the three already confirmed** (`OR`,
  `-exclude`, `"exact phrase"`) — don't design anything around wildcards or
  explicit `+require`, they don't work.
- **Czech declension is already handled for free**, and *better* than a wildcard
  would give — substring matching means a bare query like `notebook` already
  matches declined forms (`notebooku`, `notebooky`, …) without needing `notebook*`.
  Confirmed: `notebook` alone (7884) is a strict superset covering `notebooku`
  (2280) and `notebooky` (1242) results, since both contain "notebook" as a literal
  substring.
- **Flip side — substring noise on short/common query words.** The same looseness
  that gives free declension matching also means a short generic `Query.text` can
  match unrelated compound words purely by substring (e.g. `kolo` inside
  "koloběžka", `auto` inside "automat"/"automobil"). Worth a second look at any
  existing short single-word queries for false-positive risk, not just a positive.

Probe commands (reproducible):
```bash
UA="bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0"
for q in "macbook" "+macbook" "macbook ~pro" "macbook*" "macb*" "acbook" "macboo"; do
  curl -s -D - -A "$UA" -G "https://www.bazos.cz/api/v1/ads.php" \
    --data-urlencode "limit=1" --data-urlencode "sort=date" --data-urlencode "query=$q" \
    | grep -i "^x-total-count"
done
```

### 4.2 `sort` values (`td.b`)
`date` (newest), `price_asc`, `price_desc`, `distance` (nearest — requires lat/long).
Default in-app is `date` (newest first), which matches our dedup assumption
(stop on first already-known non-TOP ad). **See §4.3 — topped-ad pinning behaves
differently across these four values, confirmed live.**

### 4.3 Topped-ad pinning — no bypass exists; depth is query-shape dependent (confirmed live)

The current HTML scraper's dedup logic exists specifically because Bazos pins
"topped" (paid-promotion) ads to the front of `date`-sorted results regardless of
actual post date — the newest genuinely-organic ad can be many positions deep.
The natural question: can the API be asked to ignore this and return pure
chronological order? **No client-controllable bypass was found**, but the bigger
page size (§4.0) still helps a lot in the common case. Details:

**No app-side or guessable param exists.** Grepped the whole decompiled app for
any query key controlling topped inclusion (`Filters.java`, `AdRetrofitDataSource`)
— none exists; the app itself has no client control over this. Live-tested a set of
plausible guesses against `query=iphone&sort=date` — `topped=false`, `notop=1`,
`exclude_topped=true`, `top=0`, and invalid `sort` values (`date_only`, `newest`) —
**all were silently ignored**, returning byte-identical results to plain
`sort=date`. The server accepts unknown query keys without error and just falls
back to default behavior; there is no hidden flag to discover this way.

**Pinning is tied to specific `sort` values, confirmed by testing all four:**

| `sort` | Topped pinned to front? | Evidence |
|---|---|---|
| `date` | **Yes** | `query=iphone`: 134/210 topped, all at the front |
| `distance` | **Yes** | `query=iphone`: 50/50 topped in first 50 |
| `price_desc` | **No** — interleaved at natural price position | 15/50 topped, scattered by price, not pinned |
| `price_asc` | Appears no (inconclusive) | 0/50 topped in the cheapest/free tier — likely just because topped ads (dealer stock) skew expensive, not proof pinning is disabled |

So there's no way to get "chronological order, topped ads included in their real
position" — `price_desc`/`price_asc` un-pin topped ads but reorder by price
instead, which doesn't recover date order.

**How deep the topped run actually goes is highly query-shape dependent** —
tested by walking `offset` in 210-item steps:

| Query | `x-total-count` | Topped run depth |
|---|---|---|
| `query=iphone` (typical narrow text search) | 6,986 | ends at index **132** |
| `category=439` (Apple — typical category-scoped query) | 6,040 | ends at index **126** |
| `section=DE` (whole "Děti" section, no text — a broad query) | 143,124 | ends at index **199** (barely fits in one page) |
| `section=AU` (whole "Auto" section, no text — worst case) | 403,814 | **still 100% topped after 3,150+ items** (15 pages of 210, stopped there) |

**Practical takeaway:** for the query shapes this project actually issues — a
`Query` with real `text` and/or a specific `category` — the topped run
comfortably fits inside a single `limit=210` request (confirmed ~126–132 deep vs.
a 210-item page), so what used to require walking several of the app's own
20-item pages now resolves in **one** API call. This is a real, quantified version
of the improvement, not just "a bigger number." The caveat is queries that are
broad and section-only with no text filter (which the `Query` model does allow,
`text` is `blank=True`, and `generate_random_queries` picks a category without
text) — in a dealer-saturated section like Auto this can, in the worst case, not
resolve within any bounded number of pages; scope such queries with `category`
rather than bare `section` where possible.

One more nuance: for topped ads, the listing `from` timestamp is **not the
original post date** — in the `section=AU` sample, all 30 topped ads in a page
shared the exact same `from` value equal to the request's own timestamp,
consistent with `from` reflecting a bump/rebroadcast time rather than when the ad
was first posted. This means client-side re-sorting by `from` cannot recover true
chronological order for topped ads either — the pinning is unavoidable by any
means found so far, and the existing "stop scanning once we hit a known
non-topped ad" logic in `query_runner.py` should be kept as-is **for the
per-`Query` polling model**.

**If the actual goal is different — capturing every ad on the site, not just
matches for curated `Query` rows — the topped-pinning problem can be sidestepped
entirely** by walking ad ids directly via bulk lookup instead of search results;
that endpoint has no ranking logic at all. See §6.4f.

---

## 5. Response model — listing vs. detail are NOT the same payload

This is a critical distinction the `ApiAd.java` model class alone doesn't show
(Gson maps whatever keys are present; the model just declares the union of
possible fields across *all* callers of the class). **Live probes confirm the two
endpoints return genuinely different field sets:**

### 5.1 `ads.php` (listing / search / bulk-by-id) — thin, confirmed live

Actual response for a real ad from `GET ads.php?query=iphone&limit=3&offset=0`:

```json
{
  "id": "221354384",
  "from": "2026-07-19 09:45:51",
  "title": "Karoq 2.0 TDI DSG / Facelift / Asistenti / Spotřeba 5 l",
  "price_formatted": "429 000 Kč",
  "currency": "CZK",
  "image_thumbnail": "https://www.bazos.cz/img/1m/384/221354384.jpg?t=1784152511",
  "locality": "Praha 10",
  "topped": "true",
  "image_thumbnail_width": "350",
  "image_thumbnail_height": "233",
  "favourite": "false",
  "url": "https://auto.bazos.cz/inzerat/221354384/...",
  "views": "837"
}
```

**11 fields.** No `description`, no `images[]`, no `latitude`/`longitude`/`zip_code`,
no `email_id`/`phone_id`, no `section`/`category` **objects**, no `price_type`, no
`status`. This is true for **both** the paged form and the bulk `ad_id[]=` form —
bulk-by-id does **not** upgrade you to rich data, it's the same thin shape,
just letting you re-check up to 210 known ads' price/views/topped/title in one call.

**Correction — section is recoverable for free from `url` alone.** Every listing
`url` is `https://{section-slug}.bazos.cz/inzerat/{id}/{title-slug}.php` —
confirmed live across six different sections/categories (`mobil.`, `auto.`,
`dum.`, `reality.`, `zvirata.`, `motorky.`), and the subdomain slug matches
exactly the `url` field `sections.php` returns (e.g. `auto`, `mobil`) — the same
pattern the existing `Section.full_url` model property already relies on. So
`Section` can be derived from the thin listing with zero extra requests, just a
subdomain-to-id lookup against a cached `sections.php` sync. **Category is not**
— the path is always `/inzerat/{id}/{title-slug}.php`, no category segment ever
appears, confirmed across all six samples. Category still requires a detail call.

### 5.2 `ad-detail-2.php` (single ad) — rich, confirmed live

Actual response for the **same ad id** from `GET ad-detail-2.php?ad_id=221354384`:

```json
{
  "id": "221354384", "from": "Sun, 19 Jul 2026 09:46:53 +0200", "status": "active",
  "topped": true, "title": "...", "description": "<full ad text>",
  "price_formatted": "429 000 Kč", "currency": "CZK", "price": "429000",
  "price_type": "EXACT", "name": "Autodraft", "phone": "731", "phone_id": "9384",
  "email_id": "4788860", "zip_code": "101 00", "locality": "Praha 10",
  "latitude": "50.062098", "longitude": "14.464788",
  "category": {"id": "93", "title": "Škoda", "url": "skoda"},
  "section": {"id": "AU", "title": "Auto", "url": "auto", "image": "..."},
  "images": ["<14 full-size image URLs>"], "image_thumbnail": "...",
  "top_possible": "false", "top_total": "21", "top_limit": "21",
  "topped_for_days": "42", "action_possible": "false", "views": "837",
  "favourite": "false",
  "user_ads_count": "292", "user_reviews_count": "10"
}
```

**~30 fields**, and two of them — **`user_ads_count`** and **`user_reviews_count`**
— aren't in the decompiled `ApiAd.java` model at all (they're presumably deserialized
into a different/newer response class not present in this APK build, or via a loose
Gson map). They're a free seller-reputation/volume signal on every single ad detail
call — see §6.4.

One quirk: the `phone` field in the detail response is **truncated to the area-code
prefix** (`"731"`, not the full number) — the app must resolve the real number
separately via `ad-phone.php`, which is auth-gated (§3.2). However the full number
routinely appears in **plaintext inside `description`** (sellers write it directly
in the ad text), so it's often obtainable anyway without the gated endpoint.

### 5.3 Practical consequence for request budgeting

The original assessment implicitly assumed listing-endpoint calls were as rich as
`ApiAd.java` — they are not. The corrected cost model:

| Need | Cheapest endpoint | Cost |
|------|-------------------|------|
| New-ad discovery (id/title/price/views/topped) | `ads.php` (paged, `limit=210`) | 1 call per 210 ads |
| Cheap re-check of known ads (price/view drift, still-listed) | `ads.php?ad_id[]=` (bulk) | 1 call per 210 ids |
| Full description, images, GPS, section/category, seller ids | `ad-detail-2.php` | **1 call per ad** — unavoidable, same cost the current HTML `load_full_description` page-fetch already pays |
| Sold/removed detection | `ad-detail-2.php` → `410 {"status":"deleted"}` | 1 call per ad (see §6.4) |

So the API is a straight win for the *discovery* pass (10.5x fewer requests than
the app's own paging), but does **not** eliminate the per-ad detail fetch for rich
fields — it just replaces the HTML page-scrape (`popisdetail`) with a cleaner JSON
call at the same call count.

### 5.4 API vs. current HTML scraper (`bazos_scraper.py` → `Ad`)

| Data | HTML scraper | API listing | API detail |
|------|--------------|:---:|:---:|
| id / url / name / price (raw) | ✅ (parsed from DOM) | ✅ | ✅ |
| short description | ✅ | ❌ | ✅ (`description`) |
| full description | extra page fetch (`popisdetail`) | ❌ | ✅ **1 call**, same cost as today |
| location text | ✅ | ✅ | ✅ + **`latitude`/`longitude`/`zip_code`** |
| view count | ✅ | ✅ | ✅ |
| publish date | parsed from `[dd.mm.yyyy]` | ✅ `from` | ✅ `from` |
| topped flag | ✅ | ✅ | ✅ + top metadata |
| **structured price** | ❌ (`price_raw` string, TODO) | partial (`price_formatted`) | ✅ `price`+`price_type`+`currency` |
| **all images** | ❌ | ❌ | ✅ `images[]` |
| publisher email/phone ids | ✅ (scraped from `onclick`) | ❌ | ✅ `email_id`/`phone_id` |
| **section/category objects** | ❌ | ❌ | ✅ |
| **seller volume/reputation** | ❌ | ❌ | ✅ `user_ads_count`/`user_reviews_count` (undocumented) |
| **sold/removed signal** | ❌ (ad just vanishes from listing) | n/a (silently omitted from bulk) | ✅ explicit `410 deleted` |
| **total result count** | ❌ (walks pages till empty) | ✅ `x-total-count` | n/a |

The listing endpoint alone is a straight upgrade over HTML for the discovery loop
(structured + 10.5x fewer requests). The detail endpoint remains the only source
for description/images/GPS/reputation, same as today's `load_full_description` call.

---

## 6. Should we switch? — Assessment

### 6.1 Advantages of the API
1. **Robustness.** JSON contract vs. HTML classes (`inzeratynadpis`, `popisdetail`,
   `onclick`-argument parsing). Any Bazos redesign breaks the HTML scraper; the API
   is far more stable.
2. **Richer data**, incl. GPS, full image galleries, structured price/currency/type,
   section/category — enabling better filtering rules later (`RuleEngine`).
3. **Cheaper full descriptions.** `ad-detail-2.php` returns the full description in
   the same shape as search — removes the separate `load_full_description` page GET.
4. **Real pagination + total count, and a much bigger page.** `limit`/`offset` +
   `x-total-count` replaces "keep fetching pages until an empty one" (fixes the
   existing "not working" pagination TODO at `bazos_scraper.py:230`) — and the
   server-confirmed **210 cap** (§4.0) means **~10.5x fewer HTTP requests** than
   the app's own `limit=20` for the same discovery pass.
5. **Bulk re-check by id** (`ads.php?ad_id[]=`). Confirmed: up to 210 ids per call,
   missing/removed ads silently dropped. Good for a cheap price/view/still-listed
   refresh of known ads — though it does **not** return `status`, so it can't by
   itself distinguish "removed" from "not in this batch" (see §6.4 for the
   endpoint that does).
6. **Multi-country / multi-marketplace for free.** Confirmed live on `.sk` (same
   JSON shape, EUR currency, working `x-total-count`) — directly serves the
   abstraction roadmap (Stages 6–7) and future non-CZ Bazos.
7. **Taxonomy sync.** `sections.php`/`categories.php` confirmed live with
   human-readable CZ titles + slugs; can replace the hand-maintained
   `create_sections` / `create_categories` management commands.
8. **Server-side sort** (date/price/distance) — pull newest-first deterministically.
   Note: topped ads are still pinned to the front under `date`/`distance` sort with
   no bypass (§4.3) — but for the narrow, realistic query shapes this project
   actually uses, the topped run fits comfortably inside a single `limit=210`
   page, so the existing multi-page skip-until-non-topped problem mostly
   collapses to one request instead of several.
9. **Server-side full-text search** (§4.1) already matches against `description`,
   not just `title` — confirmed live. Fewer, broader `Query` rows can cover more
   ground than today's title-oriented HTML search.
10. **New capabilities with no HTML equivalent at all** — seller reputation lookup
    and explicit sold/removed detection. See §6.4.

### 6.2 Risks / costs
1. **Undocumented & unversioned-in-practice.** It can change without notice. (So can
   HTML — but a `/v1/` path and a shipped app suggest reasonable stability.)
2. **Fingerprinting surface.** Must mimic app headers (`User-Agent`). Mitigate:
   realistic UA (`USER_AGENT.md`) — **confirmed live that `X-DeviceId`
   and `token` are not required**, so there's no device-id/GUID identifier that
   needs to travel with the requests at all for read-only scraping.
3. **Unknown *sustained* rate-limit / blacklist behaviour on `api/v1/*`.** A
   20-request rapid burst returned `200` every time with no `429`/`Retry-After`
   (confirmed §7) — but that only rules out a very tight per-second limiter, not a
   longer sliding-window one. Treat the existing Tor IP rotation and `MAX_ATTEMPTS`
   backoff as still necessary; watch for `403`/`429` in production and wire them
   into `check_blacklisted`.
4. **ToS.** Driving a private mobile API is still scraping; arguably a clearer ToS
   breach than fetching public web pages. No change to the legal posture we already
   accept, but worth acknowledging.
5. **Third-party personal data exposure (new).** `ratings.php` is public and
   returns real, unmasked phone numbers of *reviewers* (not just the seller) — see
   §6.4. This is a step up in what we'd be collecting versus today's scraper, which
   only touches the ad poster's own (already-public) contact ids. Worth a deliberate
   decision on whether/how to store this, not just "because the API returns it."

### 6.3 Verdict
**Yes — migrate.** The reliability and data gains are large, the pipeline is already
decoupled so the change is contained to the scraper layer, and it advances the
multi-marketplace goal. Keep the HTML scraper as a registered fallback so we can flip
back per-query if the API misbehaves.

### 6.4 New capabilities confirmed live (2026-07-19) — beyond parity with HTML

These aren't things the HTML scraper can do at all today, discovered/confirmed
during live probing. Roughly ordered by how directly they extend the existing
pipeline vs. how much new surface they'd add.

#### a) Ad lifecycle / sold-removed detection (new `Ad` state, cheap)
Re-querying a **known, no-longer-listed** ad id via `ad-detail-2.php` returns:
```
HTTP 410  {"idad":"1", "status":"deleted"}
```
confirmed for both a never-existed id and an old/expired-looking id. Today, once an
ad scrolls off the newest-first listing the pipeline simply never looks at it again
— there's no way to know if it sold, was removed, or is still live further back in
the results. A periodic sweep of known `SENT`/`APPROVED` ads through
`ad-detail-2.php` (or a first-pass thin filter via bulk `ads.php?ad_id[]=`, since
gone ads are silently omitted there too) would let the pipeline explicitly mark ads
as removed/sold — e.g. a new `AdStatus.REMOVED` — and optionally post a quiet
"no longer available" follow-up rather than leaving stale Discord messages. Low
effort: same request shape as the already-planned `PRICE_CHANGED` bulk re-check,
just also checking "did it disappear."

#### b) Seller reputation & volume enrichment (new, public, no auth)
Two independent, unauthenticated signals per seller, both confirmed live:
- `ad-detail-2.php` → `user_ads_count` / `user_reviews_count` (e.g. `"292"` /
  `"10"` for a dealer) — a free, per-ad-detail-call signal for **listing
  volume** (private seller vs. dealer/bulk-poster) with zero extra requests, since
  you're already calling this endpoint for descriptions.
- `GET ratings.php?email_id=<id>` (or `phone_id=`) → full rating history: each
  entry has `name`, `phone` (reviewer's, often filled), `message`, `type`
  (`positive`/`negative`/`neutral`), `from` (date). No pagination params observed
  needed/offered; returns the full history in one call.

  **Example — re-verified live, `GET ratings.php?email_id=4788860`** (a car
  dealer's ratings; reviewers are its customers, not the dealer itself):
  ```json
  {"name": "Autodraft",   "email_id": "4788860",  "phone": "731482686",    "type": "positive", "from": "Wed, 01 Jul 2026 08:45:15 +0200"}
  {"name": "Milan ",      "email_id": "8476367",  "phone": "720704959",    "type": "negative", "from": "Tue, 30 Jun 2026 12:11:33 +0200"}
  {"name": "M. Navrátil", "email_id": "10350693", "phone": "",             "type": "positive", "from": "Wed, 27 May 2026 15:45:02 +0200"}
  {"name": "OB",          "email_id": "34948",    "phone": "420774919293", "type": "neutral",  "from": "Wed, 20 May 2026 13:57:04 +0200"}
  ```
  (`message` field omitted above for brevity — full free-text review body is also
  returned.) The first entry's `phone` (`731482686`) is the dealer's own number,
  already public elsewhere; the second and fourth (`720704959`, `420774919293`)
  belong to **the reviewers** — private individuals who left feedback, not sellers.
  Not every entry has a phone (`M. Navrátil` above is blank), so it's inconsistently
  populated, but real numbers are present often enough to be a genuine PII leak
  when it happens.

  Because `Ad.email_publisher`/`Ad.phone_publisher` already carry the exact
  `email_id`/`phone_id` values this endpoint takes, **every ad already in the DB
  can be retroactively enriched for free** — no new ids to discover, just a lookup
  keyed off data already stored. This is exactly the "look up the poster" workflow
  — confirmed technically trivial.

  **Two things worth deciding deliberately, not by default:**
  1. This exposes third-party reviewers' phone numbers, not just the seller's own
     (§6.2 point 5) — worth checking whether that's data the website itself shows
     publicly on a profile page (in which case the API isn't exposing anything new,
     just making it programmatic) before deciding what to store.
  2. A rating count/sentiment summary (`positive_count`, `negative_count`,
     `total_reviews`) is a much smaller, lower-risk thing to persist than raw
     reviewer PII — consider storing only the aggregate on `EmailPublisher`/
     `PhonePublisher` rather than the raw review list, unless the raw text is
     actually needed for something.
  - **Possible use once available:** feed a trust score into `RuleEngine`
    (`bazos/filters.py`) — e.g. auto-suppress/deprioritize first-time or
    negatively-reviewed sellers, or flag suspiciously high-volume "private" sellers
    (`user_ads_count` in the hundreds) as de-facto dealers for filtering purposes.

#### c) Smart query-to-taxonomy mapping (`suggestionsnew.php`)
Confirmed: `GET suggestionsnew.php?query=iph&limit=5` returns not just keyword
completions but the **matched section/category ids**:
```json
{"keywords": [...], "sections": [{"section":"MO","title":"Mobily"}],
 "categories": [{"category":439,"title":"Apple","parentSection":"MO", ...}]}
```
This could feed a small admin helper — given free-text like "iphone", auto-suggest
the correct `Query.section`/`Query.category` FK instead of an admin manually
browsing the taxonomy. Also usable to make `Query.generate_random_queries` (today:
picks a uniformly random `Category` row) weight toward categories with actual
current listing volume, using `sections.php`/`categories.php` + a probe search.

#### d) Geocoding for true distance-based search (`zip.php`)
Confirmed both directions: PSČ → `{lat, lon, city}` and `lat/lon` → nearest PSČ.
`Query.location_center` is currently a raw PSC string matched against the HTML
scraper's `hlokalita`/`humkreis` params. The API's `zip_code`+`distance` params are
a direct equivalent, but `latitude`+`longitude`+`sort=distance` (confirmed
accepted key, per §4.2) would let a query be genuinely nearest-first sorted rather
than just radius-filtered — meaningful for time-sensitive categories (free stuff,
same-day pickup items).

#### e) Server-side saved searches ("agents") — evaluated, likely not worth it
`agents.php`/`agent-post.php` would let Bazos itself do the polling and hand back
only matches (`ads.php?agent_id=`), rather than the pipeline polling on its own
interval. **Confirmed this requires a phone-verified logged-in account** (`403
{"message":"Číslo je neověřené"}` — same gate as `ad-phone.php`), not just a
device id. That's a real account + SMS-verification + credential-storage cost for
a benefit (fewer polls) the pipeline doesn't obviously need — the current
poll-and-diff model already works and doesn't hit any confirmed rate limit. Recommend
**not pursuing** unless polling volume itself becomes a problem.

#### f) Full-site crawl via sequential ID sweep — sidesteps topped-pinning entirely

For the specific goal of "capture every ad on `bazos.cz`" (as opposed to the
per-`Query` model), there's a materially better approach than walking `sort=date`
search results category by category: **walk ad ids directly via bulk
`ads.php?ad_id[]=`**, which has no search-ranking/sort logic at all — topped
pinning (§4.3) simply doesn't apply, since you're asking "do these specific ids
exist," not "give me a ranked page."

**Confirmed live: ids are a single, monotonically time-correlated counter, per
country.** Sampled two *unrelated* categories at nearly the same instant:

| Category | Id | `from` |
|---|---|---|
| Bazény (DU — home/garden) | `221481394` | `10:03:17` |
| Apple (MO — mobiles) | `221481991` | `10:15:07` |

Lower id → earlier time, across categories with nothing to do with each other —
strong evidence of one shared counter for the whole `.cz` site. Delta: 597 ids /
710s ≈ **~72,700 ids issued/day** site-wide. Each country TLD has its own
independent counter with a wildly different current magnitude (confirmed same
moment: `.at`≈275K, `.pl`≈742K, `.sk`≈193M, `.cz`≈221M) — ruling out a shared
cross-country pool as an explanation for anything below.

**Simpler design than "find latest id, then walk since last run":** don't bother
finding the current tip as a separate step. Just always sweep forward from your
last saved watermark in id-batches via bulk lookup, and stop at the first empty
batch; record the highest id actually found as the new watermark. The sweep
discovers new ads *and* advances the watermark as the same operation — no
detail-endpoint probing, no binary search, and it's self-healing (ids issued in
the moment between "stop" and "now" just get swept up at the start of the next
run, at the cost of a little redundant re-scanning at the boundary).

**Bulk batch size is not capped at 210 (unlike search) — it's capped by URL
length instead.** Confirmed: a batch of 450 sequential ids (URL 8,135 bytes)
succeeds; 500 ids (~9KB) returns `414 Request-URI Too Large`. Recommend **~400
ids per batch**, leaving headroom as ids grow another digit over time — nearly
2x the search endpoint's 210.

**Density near the tip is only ~15%, confirmed live** (a 200-id window at the
current tip returned 30 real ads). Ruled out cross-country id-sharing as the
cause (separate counters, confirmed above). Investigated whether abandoned ad
*drafts* explain the gap (a very reasonable hypothesis for a posting flow):

- **Ruled out, from source:** the app's `TempAd` (the in-progress ad-creation
  form state, `screens/add/TempAd.java`) is a purely local, in-memory
  `Parcelable` — `AddAdPresenter` wires form fields into it via local RxJava
  observables with no network call. A user who fills in a title/price and then
  abandons the form burns **zero** server-side ids; nothing is sent until final
  submission.
- **Still plausible:** the posting flow uploads photos via a separate
  `POST image-upload.php` call **before** the final `ad-insert.php` submission
  (confirmed — `insertAd` takes a `PartMap` of already-uploaded image
  references). A user who uploads photos and then abandons *does* leave a real
  server-side trace, just not necessarily on the ad-id sequence itself. Beyond
  that, the most likely remaining causes are the final `ad-insert.php` submission
  itself failing partway (validation/spam-filter rejection, a dropped connection
  mid-upload) after a row/id was already allocated — auto-increment counters
  commonly don't roll back even when the row does — real ads that get removed
  quickly, or another entity type (the `poukazky`/vouchers feature seen in
  `kg.g.java`) sharing the same DB sequence.
- **Empirical stability check:** re-fetched the identical 200-id window some time
  later (~20-30 min elapsed) — still exactly 30 found, and the original boundary
  id was still present. No growth (argues against a delayed/async-publish
  pattern where abandoned-but-recoverable ids later resolve) and no shrinkage
  (argues against very-fast removal within that window). Doesn't rule out slower
  removal over days, and doesn't cleanly separate "incomplete submission" from
  "real ad, removed later" as the dominant cause.

**The exact cause doesn't matter for cost** — bulk-lookup cost is fixed
per batch regardless of hit rate, and this is already priced into the estimate
below.

**Net request cost to stay fully caught up:** ~72,700 ids/day ÷ ~400/batch ≈
**~182 bulk requests/day** (~7-8/hour) to discover every new live ad, site-wide,
with zero topped-ordering interference at all.

**What you don't get for free:** bulk lookup returns the same **thin** fields as
search (§5.1) — title, price, locality, views, topped, url; no
category/description/GPS/publisher ids. Enough to filter on title-text/price/
locality directly, but category-based or full-text-description matching (needed
to fully replicate current `Query` semantics, §4.1) still requires one
`ad-detail-2.php` call **per real ad found** (not per candidate id) — at ~15%
density, ~10,900 detail calls/day for full detail on literally every ad
site-wide, ~7-8/minute averaged out. This matches the unavoidable per-ad detail
cost already established in §5.3; the sequential-id sweep only makes the
*discovery* phase cheap and topped-immune, not the rich-data phase.

#### g) Seller-scoped listing filter — `ads.php?email_id=`/`phone_id=` (undocumented, confirmed working)

**The app itself never sends this** — `AdRetrofitDataSource.getFilteredAdsQueryParams()`
(§4) builds its query map from `limit`/`offset`/`query`/`section`/`category`/
`price_from`/`price_to`/`zip_code`/`distance`/`type`/`latitude`/`longitude`/
`agent_id`/`sort` only; `email_id`/`phone_id` are not among them anywhere in the
decompiled sources. This was found by guessing and testing directly against the
live API, not by decompiling — so unlike every other endpoint/param in this doc,
there's no client dependency forcing Bazos to keep it working. Treat it as
lower-confidence-to-persist than the rest of this document, even though it's
confirmed working today.

**Confirmed live:** `ads.php?email_id=<id>` filters listings to that seller's
current active ads. Verified rigorously, not just by eyeballing plausible
results — fetched 10 listings under `email_id=4788860` (a car dealer) and looked
up every single one individually via `ad-detail-2.php`; **all 10/10** had
`email_id: "4788860"` in their detail response. `phone_id=<id>` behaves the same
way for the same seller. Composes correctly with other filters — confirmed
`email_id=4788860&category=93` correctly narrowed to just that seller's listings
in category 93. Also confirmed: a different seller's `email_id` (from an earlier
`ratings.php` sample) legitimately returned `[]` (that identity currently has no
active listings) rather than silently falling back to an unfiltered result —
i.e. this isn't the "unknown params get ignored" behavior seen elsewhere (§4.3),
it's a real filter.

**One quirk:** no `x-total-count` header is returned for this filter mode
(unlike normal search/category queries) — paginate with `offset` until an empty
page, or use `user_ads_count` from a detail call as the expected total.

**Why this matters:** it means any seller's entire current active inventory can
be pulled directly, cheaply, and completely — not just their `user_ads_count`
(§6.4b) — given only their `email_id`/`phone_id`, which are already exposed on
every ad detail response and every `ratings.php` entry (including reviewers,
§6.4b). This is the building block for a materially cheaper version of several
workflows: full dealer/reseller inventory analysis, direct diffing of a seller's
past-vs-current listings to catch reposts, and turning any harvested identity
(seller *or* reviewer) into an immediate lookup for what they're currently
selling. Full workflow design: `DISCOVERY_PIPELINE.md`.

---

## 7. Validation — completed live 2026-07-19

All items below were run directly (not through Tor — a direct, currently-unblocked
connection was available) with a faithful app UA
(`bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0`,
see `USER_AGENT.md`). Original checklist items and their outcomes:

| # | Check | Result |
|---|-------|--------|
| 1 | `GET guid.php` returns a real guid | ✅ `{"guid":"89989892"}` |
| 2 | `ads.php` works with **only** `User-Agent`, no `token`/`X-DeviceId` | ✅ plain `200` JSON, no auth headers sent at all |
| 3 | Does sending `X-DeviceId` change anything? | Not tested separately — #2 already succeeds with neither header, so this is moot for read-only scraping |
| 4 | `-word` exclusion syntax + section/category ids | ✅ confirmed (§4.1); `sections.php`/`categories.php` return real ids (e.g. `AU`/`93`) |
| 5 | Rate-limit / block response shape | 20-request rapid burst → all `200`, no `429`/`Retry-After` (short-burst only, see §6.2 caveat) |
| 6 | CZ ↔ SK/AT/PL parity | ✅ `.sk` confirmed: same JSON shape, EUR currency, working `x-total-count` |

**Additional findings beyond the original checklist** (folded into §4, §5, §6.4 above):
- Server-side pagination cap is **exactly 210**, not client-controlled — and
  verified against a genuinely huge unfiltered total (`x-total-count=1,506,118`)
  to rule out "the query just only had 210 results" (§4.0).
- Listing (`ads.php`, incl. bulk `ad_id[]=`) is a **thin** payload; only
  `ad-detail-2.php` returns the rich fields (§5).
- `ad-detail-2.php` on a gone ad returns `410 {"status":"deleted"}` (§6.4a).
- `ratings.php` is public/unauthenticated and returns reviewer names + phone
  numbers + sentiment — concrete example captured (§6.4b).
- `ad-phone.php` and `agents.php` both require a phone-verified account (`403
  {"message":"Číslo je neověřené"}`), not just a header (§3.2, §6.4e).
- `suggestionsnew.php` returns matched section/category ids, not just keywords (§6.4c).
- Full-text search matches `description`, not just `title` (§4.1).
- No bypass exists for topped-ad pinning under `sort=date`/`distance`; depth of
  the topped run is bounded for realistic narrow queries but can be pathological
  for broad section-only browsing (§4.3).
- `ads.php?email_id=`/`phone_id=` is a genuine, undocumented seller-scoped listing
  filter — not sent by the app itself, found by testing, verified 10/10 against a
  real seller (§6.4g).

Probe commands used (reproducible, no proxy needed if run from an unblocked network):

```bash
UA="bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0"

curl -s -A "$UA" "https://www.bazos.cz/api/v1/guid.php"
curl -s -A "$UA" "https://www.bazos.cz/api/v1/ads.php?query=iphone&limit=3&offset=0&sort=date" -D -
curl -s -A "$UA" "https://www.bazos.cz/api/v1/ad-detail-2.php?ad_id=<id>&edit=false"
curl -s -A "$UA" "https://www.bazos.cz/api/v1/ratings.php?email_id=<id>"
curl -s -A "$UA" "https://www.bazos.cz/api/v1/sections.php"
curl -s -A "$UA" "https://www.bazos.cz/api/v1/categories.php?section=AU"
curl -s -A "$UA" "https://www.bazos.cz/api/v1/zip.php?query=11000"
curl -s -A "$UA" "https://www.bazos.cz/api/v1/suggestionsnew.php?query=iph&limit=5&offset=0"
curl -s -A "$UA" -G "https://www.bazos.cz/api/v1/ads.php" --data-urlencode "ad_id[]=<id1>" --data-urlencode "ad_id[]=<id2>"
```

**Still open / not yet worth testing further:** sustained (multi-minute) request
volume and its rate-limit behavior — the 20-request burst rules out a tight
per-second limiter but says nothing about a longer sliding window. Verify this
under the project's real Tor-rotated load pattern before removing the existing
`check_blacklisted`/backoff safety nets, not by further ad-hoc bursts here.

---

## 8. Proposed implementation plan (fits the existing architecture)

The pipeline is already decoupled through `Ad.status`, and the marketplace layer
already keys scrapers by `query.marketplace` in `QueryRunner._build_scrapers()`.
So this is a **drop-in scraper implementation**, not a pipeline change.

> **Two additional arguments for the migration, added 2026-07-29** — neither was captured
> in §1's original case, and both are independently decisive:
>
> **a) Timestamp resolution — the HTML path is losing data every single scrape.**
> `BazosScraper.extract_date` slices the `[d.m.yyyy]` substring out of the listing and
> builds `datetime(day, month, year)` — **the time is discarded entirely**, so every
> `Ad.publish_date` collected so far sits at midnight. The API's thin listing carries
> `"from": "2026-07-19 09:45:51"` at **second** resolution (§5.1) for free, in the same
> payload. Consequences: no ad-lifetime measurement better than ±1 day, and
> `BACKLOG_IDEAS.md` #6 (posting-density interval tuning) is **impossible from
> stored data today** — it was listed as a zero-dependency quick win on the strength of
> data that doesn't exist. Caveat when relying on this: for **topped** ads the `from`
> value is not the real posting time (§4.3), so filter `topped=False` for any
> time-of-day analysis.
>
> **b) Latency, not just request efficiency.** §1 argues the API case on structure and
> request volume. The sharper point is cadence: a `limit≈10` steady-state dedup probe is
> **~1.1 KB** (§4), which per `PROXY_ROTATION.md` §5 makes a **2-minute
> cadence cost ~0.24 GB/month** — versus the ~15-minute median detection latency the
> current HTML path is stuck with. See `MONETIZATION.md` §7.1 for why that gap decides
> whether the project captures deals or merely observes them, and
> `PROMPTS.md` **P21** for the executable rollout.

### Stage A — Spike & verify — **done, see §7**
Live-confirmed 2026-07-19: auth-free (no `token`/`X-DeviceId` needed), real page
cap is 210, listing is thin / detail is rich, sold-ad detection via `410`, and
`ratings.php` seller lookup all work as documented above. Remaining: capture 2–3
real JSON responses into `bazos/tests/fixtures/` for tests (the payloads in §5.1/
§5.2 can seed these directly), and re-verify sustained-load rate-limit behavior
under real Tor rotation before removing the existing backoff/blacklist safety net.

### Stage B — `BazosApiScraper` implementing the `MarketplaceScraper` protocol — **done, 2026-07-24**
`bazos/scraping/bazos/bazos_api_scraper.py` implements this, satisfying
`bazos/scraping/marketplace.py` as a peer of `BazosScraper`. Registered in
`QueryRunner._build_scrapers()` under `marketplace = "bazos_api"` —
**inert for production**, since no existing `Query` row uses that value, so
`run_scraper` stays HTML-only until a `Query` is deliberately switched over.
Unit tests (`bazos/tests/test_bazos_api_scraper.py`) cover query-param mapping,
listing/detail JSON parsing, pagination against `x-total-count`, the `410`
sold/removed case, and blacklist detection, using real captured payloads in
`bazos/tests/fixtures/bazos_api/`. For live side-by-side validation against the
HTML scraper on real `Query` rows (read-only, no DB writes), run
`python manage.py compare_bazos_scrapers`.

Not yet implemented (left for a follow-up once Stage B is validated in
production): the richer Stage D fields (`price_type`/`currency`/`images`/GPS/
`user_ads_count`), `AdStatus.REMOVED` sold-detection sweep, and the
`ratings.php` seller-reputation enrichment — all additive and independent of
this scraper working at all.

Original plan, for reference:

- `marketplace = "bazos_api"` (or reuse `"bazos"` behind a feature flag).
- `run_query(query)`:
  - Build the query map from the `Query` model:
    `text→query`, `location_center→zip_code`, `location_radius→distance`,
    `price_lower→price_from`, `price_upper→price_to`,
    `section.<id>→section`, `category.<id>→category`, `sort=date`.
  - Page with **`limit=210`** (the confirmed server cap, §4.0 — not the app's 20)
    and `offset`; stop using `x-total-count`. This alone is the ~10.5x request
    reduction (fixes the pagination TODO at `bazos_scraper.py:230`).
  - Map the **thin listing JSON** (§5.1) → `Ad(status=PENDING)`, reusing
    `_resolve_publishers` — note listing has no `email_id`/`phone_id`, so
    publisher resolution has to happen at `load_full_description` time instead
    (or be treated as optional/deferred for ads that never get a detail fetch).
    Preserve the existing newest-first dedup (stop on first known non-TOP id).
  - Populate the previously-`TODO` structured fields (price/price_type/currency,
    images, lat/long, `user_ads_count`/`user_reviews_count`) from the **detail**
    call only, since listing doesn't carry them — additive `Ad` columns.
- `load_full_description(ad)`: `GET ad-detail-2.php?ad_id=<id>` instead of the
  `popisdetail` page scrape. Handle `410 {"status":"deleted"}` explicitly (§6.4a).
- `check_blacklisted(...)`: no `403`/`429` observed in a short burst (§7); still
  wire up detection for when they do occur in production.
- Reuse the existing Tor `requests.Session`/`PROXIES` and `run_request` retry/backoff.

### Stage C — Register & select
- Add to `QueryRunner._build_scrapers()` keyed by `query.marketplace`.
- Roll out per-query: set `marketplace="bazos_api"` on a canary `Query`, compare
  results against the HTML scraper, then migrate the rest. HTML scraper stays as
  fallback.

### Stage D — Model & follow-ups (optional, incremental)
- Add columns for the new structured data (nullable, additive): `price_type`,
  `currency`, `latitude`, `longitude`, `images` (JSON), `video`, `category`/`section`.
- Add `user_ads_count`/`user_reviews_count` (undocumented-but-confirmed, §5.2) to
  `EmailPublisher`/`PhonePublisher` — free seller-volume signal from every detail call.
- Add `AdStatus.REMOVED` (or similar) and a periodic sweep of `SENT`/`APPROVED` ads
  through bulk `ads.php?ad_id[]=` (cheap, 210 at a time) or `ad-detail-2.php`'s
  `410` (§6.4a) to detect sold/removed ads — new capability, no HTML equivalent.
- Replace `create_sections`/`create_categories` with a sync command backed by
  `sections.php`/`categories.php`.
- `PRICE_CHANGED` re-scan: batch known ids through `ads.php?ad_id[]=` for cheap
  price refresh (confirmed: thin fields include `price_formatted` and `views`).

### New workflows the API unlocks (beyond parity) — see §6.4 for full detail
- **Sold/removed detection** (§6.4a) — `ad-detail-2.php` → `410 deleted`, or bulk
  `ad_id[]=` silent omission. New `Ad` lifecycle state, cheap to add.
- **Seller reputation & volume enrichment** (§6.4b) — `ratings.php` (public, no
  auth) + `user_ads_count`/`user_reviews_count`, both keyed off ids already stored
  on `Ad`. Feeds a future `RuleEngine` trust-score rule. Needs a deliberate call on
  what to persist (aggregate score vs. raw reviewer PII).
- **Smart query-to-taxonomy mapping** (§6.4c) — `suggestionsnew.php` for an admin
  helper or smarter `generate_random_queries`.
- **Precise geo filtering** (§6.4d) — `zip.php` geocoding + lat/long + `sort=distance`
  for genuinely nearest-first results, not just radius-filtered.
- **Server-side saved searches (agents)** — evaluated and **not recommended**
  (§6.4e): confirmed to require a phone-verified account, not just a header; the
  benefit (fewer polls) doesn't clearly outweigh that cost given no confirmed rate
  limit exists yet to motivate it.

### Non-goals
- No changes to `run_filter` / `run_sender` or the `Ad.status` state machine.
- Write endpoints (post/edit/top/report) are out of scope for scraping.

---

## 9. Appendix — key source references

| Fact | File |
|------|------|
| Base-URL-per-country enum | `sources/kg/g.java`, `sources/kg/{a,b,e,f}.java` |
| Retrofit build / base url | `sources/…/shared/core/data/retrofit/RetrofitFactory.java` |
| Headers, UA, token, device-id | `sources/…/shared/core/data/retrofit/OkHttpClientFactory.java` |
| GUID handshake | `sources/…/feature/guid/data/retrofit/GuidInterceptor.java`, `GuidApiDescription.java` |
| Search endpoint + query map | `sources/…/feature/ad/data/retrofit/AdApiDescription.java`, `AdRetrofitDataSource.java` |
| `query` serialization | `sources/bi/a.java`, `…/feature/search/domain/SearchOptions.java` |
| Sort values | `sources/td/b.java` |
| Response model | `sources/…/feature/ad/data/retrofit/ApiAd.java` |
| Other endpoints | `sources/…/feature/{search,section,category,profile,agent,image,confirm,itemselection/location}/data/retrofit/*ApiDescription.java`, `sources/…/model/api/ApiDescription.java` |
| Current HTML scraper (baseline) | `bazos/scraping/bazos/bazos_scraper.py` |
| Faithful app User-Agent construction | `USER_AGENT.md`, `bazos/scraping/bazos/user_agent.py` |
| Live probe evidence for all §4–§7 findings | curl commands in §7, run directly against `www.bazos.cz`/`www.bazos.sk` on 2026-07-19 |
</content>
</invoke>
