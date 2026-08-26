---
title: MacBooks across Bazos, Sbazar and Vinted — can the three be pooled?
status: reference
updated: 2026-08-26
verified: 2026-08-26
---

# MacBooks across Bazos, Sbazar and Vinted — can the three be pooled?

Follow-up to [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md), which modelled 2,038 **Bazos**
MacBook ads. That work is now repeated on the other two marketplaces where the same product is
scraped (`Query` 13 = Vinted, 14 = Sbazar), to answer one question: **does the Bazos work
transfer, and can the three corpora go into one model?**

Everything below was measured on a fresh production pull (2026-08-26) plus one live Vinted probe
the same day. Working scripts are named in §9.

---

## 1. Verdict

| Question | Answer |
|---|---|
| Does the Bazos **spec extractor** transfer? | **Yes, essentially perfectly.** After 8 small fixes (§4), recall *given the spec is present in the text* is 98.8–100 % on all three. Nothing about the extractor is Bazos-specific. |
| Do the three **corpora** carry the same information? | **No.** Bazos has ~244 chars of description per ad; Vinted and Sbazar have **zero** — title only. That is a config choice (§3.1), not a platform limit. |
| Are the **prices** on the same basis? | **Not as stored.** Vinted stores a fee-inclusive price that is exactly `seller_ask × 1.05 + 18 CZK` (§5.1). It is fully invertible, so this is fixable, not fatal. |
| Can Bazos + **Sbazar** be pooled? | **Yes, with a marketplace fixed effect.** Sbazar asks **+3.5 %** for the same configuration (95 % CI +1.8 % … +5.1 %, 189 Sbazar ads inside 82 spec cells shared with Bazos; the independent cell-by-cell estimate agrees at +3.8 %). Pooling lifts a Sbazar model from R² 0.72 → **0.81**. |
| Can **Vinted** be pooled? | **Not yet — pool it only as a de-fee'd, chip-controlled subset, and do not trust the level.** The apparent −17 % discount collapses to **−1.8 % (CI −15 % … +13 %)** once you look at Apple-silicon configs only. n = 15. **Method demo, not a conclusion.** |
| Combined model overall | Train **one pooled model with `marketplace` as a feature**. It never hurt any marketplace and clearly helped the two small ones (§7). |

**One-line answer: yes for Bazos + Sbazar, with a fixed effect. Vinted joins the pool but its
coefficient is not yet estimable — and its price must be de-fee'd first or every number is 5 % wrong.**

---

## 2. What was pulled

Production, read-only, 2026-08-26:

```
ssh user@raspberrypi5.local 'docker exec -i marketplace-scrapper-postgres-1 psql -U postgres -d postgres -q' \
  < xm/export.sql > xm/mb3.csv     # bazos_ad ⋈ bazos_addelivery, query_id IN (8,13,14)
```

| Query | Marketplace | Rows | First ad | Last ad | Query price floor |
|---|---|---:|---|---|---:|
| 8 | `bazos` | 2,198 | 2026-05-17 | 2026-08-25 | 5,000 |
| 14 | `sbazar` | 460 | 2026-08-23 | 2026-08-25 | **10,000** |
| 13 | `vinted` | 185 | 2026-08-23 | 2026-08-25 | **2,000** |

Delivery status is almost entirely `SENT` (2,190 / 184 / 460); 6 rejects and 3 send failures in
total, so the corpus is effectively "everything the scrapers saw".

### 2.1 Three confounds that must be controlled before any comparison

1. **The three queries do not share a price floor** (5,000 / 10,000 / 2,000 CZK). Raw medians are
   therefore meaningless: Bazos's median ask is 10,990 CZK over its own corpus but **18,595 CZK**
   once restricted to Sbazar's 10k–100k window. Every comparison below either matches on
   configuration or restricts to a common band.
2. **Bazos has 101 days of history; the other two have 2.45 days.** Bazos's median ask per ISO
   week in the 10k–100k band moves between 14,494 and 19,900 with no trend, so the 3-month Bazos
   corpus is used in full — but the Bazos rows *inside* the shared window are only 67 in-band, which
   is why the shared-window comparison is not the primary one.
3. **Composition differs sharply.** Share of MacBook rows by chip family:

   | | Apple silicon | Intel | chip not extractable |
   |---|---:|---:|---:|
   | bazos | 47.9 % | 45.8 % | 6.3 % |
   | sbazar | **80.5 %** | 8.3 % | 11.2 % |
   | vinted | 34.1 % | 21.4 % | **44.5 %** |

   Sbazar's inventory is far newer than Bazos's; Vinted's is older *and* mostly unidentifiable
   from the title. Any unmatched price comparison is measuring this table, not the marketplaces.

Row counts in the 2.45-day shared window: bazos 147, sbazar 460, vinted 185. Sbazar's are heavily
skewed by a 399-row day on 2026-08-25 (Sbazar sorts by *edit* time — see
[`SBAZAR_SCRAPER.md`](../archive/shipped/SBAZAR_SCRAPER.md) §11), so **new-ads/day is not
measurable from this window** and no rate is claimed here.

---

## 3. Field coverage

Non-null (and non-empty-string) counts, straight from Postgres:

| `bazos_ad` column | bazos (n=2,198) | sbazar (n=460) | vinted (n=185) |
|---|---|---|---|
| `price` | 2,198 (100 %) | 451 (98 %) | 185 (100 %) |
| `price_type` | all `exact` | 451 `exact`, 9 `negotiable` | all `exact` |
| `price_raw` | `"10990 Kč"` | `"19900 Kč"` / `"Dohodou"` | `"14884 CZK"` |
| `location` | 2,198 (100 %) | 460 (100 %) | **0** |
| `view_count` | 2,198 (100 %) | **0** | **0** |
| `publish_date` | 2,198 (100 %) | 460 (100 %) | **0** |
| `topped` | 276 true | 5 true | 6 true |
| `name` | 100 %, ⌀ 47 chars | 100 %, ⌀ 35 chars | 100 %, ⌀ 35 chars |
| `short_description` | 2,198 (100 %), ⌀ 244 chars | **0** | **0** |
| `full_description` | 107 (4.9 %) | **0** | **0** |
| `publisher_name` | 2,198 (100 %) | 460 (100 %, `shop_url`) | **0** |
| `email_publisher_id` | 2,132 (97 %) | **0** | **0** |
| `phone_publisher_id` | 2,198 (100 %) | **0** | **0** |

Three consequences:

- **Seller identity does not exist off Bazos.** `SellerAdCounts`, the dealer proxy, and the
  finding that *67 % of Bazos residual variance is between sellers*
  ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §5) have **no counterpart** on Sbazar or
  Vinted. Sbazar's `publisher_name` (the shop slug) is the only seller handle available anywhere
  else, and it is a string, not an id shared with `Ad`. This is the single largest thing that does
  not transfer.
- **Vinted contributes nothing but a title and a price.** No location, no publish date, no views,
  no seller.
- **`view_count` is Bazos-only**, so any demand-side feature is Bazos-only.

### 3.1 The missing descriptions are a config choice, not a platform limit

`VintedScraper.load_full_description` and `SbazarScraper.load_full_description` both exist and both
fetch a real description (Sbazar additionally back-fills `short_description[:300]` from it). They
are simply never called: **`Query.load_full_description` is `false` on queries 13 and 14** and
`true` on query 8. `QueryRunner._handle_new_product` gates on that flag.

So the text gap in §4 is closable by flipping one boolean per query, at the cost of one detail
request per new ad (both scrapers pace themselves — `VINTED_DETAIL_WAIT_TIME`, and Sbazar's
`_get`). Given the sizes above that is ~75 extra Vinted and ~190 extra Sbazar requests/day.

Note that Bazos gets its 244 chars for **free** — `BazosScraper` reads `.popis` off the listing
page. Neither Vinted's search API nor Sbazar's returns a description at all, so the two are not
comparable on cost. Bazos's own `full_description` (the detail page) only starts on 2026-08-24 and
covers 4.9 % of the corpus, which is why §4 reports Bazos both ways.

---

## 4. Does `mbfeat` transfer?

`mbfeat.py` is the regex spec extractor built for Bazos Czech text (chip / year / screen / RAM /
SSD / condition flags). It was run unchanged on all three corpora, then fixed.

### 4.1 Coverage of the **unmodified** Bazos extractor

Share of rows classified `kind == macbook` for which each field is extracted. Title-only is the
only basis on which all three are comparable (§3):

| | n | macbook | chip | year | screen | RAM | SSD | all 5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bazos, title only | 2,198 | 98.3 % | 84.7 % | 70.8 % | 88.3 % | 79.2 % | 76.3 % | 53.3 % |
| sbazar, title only | 460 | 95.9 % | 82.1 % | 54.0 % | 86.8 % | 57.8 % | 56.5 % | 25.9 % |
| vinted, title only | 185 | 93.5 % | 54.9 % | 57.2 % | 50.3 % | 47.4 % | 37.6 % | 13.3 % |
| bazos, **title + description** | 2,198 | 98.7 % | 91.6 % | 80.7 % | 91.2 % | 91.2 % | 90.3 % | **65.8 %** |

Bazos's real advantage is the last row: the description alone is worth **+12 pp** on a complete
spec. Sbazar and Vinted cannot reach it today (§3.1).

### 4.2 The gap is information absence, not extractor failure

Recall was re-measured **conditional on the signal being visibly present in the title**
(`xm/ceiling.py`), using the fixed extractor:

| | year in title / recall | screen in title / recall | capacity in title / recall | chip in title / recall |
|---|---|---|---|---|
| bazos | 71.0 % → **99.8 %** | 80.0 % → **100 %** | 81.9 % → **98.8 %** | 88.2 % → **100 %** |
| sbazar | 54.0 % → **100 %** | 36.3 % → **100 %** | 53.3 % → **99.6 %** | 87.8 % → **100 %** |
| vinted | 60.1 % → **100 %** | 38.7 % → **100 %** | 48.0 % → **98.8 %** | 55.5 % → **100 %** |

Caveat on how to read this: the *chip* probe (`\bm[1-9]\b|\bi[3579]\b|core ?2`) is close to the
extractor's own pattern, so its 100 % is partly tautological — it says "there is no third chip
spelling we are blind to", not "chip extraction is perfect". The *screen* and *year* probes are
strictly narrower than what the extractor accepts (no `SCREEN_LOOSE`, no date stripping), so their
100 % is a genuine recall measurement. The *capacity* probe asks only whether RAM **or** SSD was
recovered.

**The extractor is not the bottleneck.** Sbazar and Vinted sellers write shorter, less specific
titles (⌀ 35 chars vs 47), and the pipeline stores no description for them. Spending effort on
better regexes buys almost nothing; spending it on §3.1 buys the whole 12 pp.

### 4.3 What actually broke, and the fixes

Eight defects were found. **None of them is marketplace-specific in nature** — two are pure Bazos
bugs that Sbazar merely made visible — so the fixed extractor (`xm/mbfeat2.py`) has **no
marketplace branching at all**: the differences are absorbed as extra normalisation plus a wider
cs/pl/en synonym vocabulary in the same regexes.

| # | Defect | Where it bites | Fix |
|---|---|---|---|
| 1 | `APPLE_CHIP = m([1-4])` — **M5 is invisible** | 50 Bazos, 14 Sbazar, 1 Vinted row | `m([1-9])`. A hard-coded generation ceiling silently drops every new chip the day Apple ships it. |
| 2 | `\bm2\b` cannot see a boundary in `M2PRO` | 33 Bazos, 11 Sbazar | normalise `m2pro` → `m2 pro`; move the `\b` after the optional variant group |
| 3 | A lone `128GB` is read as **128 GB of RAM** | all three; worst where titles are terse | unlabelled-token SSD floor 240 → **120**. Verified: all 6 affected rows were storage, 0 regressions |
| 4 | en/em dash not normalised (`MacBook Air 13– 256 GB`) | 120 Bazos, 12 Vinted | map `U+2010–U+2015`, `U+2212` → `-` |
| 5 | `14-inch` — hyphen blocks the unit match | 14 Bazos, 3 Vinted | split the digit from its unit before matching |
| 6 | Polish `15 cali` (= inches) | 7 Vinted | add `cal[ie]?` (+ `zoll`) to the screen units |
| 7 | Polish `2017r.` — **no `\b` between `7` and `r`**, so the year vanishes | 5 Vinted | strip a `r`/`r.` suffix after a 4-digit year in `norm()` |
| 8 | Condition flags are Czech-only — `Uszkodzony / Na części` scores `defect = False` | Vinted (16.8 % of its rows carry Polish markers) | pl/en synonyms added to `defect`, `new`, `warranty`, `scratches`, `top_word`; `dysk`/`storage` to `SSD_WORD`, `pamięć`/`memory` to `RAM_WORD`; unitless labelled tokens (`8 ram / 256 ssd`) now parse |

Effect of the fixes (title + whatever description exists), share of MacBook rows:

| | chip v1 → v2 | year v1 → v2 | screen v1 → v2 | SSD v1 → v2 | all 5 v1 → v2 |
|---|---|---|---|---|---|
| bazos | 91.6 → **93.7 %** | 80.7 % | 91.2 → 91.4 % | 90.3 → 91.0 % | 65.8 → **66.8 %** |
| sbazar | 82.1 → **87.8 %** | 54.0 % | 86.8 % | 56.5 % | 25.9 → **27.7 %** |
| vinted | 54.9 → 55.5 % | 57.2 → **60.1 %** | 50.3 → **53.2 %** | 37.6 → **39.3 %** | 13.3 → 13.9 % |

Regression check across all 2,843 rows: chip **0 lost / 72 gained**, year 0 lost / 5 gained,
screen 0 lost / 10 gained, SSD 1 lost / 20 gained; RAM 5 "lost" and 1 changed — all six are fix #3
correctly moving a 128 GB from RAM to storage.

Two residual traps worth naming, both unfixable from a title:

- **`family` mis-assigns "MacBook Neo"** (2026 line, 41 rows) unless it is added explicitly — it was.
- **Vinted `vinted.cz` is not a Czech market.** 16.8 % of its MacBook titles carry Polish-language
  markers (`cali`, `dysk`, `sprawny`, `odbiór`, `niemiecka klawiatura`) against 0 % on Bazos and
  Sbazar. `location` is empty, so the country cannot be filtered out. This is a *population*
  difference, not a text-parsing one.

---

## 5. Price comparability — the part that would poison a pooled model

### 5.1 Vinted's stored price is **not** the seller's ask

`VintedScraper._price_amount` deliberately stores `total_item_price` (buyer-protection fee
included), not `price`. A live probe on 2026-08-26 (96 MacBook results, `xm/probe_vinted.py`) fits
the fee exactly:

```
fee = 0.050000 × price + 17.9995      max residual over 96 rows: 0.005 CZK
```

i.e. **Vinted CZ buyer protection is 5 % + 18 CZK**, deterministic. Therefore:

```python
ask = (stored_price - 18) / 1.05        # recovers the seller's ask to < 0.5 CZK
```

Inverting the *rounded* integer we store recovers the true float ask with max error 0.48 CZK and
mean error 0.19 CZK — negligible. **Every number in §6–§7 uses this correction.** Skipping it puts
Vinted ~5 % high against Bazos and Sbazar, which is the same order as the real marketplace effect
being measured (§6.2 shows exactly that).

Also confirmed live: 78 % of Vinted's `price` values and 82 % of `total_item_price` are
non-integer, matching [`PRICE_PARSING.md`](PRICE_PARSING.md) §5. The scraper's `round()` is what
keeps the `"6307.5" → 63075` trap
([`VINTED_SCRAPER.md`](../archive/shipped/VINTED_SCRAPER.md) §4.5) shut — **0 stored `price_raw`
values contain a decimal point.** Currency is `CZK` on 96/96.

### 5.2 Sbazar's zero is handled correctly

9 of 460 Sbazar rows are `price_raw = "Dohodou"`, `price = NULL`, `price_type = negotiable`. **No
row in any of the three corpora has `price = 0`.** The `price_by_agreement` boolean branch
described in [`PRICE_PARSING.md`](PRICE_PARSING.md) §6 is doing its job: negotiables land as NULL
(and are dropped from modelling), and a genuine `FREE` would land as a real `price = 0`. Query 14's
10,000 CZK floor means no free giveaway can appear here anyway.

The 9 negotiables are also visibly *not* MacBooks in 7 of 9 cases (`APPLE: konektory, adaptéry…`,
`SSD Apple 512 GB - 2 ks`, `Prodej movitých věcí`) — the `kind` filter already removes them.

### 5.3 Bazos

All 2,198 rows are `price_type = exact`. Bazos applies the query's price range server-side in the
URL, so placeholder-priced ads (`Dohodou`, `V textu`) never enter this corpus at all. The
`price_range` rule's `price is None` exemption is therefore untested here.

### 5.4 Basis summary

| | stored `price` is | fee/VAT | usable as-is? |
|---|---|---|---|
| bazos | seller's ask, CZK int | none | **yes** |
| sbazar | seller's ask, CZK int | none | **yes** (drop `negotiable`) |
| vinted | buyer's total, CZK int | **+5 % + 18 CZK** | **no — divide out first** |

---

## 6. Spec-matched comparison

A *spec cell* is `family | chip | RAM | SSD | screen` (e.g. `pro|apple1_pro|32|512|16.0`), built
from the fixed extractor. Only rows where all five are extracted qualify: **1,712 Bazos, 202
Sbazar, 35 Vinted**.

82 cells contain ≥ 2 marketplaces, covering 1,519 ads.

### 6.1 Per-config medians (selection; full table in `xm/specmatch.py` output)

| spec cell | bazos median (n) | sbazar median (n) | vinted median (n) |
|---|---|---|---|
| `pro\|apple1_pro\|16\|512\|14.0` | 17,890 (45) | 18,390 (11) | — |
| `pro\|apple1_pro\|32\|512\|16.0` | 19,900 (39) | 19,900 (13) | — |
| `pro\|apple1_max\|32\|512\|16.0` | 29,790 (12) | 28,690 (7) | — |
| `pro\|apple2_max\|32\|1000\|16.0` | 37,945 (8) | 39,990 (6) | — |
| `pro\|apple1_base\|16\|512\|13.0` | 13,145 (20) | 13,890 (13) | — |
| `air\|apple5_base\|16\|512\|13.0` | 26,500 (9) | 26,490 (6) | — |
| `pro\|intel9_base\|32\|1000\|16.0` | 13,200 (8) | 12,990 (15) | — |
| `air\|apple1_base\|8\|256\|13.0` | 9,990 (57) | 10,500 (1) | — |
| `pro\|intel5_base\|8\|256\|13.0` | 6,495 (112) | 10,290 (2) | 4,244 (1) |
| `pro\|apple3_base\|16\|512\|14.0` | 21,900 (3) | — | **7,929 (2)** |

The last row is the shape of the Vinted problem: an M3 14"/16/512 at 7,929 CZK is not a market
price. Its title ends `/ OPIS` (Polish for "see description") — a listing whose real state lives in
text we do not store.

### 6.2 The marketplace effect

Within-cell log-price deviation from the cell's own mean (`xm/model_de.py` part E). This is the
cleanest available estimate because configuration is held exactly constant:

| | n ads | effect vs cell mean | 95 % CI |
|---|---:|---:|---|
| **all 82 shared cells** | | | |
| bazos | 1,299 | −0.0 % | −0.9 % … +0.8 % |
| sbazar | 189 | **+3.5 %** | +1.8 % … +5.1 % |
| vinted | 31 | **−17.2 %** | −27.3 % … −5.6 % |
| **Apple-silicon cells only (64 cells)** | | | |
| bazos | 643 | −0.6 % | −1.8 % … +0.5 % |
| sbazar | 157 | **+2.8 %** | +1.2 % … +4.5 % |
| vinted | 15 | **−1.8 %** | −14.8 % … +13.3 % |

Read this carefully:

- **Sbazar's +3 % is real and stable.** It survives restricting to Apple silicon, and the pairwise
  cell-by-cell estimate agrees: median delta +0.3 %, size-weighted mean log delta **+3.8 %** over
  180 matched pairs across 66 cells. The earlier 1-day snapshot's "+1 %" was the same effect,
  under-powered.
- **Vinted's −17 % is a composition artifact, not a level.** It vanishes on Apple-silicon cells.
  The discount lives entirely in old Intel machines, where Vinted's population of damaged /
  for-parts / bait listings concentrates — and the `defect` flag cannot catch them because there is
  no description (§3.1). **n = 15. Method demo, not a conclusion.**
- Running the same estimate on the **raw stored price** (no fee correction) gives Sbazar +3.4 % and
  Vinted **−13.3 %** instead of −17.2 %. The ~4 pp swing is the buyer-protection fee. This is what
  §5.1 means by "poisons the model": it is the same size as the effect being measured.

### 6.3 Bazos and Sbazar share inventory

26 MacBook titles appear on both Bazos and Sbazar (23 of them ≥ 20 chars, so not generic
collisions); **61 % of those carry an identical price on both sites**. That is **8.5 % of Sbazar
rows** and 2.2 % of Bazos rows.

Two consequences: part of the reason Sbazar's effect is small is that part of Sbazar *is* Bazos;
and a pooled model must group cross-posted duplicates in CV or it will score itself on machines it
has already seen. The grouping key used below is `marketplace | lowercased title`, which does
**not** catch cross-marketplace duplicates — a known optimism of ~2–8 %.

---

## 7. Does pooling help the model?

`HistGradientBoostingRegressor` on `log(ask)`, features = family, chip key, log RAM, log SSD,
screen, age, and the condition flags. NaN is passed through natively so ads with incomplete specs
stay in. Grouped 5-fold CV on `marketplace | title`. (`xm/model_x.py`, `xm/model_de.py`)

| | bazos R² | sbazar R² | vinted R² |
|---|---:|---:|---:|
| **A** Bazos-only model, CV on Bazos | **0.907** (MAE 0.114 log, median abs err 6.5 %) | — | — |
| **B** Bazos-trained, zero-shot | — | 0.668 (bias **−6.1 %**) | 0.490 (bias **+11.3 %**) |
| **C** pooled, **no** marketplace feature | 0.912 | 0.686 | 0.561 |
| **C** pooled, **with** marketplace feature | 0.912 | **0.786** | **0.588** |
| **D** own-marketplace data only | — | 0.724 (MAE 0.144) | 0.501 (MAE 0.388) |
| **D** own + all Bazos + marketplace feature | — | **0.809** (MAE 0.116) | **0.613** (MAE 0.341) |

Findings:

1. **The Bazos baseline reproduces.** R² 0.907 here vs 0.87 in
   [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md); the gain is the extractor fixes plus a
   larger corpus, and it is measured under the same grouped CV.
2. **Pooling never hurt Bazos** (0.907 → 0.912) and materially helped both small marketplaces.
   Sbazar gains most: 0.724 → 0.809, MAE 0.144 → 0.116. The 436 Sbazar rows are not enough to learn
   MacBook pricing on their own; 2,170 Bazos rows are.
3. **The marketplace feature is what makes pooling safe.** Without it, Sbazar sits at 0.686; with
   it, 0.786. A single dummy recovers 0.10 of R² — the +3.5 % level shift plus whatever composition
   the model cannot see.
4. **Zero-shot transfer is biased in opposite directions** (−6 % on Sbazar, +11 % on Vinted). A
   Bazos-trained model deployed unchanged on Sbazar would systematically call Sbazar ads
   overpriced, and Vinted ads underpriced — precisely the failure mode that turns an underpricing
   alert into noise ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §4).
5. **Vinted stays bad in absolute terms.** Even pooled, MAE 0.341 log ≈ ±41 %. That is a
   title-only, 44 %-unknown-chip, mixed-country corpus. It is not a modelling problem.

**Recommendation: one pooled model with `marketplace` as a categorical feature.** Not separate
models (Sbazar and Vinted are too small), not naive pooling (loses 0.10 R² on Sbazar).

---

## 8. What to change, in priority order

1. **Set `load_full_description = true` on queries 13 and 14.** Both scrapers already implement it;
   both already pace themselves. Expected gain, by analogy with Bazos: **+12 pp** on complete-spec
   coverage, plus the condition flags (`defect`, `warranty`, battery %, cycles) that are currently
   0 % off Bazos and are exactly what §6.1's 7,929 CZK M3 needs. Cost ≈ 265 extra detail requests/day.
2. **Store the Vinted seller ask alongside the buyer total**, or record the basis explicitly.
   Today `Ad.price` silently means two different things depending on `marketplace`, and the
   difference is 5 % + 18 CZK. Any consumer that does not know this is wrong by more than the
   marketplace effect it is trying to measure. `price_raw` (`"14884 CZK"`) does not disambiguate.
3. **Give the three MacBook queries the same price floor** (or drop the floors and filter in
   `run_filter`). The current 5,000 / 10,000 / 2,000 split makes every raw cross-marketplace
   aggregate wrong by construction.
4. **Fold the extractor fixes into whatever productionises it** (P23). #1 (M5) and #3 (lone 128 GB)
   are Bazos bugs today, independent of this study.
5. **Do not build seller-identity features into a pooled model.** They exist on Bazos only (§3).
   A pooled model that uses them is a Bazos model with two decorative extra marketplaces.

---

## 9. Reproduction

Scripts are in [`experiments/price_model/xm/`](../../experiments/price_model/xm/) —
throwaway analysis, excluded from ruff and mypy, needing `poetry install --with ml`.
The exported corpus is not committed (seller names, publisher ids); re-export with
`xm/export.sql` against a read-only connection:

| File | What it does |
|---|---|
| `export.sql` | the production pull (read-only join of `bazos_ad` × `bazos_addelivery`, queries 8/13/14) |
| `cov.sql`, `s1.sql`, `s2.sql` | §3 field coverage, raw row samples, price-shape checks |
| `probe_vinted.py`, `fee_fit.py` | §5.1 live probe of `vinted.cz` and the fee fit |
| `mbfeat2.py` | the fixed extractor — diff against `../mbfeat.py`, every change tagged `# v2:` |
| `xfeat.py`, `xfeat2.py` | §4.1 / §4.3 coverage tables, v1 vs v2 |
| `ceiling.py` | §4.2 recall-given-signal-present |
| `combine.py` | §5–6 pooled dataset, fee correction, spec cells → `xm/pool.pkl` |
| `specmatch.py` | §6.1 per-config medians and pairwise deltas |
| `model_x.py`, `model_de.py` | §6.2 within-cell effects and §7 model table |

---

## 10. What this does *not* establish

- **Nothing about realised prices.** Every number here is an *asking* price. The gap
  [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §6 names — the DB records no outcomes — is
  unchanged and now applies to three marketplaces instead of one.
- **The Vinted coefficient.** 15–31 matched ads. Re-run this section once Vinted has ~30 days and a
  description; until then treat Vinted as unpriced.
- **Sbazar's +3.5 % is a 2.45-day measurement** against 101 days of Bazos. It is well-estimated
  *within* that window and stable across sub-populations, but it has never been observed to persist.
- **New-ads/day per marketplace** — the Sbazar day-3 spike makes the window unusable for a rate
  (§2.1). Use the method in
  [`METHOD_CALIBRATION.md`](marketplaces/METHOD_CALIBRATION.md) instead.
- **Cross-marketplace duplicate detection.** 8.5 % of Sbazar rows are title-identical to a Bazos
  row; a real dedup key (there is no shared seller id) was not attempted.
