---
title: Where a price model can work — five categories measured against the MacBook recipe
status: reference
updated: 2026-09-18
verified: 2026-09-13
---

# Where a price model can work — five categories measured against the MacBook recipe

> Written 2026-09-12 from one read-only delivery-level pull of the production database on
> `raspberrypi5.local`: **12,078 `AdDelivery` rows over 11 queries and 4 marketplaces —
> 11,948 distinct ads**, created 2025-12-13 → 2026-09-12 (§10 has the SQL). The question is
> whether the recipe that produced [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) —
> regex spec extractor → linear model on log price, seller-grouped — carries to four other
> categories: **headphones** (query 12, n=343), **mountain bikes** (query 16, n=2,343, with
> road bikes query 17, n=715), **skis** (query 18, n=127) and **golf clubs** (query 11,
> n=390). Desktops are the fifth and have their own doc,
> [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md); they appear here as one verdict row and as a
> size-matched control.
>
> Nothing in this document is wired into the pipeline. The shipped registry still holds one
> model (MacBook) — but `price_model` **is** live on query 8 in production, which §7 is about.
>
> The standing caveat applies to every number below, **re-based 2026-09-18**: the database now
> records an outcome, and it cannot be calibrated against. The delisting sweep shipped
> 2026-09-17 and `Ad.removed_at` is populated on 19 008 of 30 037 ads, but the sweep's bulk id
> fetch omits `limit`, so it asks about 210 ads per request and is answered about 30 and writes
> the other ~180 off as removed - about 86 % of the column is false, and since a removed ad is
> never re-checked it stays that way (open as of 2026-09-18). `removed_at` also conflates sold
> with withdrawn, deleted and **expired**, and `AdOutcome` - the logbook that would tell you how
> often "removed" means "sold" - holds **zero rows**. Every precision figure here is therefore
> still a composition audit, not a measurement
> ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §6).

## 1. Summary

| Question | Answer |
|---|---|
| Headphones — query 12, n=343? | **No, and title-only is not the reason.** Titles name the product (brand 99.4%, brand+model 88.0%) and a GROUP BY reaches R² 0.64 / MedAPE 15.1% on the 57% with comparables. **Binding constraint: the hidden-API payload** — no description, no seller ids — plus a no-comparable tail that none of 15 estimators prices above R² 0.3 (§3) |
| Mountain bikes — query 16, n=2,343? | **No — extraction.** 32.5% of the category is not an adult mountain bike by classifier, ~36% on a hand audit, and **Bazos truncates `short_description` at its 254-character cap on 57.0% of the query's rows**, before the specs appear. −25% is 0.53σ and fires 223×/week ungated (§4) |
| Skis — query 18, n=127? | **No, and not answerable yet.** 94 alpine-ski rows over 5.6 days; R² 0.287 / MedAPE 26.8% against a median baseline of −0.005 / 35.6%. **Binding constraint: the 4,000 CZK floor against a 7,200 median** — the most binding in the study — and a September arrival rate that says nothing about the season (§5) |
| Golf — query 11, n=390? | **No, and it is not a sample-size effect.** R² 0.150 (CI +0.014…+0.307) where MacBook at the identical n=390 gives 0.670 ± 0.072 and iPhone 0.756 ± 0.022. **Binding constraint: identification** — `Qi10 LS`, `SM10`, `TW757` order nothing (§6) |
| Desktops — query 9? | **Score, but do not alert.** R² 0.806 / MedAPE 13.2% behind a completeness gate, but −25% is 0.97σ. See [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md); not restated here |
| What predicts whether a category is modelable? | **Rarefied vocabulary breadth and title spec density.** Every corpus at ≤215 types per 900 sampled title tokens scores probe R² ≥0.645; every corpus at ≥273 scores ≤0.595. **No overlap** (§2) |
| What does *not* predict it? | **Seller concentration (Spearman −0.15), full-description coverage (+0.02) and corpus size (+0.33).** All three are the obvious screens and all three are worthless (§2) |
| Is there a result that transfers to every category? | **Yes — one.** Ads within 1% of the query's own price floor are **3.0–14.0× enriched** in the underpriced tail of all eleven corpora, no exception. The gate is free: `Query.price_lower` is already known to the filter (§7) |
| Which category is worth building next? | **iPhone, query 19** — and none of these five. It is the only corpus that pays no penalty against MacBook's own size-matched control (§8) |
| Can any threshold here be calibrated? | **No** - and P24 landing did not change that. Outcomes exist but are a confounded, uncalibrated proxy (§9) |

**One-line answer: none of the five. Build the iPhone model instead, ship the price-floor gate
once for every category at the same time, and screen the next candidate with two statistics
that cost an hour rather than a week.**

## 2. The screening result — the part of this study that generalises

Five category studies, each with its own extractor, and four of them ended in "no". The
transferable contribution is not any of the four verdicts; it is that **a category-agnostic probe
ranked all four correctly before a single regex was written**.

### 2.1 The instrument

One probe, identical on all eleven corpora: TF-IDF (word 1–2gram + `char_wb` 3–5) over the
normalised **title only** → ridge on log price, `GroupKFold(5)` on the seller, 3 permuted
repeats, pooled out-of-fold, **vectoriser fitted inside each training fold**. No per-category
regex anywhere, so the number is a property of the corpus rather than of how much extractor
effort someone spent on it.

It is calibrated against the project's only two published outcomes:

| Corpus | Probe | Published | Δ |
|---|---|---|---|
| MacBook (query 8) | 0.838 | 0.873 ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §3) | −0.035 |
| PC (query 9, title + description) | 0.689 | 0.635 ([`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §5) | +0.054 |

It misses in both directions, so treat it as **a screen with roughly ±0.05 of slack, on n=2
calibration points** — not as a prediction of the achievable number. The PC point is the weaker
of the two: 0.635 was measured on 1,411 desktops under a 10,000 CZK query floor, and
[`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §2.1 is explicit that R² is not comparable across that
floor change, so the +0.054 is a cross-basis difference as much as a probe error.

### 2.2 The ranking

| Corpus | q | n | probe R² | MedAPE | resid σ | −25% in σ | fires at −25% | vocab/900 tok | model-token % |
|---|---|---|---|---|---|---|---|---|---|
| macbook (Bazos) | 8 | 2,851 | **0.838** | 10.5% | 0.250 | 1.15σ | 8.8% | 131 | 91.4% |
| macbook (Sbazar) | 14 | 621 | 0.785 † | 6.9% | 0.192 | 1.50σ | 5.9% | 105 | 92.4% |
| iPhone | 19 | 613 | **0.779** | 16.3% | 0.396 | 0.73σ | 14.0% | 148 | 64.1% |
| macbook new/high-end | 15 | 182 | 0.681 | 13.3% | 0.275 | 1.05σ | 8.8% | 130 | 94.5% |
| macbook (Vinted) | 13 | 1,037 | 0.645 † | 21.4% | 0.437 | 0.66σ | 20.4% | 213 | 60.4% |
| road bike | 17 | 715 | 0.595 | 37.0% | 0.591 | 0.49σ | 30.5% | 414 | 16.4% |
| MTB | 16 | 2,343 | 0.592 | 33.2% | 0.531 | 0.54σ | 29.2% | 349 | 11.6% |
| PC (Počítače) | 9 | 2,856 | 0.582 | 26.0% | 0.564 | 0.51σ | 23.5% | 334 | 75.4% |
| headphones (API) | 12 | 343 | 0.353 † | 21.1% | 0.474 | 0.61σ | 24.5% | 325 | 37.9% |
| ski | 18 | 127 | 0.178 | 23.6% | 0.404 | 0.71σ | 22.0% | 336 | 49.6% |
| golf | 11 | 390 | **0.153** | 58.6% | 0.898 | 0.32σ | 37.4% | 273 | 17.9% |

† Seller grouping is **degenerate** on these three — zero publisher ids, so `GroupKFold`
silently becomes `KFold`. Sbazar's honest figure, grouped by `publisher_name`, is **0.635**
(§9). The PC row is title-only, for comparability; with the description it is 0.689.

The last column pair is the screen. "Fires at −25%" is the operational consequence: the same
flat threshold that is 1.15σ out on MacBooks is **0.32σ out on golf, where it fires on more
than a third of the market and therefore carries no information at all**.

### 2.3 The two predictors that survived

**Vocabulary breadth, rarefied.** Sample a fixed 900 title tokens from each corpus (so the
measure is size-unbiased) and count distinct types. Every corpus at **≤215 types scores probe
R² ≥0.645**; every corpus at **≥273 scores ≤0.595**. There is no overlap across eleven corpora.
MacBook 131 against PC 334 — **2.5× the product space for the same corpus size** (2,851 vs
2,856 ads). The statistic is measuring how many distinct things are being sold under one query.

**Title spec density.** Mean digit-runs per title, and the share of titles carrying an
alphanumeric model token (`m3`, `rtx3060`, `i5`, `xm5`): MacBook 3.39 / 91.4%, PC 2.73 / 75.4%,
iPhone 2.15 / 64.1%, MTB 1.08 / 11.6%, golf 0.79 / 17.9%, road bike 0.70 / 16.4%. Spearman with
probe R² is **+0.65** and **+0.64** across the eleven. This is the thing visible by reading 130
titles: the failing corpora name a *category*, not a *product instance* — `Kolo`, `Dámské kolo`,
`Golfové hole`, `Sjezdové lyže`, `Prodám sluchátka` — against
`MacBook Air 13'' 2022 / M2 / 16GB / 512GB SSD`.

### 2.4 The three that did not — and they are the obvious ones

| Candidate screen | Spearman with probe R² (n=11 corpora) | Why it is tempting, and wrong |
|---|---|---|
| Top-10 seller concentration | **−0.15** | MacBook is dealer-heavy (49.8%) and so is golf (65.6%) — opposite ends of the ranking. iPhone scores 0.779 on 29.0% |
| Full-description coverage | **+0.02** | PC has the second-highest coverage (47.9%) and ranks eighth of eleven |
| Corpus size | +0.33 | See §2.5 |
| *(for contrast)* vocabulary standardisation | +0.82 | |
| *(for contrast)* residual σ | −0.76 | |

**The MacBook corpus's dealer-heaviness is not what makes it modelable.** That is the
counterintuitive one, and it matters because "find another dealer-dense category" is the
natural next move after reading [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §5.2. It is
the wrong move. Dealers are the *price reference* once a category is modelable (that doc §5.3);
they do not make one modelable.

### 2.5 Small versus unmodelable, settled by a size-matched control

Known-good corpora were subsampled **by whole sellers** down to each small corpus's n and
re-run under the identical probe (mean of 3 draws):

| subsample n | macbook q8 | iPhone q19 | MTB q16 | PC q9 | the small corpus at this n |
|---|---|---|---|---|---|
| 127 | 0.487 | 0.587 | 0.349 | 0.233 | **ski = 0.178** |
| 182 | 0.577 | 0.700 | 0.319 | 0.213 | macbook-new = 0.681 |
| 343 | 0.670 | 0.748 | 0.426 | 0.446 | headphones = 0.353 † |
| 390 | 0.689 | 0.759 | 0.447 | 0.458 | **golf = 0.153** |
| 613 | 0.747 | **0.779** | 0.533 | 0.565 | iPhone, full corpus |
| 2,000 | 0.836 | — | 0.576 | 0.581 | — |

† Headphones' own figure is a random split in disguise (see §2.2). Draw-to-draw noise is real
at these sizes: §6 re-runs the n=390 row with 15 draws instead of 3 and gets MacBook 0.670 ±
0.072 rather than 0.689 — a different basis, not a contradiction.

> ⚠️ **Correction, 2026-09-13 — the sampler in this table is biased against dealer-heavy
> corpora, so every "known-good" column above is depressed.** Subsampling *by whole sellers*
> gives each seller equal probability regardless of size, while a real scrape samples rows —
> so a 359-ad dealer enters a draw as often as a one-off seller, and a corpus whose signal
> lives in dealer inventory loses it. Measured on MacBook at n=655: whole-seller draws carry
> **7.7** sellers with ≥10 ads and score **R² 0.764**, row draws carry **11.5** and score
> **0.799** — the instrument costs MacBook **0.035 R²**, and costs iPhone (top-10 share 28.5%
> against MacBook's 49.7%) almost nothing. An independent re-run measured the same direction
> at 0.06. **The effect scales with dealer concentration, so the more dealer-heavy the corpus,
> the more this table understates it.**
>
> **What that changes:** the iPhone-versus-MacBook ordering, and nothing else. Under
> whole-seller sampling iPhone leads by 0.023 (0.787 vs 0.764); under row sampling MacBook
> leads by 0.012 (0.787 vs 0.799). **The two are indistinguishable and the ordering is an
> artifact of the sampler** — see [`IPHONE_PRICE_MODEL.md`](IPHONE_PRICE_MODEL.md) §2.
> **What it does not change:** golf and ski. Both sit far below every control under either
> sampler, and correcting the bias moves the controls *up*, which strengthens their verdicts.

Golf is not small; it is unmodelable (§6). Ski sits below every control at its own n, but
n=127 cannot settle it (§5). ~~**iPhone at n=613 does not pay a size penalty against MacBook at
the same n (0.779 vs 0.747)**~~ — **withdrawn by the correction above**: that gap is the
sampler, not the corpora. iPhone is still the category §8 recommends, but on the two screening
statistics and the full study in [`IPHONE_PRICE_MODEL.md`](IPHONE_PRICE_MODEL.md), not on a
size-matched ordering that does not survive its own instrument.

**This section would have produced the golf, ski and bike verdicts without writing a single
regex.** Both statistics are computable from the `bazos_ad` table in minutes.

## 3. Headphones (query 12) — the constraint is not where it looks

Bazos hidden-API corpus, n=343 over 35.1 days (2026-08-08 → 2026-09-12) at 8.5 ads/day, 100%
`price_type=exact`. **26 rows (7.6%) are not a single pair of headphones** — 9 amplifiers/DACs
(`sluchátkový zesilovač` contains `sluchátk`), 7 multi-item bundles, 5 not headphones at all, 3
hearing aids, 2 motorcycle intercoms. The modelling set is the **324 rows that pass a kind
gate**, bundles included but flagged: their raw median is 16,450 CZK against 5,000, which is
confounded with being high-end (within-model the effect is −7.7%), so a bundle is a reject gate
rather than a coefficient.

**Title-only is not the binding constraint it looks like.** The titles do name the product:
brand resolves on **99.4%** and (brand, model) on **88.0%** of the 324. What actually binds is
everything the `ads.php` thin payload omits — `short_description`, `full_description`,
`publisher_name` and both publisher ids are empty on **343 of 343 rows**
([`HIDDEN_API.md`](bazos-api/HIDDEN_API.md) §5; the same three silent degradations that
[`API_CUTOVER.md`](../backlog/API_CUTOVER.md) §2 warns about for filtering).

### 3.1 A GROUP BY is the model, and the shrinkage is the only part that earns its keep

| Estimator, title-grouped 5-fold ×3 | scope | R² | MedAPE |
|---|---|---|---|
| median by exact (brand, model), ≥3 comparables | 57.1% of rows (n=185) | **0.641** | 15.1% |
| ridge over product dummies, same rows | n=185 | **0.641** | 14.6% |
| ridge, brand dummies only | n=324 | 0.163 | 34.8% |
| TF-IDF char 3–5gram ridge (upper bound on title signal) | n=324 | 0.276 | 24.5% |
| HistGradientBoosting, same design | n=324 | 0.193 | 22.9% |
| global median baseline | n=324 | −0.092 | 33.3% |

Under an independent grouping key (`location`, §9) the median lookup scores **0.638** — the same
number from a better instrument.

The ridge and the GROUP BY are **the same estimator to within 3.8% of predicted CZK**: OOF
correlation 0.9928, mean absolute divergence 0.0372 log, paired ΔR² +0.019 (95% CI −0.006…+0.051,
n=185). **Except on the rare levels, which is exactly where it matters**: restricted to
(brand, model) keys with ≤7 corpus rows, the ridge beats the median by **ΔR² +0.112 (CI
+0.014…+0.277, n=33)** and 4.9 pp of MedAPE, P(ridge better) 99.1%. So a JSON manifest here is a
GROUP BY *plus per-level shrinkage*, and only the shrinkage pays for the manifest.
[`PROMPTS.md`](../backlog/PROMPTS.md) P23's "start with a plain ORM aggregate" is not a first
step on this corpus; it is nearly the destination.

### 3.2 The 43% tail is threshold-defined, not structural

The no-comparable tail is an artefact of choosing ≥3:

| comparables required | covered | tail | the rows that move |
|---|---|---|---|
| ≥1 | 71.3% | **28.7%** | the 46 rows between ≥1 and ≥3 price at R² +0.537 / MedAPE 21.1% |
| ≥2 | 62.0% | 38.0% | |
| ≥3 | 57.1% | 42.9% (n=139) | |
| ≥5 | 49.7% | 50.3% | |

And the residual tail is **not "unpriceable by any method"**, which is how the first pass
recorded it. A global regression over a nominal token does fail (ridge R² 0.061 / MedAPE 54.0%),
but a *local* estimator does substantially better: a **word-TF-IDF cosine 5-NN reaches R²
+0.229 / MedAPE 39.8%** on the identical 139 rows (95% CI +0.031…+0.372), holding at +0.213 /
39.4% under an independent grouping key, and a char-TF-IDF ridge at α=0.2 lands at +0.237.
Under honest nested selection the number is 0.135 / 51.1%.

What survives is the threshold, not the adjective: **nothing tried reaches R² 0.3**
(P(R² ≥ 0.30) = 16.6%), and at the best residual sd found (0.654 log) a −25% rule fires on
**34.5% of tail rows**. The tail stays ungated on arithmetic, not on the claim that it is
inert. One correction to carry: the 0.092 char-ngram figure quoted against this tail was
measured on a *different* 108-row tail definition, not these 139 rows.

### 3.3 Why a model name cannot interpolate where a spec can

25.3% of the headphone corpus is one product — AirPods Max, 82 rows — and **52.4% of those do
not state a generation**, across a **1.50× price step** (gen 1 median 5,000 CZK vs gen 2 7,500;
mean log gap 0.343 = +41%). No regex fixes that: the seller did not write it. Those rows are
37.5% of the ≥25%-below tail against a 23.2% base rate (1.61×) — the
[`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §4 "missing spec manufactures fake
underpricing" mechanism, verbatim. And knowing the generation is only a partial fix: within-
AirPods-Max σ falls from 0.262 to 0.225, which moves a −25% ad from 1.10σ to 1.28σ and no further.

The structural point is the one to carry to the next category. **A MacBook's price is carried by
*ordered* specs (year, RAM, SSD) and a desktop GPU's name encodes tier and generation
*positionally* — both interpolate to configurations never seen in training
([`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4). A headphone model name is a pure nominal token:
107 distinct keys over 324 rows, with an 18.5% novelty rate still running in the last quarter of
the corpus.** There is nothing to interpolate along. "A Sennheiser HD 660S2 seen once" is
unpriceable and stays unpriceable however large the corpus grows.

## 4. Mountain bikes (query 16) — two constraints bind before the model does

n=2,343 over 13.3 days (2026-08-30 → 2026-09-12) — **176.6 ads/day over the window, 164.8/day
in steady state, the project's largest feed** — 1,583 sellers, 85.0% singletons, 100% carrying a
real publisher id.

**32.5% of the category is not an adult mountain bike**: kids' and junior bikes 25.1% (n=587),
cross/trekking/gravel 4.7%, parts and bare frames 1.0%, e-bikes 0.7%, accessories 0.7%, road
bikes 0.3%. That figure is a classifier estimate, and the honest error bar on it is the
classifier's, not the sample's: a hand audit of 80 random rows found **6 errors (7.5%), all six
in the same direction** (non-MTB leaking *into* the MTB class), which puts the true adult-MTB
share at 51/80 = 63.8%, i.e. contamination nearer 36%. Kids' bikes are not noise — modelled
alone they score R² 0.328 / MedAPE 24.5% — they are a different product with a premium brand
tier (Woom, Kubikes, Rascal, Frog) that has no adult analogue.

**The text is cut off before the specs.** `Ad.short_description` is Bazos's own listing-page
teaser, capped at 254 characters and ending in ` ...`: **7,456 of the 9,947 deduped Bazos ads in
this pull — 75.0% — end in that marker**, and no row anywhere is longer than 254. It is not a
schema limit — `short_description` is a `TextField`.

**One basis correction: the first pass read the cap as a fixed width** — "7,515 rows exactly 254
characters long, 22 at 252, 7 at 253". Re-derived from the same export, only **2,712** rows are
exactly 254 long (703 at 252, 368 at 253); what reproduces is the count of rows ending in the
*marker*. The cap is real, the cut lands on a word boundary, so count the marker and never the
length ([`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md) §10).

| query | rows ending in the truncation marker | `full_description` coverage |
|---|---|---|
| 8 macbook | 85.9% | 27.6% |
| 9 PC | 87.1% | 47.9% |
| 11 golf | 80.0% | **0%** |
| **16 MTB** | **57.0%** | **0%** |
| 17 road bike | 51.9% | **0%** |
| 19 iPhone | 62.2% | **0%** |

(Per query, so an ad delivered to two queries counts in both.)

On the 2,387 Bazos rows in this pull that *do* carry a full description, the median is 530
characters, 82.0% exceed 250, and **a mean 45.6% of the description text lies past the cut**
(median 388 further characters). MTB extraction coverage is still climbing steeply *at* the
boundary — per extra 50 visible characters: fork +5.5 pp, rear cogs +4.8 pp, groupset +4.7 pp,
wheel +3.0 pp. Coverage today: brand 81.6%, wheel 65.4%, frame size 59.9%, material 40.6%,
groupset 30.0%, **anchored model year 6.6%**.

### 4.1 The refuted claim — and it is the most instructive paragraph in this doc

The first pass concluded that the Shimano/SRAM **groupset tier ordinal** fails where the PC GPU
ordinal succeeds *because premium sellers do not state their groupset*. A verification pass
reproduced every number and then **refuted both the mechanism and the remedy**.

The weakness itself is real and survives a matched attack — same estimator, same seller-grouped
protocol, same metric, near-identical target variance in both subsamples (sd log price 0.755 vs
0.757):

| feature, alone | on rows where it parses | on all rows |
|---|---|---|
| PC GPU tier + generation ordinal | **0.474** (n=1,619) | 0.352 (n=2,336) |
| MTB groupset tier ordinal | 0.130 (n=474) | 0.046 (n=1,581) |

**The PC row is a re-derivation, not [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4's published
0.515/0.480** — the basis moved twice: that corpus has grown from 1,411 desktops to 2,336, and
this is a GPU ordinal *reduced to tier + generation* so it matches the groupset feature exactly.
The matched comparison is internally consistent; it does not audit the published figures.

But the stated cause and the implied remedy are both wrong:

- **The ladder merges two manufacturers the market does not price as equal.** SRAM GX rows have
  a median of **35,400 CZK** against Shimano Deore's **8,500** — both rated tier 6; SRAM NX
  27,000 against Alivio 7,995, both tier 4. **Free per-token dummies over the identical 16
  matched tokens score ΔR² +0.175 (CI +0.091…+0.263) above the ordinal on the identical 474
  rows — the exact reverse of [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4, where the ordinal
  beat per-model dummies.** Adding one bit for *which manufacturer matched* doubles the all-rows
  figure, 0.046 → 0.095 (Δ CI +0.021…+0.075). Within Shimano alone the ladder is perfectly
  monotone in mean log price across all eight rungs (Spearman +0.523, CI +0.416…+0.621, n=385).
- **The missing axis is generation, and it is the larger effect.** On the 217 rows where both
  parse: groupset tier alone 0.059, **speed count alone 0.597**, the two together 0.645. The
  speed ladder is clean: 7sp 4,800 · 8sp 5,745 · 9sp 8,499 · 10sp 13,500 · 11sp 20,000 · 12sp
  28,950 CZK.
- **Groupset-stating rises with price, not falls.** 17.1% in the cheapest quintile → 26.1% →
  34.2% → **41.0%** in Q4, dipping to 32.6% in Q5. The driver is listing length, not seller
  segment: 17.2% of short blobs state a groupset against 39.6% of long ones — cheap bikes get
  short listings.
- **The untested alternative works.** Brand + bicycle *model* token alone scores **0.231**
  against the ordinal's 0.046 (Δ +0.184, CI +0.125…+0.244) at 72.8% token coverage.
- The original "+0.014 marginal value" should never have been quoted as positive: ΔR² +0.0125,
  CI **−0.0056…+0.0314**.

Two more corrections from the same pass. **`year` must be dropped from any bike feature list**:
its missingness indicator alone scores 0.101 while its value on parsed rows scores −0.022 — it
is missingness-as-signal, a feature that scores by detecting verbose listings. And **queries 16
and 17 should be pooled with a `kind` fixed effect**, not kept separate: the 0.601 → 0.591 drop
that argued against pooling compared metrics on different row sets (1,699 q16 rows vs 2,304
mixed), and q17 is intrinsically harder (var log price 0.849 vs 0.706). Scored on identical rows
under identical seller folds: separate 0.5723, pooled 0.5912, **pooled + `kind` 0.5991** (ΔR²
+0.0268, CI +0.0100…+0.0439). The gain is modest and every MedAPE delta straddles zero — the
refutation is of "must not pool", not a claim that pooling matters much.

**The generalisable rule, stated so the next category study does not repeat it:**
[`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4's finding is that a name-derived ordinal beats
per-model dummies *because it interpolates*. That holds only where the name encodes generation
positionally. `rtx 3070` does. `Deore` does not — it names a rung on a ladder that has been
re-cut every few years and is shared with a competitor's incompatible rung.

### 4.2 What an alert would look like, and what its tail is made of

Best seller-grouped result on the 1,581 MTB rows: HGB R² 0.583 / MedAPE 32.2% / σ 0.540; ridge
0.540 / 34.2%. On the best-covered fifth (brand + wheel + size + material all parsed, n=323):
0.756 / 23.2% / σ 0.394. A −25% threshold is therefore **0.53σ**, against 0.97σ on the desktop
gated segment and 2.92σ for a MacBook dealer. Over the 1.90-week window: **422 ads ≥25% below predicted =
222.7/week ungated**, 64 = 33.8/week after gating on parsed specs and no damage words — against
the **2.2/week** the MacBook model was tuned to and PC's 1.5/week.

The bottom-60 audit says what that tail is, and it is not what the MacBook tail was:

| | bottom 60 | base rate | enrichment |
|---|---|---|---|
| at or below 3,500 CZK (floor is 3,000) | 40.0% | 7.2% | **5.55×** |
| no brand parsed | 31.7% | 18.3% | 1.73× |
| no wheel size parsed | 53.3% | 34.5% | 1.54× |
| **damage vocabulary** | **0.0%** | 3.0% | **0.00×** |

**The tail is old bikes and parse failures, not broken bikes** — where the same audit on
MacBooks found damage 3.3× enriched. The single most "underpriced" listing in the corpus was a
`RockShox 35 Gold RL` fork at 3,300 CZK, priced by the model as a complete bike at 18,859.

## 5. Skis (query 18) — too little, too seasonal, and the floor is in the way

n=127 over 5.64 days (2026-09-07 → 2026-09-12), **of which 77 are the query's own `new_query`
backfill** (nothing to do with the delisting sweep) — so
50 organic listings. 74 sellers, 86.5% singletons. Only **94 rows (74.0%) are a bare pair of alpine skis**; the other
26.0% are boots (14), multi-product sets (11), helmets, a snowboard, a roof box, a jacket-and-
trousers set titled "set", a skiboard, and a 25,000 CZK snowmobile-towed cross-country track
groomer — *which the shipped filter SENT to Discord*, along with the skiboard and a helmet.

| | R² | MedAPE |
|---|---|---|
| best seller-grouped model (ridge, 21 columns, n=94, 44 sellers) | **0.287** | 26.8% |
| HistGradientBoosting, same protocol | 0.226 | 26.5% |
| global median baseline | −0.005 | 35.6% |
| brand only | −0.154 | — |
| brand + length | −0.111 | — |
| leave-one-seller-out median by brand × length bin (≥3 comparables, 22.3% coverage) | −0.770 | 42.8% |
| private sellers only (≤2 ads, n=43) — *the half where bargains live* | **−0.143** | 38.8% |

That ridge's residual σ is 0.361 — §2.2 ranks ski at 0.404 because that is the category-agnostic
probe on all 127 rows, a different instrument — so **−25% is 0.80σ and fires on 25.5% of the
alpine-ski corpus**; z ≤ −2 fires on
0.0%, because at this σ z = −2 means 51% below predicted. Design-matrix n/p is 94/21 = 4.5,
against the ~1,600/60 = 27 at which the shipped ridge was benchmarked.

Two findings worth more than the verdict:

- **The extraction-completeness gate inverts here, and the inversion is an artefact.** Rows with
  brand + length + radius + season all parsed score R² **−1.071** / MedAPE 31.9% (n=36); rows
  with something missing score **+0.310** / 23.6% (n=58) — the opposite of
  [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §3 and [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md)
  §5.1. The cause: 88.9% of the complete rows are top-4-dealer ads against a 54.3% base, and
  those prices are compressed into a narrow high band, so R² divides by almost no variance. **The
  completeness gate is a dealer gate on this corpus.** Four dealers supply 97.1% of stated list
  prices, 82.9% of stated model years, 68.1% of stated radii.
- **The primary physical attribute of a ski does not price it.** Pooled corr(length, log price)
  = +0.267, but *within* a dealer's own inventory: +0.289 (n=26), +0.228 (6), +0.026 (12),
  **−0.244** (7). The pooled figure is mostly "dealers stocking longer skis are dearer dealers".

**The floor is the most binding in the whole study.** 4,000 CZK against a 7,200 median —
floor/median 0.556, the highest of eleven — with **26.8% of the corpus at or below 5,000** and
the density still rising as it approaches the boundary (19 alpine rows in the 4,000–5,000
bucket, falling monotonically to 4 at 8,000–9,000). The 50,000 ceiling is dead weight: the most
expensive ad in the corpus is 25,000.

**The seasonality caveat is the point, not a footnote.** Every projection here multiplies an
arrival rate measured across five days of early September and extrapolates it across the start
of the ski season. Zero cross-country, ski-touring or poles-only rows appeared in 127 ads — in
September — so even the *composition* is unstable. The naive sizing (≈567 alpine rows for n/p =
27 in ~2.2 months, ~1,511 in ~6) is worth very little. **Re-measure in February, not "in two
months"**, over at least one full in-season month, and gate the decision on three things
measured here rather than on row count: (a) does within-seller corr(length, log price) move off
zero; (b) does the private-seller-only model clear R² 0 — it is at −0.143; (c) does anything
other than a dealer's house style predict — the strongest single feature is the seller's own
stated list price (r² 0.325, n=34), 97.1% of which comes from two shops whose behaviour does not
even agree (within-shop r² 0.846 with a 4.8 pp sd of discount, against r² 0.009 with a 12.3 pp sd).

One note that stays true regardless: `load_full_description` is **already on** for this query and
buys little — on the 35 rows that have one, radius +8.6 pp, waist +5.7 pp, season +2.9 pp, brand
/ length / list price +0.0 pp. Czech ski sellers front-load their specs into the first 254
characters, which is exactly what the teaser carries. Compare
[`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4.2's +18.7 pp on storage.

## 6. Golf (query 11) — a negative result that survived four attacks

n=390 over a 76-day span (2026-06-27 → 2026-09-12) containing a 29-day scrape outage; 116
sellers, but **241 distinct physical items** (38% of rows are re-posts), one shop owning 35.6%
and two owning 52.3%. Prague region only — the query is location-scoped, so this is not the
national golf market. Eleven
sub-types, of which the largest — "a set" (20.8%) — mixes 4,250 CZK beginner bag-sets with
14,500 CZK premium iron sets at a **3.4× ratio with no reliable text discriminator**.

| | R² | MedAPE |
|---|---|---|
| category-agnostic probe, seller-grouped (n=390) | **0.150** (95% CI +0.014…+0.307) | 58.6% |
| engineered ridge, club listings (n=351, 95 sellers) | 0.171 | 54.8% |
| HistGradientBoosting, same rows | 0.356 | 38.1% |
| global median constant | −0.007 | **50.0%** |
| median by (sub-type, brand), ≥3 comparables, leave-seller-out | 0.115 | 46.2% |
| random 5-fold ridge — *the wrong protocol* | 0.569 | 26.1% |

**It is not a sample-size effect.** Fifteen whole-seller subsamples at the identical n=390:
MacBook **0.670 ± 0.072** (0/15 draws inside golf's CI), iPhone **0.756 ± 0.022** (0/15). And it
survives every attempt to attribute it to dealer structure:

| control at n=390 | macbook | iPhone | golf |
|---|---|---|---|
| plain whole-seller subsample (6 draws) | 0.687 ± 0.047 | 0.754 ± 0.014 | 0.150 *(its whole corpus)* |
| forced to golf's 36% single-dealer share | **0.713** | 0.748 | 0.035 *(golf forced the same way, n=270)* |
| **no dealers at all** (sellers with ≤2 ads) | **0.671** | 0.746 (n=363) | 0.201 *(golf's own private slice, n=131)* |
| item-matched at 241 distinct (seller, title) | **0.726** (n=434) | 0.738 (n=251) | 0.150 |

The plain subsample does **not** preserve golf's concentration — MacBook at n=390 has a top-1
seller share of 28.8% and iPhone 7.9%, against golf's 35.6% — which is exactly why the other
three controls exist. MacBook is easy *in a purely private-seller corpus of golf's size*. The
fairness objection fails under all three.

Three corrections bound how strongly this may be stated, and they matter because the original
phrasing is quotable and slightly wrong:

1. **Golf's own R² CI excludes zero**, so the corpus is not signal-free. And against a
   size-matched **PC** corpus (0.375 ± 0.110) rather than MacBook, **6 of 15 draws fall inside
   golf's interval** (MTB 0.414 ± 0.097: 1 of 15). Golf is the bottom of a continuum, not a
   category on the other side of a line.
2. **"Indistinguishable from a constant" came from a statistic inflated by its own denominator.**
   The ΔR² bootstrap that produced the phrase resamples `var(y)` along with everything else, and
   `var(y)` swings 0.755–1.374 across seller resamples — 64% of its own size — because whether
   the 36%-of-corpus dealer is drawn once, twice or not at all reshapes the target. On the
   denominator-free paired statistic the **ridge beats the constant in 96.7% of resamples**. The
   sharper and worse true statement: **it is *worse* than the constant on the typical listing**
   — MedAPE 54.8% against 50.0%, Δ(median |log residual|) +0.076 (CI −0.136…+0.284). It buys tail
   accuracy and loses median accuracy, which is the wrong trade for an alerting rule.
3. **The dedup result is not leakage.** Deduplicating to one row per (seller, title) drops both
   models (ridge 0.158, HGB 0.152, n=207) — but a **random thin-out to the same n gives HGB
   0.069 ± 0.124, worse than dedup**, so the drop is sample size, and golf's HGB R² is unstable
   to ±0.12 at this scale. Relisting cannot cross a seller fold anyway (1 golf title of 204
   appears under two seller keys). Extending the check to the one channel seller-grouping does
   leave open — an identical title under different seller keys, 24.8% of MacBook rows, 12.7%
   iPhone, 9.5% MTB, 6.9% PC, 2.8% golf — and closing it with union-find components over the
   seller↔title graph costs at most **0.033 R² (MacBook)** and essentially nothing elsewhere.
   **No previously published R² in this project needs restating on account of relisting.**

Two further facts complete the picture. The "39% of listings fire at −25%" figure is the model's
own noise width restated, not a market property: −25% is **0.33 residual sd** below prediction
here, and a Gaussian of that width fires 37.2% against the observed 39.3%. And no subset rescues
it — the junior/US-Kids segment is *worse* than a constant (n=46, R² −0.099, MedAPE 44.8% vs
32.7%), single clubs excluding sets likewise (n=213 but only 28 sellers, R² +0.011). Only the
sets slice beats a constant (n=138, ΔMedAPE −28.7 pp, CI −43.8…−7.9), and with sd(log price) 1.18
there, most of that is telling a junior half-set from a full adult bag set rather than pricing
either.

## 7. The one result that transfers everywhere: price-floor enrichment

[`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §4 measured this once, at 9.2×, and it read
as a MacBook fact. **It is a universal one.** Share of ads within 1% of the query's own floor
among the most-underpriced K listings (K = min(100, max(25, 10% of n))), against that corpus's
base rate:

| corpus | at-floor base rate | share of the underpriced tail | enrichment | share of −25% alerts that are floor ads |
|---|---|---|---|---|
| PC (q9) | 1.86% | 26.0% | **14.0×** | 7.0% |
| macbook Bazos (q8) | 1.09% | 13.0% | **12.0×** | 8.8% |
| macbook Sbazar (q14) | 1.48% | 15.0% | 10.2× | 19.4% |
| iPhone (q19) | 1.63% | 14.8% | 9.0× | 11.6% |
| golf (q11) | 1.79% | 15.4% | 8.6× | 4.8% |
| macbook new (q15) | 0.55% | — | 7.3× | 6.2% |
| MTB (q16) | 4.82% | 28.0% | 5.8× | 15.5% |
| macbook Vinted (q13) | 0.19% | — | 5.2× | 0.9% |
| ski (q18) | 7.87% | 32.0% | 4.1× | **28.6%** |
| headphones (q12) | 9.33% | 35.3% | 3.8× | **29.8%** |
| road bike (q17) | 6.01% | 18.3% | 3.0× | 16.1% |

**Eleven corpora, no exception, 3.0–14.0×.** Median log residual for floor ads runs −0.40
(macbook) to −2.13 (golf, i.e. 88% below prediction). The gate removes between 0.9% and 29.8% of
a corpus's −25% flags depending on the corpus, and it is **free**: `Query.price_lower` is already
loaded by the filter, no model change, no new feature.

**The shipped code already knows this and does not do it.** `MacbookPriceModel._gates_pass`
([`marketplace/pricing/estimators/macbook.py`](../../marketplace/pricing/estimators/macbook.py)) carries a
docstring citing "ads sitting exactly on a query's price floor are 9.2x enriched" as one of its
three reasons — and its body implements only the other two, the completeness gate and the
damage-word gate. Add the floor check as a universal `declined_reason` in `bazos/pricing`, not
as a per-category rule. The defect is written up as
[`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md) §4; the table above is its evidence.

### 7.1 Censoring is about where the floor sits, not about the category being cheap

`floor / median` correlates with the mass within 25% of the floor at **Spearman 0.91**. Golf's
floor of 200 CZK is 8% of its 2,500 median and does not bind (1.85% of ads within 25% of it);
ski's 4,000 is 56% of its 7,200 median and is the most binding in the set (26.8%). **Both are
cheap categories.** Ceilings essentially never bind: across all eleven the largest share at the
upper bound is 0.55%, and queries 16 and 17 both cap at exactly 70,000 CZK holding 1 and 3 ads
there. Every "the bounds are costing us listings" question in this project is a question about
the floor.

**Censoring and modelability are orthogonal axes**: corr(mass within 25% of the floor, residual
σ) = **0.00** across the eleven. Sbazar is heavily censored and highly modelable; golf is barely
censored and unmodelable. Do not use one as a proxy for the other.

### 7.2 The live instance, in production, today

`PRICE_MODEL_SHADOW_MODE=false` in the production `.env` (the shipped default in
`bazos/const.py` and `scraper/settings.py` is `True`; production overrides it), so
`PriceModelRule` is **live on query 8**, which carries `price_model` in `filter_rule_names` and
`filter_price_model_z = -1.5`. Of query 8's 151 delivery rejections, **101 are
`location_distance`** and **37 are `price_model`**; the SENT→REJECTED shift on 2026-09-07 is a
distance filter being configured (centre 11000, radius 40 km), **not** the price model. Do not
re-attribute it. Production holds 88 `AdPriceScore` rows for `macbook/2026-08-26`, 47 of them
declined.

Two things this makes concrete. The shipped artifact was trained on ads priced ≥5,000 CZK and
query 8's floor moved 5,000 → 3,000 two days later, so **13.0% of the current feed now sits
below the artifact's entire training support**; those sub-floor rows fire at **34.0%**
(z ≤ −1.5 and discount ≥10%) against **5.2%** for rows inside support — seller-clustered, a
**+24.1 pp gap, 95% CI [+10.9, +41.3]** (n=50 against 268). Two cautions travel with that. A
paired run of the identical rows reads 28.0% against 4.5%, and the two runs disagree outright on
the plain ≥25%-discount count for the same 50 rows — **20.0% against 26.0%, unexplained**, so
quote neither without saying so. And how much of the gap is the truncated support rather than the
ads being genuinely old machines is smaller than the gap looks: measured on the prediction side
it is 4–7% of predicted price
([`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md) §3.3–§3.4, where that argument
lives). Gate contamination, by contrast, is live rather than
hypothetical: a **motherboard** listing, `Základní deska Apple MacBook 820-01041 A1990` at 6,000
CZK, was claimed by `MacbookPriceModel.applies_to` and scored at predicted 8,814 / z −1.59. It
was rejected by the distance rule before `price_model` ever ran.

The four highest-discount scored ads on query 8 were all SENT, and three of the four are priced
at 4,000 / 3,000 / 3,999 CZK — in the stratum the floor change admitted.

## 8. What to do, ranked, with the arithmetic

**1. Build the iPhone model (query 19) next, and nothing else from this set.** ✅ **Done, and it
worked — see [`IPHONE_PRICE_MODEL.md`](IPHONE_PRICE_MODEL.md).** This section originally rested
the recommendation on a size-matched ordering (probe R² 0.779 at n=613 against MacBook's 0.747);
§2.5's correction withdraws that comparison, because the sampler was biased against dealer-heavy
corpora and the ordering reverses under row sampling. **The recommendation survives its own
evidence being withdrawn**, which is worth stating: what actually carried it was the two
screening statistics — rarefied vocabulary **148**, the second-narrowest in the set, and 64.1% of
titles carrying a model token — and both were right. A regex extractor plus a ridge reaches
**R² 0.937 / MedAPE 9.95%** on 94.2% of rows, the strongest fit in the project on its own corpus.

Two corrections to what this section assumed. The corpus is **not** inside a product-launch
cycle: the iPhone 17 is ~12 months old and it is the iPhone **18** that had not yet shipped
during the window. And the σ quoted here (0.396, giving −25% = 0.73σ) is the *category-agnostic
probe's*, not a real model's — the extractor-based ridge reaches σ **0.200**, which makes −25% a
1.43σ event. The threshold still needs re-deriving rather than copying, but for the opposite
reason: the model is far sharper than the screen suggested, and the binding constraint turned out
to be alert *volume*, not accuracy.

**2. Ship the price-floor gate (§7).** One `declined_reason` in `bazos/pricing`, applying to
every category at once, removing **0.9–29.8%** of −25% flags depending on corpus (Vinted at the
bottom, headphones at the top; Bazos MacBook 8.8%). It is the single cheapest precision gain
available and it needs no model change.

**3. The four config decisions, with their measured cost.**

| change | what it buys | cost |
|---|---|---|
| `load_full_description` on **queries 16 and 17** | 57.0% / 51.9% of rows hit the 254-character cap with 0% description coverage; coverage still climbing +4.7 to +5.5 pp per 50 chars at the cut | **+17 s on a ~12-minute pass (+2.3% wall clock)**; one detail GET per new ad = +177/day (q16, at its 176.6 ads/day) and +54/day (q17). As a share of baseline that is +13% against an estimated ~1,331 listing page requests/day, or +23% against the **measured** 756 query-run attempts/day in [`API_CUTOVER.md`](../backlog/API_CUTOVER.md) §1 — the two bases differ, quote which one you mean |
| `load_full_description` on **query 12** | not the text — **the seller key**. The API detail handler populates `email_publisher`/`phone_publisher`, which ends the 100%-singleton problem and makes grouped CV legal on that corpus for the first time | **+8.5 `ad-detail-2.php` GETs/day** = +1.1% of outbound volume on the measured basis. It does **not** fill `short_description` and does **not** fill the postcode, so the keyword rules stay name-only and `location_distance` stays dead there |
| **lower the ski floor** (query 18) from 4,000 to ~2,000, leave the ceiling | 26.8% of the corpus is at or below 5,000 and density is still rising at the floor; the ceiling is dead (max observed 25,000 of 50,000) | one admin edit, reversible; at most one extra results page per pass |
| **leave the MTB floor at 3,000** | it *is* binding (4.82% of ads sit exactly on it, and an extrapolated ~19% of the market lies below — read that as order-of-magnitude, §9) — but the PC precedent is that lowering a floor imports mostly off-target stock: of 761 newly-visible desktop ads, **only 37% were desktops** (131 monitors, 114 loose parts, 98 mini office PCs, 55 iMacs, 29 laptops, 1 printer). Lower it only after a classifier exists | — |

Golf's 200 CZK floor and every ceiling in the set can be left alone permanently; neither costs
measurable volume.

**4. Screen the next category with two statistics before commissioning anything.** Rarefied
vocabulary breadth (types per 900 sampled title tokens: **≤215 promising, ≥273 not**) and the
−25%-in-σ figure from a one-hour TF-IDF probe. Both are computable from the `bazos_ad` table in
minutes and together they would have produced the golf, ski and bike verdicts. **Do not screen
on corpus size, seller concentration or description coverage** — measured across eleven corpora,
none of the three predicts anything (§2.4).

**5. Persist a seller identity on Vinted, Sbazar and the Bazos API scraper.** Today all three
write no publisher ids, which makes every grouped-CV number on them a random split in disguise.
Sbazar already stores `publisher_name`; plumbing that into the seller key is the smallest
version of the fix, and Vinted's library exposes a user id while the scraper stores name, price
and url only.

## 9. Limits

- **No calibrated outcome, and P24 landing did not supply one.** The delisting sweep shipped
  2026-09-17, after this study's pull, so no row here carries an outcome at all; and the column
  it writes, `Ad.removed_at`, conflates a sale with an expiry and is uncalibrated while
  `AdOutcome` is empty. Every R² here measures how well text predicts an *asking* price; no
  figure anywhere in this document establishes that a flagged listing is a bargain.
- **Three corpora have a degenerate seller key, and there is no single correction factor.**
  Queries 12 (bazos_api), 13 (Vinted) and 14 (Sbazar) carry no publisher ids, so
  `ph.seller_key` falls back to a per-row unique and `GroupKFold` silently becomes `KFold`.
  Measured across the 8 Bazos corpora where a real key exists, that degeneracy is worth
  **+0.019 to +0.462 R²** (q19 +0.019, q15 −0.004, q8 +0.044, q9 +0.089, q16 +0.049, q17 +0.027,
  **q18 ski +0.219, q11 golf +0.462**; mean +0.113, sd 0.157, correlating with ads-per-seller at
  r=0.60). **A flat correction would under-correct a golf-like corpus by 0.35 and over-correct an
  iPhone-like one by 0.09, so none should be quoted.**
- **But "12/13/14 cannot be validated" is wrong for two of the three.** Sbazar carries
  `publisher_name` on 100% of rows (162 distinct names over the 609 price-bearing rows, 3.76 ads
  each; grouped by it, R² 0.635 against 0.785 degenerate), and query 12 carries `location` on
  100% of rows. `location` is a *validated* conservative substitute: across the 8 Bazos corpora
  with real ids, 97.4–100% of sellers sit in one locality and **R²(location) − R²(seller) is
  mean −0.008, range −0.039…+0.019**. Only **Vinted (q13) genuinely has no grouping key of any
  kind**.
- **The normalised-title proxy used elsewhere in this study is itself optimistic**: R²(title) −
  R²(seller) is mean +0.064, sd 0.101, up to +0.269. Title-grouped numbers are upper bounds;
  prefer location-grouped where location exists.
- **Window lengths.** Queries 16 and 17 span **13.3 days**, query 19 **3.1 days**, query 18
  **5.6 days** (of which day 1 is a 77-row backfill), query 12 35.1 days, query 11 76 days
  containing a **29-day scrape outage**. There is no seasonality in any of them. September bikes
  are not April bikes, and bicycles are the most seasonal category in the study.
- **Every extractor here is in-sample.** `hpfeat.py`, `mtbfeat.py`, `skifeat.py` and
  `gclass.py`/`gfeat.py` were written by reading the same rows they are then measured on, so both
  the coverage figures and the covered-set R² are optimistic with respect to the extractor. The
  ski classifier's 126/127 agreement is in-sample by construction; the MTB classifier's
  hand-audited error is **7.5% on 80 rows, all in one direction**.
- **Contamination percentages are classifier estimates**, and their error is dominated by
  classifier error rather than sampling error. Only the MTB figure has a hand-audited sample
  attached. Do not quote a contamination number from a keyword rule without one.
- **The probe has ±0.05 of slack on n=2 calibration points**, disagreeing with both in opposite
  directions. A corpus scoring 0.60 might reach 0.65 with a good extractor, or not.
- **Eleven-point correlations are orderings, not effect sizes.** No CI is attached to any
  cross-corpus Spearman in §2.4 and none should be read as a measurement.
- **The CSV is delivery-level, not ad-level**: 12,078 rows for 11,948 distinct
  `(marketplace, external_id)` pairs — 130 duplicated ads, 128 of them the query-8 / query-15
  overlap. Pooling queries without deduplicating inflates MacBook n by ~4%.
- **Golf's bootstrap intervals are driven by one shop.** With 116 sellers and one holding a
  third of the rows, every golf CI is effectively a statement about whether that shop is
  resampled in or out. Read [+0.014, +0.307] as wide, not as precise.
- **One estimator in §3.2 is selection-inflated.** The tail R² 0.229 is the maximum over 15
  estimators on the same 139 rows. Two unrelated families land at 0.21–0.24 and it survives a
  change of grouping key, but the pre-committed number is the nested-selection one, 0.135.
- **A second censoring channel is unmeasured.** A price-bounded Bazos query returns essentially
  no placeholder-priced listing: 13 of 12,078 rows are not `price_type=exact`. The whole
  *Dohodou* / *V textu* / *Nabídněte* population is invisible to all eleven corpora.
  [`PRICE_PARSING.md`](PRICE_PARSING.md) §3.2 measured that share at ~0% for goods queries like
  `macbook`, but it is simply unmeasured for bikes, golf and ski. One unbounded query run for a
  week would settle it.
- **Excluded-mass figures are order-of-magnitude, and the obvious method for them is
  degenerate.** A doubly-truncated log-normal MLE runs away when the floor sits near the mode —
  MTB returns an implied parent median of 22 CZK with 92.9% of the market below the floor, road
  bike diverges outright (µ = −153) — and must not be quoted. The local log-density replacement
  used instead over-predicts by **1.7× (golf), 2.8× (macbook, the one clean experiment) and 4.6×
  (PC, confounded by a seven-month gap)** against the three real bound changes, which is why §8
  quotes only its divided-down central value and why the *composition* of what lies below a
  floor — the thing that decides whether lowering one is worth it — is not inferable at all.

## 10. Reproduction

Read-only against the production Postgres over SSH; nothing was written. The corpus is
deliberately not committed — it carries seller names and publisher ids — and this document is
the durable artifact.

**The pull is unfiltered by `AdDelivery.status`, and that is load-bearing.** It is every ad the
scrapers discovered for these queries — 10,197 `SENT`, 1,420 `REJECTED`, 449 `SUPPRESSED` and 12
`FAILED`. What the filter did with an ad is an *outcome*; using it as a sampling frame would
model the filter rather than the market. The share that never reached Discord is not small and
not uniform — **82.7% of the ski corpus, 69.8% of iPhone, 34.1% of headphones and 27.4% of
mountain bikes** — and it moves the median price in whichever direction that query's rules cut
(`SENT` vs the rest: ski 5 250 vs 7 500 CZK, iPhone 12 999 vs 8 900, desktops 15 000 vs 30 995).
A SENT-only corpus would have kept 22 of 127 ski ads and biased the iPhone recommendation in §8
by a factor of 1.5 on price.

The shared harness is [`experiments/price_model/common/ph.py`](../../experiments/price_model/common/ph.py):
one protocol for every category so the numbers are comparable rather than each script inventing
its own split. `load()` reads the CSV below, `seller_key()` is the email-else-phone-else-unique
identity, `grouped_cv()` is the only protocol whose output should be quoted for model
comparison (`GroupKFold` on the seller, pooled out-of-fold), and `cluster_bootstrap_delta()`
produces every CI in this document. **Its `seller_key` fallback to a per-row unique is the
degeneracy §9 describes.** It was silent while this study ran, which is how three corpora nearly
got quoted as seller-grouped; `seller_key` now falls back through `publisher_name` and
`location` before the per-row unique, and `grouped_cv` warns when the singleton-group share
clears 90% — Vinted still trips it, because Vinted genuinely has no grouping key. The per-category
scripts named below were written against it and follow the throwaway convention of
[`experiments/price_model/`](../../experiments/price_model/) — kept for re-derivation, excluded
from ruff and mypy, needing `poetry install --with ml`.

| script | what it does |
|---|---|
| `xcorpus/probe.py` | §2's category-agnostic probe — the one instrument all eleven corpora are measured on |
| `xcorpus/s8_probe_all.py`, `s13_predictors.py`, `s14_vocab.py` | §2.2–§2.4 — the ranking, the predictor correlations, the rarefied vocabulary count |
| `xcorpus/s16_curve.py`, `s22_size.py` | §2.5 — whole-seller subsampling and the size-matched controls |
| `xcorpus/s2_floors.py`, `s10_censor.py`, `s19_tail.py` | §7 — the floor audit, censoring shape, and the floor-enrichment table |
| `xcorpus/s11_natexp.py`, `s12_below.py` | §8's three real bound changes (the only direct observations of excluded mass in this project) |
| `xcorpus/s23_artifact.py` | §7.2 — the shipped artifact evaluated below its own training support |
| `headphones/hpfeat.py` + `s01`–`s15` | §3 — brand/model extraction, the AirPods Max generation split, the alert funnel |
| `mtb/mtbfeat.py` + `s00`–`s18` | §4 — classification, coverage, the 254-char truncation curve, the ladders |
| `ski/skifeat.py`, `analyse*.py` | §5 — sub-type classification and the 21-column ridge |
| `golf/gclass.py`, `gfeat.py` + `s0`–`s15` | §6 — sub-type classification, the feature ablation, the funnel |

Verification passes (which is where the §3.2, §4.1 and §6 corrections come from) re-derived
every quoted number from the CSV before attacking it, and rebuilt each feature frame from source
rather than from the scouts' pickles.

Corpus pull — **delivery-level, one row per `(ad, query)`**:

```sql
COPY (
  SELECT d.query_id, a.id, a.created, a.external_id, a.url, a.name, a.price_raw, a.price,
         a.price_type, a.location, a.view_count, a.publish_date, a.topped,
         a.short_description, a.full_description, a.publisher_name,
         a.email_publisher_id, a.phone_publisher_id, a.marketplace, d.status
  FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id = a.id
  WHERE d.query_id IN (8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19)
) TO STDOUT WITH CSV HEADER;
```

Only three things here are worth re-deriving rather than re-reading: the two screening
statistics in §2.3, which decide whether a future category study happens at all; the floor
enrichment in §7, because it is the one finding that changes shipped code; and the groupset
encoding in §4.1, because it is the case where the intuition carried over from
[`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4 was measured and found backwards.
