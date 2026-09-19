---
title: Vinted — the v2 API is gone; the catalog page is the replacement
status: reference
updated: 2026-09-18
verified: 2026-09-18
---

# Vinted — the v2 API is gone; the catalog page is the replacement

> **Verdict: VIABLE, via a different transport.** Everything below was measured live against
> `vinted.cz` on **2026-09-16** from a residential Czech connection, unauthenticated, with no
> third-party library. Claims not measured are marked ⚠️ ASSUMED.
>
> **Re-probed live 2026-09-18** - the repo's own `pytest -m live
> bazos/tests/live/test_vinted_contract.py` (6 checks, all green) plus one extra catalog fetch.
> Unchanged: 96 rows on page 1, `per_page: 96` / `total_entries: 960` / `total_pages: 10`,
> `sortBy` and `catalogIds` echoed back, `price.amount` still a decimal string, `itemBox`
> `firstLine`/`secondLine` at 96/96, ids still past int4 (max seen `10049733256`). **Not**
> re-probed, so still carrying their 2026-09-16 date: §3's condition-id table, §6b's price-band
> measurement, §8's detail page, §10's burst run and robots.txt.
>
> This supersedes the API facts in [`VINTED_SCRAPER.md`](../../archive/shipped/VINTED_SCRAPER.md)
> and [`VINTED_SCRAPER_DESIGN.md`](../../archive/shipped/VINTED_SCRAPER_DESIGN.md). Those two
> remain the record of *why the shipped scraper looks the way it does*; their §1a field tables now
> describe an endpoint that no longer exists. The field-mapping traps they record (integer
> overflow, decimal prices, detail-fetch failures aborting a pass) are still real and still apply.

---

## 1. What broke, exactly

`RuntimeError: Cannot perform API call to endpoint /api/v2/catalog/items, error code: 404`
— first seen 2026-09-08, still firing. The `vinted-scraper` package is not at fault and no
version of it will fix this.

Measured, with a valid anonymous session (`access_token_web` cookie present):

| probe | result | reading |
|---|---|---|
| `GET /api/v2/catalog/items?search_text=macbook` | **404**, HTML body, `<title>La page n'existe pas</title>` | route removed |
| `GET /api/v2/items/<id>` | **404**, same HTML | route removed |
| `GET /api/v2/catalog` , `/api/v2/search`, `/api/v2/catalog/filters` | **404** | route removed |
| `GET /api/v2/users/current` | **403** `{"code":106,"message":"Přístup zamítnut","message_code":"access_denied"}` | **route alive**, needs auth |
| `GET /api/v2/item_upload/items/<id>` | **403**, same JSON shape | **route alive**, needs auth |
| `api.vinted.com`, `/api/v3/...`, `/web/api/...`, `/next/api/...` | 404 | no relocated base |

So `/api/v2` still routes — the client bundle still defines `API_BASE_PATH = "/api/v2"` — but the
**anonymous catalog-search and item-read endpoints were withdrawn**. The distinction matters: a
403 with a JSON error body is a live endpoint refusing us; the 404 HTML page is a route that no
longer exists. No amount of header or cookie work brings the catalog endpoints back.

⚠️ ASSUMED (not tested, and I did not test it): whether logging in restores them. Not worth
pursuing — it trades an anonymous read for an account that can be banned.

**The site itself is unaffected.** `https://www.vinted.cz/` returns 200 and sets a full anonymous
session in one request. The data is all still there; it moved from an API into the page.

## 2. The replacement transport: server-rendered Next.js

Vinted's web app is now Next.js App Router (`x-next-app: marketplace-web`, `x-powered-by: Next.js`).
The catalog page **server-renders the complete result set into the HTML** as React Server
Component "flight" data, in `self.__next_f.push([1,"<json-ish chunk>"])` script tags.

Two ways to read it, same bytes either way:

1. `GET /catalog?...` as HTML, concatenate the `__next_f` chunks, JSON-unescape.
2. `GET /catalog?...` with header **`RSC: 1`** → `Content-Type: text/x-component`, the flight
   payload raw, no HTML wrapper and no unescaping step. This is what the client itself uses for
   in-app navigation. **Prefer this** — it removes a parsing step and one class of breakage.

⚠️ Adding `Next-Router-Prefetch: 1` returns a 471-byte stub with no items. Don't.

**Cost, measured:** 803 KB on the wire (gzip), ~7.2 MB decompressed, ~1.2 s, for one page of 96
items. That is ~16× the old API response for the same data. Most of the payload is the full i18n
string table and the entire 2 920-node catalog tree, shipped on every page. There is no leaner
variant — no partial-segment fetch was found that returns items alone.

Session bootstrap: one `GET /` sets `access_token_web` (JWT, `scope: public`, **24 h**) and
`refresh_token_web` (90 d), plus `anon_id` and `v_udt`. A plain `requests.Session` with a browser
`User-Agent` gets all of it in one hop. **Without a `User-Agent` the API path 403s**; with one,
the catalog page works. No JS execution, no cookie solving, no headless browser.

## 3. Search parameters — all measured working

Query string on `/catalog`. Repeated params use PHP-style `[]` brackets.

| param | example | effect | notes |
|---|---|---|---|
| `search_text` | `macbook` | free-text query | ⚠️ **fuzzy — see §4** |
| `catalog[]` | `3580` | category filter | repeatable; ids in §9 |
| `brand_ids[]` | `54661` (Apple) | brand filter | repeatable |
| `brand_collection_ids[]` | `8565` (MacBook Pro 2019) | **model** filter | repeatable; the most precise filter Vinted has |
| `status_ids[]` | `2` | item condition | repeatable; mapping below |
| `price_from` / `price_to` | `1000` / `5000` | price bounds | ⚠️ **applies to `price`, not `totalItemPrice` — see §6** |
| `currency` | `CZK` | currency for the bounds | send it with the bounds |
| `order` | `newest_first` | sort | also `relevance` (default), `price_low_to_high`, `price_high_to_low` |
| `page` | `2` | 1-based page | max 10 — see below |
| `time` | `1789545926` | pagination snapshot | echoed back; see §7 |

Every one of these is reflected back in the payload at `initialCatalogState.filters`, which is how
you verify a param was understood rather than ignored. Unknown params are silently dropped — so
**assert on that echo, never on "the response was 200"**.

**Condition ids** (`status_ids[]`), measured by probing each id and reading back the rendered labels:

| id | label (cs) | meaning |
|---|---|---|
| 1 | Nový bez visačky | new without tags |
| 2 | Velmi dobrý | very good |
| 3 | Dobrý | good |
| 4 | Uspokojivý | satisfactory |
| 5 | — | returns nothing; unused |
| 6 | Nový s visačkou | new with tags |
| 7 | **Omezená funkčnost** | **limited functionality / faulty** |

⚠️ **The condition id on an item page is a different namespace.** An item detail page reports
`status: {"id": 50, "value": "Velmi dobrý"}`. Passing `status_ids[]=50` returns **zero** results;
the filter value for that same condition is `2`. Do not feed one into the other.

`status_ids[]=7` is a direct, structured handle on broken goods — better than the damage-word
heuristic `bazos/pricing/` currently gates on.

**Pagination**: `per_page` is fixed at **96** server-side and is not a settable param any more.
`total_entries` is **capped at 960** (`total_pages: 10`) for any broad query — a narrow one reports
its true count (`brand_collection_ids[]=8565` → 151, 2 pages). So 960/10 means "at least 960",
not 960. Pages 1 and 2 shared 1 of 96 ids, i.e. minor drift, not duplication.

## 4. ⚠️ Why the old scraper surfaced irrelevant ads — and the fix

This is the most useful finding here.

`search_text=macbook`, `order=newest_first`, first page of 96: **74 titles contained "macbook";
22 did not.** The misses were not near-misses — they included Nike and Adidas windbreakers, a Puma
hoodie, a leather briefcase and a Mango-style handbag. Vinted's text matching is semantic and
padded; it is not a keyword search.

Two distinct causes, and they need different answers:

**(a) Promoted items are injected and are frequently unrelated.** 8 of 96 rows carried
`isPromoted: true`, and *all six* of the clothing items were among them. They are Vinted's
equivalent of a Bazos TOP ad — and, like TOP ads, they sit out of chronological order.

**(b) The text matcher itself is loose** even excluding promotions: `HP ProBook 460 G11`,
`Apple Magic Mouse`, `Cabel usb. C`, `iMac 27"`, `Flashdisk Microsoft Office`.

**The fix is to stop searching by text.** Structured filters are exact:

```
/catalog?catalog[]=3580&brand_ids[]=54661&order=newest_first
```
→ **96 of 96 genuine Apple laptops.** Same page size, same cost, no junk. Narrowing further with
`brand_collection_ids[]` pins an individual model generation.

`filter_required` remains worth keeping as a backstop, but it is no longer the primary defence, and
on Vinted it was always a weak one — it matches `name + short_description`, and §5 explains why
`short_description` was empty for every Vinted ad.

**Re-measured 2026-09-18, same filter pair: 96 of 96 again** - and this sample adds a second
point. Only **88** of the 96 titles contain the string "macbook" at all; the other eight are
genuine Apple laptops whose sellers typed `MackBook Pro 13"`, `MaxBook Air 13`, `Mackbuk`,
`Mackbook Air 11`, `Mac Book Air 2017`, `McBook Air 13 palcu`, `MackBook Neo (512gb)` or
`Prodám notebook apple`. `itemBox.firstLine` normalises every one of them to `Apple MacBook …`
(§5.1). So on a structurally-filtered query the keyword backstop is now the *lossy* half: a
`filter_required=["macbook"]` would reject 8 of the 96 ads the filter pair got right. Keep it for
`search_text` queries; drop it for `catalog[]`+`brand_ids[]` ones, or key it on the normalised
`short_description` rather than the seller's spelling.

### ⚠️ `searchScore` is not a relevance signal — do not filter on it

Each row carries `catalogTracking.searchScore`, and it is tempting: 1.0015 for the first result,
0.5002 for the second, 0.3359 for the third. It looks like a confidence.

It is **reciprocal rank**. Measured against `1/position` across all 96 rows, the ratio stays within
1.00–1.06 end to end (rank 1 → 1.0015, rank 50 → 0.0212 vs 0.0200, rank 96 → 0.0106 vs 0.0104). It
carries no information beyond the position you already know. A threshold on it would be a
disguised "take the first N".

## 5. The listing payload — one item, complete

At `…"items":{"items":[…]}` in the flight payload. Per row: `{id, productItem, catalogTracking}`.
`productItem` is the whole of it — **camelCase now, not the old snake_case**:

| field | example | maps to |
|---|---|---|
| `id` | `10018454667` | `external_id` — ⚠️ **still exceeds int4**, `BigIntegerField` is load-bearing |
| `title` | `"HP ProBook 460 G11"` | `name` (truncate to 120) |
| `url` | `"/items/10018454667-hp-probook-460-g11"` | `url` — ⚠️ **relative now**; join onto the base URL |
| `price` | `{"amount":"17999.00","currencyCode":"CZK"}` | ⚠️ **decimal string**, not a float — see §6 |
| `serviceFee` | `{"amount":"917.95",…}` | buyer protection fee |
| `totalItemPrice` | `{"amount":"18916.95",…}` | what the buyer pays |
| `priceWithDiscount` | `null` | bundle/discount price when set |
| `isPromoted` | `false` | **`topped`** — the dedup walk depends on this |
| `favouriteCount` | `0` | closest available interest signal |
| `user` | `{"id":82522864,"isBusiness":false,…}` | stable seller id + dealer flag |
| `photos[]`, `thumbnailUrl(s)`, `dominantColor` | — | free, no extra request |
| `itemBox` | see below | **the short-description surrogate** |

### 5.1 ✅ There *is* a usable short description at listing level

The old scraper stored `short_description=""` for every Vinted ad, which quietly disabled both
keyword rules. That is now fixable **without a detail fetch**. `productItem.itemBox` carries:

```json
{"firstLine": "Apple MacBook Pro 2019",
 "secondLine": "Velmi dobrý",
 "accessibilityLabel": "MacBook Pro 16”, Značka: Apple, Model: MacBook Pro 2019, Stav: Velmi dobrý, 13000.00 Kč, 13668.00 Kč"}
```

- `firstLine` = brand + model generation, normalised by Vinted (not seller-typed).
- `secondLine` = condition.
- `accessibilityLabel` = title, brand, model, condition and both prices in one string.

**Coverage: 96/96 on all three fields**, across two different queries. Length of
`accessibilityLabel`: min 87, max 179, mean 118 characters (re-measured 2026-09-18: min 67, max
167, mean 114). Short either way, and `Ad.short_description` has been a `TextField` since
migration `0035`, so there is no column width left to fit inside.

`firstLine + secondLine` is the honest `short_description`: it is descriptive, it is not a
duplicate of the title, and it makes `blocklist_keyword` / `required_keyword` work on Vinted for
the first time. It is *not* the seller's prose — that still needs §8's detail fetch.

### 5.2 What is genuinely absent

- **No description.** Confirmed absent from every listing row.
- **No publish date, in any form.** Not in the listing, and **not on the detail page either** — I
  scanned the item page's full 1.75 MB payload for unix timestamps and ISO dates and found only
  unrelated Braze config. The only date is relative display text (`"před hodinou"`, `"včera"`).
  **Keep `publish_date=None`.** The repo already paid for the alternative once: synthesised dates
  are what made `BazosScraper.extract_date` produce all-midnight values.
- **No view count.** `view_count` appears in the payload only as i18n template strings; the number
  is not served to non-owners. Keep `None`, not `0`.
- **No location.** Vinted is shipping-first; no city, region or postal code is exposed. `location=""`
  stays correct, and `location_distance` stays inapplicable — as it already is for Sbazar.

## 6. ⚠️ Price traps — three of them, all new

**(a) Prices are decimal strings, not floats.** `{"amount": "17999.00"}`. The old
`parse_price` strips non-digits, so `"6307.5 CZK"` parsed to `63075`. Parse `amount` with
`Decimal`, round once, and format the integer.

**(b) The server-side price filter uses `price`, the scraper stores `totalItemPrice`.** Measured
on `price_from=1000&price_to=5000`: every returned row satisfied `1000 ≤ price ≤ 5000`, and the
returned `totalItemPrice` ranged **1088.73 – 5268.00** — outside the requested band. So a query
with `price_upper=5000` returns items the local `price_range` rule then **rejects**, because the
shipped scraper writes `total_item_price` into `Ad.price`. Today that is an invisible waste of
requests; it becomes a silent correctness bug the moment both filters are relied on.

Pick one and be consistent. Storing `price` (ex-fee) makes the server filter and the local rule
agree and matches what every other marketplace in this repo stores — a headline price. Storing
`totalItemPrice` is the honest deal-hunting number but then `price_from`/`price_to` must not be
sent, or must be sent widened.

**(c) Cross-border FX is unchanged and still dominant.** Most `vinted.cz` tech results are Polish
sellers with FX-converted CZK prices (`1385.41`, `5098.70`). The domain selects buyer currency, not
seller geography: `.sk` → EUR, `.pl` → PLN, all with the same page structure and the same 96/page.
⚠️ On the **detail** page, JSON-LD `offers.price` is the **seller's** currency (a `.cz` listing
returned `2500 PLN`), while the listing row showed converted CZK. **Never overwrite a price from
the detail page.**

## 7. Ordering and dedup — `newest_first` is genuinely chronological

`order=newest_first` is honoured (`sortBy: "newest_first"` echoes back). Verified by walking down
one result page and reading each item's own relative upload date:

| position | promoted | "Vystaveno" |
|---|---|---|
| 0 | no | před minutou |
| 3 | no | před hodinou |
| 10 | no | před 9 hodinami |
| 25 | no | před 15 hodinami |
| 50 | no | **včera** |
| 75 | **yes** | před 15 hodinami |
| 95 | **yes** | před 19 hodinami |

Monotonic for non-promoted rows; the two promoted rows sit far out of place. This is exactly the
Bazos TOP-ad shape, so `run_existing_query`'s existing continue-on-topped / break-on-known walk
works unchanged **provided `isPromoted` is mapped to `Ad.topped`**.

⚠️ **Item ids are not chronological — do not use them as a recency proxy.** Among the 88
non-promoted rows there were 36 id inversions, mean positional displacement 14.9, max 61. Ids are
evidently assigned when a draft is created, not when it is published. Sorting or deduping on id
order would be wrong; dedup on `external_id` equality, which is what the pipeline already does.

## 8. The detail page — richer than it used to be

`GET /items/<id>-<slug>`, same flight transport. Two clean extraction points:

**JSON-LD** (`"jsonLd":{…}`) — a schema.org `Product` with `name`, `description`, `image`,
`brand`, `offers{price, priceCurrency, availability, itemCondition}`, `category`. **Description
present on 3/3 items probed**, against the old library's OpenGraph scrape at 5/8. Also mirrored
into `<meta name="description">`.

**Structured attributes** — a typed spec list, which is the genuinely new capability:

```
computer_cpu_line       Procesor            Intel Core Ultra 9
computer_ram            RAM                 16 GB
computer_storage_capacity  Kapacita úložiště  1 TB
computer_operating_system  Operační systém   macOS
laptop_display_size     Velikost obrazovky  16″–17,9″ (40–44 cm)
laptop_charger_included Zahrnuje nabíječku  Zahrnuje
status                  Stav                Velmi dobrý   (id 50 — see §3)
upload_date             Vystaveno           před hodinou
```

Plus `breadcrumbs` (full catalog path with ids), and a seller block: `name` (login),
`seller_id`, `business`, `feedback_count`, `feedback_reputation`.

`docs/research/PRICE_MODEL_BENCHMARK.md` §3.1 names feature **extraction** — not model class — as
the measured weak point. Vinted hands over RAM, storage and CPU as typed fields rather than prose
to be regexed out of a description. That is the strongest argument in this document for doing the
rewrite properly rather than patching.

## 9. Taxonomy — 2 920 categories, free on every page

Every catalog page ships the entire tree. One request yields 2 920 `(id, title, slug)` nodes,
extractable with a single regex over the flight payload. Relevant spine:

```
2994  Elektronika              /catalog/2994-electronics
 3564  Počítače a příslušenství /catalog/3564-computers-and-accessories
  3580  Notebooky               /catalog/3580-laptops
  3581  Stolní počítače         /catalog/3581-desktop-computers
  3582  Počítačové díly         /catalog/3582-computer-parts-and-components
 3565  Mobilní telefony         /catalog/3565-mobile-phones-and-communication
  3661  Mobilní telefony        /catalog/3661-mobile-phones
 3567  Tablety a čtečky         /catalog/3567-tablets-e-readers-and-accessories
 3566  Audio, sluchátka, hi-fi  /catalog/3566-audio-headphones-and-hi-fi
 3054  Fotoaparáty a kamery     /catalog/3054-cameras-and-accessories
 3002  Hry a konzole            /catalog/3002-video-games-and-consoles
```

The `/catalog/<id>-<slug>` URL form means an operator can read an id straight out of the address
bar, so a seeded lookup table is a convenience, not a prerequisite.

Brand and model ids are **not** in the page — the brand/model filter option lists are lazy-loaded
(`isLazy: true`, `options: []`), and a catalog page contains no `/brand/` link at all (re-checked
2026-09-16: zero occurrences). Read them off an **item** page instead: the `brand` attribute carries
`id` + `/brand/54661-apple`, and `model_nav` carries `brand_collection_ids=8565`.

Harvested that way from four electronics catalogs, 2026-09-16 — enough to convert a query without
hunting:

| `brand_ids[]` | brand | | `brand_ids[]` | brand |
|---|---|---|---|---|
| `54661` | Apple | | `472684` | MSI |
| `109048` | Samsung | | `229494` | Dell |
| `201078` | Xiaomi | | `314542` | Lenovo |
| `441470` | OPPO | | `19553` | Amazon |
| `520598` | Doogee | | `431006` | Bowers & Wilkins |

⚠️ `1` is `emptybrand` — the sentinel for a listing with no brand set, not a real brand. Filtering
on it selects unbranded listings, which is almost never what is wanted.

## 10. Anti-bot, rate limits, robots

- **10 back-to-back catalog fetches, no delay: all HTTP 200**, 1.17–1.50 s each, full 96 rows every
  time. No 429, no challenge, no degradation. Consistent with the 2026-08 finding.
- Cloudflare (`__cf_bm`) and DataDome are in front of the site. DataDome's SDK string appears in
  every page — **do not test for a block by grepping for "datadome"**; it is present on healthy
  pages. Test for a block by checking whether items parsed.
- The request without a `User-Agent` got a DataDome interstitial on the API path. Sending a normal
  browser UA avoided it everywhere.
- ⚠️ **Tor untested here** — the local Tor container was not running (9050 closed). The standing
  finding that Vinted blocks proxy/VPN egress is unverified in this round. The shipped scraper
  bypasses Tor for Vinted anyway; keep it that way until measured otherwise.
- **`robots.txt` permits what this needs.** `User-agent: *` disallows only `/checkout`, `/util`,
  `/apipie/`, `/admin_alert/new`, `/member/`, `/inbox`. `/catalog` and `/items` are allowed, and no
  `Crawl-delay` is set. Note separately that `GPTBot`, `ClaudeBot`, `CCBot`, `Google-Extended` and
  `Amazonbot` get a blanket `Disallow: /`, and the file asserts `ai-train=no` — a restriction on
  model training and AI crawlers, not on a personal notification scraper, but worth knowing it is
  stated.

## 11. Feature parity with the Bazos HTML scraper

| capability | Bazos | Vinted (measured) |
|---|---|---|
| text search | ✅ | ⚠️ fuzzy — prefer `catalog[]` + `brand_ids[]` (§4) |
| category / section | ✅ | ✅ `catalog[]`, 2 920 ids |
| price bounds | ✅ | ✅ ⚠️ applies to ex-fee price (§6b) |
| condition filter | ❌ | ✅ `status_ids[]`, incl. "faulty" |
| brand / model filter | ❌ | ✅ `brand_ids[]`, `brand_collection_ids[]` |
| newest-first order | ✅ | ✅ verified chronological (§7) |
| "topped" ads | ✅ | ✅ `isPromoted` |
| pagination | ✅ unbounded | ⚠️ 96/page, **10 pages max** |
| short description on listing | ✅ | ✅ via `itemBox` (§5.1) — new |
| full description | ✅ detail GET | ✅ detail GET, JSON-LD, 3/3 |
| structured specs | ❌ | ✅ RAM/CPU/storage typed (§8) — new |
| publish date | ✅ | ❌ relative text only |
| view count | ✅ | ❌ not served |
| location / distance | ✅ | ❌ not served |
| seller identity | opaque id pair | ✅ stable id + login + business flag |
| blocked-IP signal | 403 + IP in body | none observed |

## 12. Reproducing this

No dependencies beyond the standard library; `vinted-scraper` is not needed and should be dropped.
(Done - the rewrite landed on 2026-09-16 and `vinted-scraper` no longer appears in
`pyproject.toml`; the shipped transport is `bazos/scraping/vinted/client.py`.)

```python
import gzip, json, re, urllib.request, http.cookiejar

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " \
     "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def get(url, rsc=False):
    h = {"User-Agent": UA, "Accept-Language": "cs-CZ,cs;q=0.9", "Accept-Encoding": "gzip"}
    if rsc:
        h |= {"RSC": "1", "Accept": "text/x-component"}
    r = opener.open(urllib.request.Request(url, headers=h), timeout=40)
    b = r.read()
    return gzip.decompress(b).decode("utf-8", "replace") if \
        r.headers.get("Content-Encoding") == "gzip" else b.decode("utf-8", "replace")

get("https://www.vinted.cz/")                       # one hop: full anonymous session
body = get("https://www.vinted.cz/catalog?catalog[]=3580&brand_ids[]=54661"
           "&order=newest_first", rsc=True)         # flight payload, no HTML wrapper

i = body.index('"items":{"items"')                  # then balanced-scan the array from '['
```

Re-run before relying on any of this. It is a server-rendered page with no stability guarantee —
weaker than an API contract, which is precisely how the previous implementation died. The repo's
`contract-check.yml` job exists for this reason and should be extended to cover Vinted.
