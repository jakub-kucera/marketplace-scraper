---
title: Aukro.cz — feasibility assessment
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# Aukro.cz — feasibility assessment

> **Verdict: VIABLE** — assessed 2026-08-22.
> All claims measured unless marked ⚠️ ASSUMED.
> Egress: residential Czech ISP (T-Mobile CZ, AS13036). **Everything below was unobtainable from a
> datacenter VPN IP** — see §4.1. Pass 1 concluded the opposite of this document on that basis;
> §1.1 explains the reversal.

## 1. Verdict and why

**Aukro exposes publicly-readable realised prices — final selling prices of completed auctions,
unauthenticated, going back at least 2.75 years.** That closes what `MONETIZATION.md` §7.2c calls
"the single biggest gap" in the entire project, and no other candidate in this study comes close.
Transport is a clean first-party JSON API (`/backend-web/api/…`) with no auth, no token, and a
permissive `robots.txt` — a far better posture than Sbazar's blanket `Disallow: /`. Scale clears
the bar comfortably (145,710 in computers, 162,492 in house & garden). The two real caveats are
that **Aukro's inventory skews heavily to collectibles/antiques rather than the flipping thesis's
phones-and-tools**, and that a `price.amount` **float** silently breaks the existing `parse_price`
by 10×.

### 1.1 ⚠️ This reverses the Pass 1 finding — read this before trusting either

Pass 1 concluded "do not promote; the realised-price capability looks absent." **That conclusion
was an artifact of the vantage point, not of Aukro.** From the datacenter VPN, Aukro returned
`403 cf-mitigated: challenge` on *every* path including `robots.txt`, so Pass 1 retrieved zero
bytes and reasoned from a legacy Allegro WSDL found on GitHub. Two of the three inferences drawn
from that WSDL are now **measured false**:

| Pass 1 claim (from WSDL) | Measured reality |
|---|---|
| "`ItemsListType` has `endingTime`, no start/publish timestamp — §2b's method doesn't transfer" | **False.** Both listing and detail carry `startingTime`. |
| "every sold retrieval is `doGetMy*`; realised prices are account-scoped only" | **Partly false.** Bulk *search* of ended items is indeed unavailable, but **per-item ended detail is fully public.** |
| "no public completed-auction archive (`archiv.aukro.cz` gone)" | **True** — independently re-verified by DNS with a no-wildcard control. |

The lesson is the brief's own §4d rule generalised: *a vendored third-party API description is not
evidence about the live service.* It should be treated exactly like an unrun library README.

## 2. Scale — measured

Via `POST /backend-web/api/offers/searchItemsCommon`, reading `page.totalElements`:

| Aukro category (`categorySeoUrl`) | Active listings | Bazos comparator |
|---|---|---|
| `dum-a-zahrada` (house & garden) | **162,492** | naradi 7,716 |
| `pocitace-a-hry` (computers & games) | **145,710** | notebook 7,849 |
| `mobily-a-gps` (mobiles & smart electronics) | **39,925** | iphone 6,586 |
| `cyklistika` (cycling) | **9,144** | — (Sbazar bikes 2,659) |

⚠️ These are **broad top-level categories**, not like-for-like with Bazos keyword searches — a
`pocitace-a-hry` count includes games and peripherals, so do not read "18× Bazos" off this table.
Even discounted heavily it clears the §2b bar in every target area.

**New/day: NOT DETERMINED.** Method 1 was attempted and correctly rejected rather than reported:
the default listing is relevance-sorted, so 60 items spanned 165 h in no order and implied a
nonsense 9/day and 4,574 days of inventory. A valid measurement needs newest-first ordering, which
**does exist publicly** (`MOBILE_SORTING_THE_LATEST` = "Nejnovější"), but the sort parameter name
was not resolved within budget. This is a ~2-request follow-up, not a research problem.
`METHOD_CALIBRATION.md` §3–§4 applies.

⚠️ **Relisting is first-class on Aukro** (the legacy API had `doSellSomeAgain`), so any future
new/day figure must separate genuinely-new auctions from relists or it will overstate.

### 2.1 The category-mix caveat that matters more than the totals

Aukro's top-level categories are: `antikvariat`, `bankovky`, `faleristika`, `filatelie`,
`numismatika`, `pohlednice`, `sberatelstvi`, `starozitny-porcelan`, `umeni`,
`vojenske-sberatelske-predmety`, alongside `pocitace-a-hry`, `mobily-a-gps`, `auto-moto`,
`cyklistika`, `dum-a-zahrada`. **That is a collectibles-and-antiques marketplace with a general
goods wing**, not a Bazos-shaped classifieds site. The flipping thesis (`MONETIZATION.md` §4.2)
targets phones, laptops, tools and bikes — present here, but not what the site is *for*.

The strategic read: **Aukro's value is primarily its realised-price data (§6), and only
secondarily its listing flow.** A recommendation that treats it as "another Bazos with more ads"
misreads it.

## 3. Legal

### 3.1 robots.txt — measured, quoted

Fetched `https://aukro.cz/robots.txt` → 200, **899 bytes** (contrast: Sbazar 20,013; Facebook
46,687). The entire `User-Agent: *` group disallows account/transaction paths only:

```
User-Agent: *

Disallow: /registrace*
Disallow: /overeni-uctu
Disallow: /zapomenute-heslo*
Disallow: /reset-hesla
Disallow: /kosik
Disallow: /kosik/*
Disallow: /rozhodnuti-vraceni-provize
Disallow: /blaznive-ceny-interni
Disallow: /nabidky-s-apv
Disallow: /zhave-aukce
Allow: /zhave-aukce$
Disallow: /nove-nabidky
Allow: /nove-nabidky$
```

It also advertises sitemaps:
```
Sitemap: https://cdn.aukro.cz/sitemaps/cs-cz/sitemap.xml
Sitemap: https://cdn.aukro.cz/sitemaps/cs-cz/sitemapimages.xml
```

**Item detail pages and category listings are NOT disallowed.** No blanket ban, no named-bot
allowlist scheme, no AI-crawler clause. Against the field: Bazos disallows exactly the search
endpoints the project needs; Sbazar and Sreality are default-deny; Avizo names `ClaudeBot`.
**Aukro has the most permissive robots.txt of every candidate assessed.**

### 3.2 Posture against MONETIZATION.md §3

Current posture is private use, the defensible end of §3's sorting line. Two Aukro-specific notes:

- ⚠️ **The realised-price archive is the highest-exposure asset in this study, and it is also the
  prize.** Per RESEARCH_BRIEF §6a: a historical completed-results archive is a clearer instance of
  "a database in which the maker made a substantial investment" than a live listing feed, precisely
  because it cannot be re-derived from the live site. Aukro *deleted* its public archive
  (`archiv.aukro.cz`) in 2018, which is evidence the operator regards it as proprietary. **Assembling
  a realised-price corpus by walking item ids is systematic extraction of a substantial part of
  exactly that database** (`MONETIZATION.md` §6.4, *Innoweb v Wegener*).
- The distinction that matters: reading a handful of ended items to price a purchase you are about
  to make is ordinary private use. **Systematically harvesting the archive to build a price index
  is the thing §6.4 is about**, and it is a different act with a much worse answer — especially if
  anything derived from it ever becomes public or commercial.

**ToS were NOT retrieved.** Not analysed. This is the largest open legal item (§9).

### 3.3 GDPR surface (§3e)

Per-listing PII is **lower than Bazos**: seller is an account (`userId`, `showName` pseudonym), no
email or phone in the payload. Location is town-level plus `postCode`. Bidder identity is
**deliberately anonymised by Aukro itself** (`highestBidderAnonymizedLogin: "j...1"`) though
`highestBidderId` is a stable integer. Aukro's own anonymisation is a signal about the operator's
expectations — do not undo it by joining bidder ids across auctions.

## 4. Transport

### 4.1 Anti-bot — the vantage point is decisive

| Egress | Result |
|---|---|
| M247 VPN datacenter (AS9009) | **403** `cf-mitigated: challenge`, `cType: 'managed'`, on `/`, `/robots.txt`, `api.`, `doc.` — **domain-wide** |
| T-Mobile CZ residential (AS13036) | **200 everywhere**, no challenge, no CAPTCHA, no token needed |

Cloudflare in front, tuned to IP reputation. **Not a UA or fingerprint problem — purely ASN.** Note
this is a harsher shape than Bazos, whose block is 403-only and path-scoped: Aukro challenges
`robots.txt` itself, so from a bad IP even the legal gate cannot be read.

### 4.1.1 ❌ Tor is CONFIRMED BLOCKED — measured 2026-08-22

The risk flagged below was probed and **it is real, not hypothetical**:

```bash
docker compose up -d tor_proxy
curl -s --socks5-hostname 127.0.0.1:9050 https://icanhazip.com   # -> 192.42.116.110 (Tor exit, verified)
curl -s -o /dev/null -D - --socks5-hostname 127.0.0.1:9050 -A "$UA" -H 'X-Accept-Subbrand: BAZAAR' \
  'https://aukro.cz/backend-web/api/offers/7130732448/offerDetail?pageType=DETAIL&requestedFor=DETAIL'
```

| Attempt | Result |
|---|---|
| 1–3 (detail API) | **403** `cf-mitigated: challenge`, body `<title>Just a moment...</title>` |
| homepage | **403** |

**Aukro cannot use the production IP-rotation stack.** For contrast, Sbazar returned `200` on
3/3 through the *same circuit* (`SBAZAR.md` §8.5), so this is Aukro's Cloudflare configuration,
not a broken proxy.

**This is now a hard infrastructure dependency, not a caveat.** Building `AukroScraper` requires
one of:
1. A **residential rotating proxy** — `docs/proxies/PROXY_ROTATION_RESEARCH.md` already
   recommends this and prices it; Aukro turns it from an optimisation into a prerequisite.
2. **Direct egress from the host IP**, as `VintedScraper` does — simplest, but it puts the Pi's
   own residential IP at risk of being the thing Cloudflare eventually challenges, with no
   rotation to fall back on.

⚠️ **Decide this before writing any scraper code.** It changes the cost model and it is the
reason `RECOMMENDATION.md` does not put Aukro immediately after Sbazar.

⚠️ **Original assessment (now confirmed):** the production pipeline runs behind Tor
(`IP_CHANGER_TYPE=TOR`). Tor exits are datacenter-reputation and near-certain to be challenged.
See `docs/proxies/PROXY_ROTATION_RESEARCH.md`; a residential proxy may be required, changing the
cost model.

### 4.2 The API — found via §4b, no APK needed

Aukro is a server-rendered **Angular** app. The `<script id="ng-state">` TransferState blob embeds
the SSR API responses, so **the full listing and detail payloads were recovered from page HTML at
zero extra request cost.** §4c (APK decompilation) was never needed.

| Endpoint | Method | Purpose |
|---|---|---|
| `/backend-web/api/offers/searchItemsCommon?page=N&size=M` | POST | Category/search listing + `page.totalElements` |
| `/backend-web/api/offers/{itemId}/offerDetail?pageType=DETAIL&requestedFor=DETAIL` | GET | Full item incl. description, bids, views |
| `/backend-web/api/token/generate` | GET | Present, **not required** for either of the above |

Search request body (measured, from the cache key):
```json
{"categorySeoUrl":"mobily-a-gps","subbrandExclusive":false,"fallbackItemsCount":12}
```
Only header needed: `X-Accept-Subbrand: BAZAAR`. **No auth, no cookie, no CSRF token** — verified by
calling both endpoints cold from `curl`.

- **Pagination:** `page` / `size` query params; `page.totalPages` returned (666 at size=60). Server
  cap NOT probed.
- **Ordering:** newest-first exists publicly (`MOBILE_SORTING_THE_LATEST`); parameter name NOT resolved.
- **Payload size:** listing at `size=60` ≈ 1.5 MB page HTML; `offerDetail` JSON 9.7–25.7 KB.
- **Rate limits:** ~15 spaced requests, zero 429s. Not pushed further per §9.
- **Promoted ads are LABELLED, not bumped** — `ppPriorityList`, `ppHighlight`, `ppBoldTitle`,
  `aukroFreePriorityList` are explicit booleans, and `startingTime` is a real post time.
  **Aukro does not have the Bazos topped-timestamp trap** (`METHOD_CALIBRATION.md` §2–§3).

## 5. Schema fit

### 5a. Field mapping — every value below was seen in a real response

Sources: `searchItemsCommon` listing (L) and `offerDetail` (D), items `7130732448` / `7090000011`.

| `Ad` column | Marketplace field | Measured example value | Notes |
|---|---|---|---|
| `external_id` | `itemId` (L+D) | `7130732448`, `7090000011` | **int, 10 digits, max seen 7,130,907,782 — fits `BigIntegerField` unchanged** ✅ |
| `name` | `itemName` (L) / `name` (D) | `"N - Bateriový železniční vůz Wittenfeld - ETA 180 015 a/b - KATO 14727"` | 71 chars; max over 60 items **70** vs column 120 ✅ |
| `price_raw` | `price.amount` (L+D) | `861.0` ⚠️ **float**, `534`, `1` | **BREAKS `parse_price` — see §5b.3** ❌ |
| `url` | `seoUrl` + `itemId` | `iphone-6-16gb-7130732448` → `https://aukro.cz/iphone-6-16gb-7130732448` | max seen 68 chars vs 1024 ✅ |
| `location` | `location` (L) / `itemLocation` (D) | `"Praha 7"` (L), `"Zlín, Česká republika"` (D) | max seen 20 vs 128 ✅. **L and D differ in format** |
| `short_description` | `descriptionStripped` (**D only**) | `"Prodám tento telefon - nefunkční zadní fotoaparát stav viz foto."` | **NOT in listing** — forces detail fetch, see §5b.8 |
| `publish_date` | `startingTime` (L+D) | `"2026-08-21T20:10:02.795+02:00"` | ISO-8601 **with offset, ms precision** ✅ real timestamps |
| `view_count` | `displayedCount` (**D only**) | `63`, `44` | Available, but detail-only |
| `topped` | `ppPriorityList` / `ppHighlight` / `ppBoldTitle` / `aukroFreePriorityList` (L) | `false` / `true` | **Four separate booleans**, no single flag — needs a mapping decision |
| `publisher_name` | `seller.showName` / `sellerLogin` (L+D) | `"pavelk633"`, `"Elektro_Aikela"` | ≤100 ✅ |
| `full_description` | `descriptionInHtml` (D) | `<html>…<div class="aukro-offer-default">…` | HTML, needs stripping |
| — | `endingTime` (L+D) | `"2025-06-04T20:15:00+02:00"` | **No `Ad` column. Load-bearing for §6** |
| — | `biddersCount` (D) | `8` | **No column. The realised-price signal** |
| — | `itemType` (L/D) | `"BIDDING"` / `"BUYNOW"` | **No column. Decides price semantics** |
| — | `buyNowPrice.amount` | `49`, `0` | **No column. Second price** |
| — | `attributes[]` | `{"attributeId":48,"attributeName":"Stav zboží","attributeValue":"Rozbaleno","attributeValueId":3}` | **No column. Structured condition** |
| — | `seller.rating` / `positiveFeedbackPercentage` / `starType` | `377` / `1.0` / `"SILVER"` | **No column. Reputation** |
| — | `seller.userId` | `100551294` | Stable int seller id — see §5b.6 |
| — | `watchersCount` (L) | `9` | Demand signal |

### 5b. The checklist, answered

1. **`external_id` integer?** ✅ **Yes.** `itemId` is a 10-digit int. **No schema blocker** — this
   was the brief's "most likely hard blocker" and Aukro passes it cleanly.
2. **Column widths?** ✅ All fit with large margin (name 70/120, location 20/128, url 68/1024,
   publisher 13/100). No `DataError` risk on the fields that map.
3. **Price shape?** ❌ **The one real breakage.** `price.amount` is a **JSON number that can be a
   float**: `{"amount": 861.0, "currency": "CZK"}`. `parse_price`'s `re.sub(r"\D","",...)` turns
   `"861.0"` into **`8610`** — **exactly 10× too large**, silently. Measured, not theorised.
   Additionally there are **two prices** (`price` = current bid, `buyNowPrice`) whose meaning
   depends on `itemType`, and `price` is `None` on `BUYNOW` items. `price_raw` (CharField 30)
   cannot express this. **This is what `PROMPTS.md` P22 (`price_raw` → real integer + `price_type`)
   was written for; Aukro makes P22 a prerequisite rather than a nice-to-have.**
4. **Newest-first ordering?** ✅ Exists publicly (`MOBILE_SORTING_THE_LATEST`). ⚠️ Parameter name
   not resolved — default is relevance-sorted, which **would silently break
   `run_existing_query`'s dedup walk** if not set. Must be resolved before building.
5. **Topped/promoted concept?** ✅ Yes, and **better than Bazos**: explicitly labelled booleans,
   with honest `startingTime`. No timestamp-bump trap.
6. **Publisher identity?** ❌ **Structural mismatch, as the brief predicted.** Aukro has real
   accounts: stable `seller.userId` (int), `showName`, `rating`, `positiveFeedbackPercentage`,
   `feedbackUniqueUserCount`, `starType`. `EmailPublisher`/`PhonePublisher` model opaque
   Bazos id-pairs, and `SellerAdCounts`' email↔phone graph walk is **meaningless here** — identity
   is already resolved. Sketch: a new nullable `MarketplaceSeller` table
   (`marketplace`, `external_seller_id`, `display_name`, `rating`, `feedback_count`,
   `positive_pct`, `star_type`) with a nullable `Ad.seller` FK. **Additive**; leaves Bazos
   untouched. Same decision Vinted deferred — Aukro makes it worth doing, because reputation is a
   real scam/dealer signal (§6b).
7. **`publish_date` / `view_count`?** ✅ Both available. `startingTime` in listing (ISO-8601 with
   offset, **ms precision** — better than Bazos's second-resolution and unblocks `BACKLOG_IDEAS.md`
   #6). `displayedCount` is detail-only.
8. **Detail-fetch cost?** ⚠️ **Required.** The listing carries no description and no view count, so
   `load_full_description` needs one `offerDetail` GET per ad (9.7–25.7 KB). Failure mode when an
   item vanishes: `GET .../6900000000/offerDetail` returned a clean **404** (254 bytes), so it is
   detectable and must be caught — per `STAGE8_VINTED_SPEC.md` §4.6, an uncaught raise truncates a
   whole query's pass.
9. **`check_blacklisted()`?** Should issue a cheap `GET /backend-web/api/server/status` (seen in
   SSR cache) or a `size=1` search, and treat **`403` + `cf-mitigated: challenge`** as blacklisted.
   ⚠️ Note this differs from Bazos: the challenge is **domain-wide**, so unlike Bazos the homepage
   is *not* a safe "am I blocked" probe — it is blocked too.
10. **Filter-rule compatibility?** `price_range` ⚠️ works only after the §5b.3 float fix.
    `blocklist_keyword`/`required_keyword` ⚠️ **weakened** — they match
    `f"{ad.name} {ad.short_description}"`, and `short_description` is detail-only, so at filter time
    it is empty unless detail is fetched first. `publisher_blocklist` ❌ inert (no publisher FKs).
    `price_drop` ⚠️ semantically wrong for auctions — a rising bid is not a price drop, and
    `PriceChange` would record every bid as a "price change".

### 5c. Required migrations — additive vs breaking

**Additive (cheap, safe for Bazos + Vinted):**
1. `Ad.ends_at` (nullable DateTime) — `endingTime`.
2. `Ad.listing_type` (nullable Char) — `BIDDING` / `BUYNOW`.
3. `Ad.bid_count` (nullable Int) — `biddersCount`.
4. `MarketplaceSeller` table + nullable `Ad.seller` FK (§5b.6).
5. `Ad.attributes` (nullable JSON) — structured `attributes[]`.
6. `Marketplace.AUKRO` choice + registry entry in `_build_scrapers()`.

**Breaking / prerequisite:**
7. **`PROMPTS.md` P22 — `price_raw` → integer + `price_type`.** Not optional for Aukro: the float
   silently corrupts by 10×, and two-prices-plus-type cannot be expressed in one CharField. Touches
   Bazos and Vinted rows. **Do P22 first, then Aukro.**

## 6. New workflows unlocked

### 6a. ⭐ Realised prices — the finding that justifies this marketplace

**Measured, reproducible, unauthenticated.** `offerDetail` serves long-ended auctions with their
final price and bid count:

| itemId | Ended | `biddersCount` | `price.amount` | Reading |
|---|---|---|---|---|
| **7090000011** | **2025-06-04** | **8** | **861.0 CZK** | **Sold — realised price** |
| 7080000007 | 2025-01-27 | 0 | 400 | Unsold — starting price |
| 7070000003 | 2024-09-10 | 0 | 1600 | Unsold |
| 7060000001 | 2024-04-21 | 0 | 10 | Unsold |
| 7050000000 | 2023-11-23 | 0 | 500 | Unsold — **2.75 years back, still served** |
| 6900000000 | — | — | — | **404** (id floor not located) |

**`biddersCount > 0` on an ended `BIDDING` item means the item sold, and `price.amount` is what it
sold for.** That is a genuine realised price — the thing `MONETIZATION.md` §7.2c says the project
has never had.

**It also solves the sold-vs-withdrawn problem** (`PROMPTS.md` P24) that Bazos structurally cannot:
Bazos delisting is ambiguous, whereas here `endingTime` + `biddersCount` distinguishes *sold* from
*expired unsold* directly. **`biddersCount == 0` is itself a strong signal — an asking price the
market refused**, which is arguably as valuable as the sale price for calibrating a deal threshold.

Connects to: `PROMPTS.md` P23 (`PriceAnomalyRule` — can baseline on realised instead of asking
prices), `MONETIZATION.md` §4.1b/§4.6 (price index), `BACKLOG_IDEAS.md` #9 (deal-scoring
calibration), `PROMPTS.md` P24 (delisting/sold detection).

### 6a.1 ⚠️ Measured density — the corpus is SPARSE, and this changes the economics

The headline finding rested on one sold auction, so four more ended ids were sampled. **None had
bids.** Full tally across 9 ended items:

| itemId | Ended | `itemType` | `biddersCount` | `price` | Sold? |
|---|---|---|---|---|---|
| 7090000011 | 2025-06-04 | BIDDING | **8** | **861.0** | **yes** |
| 7050000000 | 2023-11-23 | BIDDING | 0 | 500 | no |
| 7060000001 | 2024-04-21 | BIDDING | 0 | 10 | no |
| 7070000003 | 2024-09-10 | BIDDING | 0 | 1600 | no |
| 7080000007 | 2025-01-27 | BIDDING | 0 | 400 | no |
| 7095000021 | 2025-08-15 | BIDDING | 0 | 92 | no |
| 7099500051 | 2025-10-16 | BIDDING | 0 | 1 | no |
| 7096500033 | 2025-09-02 | BUYNOW | `null` | `null` | **undeterminable** |
| 7100000013 | 2025-11-11 | BUYNOW | `null` | `null` | **undeterminable** |

### ⭐ Update 2026-08-22 — `quantity` is the sold flag, and target categories DO carry realised prices

Two follow-up probes changed this section materially. **21 items now sampled.**

**(1) `quantity == 0` marks a sold item — 21/21 consistent.**

| Group | n | `quantity` |
|---|---|---|
| Sold (ended, bids > 0) | **2** | **`0`** |
| Unsold (ended, bids = 0, or ended BUYNOW) | 18 | `1` |
| Still active (bids > 0, not yet ended) | 1 | `1` |

The active-with-bids row is the useful control: it has bidders but has **not** sold, and it reads
`quantity: 1`. So `quantity` tracks *stock remaining*, not bid activity — which is exactly the
semantics needed. **On an ended item, `quantity == 0` ⇒ sold.**

⚠️ **Confirmed for `BIDDING` only.** No sold `BUYNOW` item has been observed yet (all 5 sampled
BUYNOWs read `quantity: 1`). If the field means the same thing there — and it plausibly does,
since it is stock — **the buy-now blind spot below is closed and realised prices stop being
auction-only.** That is the single highest-value remaining probe on Aukro and it needs one sold
buy-now item to settle.

**(2) Realised prices exist in the target categories.** The second sold item found was
`itemId 7123500091` — **7 bidders, `quantity: 0`, price 3,126 CZK, ended 2026-06-18, category
`Počítače a hry`** (computers & games). This directly retires the worry below that the capability
might be confined to collectibles. Category mix over a 10-item ended sample: Sběratelství ×3,
Knihy ×2, **Počítače a hry ×2**, Starožitnosti ×1, **Elektro ×1**, Oblečení ×1 — so target and
target-adjacent categories are roughly **30%** of ended inventory, not a rounding error.

⚠️ Note `price: 3126.0` — a **float again**, independently confirming the §5b.3 P22 trap on a
second item.

**Sell-through across all 21 samples ≈ 9.5%**, consistent with the original ~11%. The sparsity
finding stands; the collectibles-only worry does not.

---

**≈1 realised price per 9 ended items sampled (~11%).** ⚠️ n=9, random ids in a collectibles-heavy
id range — this is an order-of-magnitude indication, **not** a sell-through rate. But the direction
is clear and it has three consequences:

1. **The corpus is expensive to build.** At ~11% yield you fetch roughly 9 detail requests
   (~10–25 KB each) per realised price. Building a category-scale price history means tens of
   thousands of requests — which is exactly the "systematic extraction of a substantial part"
   shape §3.2 warns about. **The sparsity and the legal exposure compound each other:** low yield
   forces high volume, and high volume is what makes the database-right argument bite.
2. **`BUYNOW` items are a blind spot, newly measured.** They return `price: null` and
   `biddersCount: null`. There is **no observed field distinguishing a sold buy-now from an expired
   one** — so realised prices are an *auction-only* capability, not an Aukro-wide one. Since the
   flipping-thesis categories (phones, laptops, tools) skew to buy-now more than collectibles do,
   ⚠️ the capability may be weakest exactly where the project wants it most. **Untested — this is
   the highest-value follow-up in this document.**
3. **`biddersCount: 0` is still signal.** Seven measured asking prices the market refused, at known
   dates. For calibrating a deal threshold (`BACKLOG_IDEAS.md` #9) a rejected price is genuinely
   informative — arguably the cheaper half of the dataset, and it comes at 100% yield.

**Access shape, stated honestly:** there is **no bulk query** for ended items — public search is
ACTIVE-only (the sole state string in the client bundle is `"ACTIVE"`; every ended/posted filter is
namespaced `MY_AUKRO_*`, i.e. account-scoped), and `archiv.aukro.cz` is gone. So a corpus can only
be built by **walking item ids one at a time**. That is precisely the highest-legal-exposure shape
§3.2 describes. **The capability is real; the bulk-harvest route to it is the part to be careful
about.** Ids are dense enough that sequential walking works (5 of 6 sampled ids resolved), which is
what makes this both easy and legally pointed.

### 6b. Other capabilities

- **Seller reputation** — `rating`, `positiveFeedbackPercentage`, `feedbackUniqueUserCount`,
  `starType`, `companyAccount`. Feeds scam/dealer detection
  (`bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md` §3) with real data instead of inference.
- **Structured attributes** — `attributes[]` with `attributeId`/`attributeValueId` (e.g. condition
  `Stav zboží` = `Rozbaleno`, warranty months). Directly addresses the identification problem
  `BACKLOG_IDEAS.md` #4 calls "the hard part". Canonical ids, not free text.
- **Second-resolution timestamps** — `startingTime` with **ms** precision unblocks
  `BACKLOG_IDEAS.md` #6 (posting-time density).
- **Buyer-side demand signals** — `biddersCount`, `watchersCount`, `displayedCount` in one payload.
  Bazos offers only view count. Enables demand-weighted scoring.
- **No push/webhook found.** Polling only.

## 7. Effort estimate

**M — with an L-sized prerequisite and one S-sized unknown that could become a blocker.**

| Part | Size | Note |
|---|---|---|
| `AukroScraper` against the JSON API | **S** | No auth, clean JSON, protocol is 4 methods |
| P22 price refactor (prerequisite) | **M–L** | Touches Bazos + Vinted; not optional |
| `MarketplaceSeller` + migrations | **S–M** | Additive |
| **Tor/proxy compatibility** | **?** | **The risky part** — see below |
| Realised-price backfill | **M** | Plus a legal decision, not just engineering |

**The risky part is not the scraper — it is §4.1.** Aukro's Cloudflare blocks by ASN, and the
production stack runs on Tor. If Tor exits are challenged, Aukro needs a residential proxy and the
economics change. **Probe that first; it can invalidate the whole build.** Everything else is
ordinary work.

## 8. Raw probe log

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36'

# --- from M247 VPN datacenter IP: everything blocked ---
curl -s -o /dev/null -D - -A "$UA" https://www.aukro.cz/           # -> 403 cf-mitigated: challenge
curl -s -o /dev/null -D - -A "$UA" https://www.aukro.cz/robots.txt # -> 403 cf-mitigated: challenge
dig +short archiv.aukro.cz                                   # -> (empty)
dig +short nonexistent-control-xyz.aukro.cz                  # -> (empty)  [no-wildcard control]
dig +short www.aukro.cz                                      # -> 172.67.69.168 104.26.2.125

# --- from T-Mobile CZ residential: everything 200 ---
curl -sL -A "$UA" https://aukro.cz/robots.txt                # -> 200, 899 bytes
curl -sL -A "$UA" https://aukro.cz/            -o home.html  # -> 200, 814,228 bytes
curl -sL -A "$UA" https://aukro.cz/mobily-a-gps -o cat.html  # -> 200, 1,529,616 bytes

# recover SSR API payloads from the Angular TransferState — zero extra requests
python3 -c "import re,json;h=open('cat.html').read();\
d=json.loads(re.search(r'id=\"ng-state\"[^>]*>(.*?)</script>',h,re.S).group(1))['aukCache']"
#  -> POST/backend-web/api/offers/searchItemsCommon page=0&size=60
#     page = {"number":0,"size":60,"totalElements":39925,"totalPages":666}

# category counts
curl -s -A "$UA" -H "Content-Type: application/json" -H "X-Accept-Subbrand: BAZAAR" \
  -X POST "https://aukro.cz/backend-web/api/offers/searchItemsCommon?page=0&size=1" \
  -d '{"categorySeoUrl":"pocitace-a-hry","subbrandExclusive":false}'
#  -> 200  page.totalElements = 145,710
#     cyklistika -> 9,144 ; dum-a-zahrada -> 162,492

# item detail, live item
curl -s -A "$UA" -H "X-Accept-Subbrand: BAZAAR" \
  "https://aukro.cz/backend-web/api/offers/7130732448/offerDetail?pageType=DETAIL&requestedFor=DETAIL"
#  -> 200, 25,737 B. itemArchived=False itemType=BIDDING price=534 bidders=2 ends=2026-08-27

# ENDED auctions — the realised-price evidence
#   7050000000 -> 200  bidders=0 price=500    ended 2023-11-23   (2.75 years back)
#   7060000001 -> 200  bidders=0 price=10     ended 2024-04-21
#   7070000003 -> 200  bidders=0 price=1600   ended 2024-09-10
#   7080000007 -> 200  bidders=0 price=400    ended 2025-01-27
#   7090000011 -> 200  bidders=8 price=861.0  ended 2025-06-04   <-- SOLD, realised price
#   7100000013 -> 200  itemType=BUYNOW price=None buyNowPrice=49 ended 2025-11-11
#   6900000000 -> 404  (254 B)
```

## 9. Open questions / what I could not determine

1. **ToS were never fetched.** The largest open item. §3.1 covers robots.txt only. Bazos requires
   written consent for API use — **Aukro's equivalent clause is unknown**, and it could change the
   §3.2 assessment materially. Do this before building.
2. ~~**Is Aukro reachable through Tor?**~~ **ANSWERED 2026-08-22: no — 403 on 3/3** (§4.1.1).
   Now a hard infrastructure dependency: residential proxy or direct host egress.
3. **The newest-first sort parameter name.** Known to exist; name unresolved. Blocks a valid
   new/day figure *and* correct dedup ordering.
4. **Server page-size cap** for `searchItemsCommon` (Bazos's is 210). Not probed.
5. **The item-id floor.** `6900000000` → 404, `7050000000` → 200. Where public history actually
   starts, and whether it is a retention policy or an id-space artifact, is unknown — this bounds
   how deep a realised-price corpus could go.
6. **Sold-vs-unsold on `BUYNOW` items — a strong candidate answer, not yet confirmed.**
   `quantity == 0` marks sold on `BIDDING` items (21/21, §6a.1). All 5 sampled `BUYNOW` items read
   `quantity: 1` (unsold), so the field has **not** yet been seen at `0` on a buy-now.
   **Find one sold buy-now item and this is settled** — it decides whether realised prices are
   auction-only or Aukro-wide.
7. **Whether `price` on an ended `BIDDING` item is always the winning bid** vs the last bid on a
   reserve-not-met auction. **Still only one sold example across 9 sampled ended items** (§6a.1).
   ⚠️ Do not generalise from it — confirming this is cheap and should precede any build.
8. **Per-category realised-price density** — what fraction of ended auctions have
   `biddersCount > 0` in the target categories. Determines whether the corpus is actually useful.
9. **How Aukro's own `x-total-count` equivalent behaves under text search** (not just category
   browse) — the text-search parameter was not identified.
