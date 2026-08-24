---
title: MacBook price prediction — measured on the production corpus
status: reference
updated: 2026-08-24
verified: 2026-08-24
---

# MacBook price prediction — measured on the production corpus

> Written 2026-08-24 from a read-only pull of the production database on
> `raspberrypi5.local`. **Scope: 2,038 Bazos MacBook ads from query 8** (`macbook`, category
> Notebooky, 5 000–100 000 Kč), created 2026-05-17 → 2026-08-23. Vinted (73) and Sbazar (55)
> MacBook ads are included only where stated; both queries started 2026-08-23, so they are one
> day of data.
>
> This doc exists because [`MONETIZATION.md`](../MONETIZATION.md) §4.2 rests on an **assumed**
> 2% "meaningfully underpriced" rate and on anomaly scoring being the project's edge (§7.7).
> Both are now measured for one category. **Everything here is one product category on one
> marketplace** — notebooks are unusually dealer-heavy, and none of the concentration numbers
> should be assumed to hold for `naradi` or `iphone`.

## 1. Summary

| Question | Answer |
|---|---|
| Can asking price be predicted from listing text? | **Yes.** R² 0.87 on held-out *sellers*; 6.2% median error in a past→future replay |
| What drives it? | Model year (0.486 of 0.875 R²), then chip, RAM, SSD. Everything else ≈ 0.017 |
| Is the ≥25%-below rate ~2%? | **Raw 4.9%, gated 1.5%** — the assumption was close, for the gated figure |
| Is the bottom tail made of deals? | **No.** 14% visibly damaged, 48% failed spec extraction, 11% at the query price floor |
| Do dealers charge a premium? | **No — this was the surprise.** Median −2.1% spec-matched; +1.5% in a within-config regression |
| Is there cross-marketplace arbitrage? | **No.** Spec-matched, Sbazar +1% and Vinted +2% vs Bazos (small n) |
| Can precision be measured? | **No.** The DB holds zero outcomes — see §6 |

## 2. Extraction

Regex over `name` + `short_description` (`bazos/models.py`), no ML, no external spec table.
Coverage on the 2,038 rows classified as MacBooks:

| Field | Coverage | | Field | Coverage |
|---|---|---|---|---|
| family (Air/Pro) | 100% | | RAM | 91% |
| chip | 92% | | SSD | 90% |
| screen size | 91% | | model year | 80% |
| battery health % | 21% | | charge cycles | 13% |

27 of 2,065 ads in the query are not MacBooks at all (Dell, ThinkPad, MSI) — Bazos full-text
matches the description, so `macbook` in a dealer's boilerplate pulls in their whole catalogue.

**Two parsing traps, both of which manufacture fake underpricing** (a nonsense spec produces a
nonsense prediction, which lands in the bottom tail):

- **RAM/SSD labels must be searched only in the gap between a number and its neighbours.** In
  `16GB RAM / 512GB SSD` the text immediately *before* "512" is `" RAM / "`. Searching left
  without bounding at the previous token labels 512 as RAM and loses the SSD entirely. The gap
  *after* a number must win over the gap before it.
- **Warranty dates parse as capacities.** `záruka do 04/2027` yields 4 GB RAM and a 2 027 GB
  disk unless date-shaped substrings are stripped first.

Both were live in a first pass and produced ~440 wrong rows (21%) before being fixed.

## 3. The model

`HistGradientBoostingRegressor` on `log(price)`, native categorical + NaN handling —
missingness is signal here, not something to impute.

**Split strategy matters more than the model.** Only 1,080 of 2,038 titles are unique; 56% of
ads come from ten `EmailPublisher` ids relisting the same inventory. A random split puts the
same listing on both sides:

| Split | R² | MedAPE | What it measures |
|---|---|---|---|
| Random 5-fold | 0.925 | 4.6% | Nothing — same ad in train and test |
| Grouped by relisting | 0.902 | 6.3% | Unseen listings, familiar sellers |
| **Grouped by seller** | **0.873** | **8.6%** | Hardest honest test |
| **Time split (past → future)** | **0.905** | **6.4%** | What production faces |

Quote the time split for deployment: in production you *do* have the dealers' history.

**Accuracy splits sharply on extraction completeness** — this is the operationally useful fact:

| Segment | n | MedAPE | Residual σ |
|---|---|---|---|
| year + chip + RAM + SSD all parsed | 832 | **4.7%** | 0.138 |
| any of the four missing | 391 | **12.3%** | 0.287 |
| chip not identified | 113 | 18.3% | 0.399 |

### 3.1 Against the median baseline that `backlog/PROMPTS.md` P23 proposes

| Approach | R² | MedAPE | Coverage |
|---|---|---|---|
| Median by exact config (≥3 comparables) | 0.873 | 10.1% | **63%** |
| Median by family+chip+screen | 0.779 | 14.9% | 88% |
| Model | 0.875 | 8.6% | **100%** |

**The model's advantage is coverage, not accuracy.** At exact-config granularity the median is
statistically level; it just cannot score the 37% of ads with fewer than three comparables.
P23's "start with a plain ORM aggregate, not an ML service" is the right call — the model is
what extends it to the long tail.

## 4. What the bottom tail is actually made of

Audit of the 100 most-underpriced listings (past→future replay) against corpus base rates:

| Category | Top 100 | Base rate | Enrichment |
|---|---|---|---|
| Visibly damaged — cracked screen, `nefunkční`, for parts | 14% | 4.3% | **3.3×** |
| Spec extraction incomplete | 48% | 32.0% | 1.5× |
| Priced at exactly the 5 000 Kč query floor | 11% | 1.2% | **9.2×** |
| Clean, fully specced, no damage language | 49% | — | — |

Missing specs cause underpricing flags *mechanically*: with no year the model falls back toward
the corpus average, which for a 2015 machine is far too high.

**Gating funnel** (57 days of scored listings, ≥25% below predicted):

| Gate | n | Per week |
|---|---|---|
| all scored ads | 1,223 | 150 |
| ≥25% below predicted | 60 | 7.4 |
| + all four specs parsed | 23 | 2.8 |
| + no damage vocabulary | 21 | 2.6 |
| + above the query price floor | 18 | **2.2** |

70% of raw hits are removed by three gates, all computable at filter time from fields that
already exist. Sensitivity: 15% → 7.9/wk, 20% → 4.7/wk, 25% → 2.2/wk, 30% → 1.1/wk, 40% → 0.2/wk.

## 5. The confound that decides the design

**67% of residual variance is between sellers, not within them.** Decompose each residual into
a per-seller mean plus a within-seller deviation and two thirds of the spread is persistent
shop-level pricing. In the top 100 raw flags, one seller accounts for 11 and the top five for 35.

- **Raw residual** = "cheap for a MacBook". Fires on a few shops' entire catalogues, repeatedly.
- **Within-seller residual** = "cheap *for this seller*". Fires on markdowns and private
  mispricing. This is the one that behaves like an alert.

### 5.1 Dealers do not charge a premium — the counterintuitive one

The plausible assumption is that a dealer corpus inflates the "market price" (VAT invoice,
warranty, 32% of ads mention DPH), so a 25%-below-market ad is really at fair private-sale
value. **Measured, that is false.** Across 32 configurations with ≥3 dealer and ≥3 private ads
each: median dealer premium **−2.1%**, mean −0.9%, dealers dearer in only 13 of 32. A
within-config regression over 1,341 ads in 57 configurations puts it at **+1.5%**.

Dealers and private sellers ask essentially the same price for the same spec on Bazos. The
model's "market price" is therefore a fair reference for both — but the friction moves to
non-price attributes: reselling into a market where dealers offer the same price *with* a
warranty and an invoice is harder than a price-only model suggests.

### 5.2 Market structure

| | |
|---|---|
| Ads from sellers with ≥10 listings | **63%** |
| Ads from one-off sellers | 21% |
| Ads from the top 10 email publishers | **56%** |
| Ads mentioning DPH / faktura | 32% |
| New MacBook ads per day (this query) | ~21 |

Relisting behaviour: of 103 listings reposted ≥3× over ≥14 days, **31 dropped, 64 stayed flat,
8 went up** — median change 0%. Dealers mostly re-post at the same number, which makes
`PriceDropRule` high-precision but very low-recall (26 price changes in the whole corpus).

## 6. Why none of this can be calibrated yet

**`Ad.modified` never advances past `Ad.created`** — measured across all 2,038 rows, max delta
1.3×10⁻⁸ hours. Ads are written once and never re-checked. There is no time-to-disappear, no
sold flag, no outcome of any kind.

Consequence: **every precision figure in §4 is a composition audit, not a measurement.** "49%
of the top 100 are clean" says they are not visibly broken; it does not say they are bargains.
The distinction cannot be closed from inside this dataset.

This is [`MONETIZATION.md`](../MONETIZATION.md) §7.2(c) confirmed from the data side, and it is
why `backlog/PROMPTS.md` **P24 must land before P23** can be calibrated rather than merely shipped.

`view_count` does not substitute: it correlates 0.06 with age in corpus because it is captured
once at discovery. It measures how long an ad had been up before we first saw it — staleness,
not demand.

## 7. Findings that need no model

- **Depreciation: 8.3% of value per year of model age**, configuration held constant (912 ads,
  33 configurations). Raw median-by-year is badly confounded — it jumps 93% from 2020 to 2021
  not because old machines appreciated but because the M1 Pro launched.
- **Price ladder.** Median asking price by family+chip, n≥25: Air Intel i5 7 390 · Pro Intel i5
  7 490 · Pro Intel i7 8 290 · Air M1 9 999 · Pro Intel i9 11 690 · Pro M1 12 490 · Air M2
  14 800 · Pro M2 15 900 · Air M3 18 499 · Pro M1 Pro 19 390 · Air M4 20 990 · Pro M2 Pro
  27 990 · Pro M1 Max 28 990 · Pro M3 Pro 32 000 · Pro M4 Pro 42 999 Kč. Note the Apple-silicon
  step: any M-series Pro clears 12 000 while Intel Pros cluster at 7 500–8 500 regardless of RAM.
- **No cross-marketplace arbitrage.** Raw medians differ wildly (Bazos 10 990, Sbazar 22 950,
  Vinted 7 742) but that is entirely each query's price bounds and model mix. Spec-matched on
  family+chip+RAM+SSD: **Sbazar +1%, Vinted +2%** (15–16 matched configs, one day of data —
  a method demonstration, not a settled result).
- **Listing volume is a Friday–Saturday business**: 448 and 396 ads vs 184 on Tuesday, and
  weekend listings carry a higher median price.

## 8. A model blind spot worth knowing about

22 listings across 13 independent sellers reference a **"MacBook Neo"** — A18 Pro chip, 13",
8/256, sold sealed with warranty at a consistent 13 000–14 500 Kč, first seen 2026-05-27.
Whether this is a real product launch or something else is not established here; 13 unrelated
sellers at consistent prices does not look like a scam ring.

Either way the mechanism is the same and it generalises: **a product with no comparables
produces large residuals**, and the model cannot tell "underpriced" from "unpriceable". A
persistent cluster of large residuals sharing an unknown token is a reasonable "new product
entered the market" detector — and a concrete reason **not** to let an anomaly score auto-reject,
which P23 step 6 already warns against.

## 9. Reproduction

Read-only over SSH against the production Postgres; nothing was written. Working scripts were
session-scratch and are not in the repo — the durable artifacts are this document and the two
parsing traps in §2, which any productionised extractor must handle.

Corpus pull:

```sql
SELECT a.*, d.query_id, d.status
FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id = a.id
WHERE d.query_id IN (8, 13, 14);
```
