---
title: All assessed marketplaces — summary table
status: reference
updated: 2026-08-22
verified: 2026-08-22
---

# All assessed marketplaces — summary table

> Study completed 2026-08-22. Index to the 13 detail files in this directory.
> All figures measured live unless marked ⚠️. Bazos row is the comparison baseline, not a candidate.
> Probes ran from two vantage points: a VPN datacenter IP (M247/AS9009) and a residential Czech
> ISP (T-Mobile CZ/AS13036). Where those differ, it is called out — it changed several verdicts.

## Track A — marketplaces to scrape

| Marketplace | Verdict | Target-category scale | vs Bazos | New/day | New capability | Effort | Legal posture |
|---|---|---|---|---|---|---|---|
| **Bazos.cz** *(baseline)* | *in production* | notebook 7,849 · iphone 6,586 · naradi 7,716 | 1× | notebook ~230 | — | — | Disallows search paths |
| **Sbazar.cz** | **✅ VIABLE — build first** | **naradi 26,738** · notebook 4,401 · iphone 2,282 · kolo 2,659 | **tools 3.4×** | tools ~139 | ❌ none | **S** | ⚠️ **Worst** — `Disallow: /` + `/api/` |
| **Aukro.cz** | **✅ VIABLE — 2nd, gated** | dum-a-zahrada 162,492 · pocitace-a-hry 145,710 · mobily 39,925 · cyklistika 9,144 ⚠️broad cats | n/a | NOT DETERMINED | ⭐ **realised prices** | M + breaking prereq | ✅ **Best** — 899 B, cart/account only |
| **bazos.sk / .at / .pl** | ✅ VIABLE — cheap breadth | `.sk` notebook 7,225 | 0.92× | not measured | ❌ none | **near-zero** | Same as Bazos |
| Hyperinzerce.cz | ❌ REJECT | naradi 530 · notebook 168 · phones 126 · site 52,206 | 15–52× below | ND | — | — | — |
| Annonce.cz | ❌ REJECT | notebook 21–40 · phones/tools 61–80 | 80–370× below | ND | — | — | — |
| Mimibazar.cz | ❌ REJECT | notebook 30 · phones 26 · tools 27 | 250–290× below | ND | — | — | — |
| Avizo.cz | ❌ REJECT | blocked, not measured | — | — | — | — | Names **ClaudeBot**, GPTBot |
| TipCars.com | ❌ REJECT | cars ⚠️scope assumed | wrong category | — | — | — | Never served a byte |
| Sauto.cz | ❌ REJECT | cars | wrong category | — | — | — | `Disallow: /` |
| Sreality.cz | ❌ REJECT | real estate | wrong category | — | — | — | `Disallow: /` · *"neplecha ukončena"* |
| Bezrealitky.cz | ❌ REJECT | real estate | wrong category | — | — | — | Blocks `/vyhledat*`, `/search*` |
| Remix (remixshop) | ❌ REJECT | apparel only, ~19,000 ⚠️derived | wrong category | ND | (JSON-LD, see notes) | — | ✅ zero `Disallow` |
| Facebook Marketplace | ❌ REJECT | not measured (deliberate) | — | — | — | — | ⚠️ `Disallow: /` + written-permission notice |

## Track B — reference-price sources

| Source | Verdict | What it gives | The blocker | Legal |
|---|---|---|---|---|
| **Heureka / Zboží.cz** | ⏸️ **DEFER** | Cross-merchant **new-price range** — Makita DHP484 → 4 canonical products, 2,920–5,391 Kč across **44 shops**; `brandName`, structured params, ratings | **The join is on our side** — `Ad` has no brand/model/GTIN. No EAN exposed. Discontinued goods fail *dangerously*: `Macbook Pro 13 2020` → **a phone case, 999 Kč** | Zboží allows the product page, **disallows the `/*?q=` search** that finds it |
| **eBay** sold listings | ⏸️ **DEFER — effectively unavailable** | Would be the canonical realised-price feed | **No route exists.** `findCompletedItems` decommissioned 2025-02-05; Marketplace Insights is Limited Release, *"not open to new users"* | ⚠️ Licence would let eBay **require deletion** — worse than scraping |

## Technical detail — the three Track A survivors

| | **Sbazar.cz** | **Aukro.cz** | **bazos.sk/.at/.pl** |
|---|---|---|---|
| **Transport** | `GET /api/v1/items/search` | `POST /backend-web/api/offers/searchItemsCommon` + `GET …/{id}/offerDetail` | Same hidden API as `.cz` |
| **How found** | `gh search code` → verified live | Angular `<script id="ng-state">` SSR blob — full payloads at **zero extra requests** | Already documented |
| **Auth** | None | None | None (app UA) |
| **Page size** | `limit=1000` served whole (1.3 MB / 1.37 s) | `size=60` seen; cap not probed | 210 (server cap) |
| **Newest-first** | ✅ **default** | ✅ exists (`MOBILE_SORTING_THE_LATEST`) ⚠️ param name unresolved | ✅ `sort=date` |
| **`external_id`** | ✅ int (6.9M–233.3M) | ✅ int, 10-digit | ✅ int |
| **Migrations needed** | ✅ **zero** | 6 additive + **P22 breaking** | zero |
| **Price shape** | ✅ int whole CZK — no trap | ❌ **float `861.0` → `8610` (10×)**; two prices | ✅ as Bazos (EUR/PLN) |
| **Promoted flag** | ✅ real boolean | ✅ 4 labelled booleans, honest `startingTime` | ⚠️ Bazos bump trap |
| **Description** | detail-only, ⚠️ **overflows 300** (679 seen) | detail-only | detail-only |
| **View count** | ❌ absent | ✅ `displayedCount` (detail) | ✅ |
| **Seller identity** | shop_url; no ratings | ✅ **accounts + reputation** (`rating`, `positiveFeedbackPercentage`, `starType`) | Bazos-shaped id pairs |
| **Anti-bot** | Seznam consent wall on HTML; **API layer unaffected** | ⚠️ **Cloudflare by ASN** — may break Tor | 403 from datacenter, IP named in body |

## Notable per-site findings

- **Aukro — realised prices.** Ended auctions are publicly readable ≥2.75 years back. `biddersCount > 0` on an ended `BIDDING` item ⇒ it sold, and `price.amount` is the sale price (measured: id `7090000011`, 8 bidders, **861 CZK**, ended 2025-06-04). ⚠️ Density only **~11%** (1 of 9 sampled), and **buy-now items expose no sold signal at all**.
- **Sbazar — the "by agreement" trap.** `price: 0` + `price_by_agreement: true`. But `price == 0` does **not** imply by-agreement — 15/1000 disagree (genuine giveaways). Branch on the boolean or `PriceRangeRule` silently rejects every negotiable ad.
- **Annonce — a fabricated-looking total.** Reported "nalezeno 1568 inzerátů" for `notebook`; **1,544 were job ads** mentioning a laptop as a perk. Real count ~21–40.
- **Remix — the transferable probe, not the site.** 30 schema.org `Product` JSON-LD blocks per page with `brand`, `itemCondition`, integer `sku`, integer CZK prices. Lesson: **grep any candidate's HTML for `application/ld+json` before assuming LLM extraction is needed.**
- **bazos.sk/.at/.pl — not the free win the docs imply.** All three refused a datacenter IP that `.cz` accepted *in the same minute*, naming the IP in the body. Stricter blocklist, same operator ⇒ **cheap breadth, not diversification.**
- **Mimibazar — a bump artifact.** Its feed returned 24 listings spanning a 4-minute window ending at request time (naive: 8,640/day). An `aktualizace.php` refresh feature, not real velocity.

## Where the vantage point changed the answer

| Site | Datacenter VPN | Residential |
|---|---|---|
| Aukro | 403 domain-wide, incl. `robots.txt` | ✅ 200 everywhere |
| Sbazar listings | anti-bot intercept | ✅ 200 |
| bazos.sk API | 403, IP named | ✅ 200, `x-total-count: 7225` |
| **eBay** | 403 | ❌ **403 — blocked just as hard** |

⚠️ A residential IP is **not** a master key — it fixed every Czech candidate and none of eBay.

## Files

`RECOMMENDATION.md` (ranked) · `AUKRO.md` · `SBAZAR.md` · `pass1/`: `pass1/RANKING.md`,
`METHOD_CALIBRATION.md`, `pass1/AUKRO.md`, `pass1/SBAZAR.md`, `pass1/MINOR_CLASSIFIEDS.md`,
`pass1/VERTICALS.md`, `pass1/BAZOS_SISTER_SITES.md`, `pass1/FACEBOOK_MARKETPLACE.md`,
`EBAY.md`, `HEUREKA_ZBOZI.md`
