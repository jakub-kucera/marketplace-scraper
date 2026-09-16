---
title: Zboží.cz — the `/api/v3` surface, measured
status: reference
updated: 2026-09-16
verified: 2026-09-16
---

# Zboží.cz — the `/api/v3` surface, measured

> Re-probe of 2026-09-16 from CESNET Prague (`147.32.96.2`, AS2852 — academic NAT, a third
> vantage point after the 2026-08-22 VPN datacenter IP and the residential re-test).
> ~120 requests, none blocked, none throttled.
>
> **This supersedes the transport and join findings of
> [`HEUREKA_ZBOZI.md`](HEUREKA_ZBOZI.md).** That file's verdict rested on the only search
> endpoint it happened to find. There is a documented JSON API it never located, it is
> robots-**allowed**, and it carries fields — `medianPrice`, `productNo`, `releaseDateUTC` —
> that change three of that file's conclusions. Heureka.cz itself is unchanged: still blocked.

---

## 1. What the previous assessment got wrong, and why

Five corrections, each measured. They are listed first because the old file is long and
persuasive, and three of its headline claims are false.

| `HEUREKA_ZBOZI.md` claim | Status | What is actually true |
|---|---|---|
| *"The join step is exactly the step robots.txt forbids"* (§4c, §7b, §7c — its compliance crux) | **FALSE** | It found only `/_next/data/<buildId>/hledej.json?q=`, which `Disallow: /*?q=` does catch. The pair that actually resolves a name is `/suggestV2?phrase=` + `/api/v3/product/<slug>/`, and **both are explicitly allowed** — verified with a real `RobotFileParser`, §4. |
| *"Neither site exposes EAN/GTIN… no identifier to key on"* (§4a) | **Misleading** | No EAN, correct. But the field `productNo` carries the **manufacturer part number** (`MLPJ3CN/A`, `DCD796D2-QW`, `SM-X520NZAREUE`). §4a grepped for `mpn`/`partNumber`/`sku` and missed it on spelling. Present on roughly half of catalogued products. |
| *"Zboží.cz has no canonical product entry for a 2020 MacBook Pro at all"* (§4c, the finding that made it REJECT) | **Not established** | A 2017 MacBook Pro 13 **is** catalogued (`apple-macbook-pro-13-cz-2017-mpxu2cz-a`, id `5336161`, `productNo MPXU2CZ/A`). The catalogue retains discontinued entries; **suggest cannot reach them** because it ranks by current commercial relevance, and they decay to `shopCount ≤ 1`. "Unreachable and priceless" is a different defect from "absent", with a different fix. |
| *"`minPrice`/`maxPrice` … prefer JSON-LD if only the range is needed"* (§5) | **Superseded** | There is a **`medianPrice`**, in both the API and `__NEXT_DATA__`. It is the field this project should use: §5a's mis-pairing defect (an iPhone 13 **mini** offer setting the iPhone 13's `minPrice`) is still live today, and it poisons `min`, not `median`. |
| *"`buildId` … will rotate on every release, silently 404-ing the data route"* (§3b) | **True but now irrelevant** | Confirmed rotated (`qKaIrxCbar6XQmnqpuYPF` → `ymhild8AjF8v2O4u7p80Q` in 25 days). The `/api/v3/` surface **takes no buildId**, so the stability risk the old file called out does not apply to the path recommended here. |

One old finding is reconfirmed and should not be softened: **there is no official third-party read
API.** Every Heureka interface is merchant-side. `api.heureka.cz` → 404. Nothing here is supported;
all of it is the website's own XHR surface and can change without notice.

---

## 2. Heureka.cz — still blocked, from a third vantage point

```
GET https://mobilni-telefony.heureka.cz/apple-iphone-13-128gb/
HTTP/2 403 | cf-mitigated: challenge | server: cloudflare | cf-ray: …-PRG
<title>Checking security</title>
```

Identical to the 2026-08-22 result: immediate Cloudflare managed challenge, zero `ld+json`,
zero `__NEXT_DATA__`. Three egress types now (datacenter VPN, residential, academic) and the
content surface has never rendered to a plain client. `www.heureka.cz/robots.txt` still 200s, and
`www.heureka.cz/api/v1/product/` 404s **without** a `cf-mitigated` header — so the challenge is
scoped to content paths, not the whole host.

**Recommendation: treat Heureka as unavailable and build on Zboží.** Heureka does have a price
history feature (the affiliate kit sells a *Graf ceny produktu* widget), so it is a real capability
behind a real wall — worth a provider slot in the design, not worth engineering effort now. No
challenge-solving was attempted and none should be.

---

## 3. The API

Base is `API_PATH = "/api"`, recovered from `_app-*.js`:

```js
{DEVEL:!1, API_PATH:"/api", SUGGEST_URL:"/suggestV2", LOGIN_SERVICE_ID:"zbozi", …}
```

No auth, no cookie, no token, no buildId on any endpoint below.

### 3a. `GET /suggestV2?phrase=<text>` — name → candidate slugs

```bash
curl -s 'https://www.zbozi.cz/suggestV2?phrase=makita%20dhp484'
```
```json
{"suggestProductItems":[
   {"sentence":"Makita DHP484Z Li-ion 18 V","normalizedName":"makita-dhp484z-li-ion-18-v","imageUrl":"…"},
   {"sentence":"Makita DHP484RFJ","normalizedName":"makita-dhp484rfj"}],
 "SuggestOffer":[{"sentence":"makita dhp484z"}], "SuggestEshops":[], "status":200}
```

`normalizedName` is exactly the slug §3b takes. **Note the trailing slash matters**: `/suggestV2/?phrase=`
is a 404, `/suggestV2?phrase=` is a 200. Behaviour and limits in §5.

### 3b. `GET /api/v3/product/<slug>/?filterFields=…` — the product

`filterFields=$all$` returns everything (29.4 KB). A named field list returns **261 B** — a 113×
reduction, and the difference between a service that is cheap to run and one that is not:

```bash
curl -s 'https://www.zbozi.cz/api/v3/product/apple-iphone-13/?filterFields=displayName,minPrice,medianPrice,maxPrice,shopCount,productNo,releaseDateUTC,vendorName,categoryId,id,availability'
```

Fields that matter, measured on `apple-iphone-13`:

| Field | Example | Notes |
|---|---|---|
| `id` | `6712579` | integer, stable-looking; the key for §3c |
| `normalizedName` | `apple-iphone-13` | the slug |
| `minPrice` / **`medianPrice`** / `maxPrice` | `649900` / **`724000`** / `1095000` | **hundredths of CZK.** Divide by 100 exactly once, at the provider edge |
| `shopCount` | `4` | **< 2 means the price is one merchant's opinion, not a market** |
| `availability` | `in_stock` | lifecycle signal |
| `productNo` | `MLPJ3CN/A` | **manufacturer part number**, present ~50 % of the time |
| `vendorName` / `vendor.id` | `Apple` / `17819163333647859135` | structured brand; the id is a **string** |
| `categoryId` / `rootCategoryId` | `81` / `69` | the cheapest sanity gate — see §5 |
| `releaseDateUTC` | `1631570400` | unix s. **Catalogue-entry date, not manufacture date** — Makita DHP484Z reads 2017-06 |
| `parameterGroups` | structured specs | enum/numeric attributes per category |
| `variants[]` | 18 entries | each with own `id`, prices, `offerCount`, `url` |
| `productGroup.priceComparsion` | `{minValue, maxValue, intervals[]}` | a **price histogram over the whole category** (1 418 smartphones) — a percentile baseline for free |
| `productParentHits` | `{parentHitsPerPeriod:352, parentHitsPeriodDays:7}` | popularity |
| `bestOffers` / `cheapestOffers` | offer objects | **include used/refurb "Stav B" listings** — see §6 |

An unknown slug returns HTTP 404 with `{"status":404}` in the body.

### 3c. `POST /api/v3/pricetrend/product-v3/<productId>` — price over time ⭐

The endpoint the previous assessment never found, and the one that answers "what has this been
worth". Recovered from a lazily-loaded chunk named `price-trends`
(`/_next/static/chunks/price-trends.<hash>.js`; the chunk-id→hash map is in `webpack-*.js`).

```bash
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"monthsBack":13}' \
  'https://www.zbozi.cz/api/v3/pricetrend/product-v3/5325309'
```
```json
{"status":200,"pricePoints":[
  {"minPriceHa":319000,"medianPriceHa":415000,"maxPriceHa":500000,"date":1754006400}, …]}
```

- `…Ha` = **haléře**, hundredths of CZK. Same ×100 trap, different field names.
- `date` is unix seconds.
- `monthsBack` 1 → 29 points, 13 → 101, 24 → 111, 60 → 118. The archive is **~24–30 months**;
  asking for more does not invent it. Granularity is monthly early, near-daily in recent months.
- `minPrice`/`medianPrice`/`maxPrice` in the body are **client-side hints only** — the series is
  byte-identical without them (the client appends them as "today"). Send `{"monthsBack":N}` alone.
- A sibling `POST /api/v3/pricetrend/offer/<offerId>` takes `{daysBack, priceTrendOfferIds}`.

**Two 13-month series, and the whole lifecycle thesis in one table:**

| month | iPhone 13 min / median | Makita DHP484Z min / median |
|---|---|---|
| 2025-08 | 10 486 / 10 728 | 3 190 / 4 150 |
| 2026-01 | 7 990 / 10 220 | 2 490 / 3 930 |
| 2026-09 | **6 499 / 7 240** | **2 920 / 3 813** |

The phone lost **38 %** of its median in 13 months; the tool moved **−8 %** and oscillated inside
it. A single-point "new price" baseline means something quite different for these two, and only the
series tells you which case you are in. (Note the tool's 2026-03 `min` of **484 Kč** — a mis-paired
accessory offer. `min` is not usable; `median` is.)

---

## 4. robots.txt — the whole recommended path is allowed

Checked against `zbozi.cz/robots.txt` (444 lines) with Python's `RobotFileParser`, `User-agent: *`:

| Path | Verdict |
|---|---|
| `/suggestV2?phrase=…` | **ALLOW** — no rule matches; it is not a `?q=` URL |
| `/api/v3/product/<slug>/?filterFields=…` | **ALLOW** — `Allow: /api/` |
| `/api/v3/pricetrend/product-v3/<id>` | **ALLOW** — `Allow: /api/` |
| `/vyrobek/<slug>/?varianta=…` | **ALLOW** — longest-match beats `Disallow: /vyrobek/*?*=*` |
| `/_next/data/<buildId>/hledej.json?q=…` | **DENY** — `Disallow: /*?q=` |
| `/hledej/?q=…` | **DENY** ×3 |
| `/nabidka/<offerId>/` | **DENY** |

`Allow: /api/` appears **twice** in the `*` block. Read plainly, Zboží disallows its rendered search
result pages (an SEO-duplicate-content concern) and permits its API. That is close to the opposite
of the previous file's reading, which called the disallow "unusually precise … drawn exactly around
the capability the idea needs".

**Terms of Service: still NOT DETERMINED.** `napoveda.zbozi.cz/podminky-pouzivani/` 200s but serves
the Sklik/merchant help navigation, not consumer terms; the two Seznam general-terms URLs tried
404'd. robots.txt is not a contract and this gap is unclosed — the same gap
`HEUREKA_ZBOZI.md` §11.4 left open.

---

## 5. The join, honestly — where it works and how it fails

The join is `suggest → validate candidates → product`. It is **not** "take result 0".

**Measured failure modes of top-1** (8 of 17 archetypes wrong or empty):

| Query | Top-1 suggestion | Why it is a trap |
|---|---|---|
| `Samsung Galaxy S10` | *Samsung Galaxy Tab S10 FE* — 13 825 Kč | a **tablet**; the real S10 is at rank **3** |
| `Apple MacBook Pro 13 2020` | *MacBook Pro 14" M5 2025* — 47 370 Kč | five-years-newer machine; baselines a 2020 laptop at 47 k |
| `Dell XPS 13 9310` | *DELL Premier Pro XPS 13 (460-BCCU)* — 262 Kč | an **accessory**; the 999 Kč phone-case trap again, in a new category |
| `Xiaomi Redmi Note 8 Pro` | *Sligo Smart Magnet Pro …* | a phone **case** |
| `Shimano Deore XT M8100` | *Deore XT M8000* — 308 Kč | **wrong generation** and accessory-priced |
| `MacBook Pro 13` | 6 sleeves/cases before a real MacBook at rank 6 | accessories dominate a discontinued base product |
| `Bosch GSB 18-2-LI`, `Lenovo ThinkPad T480`, `Apple iPhone 13 128GB` | **0 suggestions** | see the prefix note below |

**Suggest is a typeahead over titles, not a search.** Appending spec noise empties the result:
`Apple iPhone 13` → 15 candidates, `Apple iPhone 13 128GB` → **0**. Anything that resolves an ad
must first reduce a scruffy title to *brand + line + model code* and nothing else.

**The right answer is usually present but rarely first** — S10 at rank 3, iPhone 13 at rank 1,
a real MacBook at rank 6. So candidate adjudication is the whole problem, and it is a much smaller
problem than the "per-ad LLM extraction" `HEUREKA_ZBOZI.md` §4d costed.

**A rule-only validator** (brand ∈ `vendorName`, required model tokens ⊆ title tokens, reject
`{tab, mini, pro, max, …}` contrast tokens, require `shopCount ≥ 2`) run over the first 8
candidates: correct on `Apple iPhone 13`, `Sony PlayStation 5`, `Kärcher K5`,
`Specialized Rockhopper`; **correctly declined** on `Samsung Galaxy S10` (real match exists but
`shopCount < 2` — discontinued, so no usable price) and `Dell XPS 13 9310`. Two real defects:

- **`DHP484` ≠ `DHP484Z`** — exact token equality rejects the correct Makita. Model codes need
  prefix/fuzzy comparison.
- **Kits match on the member's code** — `DeWalt DCD796` selected *DCK266P2T sada aku DCD796 +
  DCF887*, a two-tool set at 7 785 Kč. Czech bundle words (`sada`, `set`, `+`) need rejecting.

Both are fixable in rules. What is not fixable in rules is genuinely ambiguous input, which is the
correct and narrow place to spend an LLM call.

---

## 6. Data quality caveats that survive

- **Mis-pairing is live.** Today's `apple-iphone-13` `cheapestOffers[0]` is
  *"Apple iPhone 13 **Mini** 128GB (Stav A) Red"*. Name-based pairing, same defect
  `HEUREKA_ZBOZI.md` §5a measured, still setting `minPrice`. **Use `medianPrice`.**
- **Offers include used stock.** `bestOffers[0]` is *"… Stav: B, Stav baterie: 100 %"*. A
  "new-price baseline" drawn from `min` is often a refurb price. `median` dilutes this; it does not
  eliminate it.
- **`shopCount ≤ 1` means no market.** Discontinued entries persist with one stale offer.
  Treat as *no opinion*, not as a price.
- **`releaseDateUTC` is a catalogue date.** Useful as a lower bound on age; not a model year.
- **Two price scales in one response** (`minPrice` vs `…PriceHa`), both hundredths. `parse_price`
  in `bazos/filters.py` strips non-digits, so an unconverted value lands 100× too large.

---

## 7. Rate limits and transport

| Property | Measured |
|---|---|
| Auth | none — anonymous, no cookie bootstrap |
| Anti-bot | none observed; `bcr.iva.seznam.cz` (which guards Sbazar) never appeared |
| Burst | 6× `/api/v3/product/` with no delay → 6× HTTP 200, 45–56 ms each |
| Sustained | ~120 requests over ~25 min → zero 429, zero challenges, zero blocks |
| Latency | suggest ~60 ms; product ~50–160 ms; pricetrend ~70 ms |
| Payload | suggest ~0.5 KB; product 261 B trimmed / 29 KB full; pricetrend ~0.8–1 KB |

**Do not route this through Tor.** It does not block, it is not the marketplace being scraped, and
Tor exits are widely 403'd by CZ sites — the `VintedScraper` precedent (ignores the injected
session, builds its own client) is the right one. ~120 requests is characterisation, not a limit;
nothing here says anything about thousands per day.

---

## 8. Reproducing the three decisive probes

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
FF='displayName,minPrice,medianPrice,maxPrice,shopCount,productNo,releaseDateUTC,vendorName,categoryId,id,availability'

# 1. name -> slug            (robots-allowed)
curl -s -A "$UA" 'https://www.zbozi.cz/suggestV2?phrase=makita%20dhp484' \
  | python3 -c "import json,sys;[print(i['normalizedName'],'|',i['sentence']) for i in json.load(sys.stdin)['suggestProductItems']]"

# 2. slug -> product+median  (robots-allowed, 261 B)
curl -s -A "$UA" "https://www.zbozi.cz/api/v3/product/makita-dhp484z-li-ion-18-v/?filterFields=$FF" \
  | python3 -c "import json,sys;p=json.load(sys.stdin)['product'];print(p['displayName'],p['medianPrice']/100,'CZK',p['shopCount'],'shops')"

# 3. id -> 13 months of prices (robots-allowed)
curl -s -A "$UA" -X POST -H 'Content-Type: application/json' -d '{"monthsBack":13}' \
  'https://www.zbozi.cz/api/v3/pricetrend/product-v3/5325309' \
  | python3 -c "import json,sys,datetime;[print(datetime.datetime.fromtimestamp(p['date'],datetime.UTC).date(),p['minPriceHa']/100,p.get('medianPriceHa',0)/100) for p in json.load(sys.stdin)['pricePoints'][-5:]]"
```

---

## 9. What is still not determined

1. **Terms of Service**, both sites (§4). The one unclosed legal question.
2. **Whether product ids are stable across re-pairing.** `id` looks durable and `productNo` gives a
   re-resolution key if it is not, but nothing was measured across time. A cached `RefProduct` table
   should store `productNo` precisely so a churned id can be recovered.
3. **Discontinued-goods reach.** Suggest cannot see them; the robots-disallowed `hledej.json?q=`
   route can (`Bosch GSB 18-2-LI` → 33 canonical products vs suggest's 0). Whether any *allowed*
   route reaches them is open — `GET /api/v1/search` answers `400 "Method not allowed"` where a
   nonsense path answers 404, so a legacy route exists, but no method/param combination tried
   reached it.
4. **Sustained-volume behaviour** (§7).
5. **Heureka behind a real browser** — not attempted, and not proposed.
