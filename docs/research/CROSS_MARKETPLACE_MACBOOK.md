---
title: MacBooks across Bazos, Sbazar and Vinted — can the three be pooled?
status: reference
updated: 2026-09-12
verified: 2026-09-12
---

# MacBooks across Bazos, Sbazar and Vinted — can the three be pooled?

> Follow-up to [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md), which modelled 2,038 **Bazos**
> MacBook ads. The same work is repeated on the other two marketplaces where the product is
> scraped (`Query` 13 = Vinted, 14 = Sbazar), to answer one question: **does the Bazos work
> transfer, and can the three corpora go into one model?**
>
> **First written 2026-08-26** against 2.45 days of Sbazar (460 ads) and Vinted (185).
> **Re-measured 2026-09-12** on 20 days: **Sbazar 621, Vinted 1,037**, against **2,905** Bazos ads
> over 118 days (queries 8 + 15, deduped) — 1.35× the Sbazar rows and 5.6× the Vinted rows, and the
> extractor is now the **shipped** `bazos/pricing/features.py` rather than this study's own copy.
> Three things changed, two of them headline results:
>
> - **§6.2's "Sbazar asks +3.5 %" is WITHDRAWN.** Above a common price floor it is **+1.3 %
>   (95 % CI −1.1 % … +3.0 %)**, and the published interval was never clustered at all.
> - **§5.1's Vinted fee formula is PROMOTED** from "measured once by a live probe" to confirmed
>   from the stored corpus — but by a different argument than the obvious one, which is circular.
> - **New, and it is what decides Vinted (§5.2): ~73 % of the Vinted MacBook corpus is not priced
>   in CZK by the seller.** About 34 % is positively shown to be a PLN price converted at Vinted's
>   own daily rate, which drifts. §5.3 is the live pipeline consequence of that.
>
> Standing caveat, unchanged and applying to every figure below: **`Ad.modified` never advances, so
> the database records zero outcomes** — no sold flag, no time-to-disappear. Every precision number
> here is a composition audit, not a measurement.

---

## 1. Verdict

| Question | Answer |
|---|---|
| Does the Bazos **spec extractor** transfer? | **Yes.** Recall *given the spec is visibly in the title* is 97.9–100 % on all three; the one gap is Vinted screen size at 92.3 %, which is two missing glyph/loanword rules (§4). Nothing about the extractor is Bazos-specific. |
| Do the three **corpora** carry the same information? | **No.** Bazos carries ⌀ 239 chars of description per ad; Vinted and Sbazar carry **zero**. That is a config choice (§3.1), not a platform limit. |
| Are the **prices** on the same basis? | **No, twice over.** Vinted stores the buyer total, `ask × 1.05 + 18 CZK` (§5.1) — *and* for ~73 % of rows that ask is a zloty price re-expressed at a drifting FX rate (§5.2). The first is invertible; the second is not absorbable by any fixed effect. |
| Can Bazos + **Sbazar** be pooled? | **Technically yes; the level shift is not measurable.** Within shared spec cells above a common 10,000 CZK floor, Sbazar is **+1.3 % (95 % CI −1.1 % … +3.0 %)** — 292 Sbazar ads across **51 shops**, 627 Bazos ads, 76 cells. The earlier **+3.5 % (CI +1.8 % … +5.1 %) is withdrawn** (§6.2). |
| Can **Vinted** be pooled? | **No — and not on a schedule either.** Its stored price is non-stationary for structural reasons (§5.2). The apparent −13 % is still composition: Apple-silicon cells give −2.7 % (CI −7.3 % … +4.4 %, n=37) on 2.4× the data (§6.2). |
| Should either extension **ship**? | **Neither now.** Sbazar is ~40 lines and the model transfers, but it buys **0–1 alerts per 20 days against Bazos's 16** (§7.3). Vinted's prerequisites are three schema changes deep (§8). |
| Combined model | Still **one pooled model with `marketplace` as a feature** — but read the coefficient as absorbing **dealer and floor composition**, not a marketplace price level (§7.2). |

**One-line answer: the Sbazar premium was an artifact of two queries with different price floors, so
pooling is safe and buys nothing measurable; Vinted cannot be pooled at all until `Ad.price` stops
silently meaning two different things on the same row.**

---

## 2. What was pulled

Production, read-only, 2026-09-12. Delivery-level export joined `bazos_ad ⋈ bazos_addelivery`;
**deduped on `(marketplace, external_id)` before anything else** — the wider export carries 12,078
delivery rows for 11,948 distinct ads, and queries 8 and 15 share 128 of them. Pooling queries
without deduping inflates the Bazos MacBook n by ~4 %.

| Query | Marketplace | Rows | First ad | Last ad | Query price floor |
|---|---|---:|---|---|---|
| 8 | `bazos` | 2,851 | 2026-05-17 | 2026-09-12 | 5,000 → **3,000** from 2026-08-30 |
| 15 | `bazos` | 182 | 2026-08-07 | 2026-09-12 | not read; observed min 6,499 |
| 14 | `sbazar` | 621 | 2026-08-23 | 2026-09-12 | **10,000** (min *and* p1 are both exactly 10,000) |
| 13 | `vinted` | 1,037 | 2026-08-23 | 2026-09-12 | **2,000** (min stored 2,118 = 2,000 × 1.05 + 18) |

Query 8 union query 15 = **2,905** Bazos ads. Delivery status is overwhelmingly `SENT` (2,697 /
1,020 / 618); query 8 carries 151 `REJECTED` and 3 `FAILED`, the other two 17 and 3. **Of query 8's
151 rejections, 101 are `location_distance` and 37 are `price_model`** — the `SENT → REJECTED`
change of regime on 2026-09-07 is a distance filter being configured (centre 11000, radius 40 km),
**not** the price model starting to reject.

### 2.1 Three confounds that must be controlled before any comparison

1. **The queries do not share a price floor, and query 8's moved mid-window.** 5,000 → 3,000
   (Bazos), 10,000 (Sbazar), 2,000 (Vinted). The first query-8 ad below 5,000 CZK appears
   2026-08-28; from 2026-08-30 the daily minimum is 3,000, and 76 ads now sit below the old floor.
   **This is the confound that breaks §6.2** — and the first version of this document named it in
   *this* section and then failed to apply it in that one.
2. **Bazos has 118 days of history; the other two have 20.** The Sbazar and Vinted windows are
   2026-08-23 → 2026-09-12 and carry no seasonality control.
3. **Composition differs sharply.** Share of `kind == macbook` rows by chip family, **title-only**
   extraction (the only basis on which the three are comparable — §3):

   | | Apple silicon | Intel | chip not extractable |
   |---|---:|---:|---:|
   | bazos (n=2,856) | 46.3 % | 38.5 % | 15.2 % |
   | sbazar (n=586) | **77.3 %** | 11.1 % | 11.6 % |
   | vinted (n=948) | 31.5 % | 18.6 % | **49.9 %** |

   Sbazar's inventory is far newer than Bazos's; Vinted's is older *and* half of it is
   unidentifiable from the title. Any unmatched price comparison measures this table.

The 2.45-day snapshot the first version used is no longer the basis for anything here; where a
number moved, the paragraph says which **basis** moved — corpus size, extractor, protocol, or
design matrix.

---

## 3. Field coverage

Non-null (and non-empty-string) counts, straight from the export:

| `bazos_ad` column | bazos, q8 (n=2,851) | sbazar (n=621) | vinted (n=1,037) |
|---|---|---|---|
| `price` | 2,851 (100 %) | 609 (98 %) | 1,037 (100 %) |
| `price_type` | all `exact` | 609 `exact`, 12 `negotiable` | all `exact` |
| `price_raw` | `"7 000 Kč"` (thin space) | `"20000 Kč"` / `"Dohodou"` | `"7732 CZK"` |
| `location` | 2,851 (100 %) | 621 (100 %) | **0** |
| `view_count` | 2,851 (100 %) | **0** | **0** |
| `publish_date` | 2,851 (100 %) | 621 (100 %) | **0** |
| `topped` | 319 true (11.2 %) | 8 true (1.3 %) | 37 true (3.6 %) |
| `name` | 100 %, ⌀ 46 chars | 100 %, ⌀ 37 chars | 100 %, ⌀ 37 chars |
| `short_description` | 2,851 (100 %), ⌀ 239 chars | **0** | **0** |
| `full_description` | 788 (27.6 %) | **0** | **0** |
| `publisher_name` | 2,851 (100 %) | 621 (100 %, shop slug) | **0** |
| `email_publisher_id` | 2,750 (96 %) | **0** | **0** |
| `phone_publisher_id` | 2,851 (100 %) | **0** | **0** |

Four consequences, and the third **corrects** the first version of this section:

- **Vinted contributes nothing but a title and a price.** No location, no publish date, no views,
  no seller — `publisher_name`, `email_publisher_id` and `phone_publisher_id` are empty on
  **1,037 / 1,037** rows. A `GroupKFold` on Vinted silently degenerates into a random split
  (92 % of title-groups are singletons), so every Vinted CV number in this document is an
  **upper bound**.
- **`view_count` is Bazos-only**, so any demand-side feature is Bazos-only.
- **Sbazar *does* have a usable seller key, and it is `publisher_name`.** 172 distinct values over
  621 ads — 602 ads under 155 named shops, 19 under 17 anonymous 32-hex ids; 162 of those values
  carry a price, which is the basis
  [`CATEGORY_PRICE_MODELS.md`](CATEGORY_PRICE_MODELS.md) §9 groups on — and the two largest
  (MacBookprodejna 193, MacPoint2 167) are **58.0 %** of the corpus between them. The blanket claim
  that seller identity does not exist off Bazos was wrong: what does not exist off Bazos is an
  *id shared with `Ad`*. **The reverse trap matters more: Bazos's own `publisher_name` is not an
  identity** — it is a display first name, and across the 9,947 Bazos ads in the wider export
  13.0 % of names map to more than one `email_publisher_id` ("Martin" covers 131 of them). Any
  marketplace-aware seller key must branch per marketplace and must never fall back generically;
  a generic fallback is migration 0025's `bazos_id=0` sentinel wearing a different hat.
- The finding that **67 % of Bazos residual variance is between sellers**
  ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §5) still has no Vinted counterpart, and on
  Sbazar it is not a variance decomposition worth running: 80 % of the scoreable rows are two shops.

### 3.1 The missing descriptions are a config choice, not a platform limit

`VintedScraper.load_full_description` and `SbazarScraper.load_full_description` both exist and both
fetch a real description (Sbazar additionally back-fills `short_description[:300]` from it). They
are simply never called: **`Query.load_full_description` is `false` on queries 13 and 14** and
`true` on query 8. `QueryRunner._handle_new_product` gates on that flag.

Bazos gets its 239 chars for **free** — `BazosScraper` reads `.popis` off the listing page — and its
description is worth **+17.5 pp** on complete-spec coverage (§4.1). Neither Vinted's search API nor
Sbazar's returns a description at all, so the two are not comparable on cost: ~52 extra Vinted and
~31 extra Sbazar detail requests/day at current volumes.

---

## 4. Does the extractor transfer?

Re-measured with the **shipped** `bazos/pricing/features.py`, not the study's `mbfeat2.py`. That is
a basis change from the first version and it moves every coverage number in this section down a
little, because six of the eight fixes §4.3 lists never landed in the shipped file.

### 4.1 Coverage, shipped extractor

Share of `kind == macbook` rows for which each field is extracted. Title-only is the only basis on
which all three are comparable (§3):

| | n | chip | year | screen | RAM | SSD | all five |
|---|---:|---:|---:|---:|---:|---:|---:|
| bazos, title only | 2,802 | 84.6 % | 68.4 % | 87.2 % | 77.0 % | 74.5 % | 49.2 % |
| sbazar, title only | 594 | 87.4 % | 60.4 % | 86.9 % | 65.2 % | 63.3 % | 37.9 % |
| vinted, title only | 948 | 50.1 % | 55.4 % | 55.7 % | 44.8 % | 40.0 % | **11.9 %** |
| bazos, **title + description** | 2,819 | 93.0 % | 81.9 % | 90.8 % | 90.2 % | 90.6 % | **66.7 %** |

(The two Bazos n differ because `kind` is itself decided on whatever text is available.) The
description is worth **+17.5 pp** on a complete spec, against +12 pp in the first version — **two
bases moved at once**, a 1.4× larger Bazos corpus and a different extractor, so read it as
"still worth more than any regex change", not as a measured increase. Sbazar and Vinted cannot
reach it today (§3.1).

### 4.2 The gap is information absence, not extractor failure

Recall re-measured **conditional on the signal being visibly present in the title**:

| | year | screen | chip | capacity |
|---|---|---|---|---|
| **recall given present** — bazos | 99.3 % | 99.7 % | 98.6 % | 98.6 % |
| sbazar | 99.4 % | **100 %** | 97.9 % | 99.7 % |
| vinted | 99.8 % | **92.3 %** | 99.8 % | 99.1 % |
| **present in the title at all** — bazos | 68.9 % | 76.9 % | 85.8 % | 80.0 % |
| vinted | 55.5 % | 43.9 % | 50.2 % | 49.5 % |

Read the two halves together: **Vinted's titles carry the spec roughly half the time, and when they
carry it the extractor reads it.** The one real recall gap anywhere is Vinted screen size at 92.3 %,
and §4.3's fixes #6 (`cali`) and #9 (`″`) recover +18 and +4 Vinted screen sizes between them —
which is what that gap is made of.

The *chip* probe is close to the extractor's own pattern, so its ~99 % is partly tautological — it
says "there is no third chip spelling we are blind to", not "chip extraction is perfect". The
*screen* and *year* probes are strictly narrower than what the extractor accepts, so those are
genuine recall measurements.

### 4.3 The eight fixes — six are still not shipped, and there are two more

The defect list below is unchanged and still correct. What is new is that it was **never fully
applied**: only **#1 (M5) and #3 (lone 128 GB)** are in `bazos/pricing/features.py` today —
`APPLE_CHIP` reads `m([1-9])` and `PLAUS_SSD` contains 120. The other six are absent, plus two found
in this pass. **These are Bazos bugs independent of any cross-marketplace work**, and they should be
judged on their own merits rather than ride on a marketplace decision.

| # | Defect | Fix |
|---|---|---|
| 1 | `APPLE_CHIP = m([1-4])` — **M5 is invisible** | `m([1-9])`. **Shipped.** A hard-coded generation ceiling silently drops every new chip the day Apple ships it |
| 2 | `\bm2\b` cannot see a boundary in `M2PRO` | normalise `m2pro` → `m2 pro`; move the `\b` after the optional variant group |
| 3 | A lone `128GB` is read as **128 GB of RAM** | unlabelled-token SSD floor 240 → **120**. **Shipped** |
| 4 | en/em dash not normalised (`MacBook Air 13– 256 GB`) | map `U+2010–U+2015`, `U+2212` → `-` |
| 5 | `14-inch` — hyphen blocks the unit match | split the digit from its unit before matching |
| 6 | Polish `15 cali` (= inches) | add `cal[ie]?` (+ `zoll`) to the screen units |
| 7 | Polish `2017r.` — no `\b` between `7` and `r`, so the year vanishes | strip a `r`/`r.` suffix after a 4-digit year in `norm()` |
| 8 | Condition flags are Czech-only; unitless labelled tokens (`8 RAM / 256 SSD`) do not parse | pl/en synonyms for `defect`/`new`/`warranty`/`scratches`; `dysk`/`pamięć` to the SSD/RAM word lists; **(8b)** accept a labelled number with no unit |
| **9** | **NEW: `U+2033` (″) is not folded to `"`**, so `13″` yields no screen size | add it to `norm()` beside the existing quote glyphs |
| **10** | **NEW: `MACBOOK` ends in `\b`**, which fails on Czech/Polish declension (`MacBooku`, `MacBooka`) | accept the declined forms — but **consult them last**, after `OTHER_BRAND` and `NON_MACBOOK` |

Measured yield, **production basis** (`name` + `short_description`, not title-only), 4,563 deduped
ads. Format is *field gained* | *gate-eligible ads gained*, where the gate is the shipped
`_gates_pass` (`kind == macbook`, EXACT price, year + chip + RAM + SSD parsed, no damage word):

| # | bazos (n=2,905) | sbazar (n=621) | vinted (n=1,037) |
|---|---|---|---|
| 2 | · \| +0 | chip +11 \| **+1** | · \| +0 |
| 4 | · \| +0 | · \| +0 | · \| +0 |
| 5 | screen +7 \| +0 | · \| +0 | screen +13 \| +0 |
| 6 | · \| +0 | · \| +0 | screen +18 \| +0 |
| 7 | · \| +0 | · \| +0 | year +14 \| +0 |
| 8a | SSD +1 \| **+1** | · \| +0 | SSD +1 \| +0 |
| **8b** | **RAM +5, SSD +13 \| +8** | · \| +0 | **RAM +2, SSD +13 \| +5** |
| 9 | screen +4 \| +0 | · \| +0 | screen +4 \| +0 |
| 10 | macbook +2 \| +0 | macbook +1 \| +0 | macbook +5, chip +2 \| +0 |
| **all ten** | 1,914 (65.9 %) → **1,923 (66.2 %)** | 228 (36.7 %) → **229 (36.9 %)** | 142 (13.7 %) → **150 (14.5 %)** |

**The whole fix set is worth +9 gate-eligible Bazos ads over 118 days — half an ad a week — and
+8 of those 9 are fix #8b alone.** That is the counterintuitive part, and it is why the list should
not be shipped as a block: measured on the production basis rather than on titles, most of these
fixes recover a field the description had already supplied. Fix #2's "34 Bazos ads" from the first
version becomes **0** once the description is read; its real value is one *wrong* extraction
corrected (`NOVY MacBook PRO 16" M3PRO/18GB/512GB` was read as M4 Pro).

Two warnings that must travel with fix #8, because both manufacture the exact failure
`features.py`'s own docstring warns about — a nonsense spec produces a nonsense prediction, which
lands in the underpriced tail:

- a lookbehind that does not exclude letters reads `procesor: m2 ram: 8gb` as **2 GB of RAM**
  (18 Bazos ads);
- with no plausibility test, `model 2020 SSD 512` becomes a **2,020 GB disk**.

Any rule that promotes an unlabelled number needs both a non-letter lookbehind and a
`PLAUS_RAM`/`PLAUS_SSD` membership test. Regression audit of all ten fixes over 4,563 rows:
chip 0 lost / 11 gained, year 0 / 14, screen 0 / 49 (1 changed), RAM 0 / 7, SSD 1 / 31, `kind`
0 / 8. The single lost SSD is on an ad with a cracked display, which the damage gate declines anyway.

Two residual traps, both unfixable from a title:

- **`family` mis-assigns "MacBook Neo"** (the 2026 line) unless it is added explicitly — 10 Sbazar
  and 44 Vinted rows here.
- **`vinted.cz` is not a Czech market.** ~20 % of its MacBook titles carry Polish-language markers
  against ~0 % on Bazos and Sbazar, and `location` is empty so the country cannot be filtered out.
  §5.2 turns this from a population remark into the reason Vinted's price is unusable.

---

## 5. Price comparability — the part that would poison a pooled model

### 5.1 Vinted's stored price is not the seller's ask — now confirmed from the corpus

`VintedScraper._price_amount` deliberately stores `total_item_price` (buyer-protection fee
included), not `price`. The live probe of 2026-08-26 (96 MacBook results) fitted
`fee = 0.050000 × price + 17.9995`, max residual 0.005 CZK, so:

```python
ask = (stored_price - 18) / 1.05        # recovers the seller's ask to < 0.5 CZK
```

**This is now confirmed independently of that probe — but the obvious confirmation is circular and
should not be used.** Refitting `(a, b)` from the stored integers by maximising how many inverted
asks land on a round CZK lattice, and then testing that the inverted asks land on a round CZK
lattice, is one statistic reported twice. What actually confirms the structure is a **free
(period, phase) scan of the raw stored integers that assumes no formula at all**:

| scan result over the 1,037 raw stored prices | hit rate | chance |
|---|---:|---:|
| period 52.5, phase 17.50 | **18.80 %** | 1.90 % |
| period 52.4 / 52.6, best phase (0.1 CZK away) | 3.95 % / 3.09 % | 1.90 % |
| period 105.0, phase 17.50 (harmonic) | 17.65 % | 0.95 % |
| period 10.5, phase 7.05 (= 18 mod 10.5) | 23.92 % | 9.52 % |
| raw stored price is a multiple of 50 | **0.96 %** | 2.00 % |

A 50 CZK seller lattice scaled by 1.05 is 52.5, and every harmonic (105 / 70 / 35 / 10.5) sits on
the same phase 17.50. The last row is the negative control: the untransformed price is *less* round
than chance, so a transform is definitely present.

The additive **18 CZK is independently identified** by a refit on the Polish subpopulation through
the *PLN* lattice (§5.2), which uses no CZK-round evidence at all: every top-scoring `(a, b)` pair
has `b = 18.0` over a `[-10, 60]` grid (n=202). The multiplicative **1.05 is identified only up to
the assumed seller lattice** — the scan pins `seller lattice × a = 52.5`, so `a` follows only from
assuming sellers price on 50 CZK steps, and it still rests on the live probe. The consequence is
carried into §5.2: at a = 1.04 the fitted FX rate would be 5.73 rather than 5.66, which is also
plausible, so the external FX check does not pin `a` either.

**Retire the floor argument.** The first version called query 13's minimum stored price decisive:
`(2118 − 18) / 1.05 = 2000.0000` exactly. It is not. There are **2** rows at 2,118, and the
constraint is the *line* `b = 2118 − 2000a`, on which `(1.04, 38)` and `(1.06, −2)` sit as
comfortably as `(1.05, 18)`.

Inverting the rounded integer recovers the true float ask with max error 0.48 CZK. **Every number in
§6–§7 uses this correction.** Skipping it is not cosmetic: it removes 7 of 35 Vinted alerts at a
−25 % threshold, i.e. **20 % of a Vinted alert stream would be created by the fee alone**. Also
confirmed: **0 stored `price_raw` values contain a decimal point**, so the `"6307.5" → 63075` trap
([`VINTED_SCRAPER.md`](../archive/shipped/VINTED_SCRAPER.md) §4.5) is shut.

### 5.2 …and for ~73 % of rows it is not a Czech price either

This is the finding that changes the Vinted verdict, and it is new. **The seller's price is not set
in CZK for roughly three quarters of the Vinted MacBook corpus.**

| measurement (n=1,037 unless stated) | value | chance rate |
|---|---:|---:|
| Czech-priced share of the corpus (3-component lattice solve) | **27.2 %** | — |
| … 95 % CI, row bootstrap | 21.5 % … 34.1 % | — |
| … 95 % CI, clustered by scrape day (21 clusters) | 22.8 % … 33.1 % | — |
| share **positively shown** to be a converted PLN price | **34.2 %** | — |
| **mixture-free floor**: rows on a CZK-10 lattice at all | 29.5 % | 10.0 % |
| de-fee'd ask on a 10-PLN lattice at the day's rate — Polish-marked rows (n=202) | **55.4 %** | 2.0 % |
| … Czech-marked rows (n=55) | 1.8 % | 2.0 % |
| … neutral rows (n=779) | 32.7 % | 2.0 % |
| implied PLN amounts that are multiples of 50 PLN (n=312) | **81.4 %** | 0.6 % |
| … multiples of 100 PLN | 62.2 % | 0.3 % |

Three separate things make this hard to explain away. The **PLN evidence is positive, not
residual** — Polish-marked rows hit the zloty lattice ~28× above chance while Czech-marked rows sit
*exactly at* chance, so the two marker groups are near-perfectly separated on each other's lattice.
The implied zloty amounts are **human round numbers** (400, 450, 600, 750, 1000), which chance hits
would not be. And the fitted rate is **externally correct**: 5.6774 CZK/PLN for 2026-09-07 against a
published mid-market 5.6173, i.e. **+1.07 %**, which is what a platform FX markup looks like —
**this is the one check here that cannot be re-run offline**, since the comparison rate came from a
web lookup; every other row above re-derives from the stored integers alone. The
rate runs 5.55–5.68 over the window and drifts upward (+2.5 % across the well-fitted days,
corr 0.58 with date — a drift, not a measured rate of drift).

The mundane alternatives fail concretely: scraper rounding is ruled out by `price_raw` carrying no
decimal point; "sellers type odd numbers" is ruled out because the odd rows are round *in PLN*;
promoted listings are **more** CZK-round, not less (24.3 % vs 16.0 %), the wrong direction; and a
different cross-border fee is ruled out because the PLN-subpopulation refit returns the same
`b = 18`. As a calibration check, known-CZK corpora sit where they should on the CZK-50 lattice:
Bazos MacBooks 42.1 % (n=2,851), Sbazar MacBooks 52.9 % (n=609), Bazos mountain bikes 81.6 %
(n=2,342).

**The strongest form of the claim needs no mixture model at all: only 29.5 % of Vinted rows sit on a
CZK-10 lattice against a 10 % chance rate, so at least 70.5 % is not Czech-priced even crediting
every hit as genuine.** Across 16 lattice/tolerance choices the answer lands at 66.1–75.3 % non-CZK.

**Be precise about what this does and does not mean.** `Ad.price` on a Vinted row **is** a genuine
CZK integer that a Czech buyer would pay — it is not mis-denominated. It is (a) the *buyer total*,
5 % + 18 CZK above the ask, and (b) for ~70 % of rows a *re-expression of a zloty price at Vinted's
daily rate*. The second property is the fatal one, because it makes the price **non-stationary in a
way no marketplace fixed effect can absorb**: a dummy shifts a level, and this is a time-varying
multiplier on three quarters of the rows. That — not thin data — is why §6.2's Vinted coefficient
was never estimable, and it is a better reason than the one the first version gave.

### 5.3 A live consequence: FX drift manufactures `PriceChange` rows

This belongs here because it is a property of the Vinted *price*, not of the price model, and
nothing in the pipeline docs records it.

`QueryRunner.run_existing_query` detects a price change by **string comparison of `price_raw`**
(`bazos/scraping/query_runner.py:194`), and `VintedScraper._map_item` builds that string as
`f"{round(total_item_price)} {currency}"`. The fitted rate moves on the order of 0.1 %/day (§5.2
measures a direction, not a calibrated rate), which on the **median
Vinted stored price of 7,732 CZK** is **~8 CZK/day** — far above the 1 CZK granularity of the
string. So a re-seen Polish-priced Vinted listing whose seller changed nothing still compares
unequal, writes a `PriceChange` row, and — via the unconditional
`AdDelivery.objects.filter(ad=known_ad).update(status=PRICE_CHANGED)` at `query_runner.py:215` —
flips **every** delivery of that ad back into the filter. When the zloty falls, `PriceDropRule` sees
a genuine-looking drop, returns `PASS`, and the delivery can be approved and sent again.
`PriceChange.old_price_amount` / `new_price_amount` record the FX move as real CZK price history.

**What is verified and what is inferred.** The mechanism is verified in the code (both call sites
above, read this pass) and the FX drift is measured (§5.2). **The blast radius is inferred, and it
is narrower than the mechanism suggests**: `VintedScraper` does not override `dedup_break_streak`,
so it is 1 — `run_existing_query` breaks at the first already-known non-topped ad. Only the boundary
ad plus any topped ones are re-compared per pass, and `topped` is 3.6 % of query 13 (37/1,037).
So the realistic shape is not a corpus-wide price-change stream but *a handful of listings re-priced
on every pass* — 32–96 passes/day at the configured 15–45-minute interval — each flip re-entering
the filter. That is a repeat-notification loop on a small set: nastier per listing than the
corpus-wide reading, and cheaper in aggregate. **The DB was not queried for this** — the corpus
export carries no `PriceChange` table and this session had no database access. Counting
`PriceChange` rows per marketplace is a one-line query and is the check that would settle it.

### 5.4 Sbazar's zero is handled correctly

12 of 621 Sbazar rows are `price_raw = "Dohodou"`, `price = NULL`, `price_type = negotiable`. **No
row in any of the three corpora has `price = 0`**, and Bazos and Vinted have no non-EXACT price at
all in 3,888 rows. The `price_by_agreement` branch described in
[`PRICE_PARSING.md`](PRICE_PARSING.md) §6 is doing its job: negotiables land as NULL (and are
dropped from modelling), and a genuine `FREE` would land as a real `price = 0`.

8 of the 12 are visibly not MacBooks (parts, adapters, office furniture) and the `kind` filter
removes them. One practical note: these 12 rows mean `price_range`'s `price is None` exemption is
**live on Sbazar and untested on Bazos**, where the marketplace applies the range server-side.

### 5.5 Bazos

All 2,851 query-8 rows are `price_type = exact`. Bazos applies the query's price range server-side
in the URL, so placeholder-priced ads (`Dohodou`, `V textu`) never enter this corpus — which is also
why a change to that range changes the *support* of the corpus rather than just its size (§2.1).

### 5.6 Basis summary

| | stored `price` is | correction needed | usable as-is? |
|---|---|---|---|
| bazos | seller's ask, CZK int | none | **yes** |
| sbazar | seller's ask, CZK int | none | **yes** (drop `negotiable`) |
| vinted | buyer's total, CZK int | `÷ 1.05` after `− 18`, **and then it is still a zloty price for ~70 % of rows** | **no** |

---

## 6. Spec-matched comparison

A *spec cell* is `family | chip | RAM | SSD | screen` (e.g. `pro|apple1_pro|32|512|16.0`), built
from the shipped extractor on titles. Only rows where all five are extracted qualify.

### 6.1 Per-config medians — the largest shared cells

Asks in CZK, Vinted de-fee'd. Sorted by Sbazar count:

| spec cell | bazos median (n) | sbazar median (n) | vinted median (n) |
|---|---|---|---|
| `pro\|intel9_base\|32\|1000\|16.0` | 11,250 (6) | 12,990 (29) | 13,626 (1) |
| `pro\|apple1_pro\|16\|512\|14.0` | 18,290 (40) | 18,390 (20) | 17,124 (2) |
| `pro\|apple1_base\|16\|512\|13.0` | 12,999 (23) | 13,590 (18) | 13,504 (1) |
| `pro\|apple1_max\|32\|512\|16.0` | 29,540 (14) | 28,690 (12) | 29,438 (1) |
| `pro\|apple1_pro\|32\|512\|16.0` | 19,900 (28) | 19,945 (12) | 25,478 (1) |
| `pro\|intel9_base\|32\|512\|15.0` | 11,690 (37) | 11,690 (12) | — |
| `air\|apple2_base\|16\|512\|13.0` | 16,990 (14) | 16,790 (10) | — |
| `pro\|apple2_max\|32\|1000\|16.0` | 39,990 (7) | 39,990 (8) | — |

**Look at how many of those pairs are equal to within a rounding of the price ladder.** That is the
visual form of §6.2's withdrawal: at matched configuration, in the price band where both queries can
see, Sbazar and Bazos ask the same. The cells where Vinted is cheap are the old Intel ones —
`air|intel5_base|8|128|13.0` runs 5,490 (31) against 4,453 (14), −18.9 %, and
`pro|intel7_base|16|256|15.0` 8,300 (121) against 5,279 (6), −36.4 % — while Apple-silicon cells go
the other way (`air|apple1_base|8|256|13.0` +2.1 %, `air|apple2_base|8|256|13.0` +11.1 %).

### 6.2 The marketplace effect — the +3.5 % is withdrawn

> **Withdrawn:** "Sbazar asks **+3.5 %** for the same configuration (95 % CI +1.8 % … +5.1 %,
> 189 Sbazar ads inside 82 spec cells)."
>
> **Corrected:** within spec cells shared with Bazos, **Sbazar's ask is +1.3 % (95 % CI
> −1.1 % … +3.0 %)** — indistinguishable from zero — once both sides are restricted above the
> 10,000 CZK floor that query 14 imposes and query 8 does not. 292 Sbazar ads across **51 shops**,
> 627 Bazos ads, 76 cells, seller-clustered pairs bootstrap.

The old figure fails on **two** counts, and it is worth separating them because only one is about
statistics:

1. **The published interval was never clustered at all.** `xm/model_de.py` computes
   `groupby('marketplace').res.agg(mean, sem)` and multiplies by 1.96 — an i.i.d. SEM over *ads*.
   It treated 189 listings, most of them a handful of dealers' inventory, as 189 independent draws.
2. **Roughly half the point estimate is truncation.** Inside a spec cell whose price distribution
   straddles 10,000 CZK, Sbazar's cheap ads are unobservable *by construction* while Bazos's are
   not. The effect is entirely concentrated there:

| specification (5-way cell, title basis) | Sbazar effect | Sbazar n | cells |
|---|---:|---:|---:|
| no control — the published estimand, on 1.35× the data | +3.25 % | 295 | 78 |
| both sides restricted to ask ≥ 10,000 CZK | **+1.32 %** | 292 | 76 |
| both sides ≥ 12,000 / ≥ 15,000 | +1.02 % / +0.82 % | 256 / 188 | 68 / 57 |
| **the truncation-exposed cells only** (Bazos p10 < 10,000) | **+9.93 %** | 53 | 8 |
| cells where **no** Bazos ad falls below 10,000 | **+1.08 %** | 230 | 66 |

The last two rows are cuts of the *uncontrolled* sample by different rules — "exposed" is
`Bazos p10 < 10,000`, "safe" is "no Bazos ad at all below 10,000" — so their cell counts do not sum
to 76. Seller-clustered pairs bootstrap on the preferred row: mean-deviation **+1.32 % CI [−1.05 %,
+2.97 %]**, cell-fixed-effects OLS +2.23 % CI [−1.83 %, +6.92 %].

**The intermediate diagnosis — "it is one shop, MacPoint2" — is also wrong, and that matters more
than the conclusion.** Leave-one-shop-out across **all 52** Sbazar shops at the published 5-way cell
moves the estimate only between **+2.14 % and +3.68 %** (full +3.25 %); dropping MacPoint2 leaves
+2.14 %, not +0.71 %. The +0.71 % appears only at a 6-way cell where removing that shop leaves 44
Sbazar ads — a sample collapse, not a demonstration. And clustering never moves a point estimate at
all, so "clustering artifact" could only ever have been a claim about the interval. **It was never
one shop; it was one uncontrolled confound**, and the confound was named in §2.1 of the first
version of this document and then not applied here.

Three limits bound what any Sbazar level figure can mean:

- **The complete-spec gate selects *sellers*, not ads.** MacPoint2's 167 listings survive it at
  **99 %** because its titles are formulaic (`MacBook Pro 16'' 2023 / M2 Max / 64GB / 512GB SSD`);
  **MacBookprodejna — the largest Sbazar shop at 193 ads — survives at 24 %** (5-way) and **1 %**
  (6-way), because its titles read `MacBook PRO 14"`. So 53–73 % of matched Sbazar rows are one
  dealer, only 22–57 of 143 shops appear at all, and **the estimate speaks for 38–53 % of the Sbazar
  corpus.** That is a sharper statement than "one shop dominates", and it generalises: every
  spec-matched number in this document is computed on whichever sellers write machine-readable
  titles.
- **Cluster-robust inference is undefined on this design.** With one shop holding ~80 % of the
  treated rows, a simulation matched to this cluster structure rejects a *true null* **50 % of the
  time under CR1 and 30 % under CR3** at nominal 5 %; spread the same treated n over 49 equal
  clusters and CR1 is correctly sized at 5.5 %. Only the **pairs cluster bootstrap** held size
  (6–7 %), which is why it is the one quoted. **Quote the number of shops, never the number of ads.**
- **`Ad.modified` never advances.** A durable +1.3 % ask gap could equally be a longer time-to-sale
  at the same clearing price. Nothing in the DB separates the two.

Vinted, same protocol on 2.4× the earlier data: **−13.37 % (CI −17.33 % … −5.92 %)** over 76 shared
cells, collapsing to **−2.66 % (CI −7.30 % … +4.44 %, n=37)** on Apple-silicon cells only. **The
original reading — "Vinted's −17 % is composition, not a level" — reproduces.** The discount lives
in pre-2018 Intel machines, where Vinted's damaged/for-parts/bait population concentrates and the
`defect` flag cannot catch it because there is no description. The *sub-population* result is now
well-estimated; the *marketplace* coefficient still is not, and §5.2 says it never will be from this
column.

### 6.3 Bazos and Sbazar share inventory

42 normalised MacBook titles (≥ 20 chars) appear on both Bazos and Sbazar — **77 Sbazar ads
(12.4 %) and 80 Bazos ads (2.8 %)**. On the 586 Sbazar MacBook rows with an EXACT price the overlap
is **87 titles (14.8 %)**, of which **63 fall inside the shipped artifact's training window** and
**48 of 87 carry an identical ask on both sites**. Bazos × Vinted is 36 titles (58 Bazos / 46
Vinted); Sbazar × Vinted is 3.

Two consequences. Part of the reason Sbazar's effect is small is that **part of Sbazar is Bazos**.
And a pooled model must group cross-posted duplicates in CV or it scores itself on machines it has
already seen: removing cross-posted titles moves the shipped artifact's Sbazar score from R² 0.817
to 0.773 and MedAPE 10.8 % → 11.4 %, so the leakage is worth ~0.04 of R².

---

## 7. Does pooling help the model?

Basis change, stated up front: the first version ran `HistGradientBoostingRegressor` on all MacBook
rows grouped by `marketplace | title`. This version runs **Ridge** (the estimator class actually
shipped — see [`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md)) on **gate-eligible rows only**
— what the production model would actually score — grouped by the **seller** (`email`/`phone`
publisher id on Bazos, `publisher_name` on Sbazar, lowercased title on Vinted, which is degenerate).
Pooled out-of-fold, `GroupKFold(5) × 3`. **Sign convention also changed**: `bias = mean(log ask −
log pred)`, so **positive means the model under-predicts, i.e. calls the ad expensive** — the
opposite of the first version's sign.

### 7.1 The pooling table

| | bazos R² (n=1,932 pooled out-of-fold rows) | sbazar R² (n=229) | vinted R² (n=150) |
|---|---:|---|---|
| **A** Bazos-only model, CV on Bazos | **0.923** | — | — |
| **B** Bazos-trained, zero-shot | — | 0.907, MedAPE 8.9 %, bias **+8.8 %** | 0.798, bias **−7.1 %** |
| **C** pooled, **no** marketplace feature | 0.928 | 0.910, bias +7.5 % | 0.810 |
| **D** pooled, **with** marketplace feature | 0.928 | **0.940**, MedAPE 6.0 %, bias **+1.2 %** | 0.820 |
| **E** own-marketplace data only | — | **0.406** | 0.770 |
| bootstrap D − C (800 reps) | +0.001 [−0.002, +0.005] | +0.019 **[−0.038, +0.042]** | +0.011 [−0.006, +0.030] |
| bootstrap D − A on Bazos | +0.005 [−0.000, +0.012] gate-eligible; −0.007 [−0.019, +0.003] all rows | | |

Four readings, two of which revise the first version:

1. **"Pooling never hurt Bazos" survives — but as *indistinguishable from zero*, not as a gain.**
   Both bootstrap intervals straddle it.
2. **Sbazar cannot have its own model.** R² 0.406 under Ridge and −0.211 under HGB on 229 ads in 25
   shops. The choice is pooled-with-a-dummy, or nothing.
3. **The marketplace dummy's value is the *bias*, not the R².** It lifts Sbazar R² 0.910 → 0.940 but
   that difference's CI includes zero; what it unambiguously buys is bias +8.8 % → +1.2 %. Under HGB
   the dummy adds no R² at all (0.870 → 0.865) because the tree finds the level through its own
   splits, yet still leaves +5.3 % bias. **For an inverted alert rule the level, not the R², is the
   statistic that decides anything.**
4. **The R² 0.919 / MedAPE 8.3 % that the shipped artifact scores on Sbazar is not evidence of
   transfer.** At the identical gate it scores *in-sample* Bazos at 0.940 / 8.1 %, so Sbazar is not
   beating the model's home turf — it is an easier subset. **73 % of those rows are MacPoint2, whose
   median within-config sd of log ask is 0.017: a price ladder, not a market.** Strip it at the
   5-way gate and the same artifact gives **R² 0.687 / MedAPE 16.9 % with a +19.3 % bias**;
   MacBookprodejna alone is R² 0.250 / MedAPE 21.9 %.

### 7.2 What the marketplace coefficient actually absorbs

Keep the pooled-model-with-a-marketplace-feature recommendation, but stop reading the coefficient as
a marketplace price level. **Sbazar's level shift is not constant across spec-completeness strata,
and `training.py` as written fits the dummy mostly on the stratum the gate throws away:**

| variant | coef (sbazar − bazos) | bias on gate-eligible **Sbazar** | bias on gate-eligible **Bazos** |
|---|---:|---:|---:|
| zero-shot Bazos model, gate-eligible Sbazar rows | n/a | +8.12 % | — |
| zero-shot Bazos model, **declined** Sbazar rows (61 % of them) | n/a | **+23.47 %** | — |
| pooled, trained on all `macbook` + EXACT rows (`training.py` today) | **+15.7 %** | **−9.12 %** (over-corrects, the false-deal direction) | +0.25 % |
| pooled, trained on **gate-eligible rows only** | **+9.3 %** | **−0.71 %** | +0.53 % |

Training on gate-eligible rows fixes it and does not hurt Bazos (R² 0.9300 vs 0.9253, MedAPE 8.17 %
vs 8.34 %). This contradicts `training.py`'s own docstring — "ads with incomplete specs are KEPT,
their missingness is a feature" — and the resolution is that **the model never *scores* those ads**,
so the training distribution that matters is the gated one. The coefficient is therefore composed of
dealer mix and query-floor truncation (§6.2), not of a marketplace effect.

One methodological rule falls out of the same data, and it is the one to carry forward:
**a bootstrap over marketplace comparisons must cluster on the seller, not on `marketplace | title`.**
The identical +3.90 % point estimate over the same 1,684 ads gives [+1.47 %, +6.46 %] under title
clustering and [−0.69 %, +6.06 %] under shop clustering. When 61 % of a corpus comes from two shops,
title clustering counts one shop's relistings as independent evidence — that is the whole difference
between "real and stable" and "not distinguishable from zero".

### 7.3 What shipping the Sbazar extension would actually buy

Shipping is priced: **≈40 lines across 5 files, one migration (an index on
`Ad(marketplace, publisher_name)`), one retrained artifact and a test.** The return, measured on the
**same 20.4-day window** with the shipped artifact's residuals, gate-eligible rows only:

| marketplace | scoreable | ≤ −15 % | ≤ −25 % | live rule (`z ≤ −2` **and** discount ≥ 10 %) |
|---|---|---|---|---|
| bazos | 486 (167/wk) | 90 (30.9/wk) | 34 (11.7/wk) | **16 alerts = 5.50/wk** (60 over the full 118 d = 3.56/wk) |
| sbazar | 229 (79/wk) | 2 (0.69/wk) | **0** | **0 alerts.** Deepest discount in 20 days: 24.0 %, against a 46.5 % bar |
| sbazar, retrained pooled artifact | 229 | — | — | **1 alert = 0.35/wk** |
| vinted | 150 (52/wk) | 53 (18.2/wk) | 35 (12.0/wk) | 13 = 4.47/wk — but see §5.2 and below |

**0 is an upper-bounded zero, not an estimate**: 0/229 bounds the true rate at 1.31 % (95 %, rule of
three), i.e. up to ~1.04 alerts/wk. The decision survives that easily — Bazos runs 5.50/wk on the
same rule in the same window.

**Why Sbazar is silent is structural, not a threshold artifact.** 80.3 % of the 229 gate-eligible
ads belong to two shops (MacPoint2 165, KupJablko 19) whose residual spread is σ 0.08 and whose
levels are +4.1 % and −10.6 % against the Bazos market. **Professional shops do not underprice.**
Pooled within-shop σ is 0.0796 across the seven shops with ≥ 3 ads.

A real defect sits underneath, and it would bite any seller-less marketplace: **`seller_prior_ads`
counts `email_publisher_id`, which is NULL on 100 % of Sbazar and Vinted rows, so every such ad
lands in the *widest* sigma bucket.** That is backwards — a seller-less marketplace is not a
first-time private seller, it is an unknown.

| σ source | value | `z ≤ −2` means |
|---|---:|---|
| shipped bucket 0 — what a Sbazar ad **would** get under the extension | 0.3129 | **46.5 % below prediction** |
| shipped bucket 50+ | 0.1129 | 20.2 % |
| **measured** Sbazar, all shops (n=229) | **0.1046** | **18.9 %** |
| measured MacPoint2 alone (n=165) | 0.0806 | 14.9 % |
| measured Bazos (n=1,923) | 0.1617 | 27.6 % |
| measured Vinted (n=150) | 0.2849 | 43.4 % |

Sbazar's `publisher_name` reproduces the shipped bucket structure exactly once used as the key
(0 → 0.156, 3–9 → 0.062, 10–49 → 0.097, 50+ → 0.081, the same monotone shape as Bazos's
0.246 → 0.104), so the fix is a key, not a model. **But it cannot ship on its own**: nothing off
Bazos is scored at all until the extension it is meant to support ships.

Finally, a correction to how an alert *rate* may be compared at all. **Use Bazos rows created after
the artifact was trained.** The shipped artifact's in-sample Bazos rate at −25 % is 2.8 %;
out-of-sample it is 8.7 %. A Vinted-vs-Bazos ratio quoted against the in-sample denominator reads
8×; the honest figure is **2.7×**. The same measurement shows the artifact drifts: 17 days after
training, Bazos gate rows show **−5.29 % bias** (−4.52 % holding spec cells fixed) against −0.63 %
in-sample, and September alone is −5.52 % where May–August are all near −1 %. **A threshold
calibrated once is perishable, and retraining cadence matters more than the choice of estimator.**

### 7.4 This is no longer hypothetical

The first version could say "nothing in production consumes these numbers". That is no longer true.
`PRICE_MODEL_SHADOW_MODE` is **`false` in the production `.env`** (the shipped default in
`bazos/const.py` and `scraper/settings.py` is `True`; production overrides it), and query 8 carries
`price_model` in `filter_rule_names` with `filter_price_model_z = −1.5`. **The rule is live**, it
has produced 88 `AdPriceScore` rows for `macbook/2026-08-26` — 47 of them declined — and 37 of query
8's 151 delivery rejections are its doing.

Two live observations worth carrying:

- **The four deepest-discount scored ads on query 8 were all `SENT`**, and three of the four are
  priced at 4,000 / 3,000 / 3,999 CZK — i.e. in exactly the stratum the query-floor change admitted
  (§2.1). The model's most extreme opinions are concentrated on inventory that did not exist in its
  training support.
- **Gate contamination is real, not theoretical.** A *motherboard* listing — `Základní deska Apple
  MacBook 820-01041 A1990`, 6,000 CZK — was claimed by `MacbookPriceModel.applies_to` and scored at
  predicted 8,814 / z −1.59. It was rejected by `location_distance` before `price_model` ever ran.
  A part priced like a laptop is precisely the "nonsense spec → nonsense prediction → underpriced
  tail" failure, and here the gate that caught it was unrelated.

Because `price_model` is the one **inverted** rule, a silent failure is a *rejecting* failure. With
shadow mode off and today's artifact, extending to Sbazar would make the model **decline 392 of 621
ads (63.1 %) — which `PASS` — and score 229, finding 0 deals, rejecting all 229**. The net effect of
turning it on would be to drop every Sbazar ad the model could read and deliver the 63 % it could
not.

---

## 8. What to change, in priority order

1. **Do not extend `MacbookPriceModel.applies_to` to Sbazar now.** The extension is correct and
   nearly worthless (§7.3). Revisit when **either** (a) P24 / `AdOutcome` exists, so precision is
   measurable at all rather than composition-audited, **or** (b) Sbazar's gate-eligible
   private-seller share rises above ~50 % — today it is **20 %** (46 of 229 ads are outside the top
   two shops).
2. **Equalise the query price floors, or drop them and filter in `run_filter`.** This is now the
   single highest-value change for any cross-marketplace work: it is what invalidated §6.2, and
   query 8's own floor moved *inside* the artifact's training window (5,000 → 3,000 on 2026-08-30),
   so it also breaks the model's own support. It is a configuration change, not a modelling one.
3. **Vinted needs three things, in this order, before it is worth re-measuring at all:**
   (i) **store the seller ask alongside the buyer total**, or add an explicit price-basis column —
   `Ad.price` silently means two different things today and the difference is 5 % + 18 CZK;
   (ii) **capture the country/currency the seller set**, which is what makes §5.2's ~70 % separable
   per row instead of estimable only in aggregate; (iii) **then** set `load_full_description`, which
   is worth the condition flags (`defect`, warranty, battery %) that are 0 % off Bazos today.
   Doing (iii) first buys better features on a price that is still unusable.
4. **Ship extractor fix #8b on its own merits** (`8 RAM / 256 SSD`, unitless labelled tokens): +8
   gate-eligible Bazos ads, the only one of the ten with real Bazos value, plus fix #2 for the one
   *wrong* extraction it corrects. Carry the two spec defects in §4.3 with it. Treat #5–#7, #9 and
   #10 as Vinted work, and **measure any extractor change on the production basis** (`name` +
   `short_description`), never title-only.
5. **Make `seller_prior_ads` marketplace-aware** — `email_publisher_id` on Bazos, `publisher_name`
   on Sbazar, nothing on Vinted — and **never fall back generically**. It is a prerequisite for
   item 1 rather than an independent win (§7.3).
6. **Train any pooled artifact on gate-eligible rows only** (§7.2), and pin `PRICE_MODEL_VERSION`
   before adding an artifact directory: it is a single global string resolving `latest` by string
   sort, so a new dated directory re-scores **every** marketplace at once, Bazos included.
7. **Do not build Bazos seller-identity features into a pooled model**, and do not reach for
   `publisher_name` as a substitute on Bazos — it is a display first name (§3).

---

## 9. Reproduction

Read-only against the production Postgres; nothing was written. The shared protocol —
seller-grouped CV, pooled out-of-fold scoring, MedAPE in CZK against R² on the log scale, and the
prohibition on random splits — lives in
[`experiments/price_model/common/ph.py`](../../experiments/price_model/common/ph.py), which is the
same harness every `*_PRICE_MODEL.md` in this directory uses, so the numbers are comparable across
corpora. The 2026-08-26 scripts are in
[`experiments/price_model/xm/`](../../experiments/price_model/xm/) — throwaway analysis, excluded
from ruff and mypy, needing `poetry install --with ml`. The exported corpus is **not** committed
(seller names, publisher ids); re-export with `xm/export.sql` against a read-only connection.

| File | What it does |
|---|---|
| `export.sql` | the production pull (read-only join of `bazos_ad` × `bazos_addelivery`) |
| `cov.sql`, `s1.sql`, `s2.sql` | §3 field coverage, raw row samples, price-shape checks |
| `probe_vinted.py`, `fee_fit.py` | §5.1's original live probe of `vinted.cz` and the fee fit |
| `mbfeat2.py` | the 2026-08-26 extractor — §4.3's fixes, every change tagged `# v2:`. Compare against `bazos/pricing/features.py`, which has two of them |
| `xfeat.py`, `xfeat2.py`, `ceiling.py` | §4.1–§4.2 coverage and recall-given-signal-present |
| `combine.py`, `specmatch.py` | §5–§6 pooled dataset, fee correction, spec cells, per-config medians |
| `model_x.py`, `model_de.py` | the original §6.2 / §7 tables — **`model_de.py` is where the unclustered SEM lives**; read it before quoting any interval from the first version |

The 2026-09-12 re-measurement (the free (period, phase) scan, the PLN lattice solve, the truncation
control, leave-one-shop-out, the matched-null cluster simulation, and the alert funnels) was run as
throwaway scripts against the same export and is **not** committed. Two things there are worth
re-deriving rather than re-reading: the **(period, phase) scan** of §5.1, because it is the only
non-circular confirmation of the fee, and the **matched-null simulation** of §6.2, because it is
what rules out every cluster-robust estimator on this design.

---

## 10. What this does *not* establish

- **Nothing about realised prices.** Every number here is an *asking* price. `Ad.modified` never
  advances past `created`, so the DB records **zero** outcomes — the gap
  [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §6 names, now applying to three marketplaces.
  Both the case for and the case against shipping rest on alert **volume** and residual structure,
  never on whether the alerts are good.
- **A Sbazar level, in either direction.** +1.3 % with a CI through zero is not "no premium
  measured"; it is "not measurable on this design". The gate selects sellers (§6.2), one shop holds
  ~80 % of the treated rows, and cluster-robust inference is undefined here.
- **The Vinted marketplace coefficient**, and §5.2 says it is not merely under-powered — it is not
  identified from a column that mixes CZK sellers with zloty sellers at a drifting rate.
- **Whether the FX churn of §5.3 has actually fired.** The mechanism is code-verified and the drift
  is measured; the `PriceChange` count per marketplace was not queried.
- **Persistence.** 20 days of Sbazar and Vinted against 118 of Bazos. Nothing here has been observed
  to hold across a season, and Sbazar sorts by *edit* time
  ([`SBAZAR_SCRAPER.md`](../archive/shipped/SBAZAR_SCRAPER.md) §11), so its corpus over-represents
  re-edited inventory in a way nothing here models.
- **New-ads/day per marketplace.** Use the method in
  [`METHOD_CALIBRATION.md`](marketplaces/METHOD_CALIBRATION.md) instead.
- **Cross-marketplace duplicate detection.** 12.4 % of Sbazar ads are title-identical to a Bazos
  row; a real dedup key (there is no shared seller id) was not attempted, and those rows sit on both
  sides of every comparison above.
