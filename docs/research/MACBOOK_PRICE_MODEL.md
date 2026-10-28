---
title: MacBook price prediction — measured on the production corpus
status: reference
updated: 2026-09-18
verified: 2026-08-26
---

# MacBook price prediction — measured on the production corpus

> Written 2026-08-24 from a read-only pull of the production database on
> `raspberrypi5.local`. **Scope: 2,038 Bazos MacBook ads from query 8** (`macbook`, category
> Notebooky, 5 000–100 000 Kč), created 2026-05-17 → 2026-08-23. Vinted (73) and Sbazar (55)
> MacBook ads are included only where stated; both queries started 2026-08-23, so they are one
> day of data.
>
> This doc exists because `MONETIZATION.md` §4.2 rests on an **assumed**
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
| Can precision be measured? | **Still no - but the reason moved.** Outcomes now exist (`Ad.removed_at`) and are *uncalibrated*, not absent: see §6 |
| Should dealers be excluded from the model? | **No.** Training on all sellers scores small sellers *better* (R² 0.818 vs 0.791) — dealers are the price reference (§5.3) |
| Can dealers be ranked against each other? | **Yes.** A 35-point spread in price level, benchmarked leave-seller-out, with significance (§5.4) |
| Does a per-seller term improve prediction? | **Barely** — 6.98% → 6.50% MedAPE, and only with ~20× more shrinkage than the textbook estimator suggests. Its real value is fixing the *threshold* (§5.7) |

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

> ℹ️ **The aggregate now exists in the codebase** (`bazos/comparables.py`, checked 2026-09-18),
> though as a *display* surface rather than an estimator: it reads the persisted
> `AdPriceScore.features` back and shows where the ad sits among same-bucket listings, in the
> Discord message and on the admin ad page. Two differences from the "exact config" measured
> here, both deliberate. The bucket is
> `MacbookPriceModel.comparable_keys = ("chip_key", "ram_gb", "ssd_gb", "screen")` - **no
> `year`**, because year is implied by the chip and is the field listings most often omit - and
> it is windowed (`COMPARABLE_MAX_AGE_DAYS=90`, `COMPARABLE_MAX_ROWS=60`). So its coverage is
> not the 63% in the table above, and it is available only for ads a model already scored. Do
> not read §3.1's numbers as a measurement of that panel.

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

### 5.3 Excluding the dealers is the wrong instrument

The obvious response to a two-thirds between-seller confound is to drop the dealers and model
only the private market, where the bargains presumably are. Measured, that makes the model
worse at exactly the job it was narrowed to do:

| Trained on | Scored on | R² |
|---|---|---|
| **all sellers** | small sellers (n=436) | **0.818** |
| small sellers only | small sellers (n=436) | 0.791 |
| dealers only | small sellers (n=436) | 0.566 |

**Dealers are the price reference even if you never buy from them.** They are the densest,
most consistently-described, most repetitive part of the corpus, and removing them starves the
model of the comparables it needs to price a private listing. Train on everything; decide
separately who you are willing to *buy* from.

The deeper problem is that seller tiers are not equally predictable, and a threshold expressed
as a flat percentage silently assumes they are:

| Seller tier | scored ads | R² | MedAPE | residual σ |
|---|---|---|---|---|
| private (1–2 ads) | 337 | 0.762 | 15.0% | **0.302** |
| small (3–9) | 99 | 0.945 | 8.8% | 0.174 |
| medium (10–49) | 134 | 0.879 | 9.5% | 0.200 |
| large (50+) | 653 | 0.970 | 4.3% | **0.098** |

A private seller's price is three times noisier than a dealer's. So a fixed "25% below
predicted" rule is not one rule — it is four different standards of evidence wearing the same
number:

| Seller tier | −25% expressed in σ | % of that tier's ads firing | Reads as |
|---|---|---|---|
| private (1–2) | 0.95σ | 10.4% | ordinary noise |
| small (3–9) | 1.64σ | 6.1% | mildly unusual |
| medium (10–49) | 1.43σ | 6.7% | mildly unusual |
| large (50+) | **2.92σ** | 1.2% | genuinely exceptional |

The flat rule therefore spends most of its alert budget on private-seller noise while ignoring
dealer markdowns three standard deviations out. **Filtering by seller size does not fix that —
it discards the half of the market where the evidence is strongest.** The fix is to
standardise the residual (§5.7), not to drop rows.

### 5.4 The dealer scorecard

If dealer price level is two thirds of the signal, it is worth measuring per shop rather than
subtracting it away. Each seller with ≥25 ads was scored against a model trained with **that
seller held out** (GroupKFold by seller), so their own pricing cannot define their benchmark.

`level` is the mean residual converted to a percentage; `t` is that level in standard errors,
so |t| ≥ 2 means the level is real rather than small-sample noise.

| seller | ads | level | t | specs parse | discloses | damaged | median Kč | Apple si. | median yr |
|---|---|---|---|---|---|---|---|---|---|
| e2454 | 52 | **−9.7%** | **−5.1** | 96% | 100% | 0% | 19 900 | 96% | 2021 |
| e2451 | 63 | **−8.3%** | **−5.0** | 21% | 100% | 3% | 18 999 | 83% | 2019 |
| p1242 | 32 | −2.4% | −0.6 | 97% | 100% | 0% | 28 900 | 97% | 2023 |
| e2600 | 34 | −2.3% | −1.2 | 79% | 100% | 0% | 17 900 | 97% | 2021 |
| e1371 | 62 | −1.9% | −0.7 | 95% | 95% | 2% | 23 900 | 92% | 2022 |
| e2488 | 98 | −1.8% | −2.2 | 100% | 100% | 0% | 6 540 | 5% | 2017 |
| e2479 | 207 | +1.4% | +2.8 | 100% | 99% | 0% | 6 590 | 5% | 2017 |
| e2477 | 76 | +3.4% | +1.6 | 78% | 96% | 1% | 19 900 | 100% | 2021 |
| e2511 | 359 | +3.5% | +8.9 | 100% | 100% | 0% | 8 490 | 17% | 2018 |
| e2572 | 87 | +7.0% | +7.2 | 97% | 93% | 0% | 8 490 | 25% | 2017 |
| e2464 | 84 | **+10.6%** | +4.3 | 64% | **26%** | **13%** | 9 990 | 37% | 2020 |
| e472 | 52 | **+17.8%** | +8.0 | 56% | 100% | 0% | 17 980 | 73% | 2021 |
| e476 | 27 | **+25.3%** | +6.8 | 7% | 100% | 4% | 14 490 | 4% | 2019 |

The cheapest shop asks 9.7% below market and the dearest 25.3% above — a spread of 35
percentage points, and both ends are statistically solid.

Four things the table says that a single price-level number would not:

- **Two shops are genuinely cheap** — `e2454` and `e2451`, both |t| ≈ 5.
- **Three are genuinely dear** — `e476`, `e472`, `e2464`, all |t| > 4.
- **`e2464` is the one to avoid.** Dear *and* opaque *and* selling broken machines: 10.6% above
  market, **13% of its listings mention damage**, and it is the only large seller with
  essentially no condition disclosure (26% against 93–100% everywhere else).
- **Middling levels are mostly not real.** `p1242`, `e2600` and `e1371` all look ≈2% cheap on
  |t| < 1.3. Any ranking that reads those as "cheap shops" is reading sampling error.

**Specs-parse rate is an independent axis and worth carrying separately.** `e2451` is
genuinely cheap but describes stock badly (21% parse), so most of what it lists cannot be
scored at all; `e2479` and `e2511` parse at 100% but sit slightly above market. Cheapness and
scoreability are different properties of a shop.

#### 5.4.1 How much history a price level needs

The same computation across every seller with ≥3 ads (57 sellers, of which 28 — 49% — have a
level significantly different from market) shows how quickly an apparent discount stops being
real:

| ads from the seller | sellers | % with a significant level | median absolute level |
|---|---|---|---|
| 3–4 | 23 | 35% | **9.3%** |
| 5–9 | 15 | 47% | 7.2% |
| 10–24 | 6 | 67% | 22.4% |
| 25+ | 13 | **69%** | **3.5%** |

Read the first and last rows together: **sellers with three or four listings show the largest
apparent discounts and the least reason to believe them.** Median absolute level falls from 9.3% to
3.5% as sample size grows, which is the signature of noise, not of small shops being cheaper.
Among non-significant sellers the median apparent discount is 5.4%; among significant ones,
11.0%. This is the whole case for shrinkage (§5.5).

#### 5.4.2 Are the cheap shops just dumping worse stock?

The obvious confound. Partially testable, and it does not hold:

| | damaged | scratches mentioned | warranty |
|---|---|---|---|
| cheap dealers (level < −5%, n=2) | 1.6% | 0.8% | 74% |
| dear dealers (level > +10%, n=3) | 5.6% | 6.0% | 66% |

The cheap shops disclose *more* warranty and mention *less* damage than the dear ones. **The
limit of this check must be stated: the model sees only text.** It cannot see photographs,
true cosmetic grade, battery wear beyond what is written, or whether an invoice is real. This
rules out the disclosed-defect explanation and nothing more.

### 5.5 A seller term that survives small samples

A seller with one prior listing that happened to be cheap is not a cheap seller. The standard
correction is partial pooling: believe a fraction `n/(n + κ)` of a seller's apparent price
level and the population average for the rest, where `n` is how many of their listings were
scored **before** the ad being priced. Everything below is computed time-causally — a seller's
history at scoring time contains only listings that appeared earlier.

**κ has to be tuned, not derived.** The method-of-moments estimator (σ²within / σ²between,
measured at 0.1247 and 0.1721) returns **κ = 0.53**, which credits a *single* listing with 66%
weight. At that setting the seller term actively **hurts** sellers with 1–2 prior ads. The
estimator is inflated by the many two-ad sellers whose apparent spread is pure noise —
precisely the population §5.4.1 shows cannot be trusted. Sweeping κ against held-out error
puts the optimum near **12**, roughly 20× more shrinkage:

| κ | weight at n=1 | weight at n=50 | 1–2 prior | 3–9 prior | 10+ prior | overall |
|---|---|---|---|---|---|---|
| 0.5 *(≈ raw mean)* | 0.67 | 0.99 | 8.65% | 6.87% | 4.50% | 6.92% |
| 1 | 0.50 | 0.98 | 8.02% | 6.70% | 4.50% | 6.87% |
| 2 | 0.33 | 0.96 | 9.07% | 6.83% | 4.49% | 6.79% |
| 3 | 0.25 | 0.94 | 9.82% | 6.67% | 4.50% | 6.74% |
| 5 | 0.17 | 0.91 | 9.46% | 6.24% | 4.45% | 6.58% |
| 8 | 0.11 | 0.86 | 9.28% | 5.65% | 4.52% | 6.60% |
| **12** | **0.08** | **0.81** | 9.60% | **5.51%** | 4.43% | **6.50%** |
| 20 | 0.05 | 0.71 | 9.77% | 5.97% | 4.35% | 6.54% |
| 35 | 0.03 | 0.59 | 9.91% | 6.10% | 4.30% | 6.54% |
| 60 | 0.02 | 0.45 | 9.88% | 6.50% | 4.37% | 6.57% |
| ∞ *(seller term off)* | 0.00 | 0.00 | 10.02% | 7.20% | 4.64% | 6.98% |

Values are MedAPE. Three readings:

- **The headline gain is small.** Seller-blind 6.98% → raw per-seller mean 6.92% → shrunk at
  κ=12 **6.50%**. The base model already infers dealer identity from text (`DPH`, warranty
  language, town, the formulaic title style), so an explicit seller term is largely redundant.
- **The gain concentrates where it should**: sellers with a little history but not much. At
  3–9 prior listings, error falls 7.20% → 5.51%, a **23% reduction**. Below that there is not
  enough history; above it the base model already knows the shop.
- **The curve is flat between κ = 5 and 20**, so the choice is not delicate — but the
  difference between κ = 0.5 and κ = 12 is real, and the moment estimator lands on the wrong
  side of it.

Sellers with no history are untouched by construction, and that is correct behaviour rather
than a limitation. **About 24% of listings come from a seller with no prior appearance, and
that rate is stable across the window** — the cold-start case is a permanent feature of this
market, not a transitional one that accumulating data will close.

⚠️ κ was tuned on the same 99 days it is scored on. With a single parameter and a flat optimum
this is not a serious overfit, but it has not been validated out-of-period.

### 5.6 The noise prior must depend on seller maturity

Shrinking the seller's *level* is only half of it. A threshold expressed in standard deviations
needs a per-seller σ, and that σ must itself be shrunk toward a prior — which cannot be a single
global value. Residual σ by how many listings the seller had already shown:

| prior listings from this seller | scored ads | residual σ |
|---|---|---|
| 0 (never seen before) | 407 | **0.294** |
| 1–2 | 117 | 0.219 |
| 3–9 | 144 | 0.172 |
| 10–49 | 365 | 0.143 |
| 50+ | 394 | **0.065** |

**A first-time seller is 4.5× noisier than a shop with 50+ listings.** The first attempt here
shrank every seller's σ toward one population value of 0.125 — a figure dominated by
high-volume dealers, whose pricing is formulaic. Applied to private sellers that understates
their true spread by more than half, and `z ≤ −2` fired on **15%** of their listings. The prior
has to be a function of seller maturity, not a constant.

### 5.7 What the seller term actually buys: a comparable threshold

With both the level and the noise shrunk against maturity-aware priors, "2σ below this
seller's own baseline" becomes one standard of evidence instead of four:

| Seller tier | shrunk σ | z ≤ −2 means | % firing, flat −25% | % firing, z ≤ −2 |
|---|---|---|---|---|
| private (1–2 ads) | 0.294 | **44% below** | 10.4% | 4.3% |
| small (3–9) | 0.219 | 35% below | 6.1% | 3.8% |
| medium (10–49) | 0.159 | 27% below | 6.7% | 7.0% |
| large (50+) | 0.076 | **14% below** | 1.2% | 1.7% |

Gated alert volume barely moves — **2.6/week against 3.2/week** for the flat rule — but the
composition changes completely: private-seller flags fall from 9 to 2 and dealer flags rise
from 9 to 10. The rule stops firing on the noisiest listings in the corpus and starts firing on
shops discounting 30–40% against their own established baseline. It also demands a **44%
discount from an unknown private seller** before calling it a deal, which is the right bar for
the segment where the model is least sure.

**This is the payoff, and it is not accuracy.** The seller term moves prediction error by half
a percentage point (§5.5); what it fixes is the threshold. If only one piece of §5.3–§5.7 is
built, build this one.

⚠️ Everything in §5.3–§5.7 is measured against *prediction error*, not money. The seller-aware
rule is demonstrably better at finding listings that are unusual for their seller. It is **not**
established that those sell faster or resell for more, because §6 still applies: the outcome
column that exists today (`Ad.removed_at`) is a confounded proxy nobody has calibrated. This
changes which listings you look at; whether that is an improvement in profit is the question
P24 was built to answer, and P24 has now shipped without yet answering it (§6).

## 6. Why none of this can be calibrated yet

> ⚠️ **Re-based 2026-09-18. The premise below is now wrong; the conclusion still holds, for a
> different and smaller reason.** P24 shipped on 2026-09-17 (commit `5856bf0`):
> `bazos/delisting.py` re-checks live ads on an age-decayed schedule and records
> `Ad.last_seen_at` / `Ad.removed_at`, and `AdOutcome` is the logbook of what a human actually
> did. So the database *does* record outcomes now. Measured read-only on production
> 2026-09-18, one day into the sweep:
>
> | | |
> |---|---|
> | ads | 30 037 |
> | `last_seen_at` populated | 22 218 |
> | `removed_at` populated | 19 008 |
> | …written on the sweep's **first** run (2026-09-17) | **18 403 (96.8 %)** |
> | …written on 2026-09-18 | 605 |
> | ads created **after** the sweep began that have since been removed | **1 078** - same broken batches, so mostly false too |
> | **`AdOutcome` rows** | **0** |
>
> Three things follow, and together they keep this section's verdict intact:
>
> - **Most of `removed_at` is a data-corruption bug, not an observation.**
>   `BazosApiScraper.fetch_by_ids` sends a whole `DELIST_BATCH_SIZE` of 210 ids as `ad_id[]=`
>   and **omits `limit`**, which the working `_fetch_page` sends as `limit=API_PAGE_SIZE`; so
>   `ads.php` answers with its default page and every id beyond it is absent, which is precisely
>   the sweep's delisting signal. Survivors per minute-bucket in production are 90, 30, 300, 420,
>   240, 60, 330, 360, 420, 390, 360, 150 - **every one an exact multiple of 30**. Each 210-id
>   batch keeps 30 and falsely removes ~180: roughly **86 % of everything the sweep touches**,
>   first run and 2026-09-18 run alike, so the 1 078 "observed from creation" rows are no more
>   trustworthy than the rest. And it is **permanent** - `due_for_check` filters
>   `removed_at__isnull=True` and nothing anywhere clears the column, so a falsely-removed ad is
>   never re-checked, and these rows will silently enter any later outcome study unless someone
>   deals with them. **Open as of 2026-09-18**; it is a distinct defect from the 2026-09-17
>   `None`-vs-`{}` fix, because here the request succeeds and simply answers a narrower question
>   than the caller believes it asked.
> - **`removed_at` deliberately conflates sold, withdrawn, deleted and expired**, and there is
>   deliberately no `sold` boolean (the comment above `Ad.removed_at` in `bazos/models.py` says
>   so in as many words). Bazos listings age out
>   on their own, so a disappearance near the expiry horizon says more about the clock than
>   about a buyer.
> - **The logbook that would calibrate the proxy is empty.** `AdOutcome` is what turns
>   "disappeared" into an estimate of "sold", and it holds zero rows.
>
> So: **read §4's precision figures as composition audits, as written - not because outcomes
> are absent, but because the one outcome column that exists is mostly wrong, and what it would
> mean if it were right is a confounded proxy nobody has calibrated.** The gate is no longer
> "P24 must land"; it is "the sweep has to record what actually happened, and the logbook has to
> carry rows". That is a smaller obstacle and a different one.
>
> One correction worth carrying, since it is the natural next assumption: **`Ad.modified` is
> still not the field to read.** It is no longer true that it never advances - 4 266 of the
> 30 037 production ads now have `modified > created + 1 s` - but 4 233 of those advance by
> under a minute, because `QueryRunner._handle_new_product` re-saves the ad seconds later with
> its full description, and only 29 advance by more than a day. `modified` therefore means "we
> fetched more text about it", which is a fact about the scraper, not about the ad. The sweep
> itself keeps out of the way on purpose: it writes `last_seen_at`/`removed_at` with a queryset
> `.update()`, which bypasses `auto_now` entirely. The fields that answer this question are
> `last_seen_at`, `removed_at` and `AdOutcome`.

**As measured on 2026-08-24, `Ad.modified` never advanced past `Ad.created`** - across all
2,038 rows of this corpus, max delta 1.3×10⁻⁸ hours. Ads were written once and never
re-checked. There was no time-to-disappear, no sold flag, no outcome of any kind. That is the
state every number in this document was measured under, and the blockquote above records what
has changed since.

Consequence, unchanged: **every precision figure in §4 is a composition audit, not a
measurement.** "49% of the top 100 are clean" says they are not visibly broken; it does not say
they are bargains. The distinction still cannot be closed from inside this dataset.

This is `MONETIZATION.md` §7.2(c) confirmed from the data side. It was
written as the reason `backlog/PROMPTS.md` **P24 must land before P23** can be calibrated
rather than merely shipped; both have since shipped, and the calibration is still outstanding
for the reason the blockquote gives.

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

Read-only over SSH against the production Postgres; nothing was written.

The working scripts are kept in [`experiments/price_model/`](../../experiments/price_model/)
— throwaway analysis, excluded from ruff and mypy, needing `poetry install --with ml`. The
corpus itself is deliberately not committed: it carries seller names and publisher ids.
This document remains the durable artifact. The pipeline was, in order:

| script | what it did |
|---|---|
| `mbfeat.py` | the regex spec extractor of §2 — chip, year, screen, RAM, SSD, condition flags |
| `harness.py` | feature matrix + the time-causal expanding-window replay used throughout §5.3–§5.7 |
| `seller_base.py` | seller identity (email id, else phone id, else per-row unique) and time-causal prior-ad counts |
| `part1.py` | §5.3 — train-on-all vs train-on-small, and predictability by seller tier |
| `part2.py` | §5.4 — the leave-seller-out dealer scorecard |
| `part3.py` / `part3b.py` / `part3c.py` | §5.5–§5.7 — partial pooling, then the maturity-aware noise prior |
| `ksweep.py` | §5.5 — the κ sweep that overturned the moment estimator |

Only two things here are worth re-deriving rather than re-reading: the two parsing traps in §2,
which any productionised extractor must handle, and the κ tuning in §5.5, which must be redone
against whatever feature set a real implementation ends up with.

Corpus pull:

```sql
SELECT a.*, d.query_id, d.status
FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id = a.id
WHERE d.query_id IN (8, 13, 14);
```
