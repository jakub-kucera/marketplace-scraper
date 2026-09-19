---
title: Price model benchmark — is a linear model good enough?
status: reference
updated: 2026-09-18
verified: 2026-08-26
---

# Price model benchmark — is a linear model good enough?

> Written 2026-08-26. **Scope: the same 2,038 Bazos MacBook ads as
> [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md)** (query 8, `macbook`, 5 000–100 000 Kč,
> created 2026-05-17 → 2026-08-23, 98 days). 25 models, two honest validation protocols,
> nested hyperparameter selection throughout. Nothing here was tuned on a test fold and no
> random train/test split appears anywhere.
>
> This doc answers one question the incumbent `HistGradientBoostingRegressor` never had to
> face: **does it actually beat a linear model by enough to be worth its deployment cost?**
> That cost is real and asymmetric — the runtime carries no numeric stack, so a linear model
> exports to a JSON coefficient manifest and evaluates in pure Python, while a tree ensemble
> means either numpy + scikit-learn on an ARM64 Raspberry Pi image or a hand-written tree
> serializer.

## 1. Summary

| Question | Answer |
|---|---|
| Is the GBM's advantage real, or fold noise? | **Real.** Against the recommended linear model, ΔR² **−0.026** (95% CI −0.044…−0.012), ΔMedAPE **+1.43 pp** (CI +0.22…+2.80), paired seller-cluster bootstrap |
| How big is it in practice? | Best linear **R² 0.866 / MedAPE 10.4%** vs GBM **0.887 / 8.9%**, held-out sellers. On the median 10 990 Kč ad that is a typical miss of **1 112 Kč vs 935 Kč** (§10) |
| Does that justify the deployment burden? | **No — ship the linear model.** The gap is 1.4 pp of median error and 0.026 of R² — 177 Kč on the median ad; the numeric stack on ARM64 is permanent |
| What mattered *more* than model class? | **Fixing two extractor regexes.** That moved the linear model +0.036 R² — 1.5× the entire linear-vs-GBM gap |
| Does regularisation matter? | **No.** OLS, ridge, lasso and elastic net land within 0.008 R² of each other; inner CV picks α ≈ 0.1 (ridge) and 3·10⁻⁴ (lasso), i.e. almost none. n/p ≈ 1 600/60 |
| Best linear form? | **Stop treating year as a number.** Spline, piecewise-linear hinges and one dummy per year are statistically identical (R² 0.866–0.868) and all beat year-as-linear by ~1 pp of MedAPE. The dummies need **no new manifest feature kind** |
| Does a median-by-config lookup suffice? | Nearly, where it applies: R² 0.836 / MedAPE 10.2% — but only **81% coverage** (62% if all four specs must parse), and R² −0.37 on the chip-unidentified tail |
| Are naive prediction intervals honest? | **For the linear model, yes** (80.2% empirical at nominal 80%). **For the GBM, catastrophically not** (39.8%) — it needs split conformal, which is one more serving component |

**The headline for the shipped artifact - ✅ acted on, 2026-08-29.** When this was written, the
v1 Ridge manifest at `bazos/pricing/artifacts/macbook/2026-08-26/manifest.json` recorded
R² 0.861 / MedAPE 11.72% over **40** feature rows, with `year` entering as a single `num`
coefficient plus a `missing` companion. §11.3's recommendation - turn `year` into one dummy per
model year plus an `na` level - was implemented and the artifact **retrained in place** (commit
`de41c15`, same `2026-08-26` version directory). Read live on 2026-09-18, that file now records:

| | v1, as published here | shipped today |
|---|---|---|
| feature rows | 40 (`num` 4, `missing` 4, `bool` 9, `cat` 23) | **54** (`num` 3, `missing` 3, `bool` 9, `cat` 39) |
| year form | `year` as `num` + `missing` | **`year_cat`, 16 `cat` levels** |
| `r2_seller_grouped` | 0.8612 | **0.8604** |
| `medape_pct` | 11.72% | **10.14%** |
| `residual_sigma` | 0.2264 | **0.2308** |
| `n_train` | 2 038 | **2 258** |

Same estimator (`Ridge(alpha=1.0)`), **1.58 pp lower median error**, no new feature kind and no
new code in `bazos/pricing/features.py` - which is what §11.3 predicted. R² is flat because the
seller-grouped folds are dominated by dealers the model already fits well; the gain is in the
middle of the distribution, which is what MedAPE measures and what an alert threshold reads.
**Anywhere below that says "the shipped artifact" and quotes 0.861 / 11.72% / 0.2264 is
describing v1, not the file on disk.**

## 2. Method

### 2.1 Why no random split, ever

Of 2,038 ads only **1,069 titles are unique**, and **10 sellers account for 55.9%** of the
corpus — dealers relisting the same inventory. A random k-fold puts the same physical listing
on both sides of the split and reports a number that means nothing. Two protocols are used
instead, and both are reported for every model:

| Protocol | What it is | What it measures |
|---|---|---|
| **A — grouped by seller** | `GroupKFold(5, shuffle=True)` on the seller key, repeated 3× (15 folds), nested | Hardest honest test: an unseen shop |
| **B — chronological** | train on the first 1,426 ads (→ 2026-08-07), test on the last 612 | What production faces: the dealers' history *is* known |

Protocol A's seller key is `email_publisher_id`, else `phone_publisher_id`, else a per-row
unique id (528 sellers). Protocol A is the number to compare models on; protocol B is the
number to quote for deployment, and it is systematically ~0.02 R² and ~2 pp MedAPE kinder.

A third, non-shuffled `GroupKFold(5)` pass is also run, purely to reconcile with previously
published figures (§3.3).

### 2.2 Nested, so nothing is tuned on the test fold

Every hyperparameter (ridge/lasso/elastic-net α, tree depth, forest `max_features`, GBM
learning rate and leaf count) is chosen by an **inner** `GroupKFold(3)` *inside* each outer
training fold. Under protocol B the inner selection is an expanding window over the training
slice only. Preprocessing — imputation medians, one-hot vocabularies, standardisation, spline
knots — lives inside the pipeline, so it is refitted per fold and never sees the test rows.

### 2.3 Metrics, and how noise is measured

Target is `log(price)`. **R²** is on the log scale, pooled over the out-of-fold predictions.
**MedAPE** is the median of `|exp(pred) − price| / price` in CZK.

Fold-to-fold spread is reported, but it is *not* the right test of a model difference: the
seller folds are wildly heterogeneous (one fold may hold the 359-ad dealer), so MedAPE has a
±3–4 pp fold sd for *every* model, including the GBM. Model differences are therefore tested
with a **paired seller-cluster bootstrap** — resample the 528 sellers with replacement,
recompute both models' metrics on the same resampled rows, 2 000 replicates (§4).

## 3. The finding that outranks the model choice

### 3.1 Two extractor bugs were worth more than the entire linear-vs-GBM gap

`mbfeat.py` had `APPLE_CHIP = r'\bm([1-4])\b'`, so **every M5 machine was invisible** — 44 ads
(2.2%) collapsed into the `unknown` chip bucket alongside genuinely unparseable junk. And a
lone `128GB` was read as 128 GB of *RAM* rather than a 128 GB disk. Both are already repaired
in the production extractor (`bazos/pricing/features.py` now reads `m([1-9])`); this section
measures what that repair was worth. Rebuilding the analysis features the same way
(`mbfeat_fix.py` → `mb/ds_fix.pkl`) and re-running the identical protocol:

| Model | R² before | R² after | MedAPE before | MedAPE after |
|---|---|---|---|---|
| **`ridge_spline`** | 0.831 | **0.867** | 11.33% | **10.68%** |
| `ols` | 0.831 | 0.864 | 11.43% | 11.53% |
| `config_median_strict` | 0.788 | 0.836 | 10.32% | 10.16% |
| `hgb_incumbent` | 0.880 | 0.887 | 8.82% | 8.85% |

**+0.036 R² for the linear model, +0.007 for the GBM.** A tree ensemble routes an
unidentifiable chip down its own subtree and recovers most of the signal from year, RAM, SSD
and screen; a linear model has one `chip_key_unknown` dummy and cannot. Bad features cost the
linear model roughly 1.5× what the whole model-class choice costs it.

Everything from here on is measured on the repaired features.

### 3.2 The ladder

Protocol A is 15 folds (5×3); `±` is the fold-to-fold sd, which is a property of the folds,
not a confidence interval on the model (see §2.3 and §4).

| # | Model | A: R² | A: MedAPE | B: R² | B: MedAPE |
|---|---|---|---|---|---|
| | *— baselines —* | | | | |
| 1 | global mean | −0.038 ±0.161 | 49.60% | −0.003 | 50.50% |
| 2 | global median | −0.099 ±0.313 | 44.49% | −0.039 | 39.91% |
| 3 | median by exact config, ≥3 comparables (81% coverage) | 0.836 ±0.054 | 10.16% | 0.870 | 6.26% |
| 4 | …with a fallback ladder (100% coverage) | 0.789 ±0.067 | 11.59% | 0.827 | 7.15% |
| | *— linear, mean loss —* | | | | |
| 5 | OLS, year linear | 0.864 ±0.052 | 11.53% | 0.881 | 9.58% |
| 6 | OLS, year cubic spline | 0.867 ±0.054 | 10.48% | 0.883 | 8.41% |
| 7 | ridge, year linear | 0.863 ±0.053 | 11.47% | 0.882 | 9.47% |
| 8 | **ridge, year cubic spline** | **0.867 ±0.054** | 10.68% | **0.885** | 8.48% |
| 9 | **ridge, year piecewise-linear (hinges at 2016/18/20/22/24)** | **0.868 ±0.054** | 10.63% | **0.885** | 8.94% |
| 10 | **ridge, year as a 15-level categorical** | **0.866 ±0.054** | **10.37%** | **0.885** | 8.57% |
| 11 | lasso | 0.862 ±0.056 | 11.45% | 0.882 | 9.68% |
| 12 | elastic net | 0.856 ±0.060 | 11.54% | 0.881 | 9.62% |
| 13 | ridge + screen as categorical | 0.864 ±0.057 | 10.80% | 0.885 | 8.87% |
| 14 | ridge + exact-config dummies (196 cols) | 0.858 ±0.055 | 11.19% | 0.892 | 8.53% |
| 15 | ridge + per-chip-family slope vectors | 0.845 ±0.071 | 11.38% | 0.883 | 8.19% |
| 16 | ridge on all pairwise interactions (1 176 cols) | 0.835 ±0.071 | 12.08% | 0.870 | 6.89% |
| | *— linear, robust / median loss —* | | | | |
| 17 | Huber | 0.857 ±0.058 | 10.45% | 0.879 | 7.85% |
| 18 | L1 (median regression), year spline + screen cat. | 0.851 ±0.064 | 10.42% | 0.878 | 7.79% |
| 19 | L1, year linear | 0.855 ±0.056 | 11.19% | 0.882 | 7.83% |
| 20 | L1 + per-chip-family slopes | 0.840 ±0.077 | 10.24% | 0.873 | 7.77% |
| | *— trees —* | | | | |
| 21 | single CART (tuned) | 0.771 ±0.093 | 12.74% | 0.830 | 7.49% |
| 22 | random forest (400 trees, tuned) | 0.878 ±0.049 | 9.13% | **0.925** | **4.77%** |
| 23 | HistGradientBoosting, tuned | 0.885 ±0.047 | 9.03% | 0.910 | 6.37% |
| 24 | HistGradientBoosting, absolute-error loss | 0.880 ±0.048 | 8.96% | 0.900 | 4.75% |
| 25 | **HistGradientBoosting, incumbent params** | **0.887 ±0.047** | **8.85%** | 0.912 | 6.26% |

Five things this table says.

- **Regularisation is irrelevant on this problem.** Rows 5, 7, 11 and 12 span 0.008 R². The inner CV
  picks ridge α = 0.1 in 10 of 15 folds and lasso α = 3·10⁻⁴ in 15 of 15 — i.e. essentially no
  shrinkage. With ~1 600 training rows and ~60 columns there is nothing to shrink. Reaching for
  elastic net here is cargo cult; it is the *worst* of the four.
- **The one linear-feature change that pays is giving `year` a nonlinear form** (rows 6, 8,
  9, 10 against rows 5 and 7): ~1 pp of MedAPE, no R² cost. Model year is the dominant feature
  and its effect is not log-linear — the Apple-silicon step in 2020–21 is a genuine
  discontinuity. **How the nonlinearity is expressed does not matter**: cubic spline 0.867,
  piecewise-linear hinges 0.868, one dummy per year 0.866, all inside a ±0.054 fold sd. Pick
  the cheapest to serve, which is the dummies.
- **More linear capacity does not help, it hurts.** Config dummies (14), per-chip-family slope
  vectors (15) and full pairwise interactions (16) all *lose* R² against held-out sellers,
  while gaining on the chronological split — the classic signature of fitting seller-specific
  structure that does not transfer. Row 16 is the most flexible linear model in the table and
  the worst of them — 0.033 R² below plain OLS.
- **The loss function is a lever for MedAPE and only for MedAPE, and a small one here.**
  MedAPE is a median of `|exp(p) − price|/price`, which for small residuals is `|p − y|` on the
  log scale — so fitting the conditional *median* (L1) optimises the metric directly, while
  least squares fits the conditional mean. It works: the best L1 model reaches 10.24% MedAPE
  against 10.37% for the best mean-loss linear model — but it pays 0.026 R² for those 0.13 pp,
  which is a bad trade. On the unrepaired features the same trick was worth a full 1.4 pp
  (9.97% vs 11.33%), so **most of what L1 was buying was robustness to the extractor bugs.**
  The same trick does nothing for the GBM (24 vs 25).
- **A single tree is not a cheap GBM.** Row 21 is worse than plain OLS on both metrics. The
  ensemble is the whole point; the "small decision tree" option is not on the table.

### 3.3 Reconciling with previously published figures

Protocol details move these numbers by more than several models do, so:

| Model | pooled-OOF R² | mean-of-folds R² | fold sd |
|---|---|---|---|
| ridge, year linear | 0.860 | 0.848 | ±0.047 |
| ridge, year spline | 0.865 | 0.854 | ±0.055 |
| ridge, year categorical | 0.864 | — | — |
| OLS, year spline | 0.864 | 0.853 | ±0.056 |
| L1, year spline | 0.851 | 0.839 | ±0.071 |
| HGB (incumbent) | 0.887 | 0.878 | ±0.046 |

(non-shuffled `GroupKFold(5)`, repaired features). Pooling the out-of-fold predictions and
scoring once is ~0.011 higher than averaging per-fold R², because per-fold R² divides by each
fold's own variance. The **v1** Ridge's **0.861** sits exactly on the pooled ridge line
here, which is what it should be — that artifact was trained on repaired features. Its MedAPE
of **11.72%** is the plain year-linear ridge (row 7, 11.47%); any nonlinear year form recovers
the ~1 pp, and the retrain of §1 did exactly that (10.14%).

`MACBOOK_PRICE_MODEL.md` §3's GBM figures (0.873 seller-grouped / 0.905 time) were measured on
the *unrepaired* features and a single non-shuffled fold assignment; the equivalent here is
0.881 pooled / 0.912. Nothing contradicts, the basis moved.

## 4. Is the gap real? Paired seller-cluster bootstrap

Difference against the incumbent GBM, resampling **sellers** with replacement (the unit of
independence — 56% of ads belong to ten of them), 2 000 replicates, both models scored on the
same resampled rows. Negative ΔR² and positive ΔMedAPE mean *worse than the GBM*.

| Model | ΔR² | 95% CI | ΔMedAPE (pp) | 95% CI |
|---|---|---|---|---|
| HGB tuned | −0.0034 | [−0.0088, +0.0012] | +0.19 | [−0.46, +0.74] |
| HGB, absolute-error loss | −0.0089 | [−0.0205, −0.0005] | +0.24 | [−0.74, +0.82] |
| random forest | −0.0113 | [−0.0251, **+0.0029**] | +0.44 | [−1.10, +1.75] |
| **ridge, year categorical** | **−0.0259** | [−0.0436, −0.0121] | **+1.43** | [+0.22, +2.80] |
| ridge, year piecewise-linear | −0.0243 | [−0.0412, −0.0107] | +1.77 | [+0.40, +3.04] |
| ridge, year spline | −0.0244 | [−0.0416, −0.0107] | +1.96 | [+0.77, +3.18] |
| OLS, year spline | −0.0247 | [−0.0425, −0.0107] | +1.83 | [+0.70, +3.19] |
| OLS, year linear | −0.0283 | [−0.0436, −0.0156] | +2.72 | [+1.30, +3.91] |
| ridge + config dummies | −0.0317 | [−0.0501, −0.0172] | +2.65 | [+1.09, +4.03] |
| Huber | −0.0334 | [−0.0595, −0.0145] | +1.40 | [+0.03, +2.96] |
| L1, year spline | −0.0378 | [−0.0673, −0.0169] | +1.50 | [+0.08, +3.15] |
| ridge + per-chip slopes | −0.0442 | [−0.0675, −0.0271] | +2.95 | [+1.66, +4.32] |
| median by exact config | −0.0708 | [−0.1021, −0.0411] | +2.49 | [−1.99, +4.83] |
| single CART | −0.0778 | [−0.1311, −0.0434] | +2.96 | [+1.33, +4.96] |

**Stated plainly: the linear model is not within noise of the GBM.** Both intervals exclude
zero, on both metrics, for every linear variant. Anyone hoping this report would say "it's a
wash" should read the first row of §5 instead.

The random forest **is** within noise of the GBM (ΔR² CI includes zero) — if a tree ensemble is
ever deployed, the boosting is not the part that earns its keep.

## 5. Where the GBM's margin actually lives

Protocol-A out-of-fold predictions, **averaged over the 3 repeats** — averaging three
independent fold assignments is itself a mild variance reduction, so every R² here reads
~0.004 higher than the same model's §3.2 figure. It affects both models equally, so the
comparisons hold. R² is suppressed where the segment is defined by price, since conditioning
on price destroys the denominator.

| Segment | n | ridge R² | ridge MedAPE | HGB R² | HGB MedAPE | config-median MedAPE |
|---|---|---|---|---|---|---|
| all | 2 038 | 0.871 | 10.6% | 0.891 | 8.9% | 10.6% |
| year + chip + RAM + SSD all parsed | 1 416 | 0.920 | 8.8% | 0.928 | 7.3% | 9.8% |
| any of the four missing | 622 | 0.748 | 16.5% | 0.795 | 13.8% | 12.9% |
| model year missing | 400 | 0.778 | 13.8% | 0.805 | 11.8% | 11.0% |
| chip unidentified | 127 | 0.305 | 25.3% | 0.373 | 27.6% | 57.8% |
| Apple silicon | 993 | 0.823 | 12.6% | 0.861 | 10.8% | 9.3% |
| Intel | 918 | 0.544 | 7.7% | 0.590 | 6.1% | 11.0% |
| MacBook Pro | 1 435 | 0.901 | 9.9% | 0.925 | 8.1% | 11.4% |
| MacBook Air | 563 | 0.765 | 11.5% | 0.773 | 10.3% | 7.8% |
| price < 10k | 911 | — | 8.5% | — | 6.8% | 12.1% |
| price 10–20k | 674 | — | 11.8% | — | 9.9% | 6.1% |
| price ≥ 20k | 453 | 0.316 | 14.4% | 0.476 | 11.9% | 11.5% |

(config-median MedAPE is over its 81%-covered subset only, so it is not comparable row-for-row.)

The GBM's edge is **broad and shallow, not concentrated**: roughly 1.5–2.5 pp of MedAPE in
almost every segment, largest at the top of the price range (14.4% → 11.9%, ΔR² 0.16) where
each configuration has fewer comparables and a tree can borrow strength across similar specs.
It is *not* rescuing a pathological segment that a feature fix could close — the only cell
where the linear model comes out ahead is MedAPE on `chip unidentified` (25.3% vs 27.6%, and
the GBM still wins that segment on R², 0.373 vs 0.305), which is the segment the extractor fix
already shrank from 169 rows to 127.

**Both models are far worse on one-off sellers (16.7% / 14.4%) than on dealers with ≥10 ads
(8.8% / 7.2%)**, and 75% of the linear model's residual variance is between sellers rather than
within them (72% for the GBM) — the same confound `MACBOOK_PRICE_MODEL.md` §5 identifies.
Model class does not touch it.

## 6. Learning curve — does more data help?

Training sellers subsampled inside each fold, 3 repeats, α retuned at every point (the GBM
carries fixed hand-set parameters, so it is not retuned).

| training rows | ridge R² | HGB R² | ridge MedAPE | HGB MedAPE |
|---|---|---|---|---|
| ~267 | 0.728 ±0.056 | 0.780 ±0.025 | 16.0% | 14.1% |
| ~534 | 0.800 ±0.010 | 0.813 ±0.007 | 12.8% | 12.9% |
| ~890 | 0.847 ±0.007 | 0.853 ±0.010 | 11.5% | 11.2% |
| ~1 246 | 0.852 ±0.007 | 0.875 ±0.003 | 11.1% | 9.2% |
| ~1 513 | 0.859 ±0.010 | 0.879 ±0.009 | 11.3% | 9.2% |
| ~1 781 (all) | 0.865 | 0.888 | 10.6% | 8.6% |

Both curves are still rising at the right edge — the corpus grows by ~21 MacBook ads/day, so
another quarter roughly doubles it and is worth ~+0.01 R² for either model. **The gap does not
close with data**: it is ~0.02 R² from 890 rows onward, and if anything widens between 890 and
1 246 as the GBM starts finding structure the linear form cannot express. Waiting for more data
is not a strategy for making the linear model catch up.

The one place the gap is *large* is the small-data end (0.728 vs 0.780 at 267 rows), which
matters for a second category: **a newly-added query with a few hundred ads is exactly where a
linear model is weakest**, and where the config-median fallback is weaker still.

## 7. Residual diagnostics

Protocol-A residuals on the log scale.

| | ridge, year spline | HGB incumbent |
|---|---|---|
| residual sd (log) | 0.2181 | 0.1974 |
| skew | +0.24 | −0.17 |
| excess kurtosis | **+5.89** | **+7.51** |
| Breusch–Pagan LM (resid² on fitted), χ²₁ | 2.9 (p = 0.086) | 6.2 (p = 0.013) |
| between-seller share of residual variance | 75% | 72% |

- **Heteroscedasticity is weak and not a funnel.** Residual sd by fitted sextile runs
  0.183 · 0.158 · 0.222 · 0.293 · 0.209 · 0.217 for the linear model — the worst band is the
  fourth (mid-price, ~13–20k), not either extreme. The Breusch–Pagan test on the linear model
  does not reach significance; on the GBM it does, but with the same non-monotone shape, so a
  variance-stabilising transform is not the fix. A locally-scaled conformal interval would be.
- **Residuals are heavy-tailed, badly.** Excess kurtosis ~6–7.5 against a Gaussian's 0 (Shapiro
  rejects normality outright for both). This is why MedAPE and R² keep telling different
  stories in §3.2 — R² is driven by a tail the median never sees — and why a Gaussian interval
  is only usable near the middle: at nominal 80% it happens to work for the linear model (§9),
  but nothing here licenses extending it to a 99% interval.
- **No year bias.** Mean residual by model year stays within ±0.056 log points across
  2013–2026 for the linear model — the cubic spline absorbs the depreciation curve, including
  the Apple-silicon step. The GBM shows a mild monotone drift instead (−0.023 at 2013 to +0.049
  at 2026), i.e. it slightly under-predicts new machines.
- **Mean residual by fitted sextile** is +0.025 · +0.026 · +0.020 · −0.026 · +0.018 · +0.012:
  no systematic curvature left. Both models are essentially unbiased in the fitted direction.
- **75% of the residual variance is between sellers.** Neither model addresses it, and it is
  larger than every model-class difference in this document put together.

## 8. What the linear model says — coefficient interpretation

Fitted on the full corpus for reporting only (every accuracy figure above is out-of-fold).
Effects are `exp(β) − 1`, i.e. % change in asking price, with a 95% seller-cluster bootstrap
interval (400 replicates, aligned by feature name because a resample can drop a rare chip).

### 8.1 Specification

| Effect | Estimate | 95% CI |
|---|---|---|
| **Doubling RAM** (8→16 GB, 16→32 GB) | **+10.1%** | +6.5% … +14.6% |
| **Doubling SSD** (256→512 GB) | **+7.9%** | +5.2% … +10.3% |
| One inch of screen | +3.9% | +2.1% … +6.4% |
| MacBook Pro vs Air | +13.9% | +8.6% … +20.2% |

(The recommended year-categorical form gives the same figures to within rounding: RAM +10.3%,
SSD +7.6%, Pro vs Air +14.1%.)

RAM and SSD enter as `log2(capacity)`, so a constant % per doubling is a *modelling
assumption*, not a measurement. It is a defensible one here: the variant that relaxes it
(row 14, one dummy per exact configuration) is 0.009 R² **worse**, so there is no evidence of
capacity nonlinearity the log form is missing.

### 8.2 Depreciation

Fitted year curve, everything else held at its median, relative to a 2020 machine:

| 2013 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 |
|---|---|---|---|---|---|---|---|---|---|---|
| −42% | −38% | −30% | −24% | −17% | −9% | 0% | +8% | +13% | +15% | +15% |

(2014 omitted — 10 ads.) Over 2015→2023 that compounds to **8.0% of value lost per model year, configuration held
constant** — independently reproducing the 8.3% in
[`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §7 by a completely different route. The
curve flattens after 2023 and turns down at 2025–26 in this rendering; **that tail is an
artifact**, because holding `chip_key` at its corpus mode (Intel i5) asks the model to price a
2026 Intel MacBook, which does not exist. Read the curve over 2013–2023 only.

The year-categorical form makes the same statement one coefficient at a time and adds a fact
the spline cannot express: the `year = na` dummy lands at **+0.541 log points, between the 2020
(+0.533) and 2021 (+0.556) levels**. An ad whose model year cannot be parsed is priced by the
model as a ~2020 machine — which is why `MACBOOK_PRICE_MODEL.md` §4 finds unparsed ads
over-represented in the underpriced tail: a genuinely old machine with no year in its title is
scored against a 2020 benchmark and looks like a bargain. The dummies are also visibly noisier
year-to-year (2021 +2%, 2023 +12%, 2025 +5% against the 2020 baseline) because nothing smooths
them, so **use the spline curve for reading depreciation and the dummies for serving.**

### 8.3 Chip

Relative to an **M1 base** at the same model year, RAM, SSD and screen:

| M4 Max | M5 Max | M5 Pro | M3 Max | M4 Pro | M2 Max | M5 | M3 Pro | M1 Max | M4 | M2 Pro | M3 | M2 | M1 Pro | i9 | i7 | i5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| +285% | +265% | +233% | +181% | +165% | +119% | +111% | +109% | +75% | +75% | +59% | +51% | +24% | +19% | −12% | −22% | −23% |

**Caveat that must travel with this row:** chip and model year are almost collinear (an M4 Max
only exists from 2024), so "at the same model year" is a counterfactual the data cannot
support, and the split of credit between §8.2's curve and this row is not independently
identified. The bootstrap intervals are tight (M4 Max [+207%, +351%]) but they measure
sampling variability, not identification. The *joint* prediction is sound; a single
coefficient quoted alone is not.

### 8.4 Condition and seller vocabulary

| Feature | Effect | 95% CI |
|---|---|---|
| `nový` / unopened / unused | **+15.9%** | +10.0% … +21.2% |
| damage vocabulary (`nefunkční`, `vadný`, `prasklý`, …) | **−10.6%** | −18.6% … −0.4% |
| Czech keyboard mentioned | +7.6% | +0.1% … +16.6% |
| original box / complete packaging | +4.9% | −1.9% … +14.1% |
| **warranty mentioned** | **+4.0%** | **−1.7% … +8.6%** |
| **DPH / invoice / company sale** | **+3.0%** | **−3.1% … +9.3%** |
| Touch Bar | −3.8% | −11.3% … +1.6% |
| visible scratches / dents | −3.0% | −8.3% … +2.9% |
| "new battery" / battery replaced | **−15.8%** | −27.4% … +2.6% |

Two of these are worth stopping on.

- **Warranty and VAT-invoice language are not worth a measurable premium** — both CIs straddle
  zero. This is the same result `MACBOOK_PRICE_MODEL.md` §5.1 reached by spec-matched medians
  (dealer premium −2.1% to +1.5%), now reproduced as a partial coefficient with everything else
  held constant. Two unrelated estimators agreeing on a null is about as much corroboration as
  this corpus can offer — though both are still descriptions of asking prices, not of what a
  warranty is worth to a buyer.
- **"New battery" predicts a *lower* price** (−15.8%, CI just touching zero). It is not a
  feature the seller adds value with; it is a marker of an old machine that needed one. This is
  exactly the kind of sign flip that makes a linear model worth having — it is legible, and it
  is checkable against intuition, which a GBM's partial dependence is not.

## 9. Calibration — are prediction intervals honest?

`naive` is `pred ± z·σ` with σ the **training-residual** sd. `conformal` is split conformal:
fit on part of the training data, take the (1−α) quantile of absolute residuals on a
held-out calibration slice, apply that half-width. Under protocol A the calibration slice is a
disjoint 30% of the training **sellers**; under protocol B it is the last 15% of the training
window.

| Model | protocol | nominal | conformal coverage | conformal width | naive coverage | naive width |
|---|---|---|---|---|---|---|
| **ridge, year categorical** | seller | 80% | 78.2% | 5 388 Kč | **80.2%** | 5 494 Kč |
| **ridge, year categorical** | seller | 90% | 88.3% | 7 594 Kč | 87.4% | 7 099 Kč |
| **ridge, year categorical** | time | 80% | 83.7% | 5 421 Kč | 81.5% | 4 949 Kč |
| **ridge, year categorical** | time | 90% | 94.0% | 8 978 Kč | 87.6% | 6 390 Kč |
| ridge, year spline | seller | 80% | 76.1% | 5 283 Kč | 80.0% | 5 509 Kč |
| ridge, year spline | seller | 90% | 87.0% | 7 484 Kč | 88.2% | 7 117 Kč |
| ridge, year spline | time | 80% | 85.6% | 5 638 Kč | 83.0% | 5 027 Kč |
| ridge, year spline | time | 90% | 93.8% | 8 747 Kč | 87.9% | 6 492 Kč |
| HGB incumbent | seller | 80% | 73.4% | 4 899 Kč | **39.8%** | 2 009 Kč |
| HGB incumbent | seller | 90% | 86.5% | 6 965 Kč | 49.9% | 2 582 Kč |
| HGB incumbent | time | 80% | 81.2% | 3 982 Kč | 59.6% | 1 965 Kč |
| HGB incumbent | time | 90% | 92.8% | 7 318 Kč | 68.6% | 2 525 Kč |

**This is the clearest operational argument for the linear model in the whole document.** The
GBM's training residuals are a fiction — it fits the training set far too closely — so an
interval built from them covers **39.8% of the time at a nominal 80%**. The linear model's
training residual sd is nearly unbiased for its test error (80.2% at nominal 80%, 87.4% at
90%), because with ~1 600 rows and ~60 columns it barely overfits. (The v1 manifest's
`residual_sigma: 0.2264` is exactly this quantity, and §7/§10 put the true out-of-fold sd at
0.218–0.219 — if anything conservative, which is the safe direction. The retrained artifact on
disk carries **0.2308** on 2 258 training rows; §1.) A GBM therefore does not
just drag numpy onto the Pi; it drags a conformal calibration stage with it, or it ships
intervals that are wrong by a factor of two.

Split conformal is still the right answer for either model, and it is *still* not exact under
protocol A — 78.2% at nominal 80% — because exchangeability fails across sellers: calibrating
on one set of shops and scoring another is precisely the violation. Under the chronological
protocol it over-covers (83.7%). Neither is a disaster; both mean **a conformal interval on
this data should be treated as ±5 pp, not as a guarantee**, and the seller-grouped direction
is the conservative one to design against.

## 10. What the gap costs operationally

The model exists to be a "fair price" reference for an underpricing alert, so the number that
decides the trade-off is not R² — it is how many listings each model puts below the threshold,
and whether they are the *same* listings. Protocol-A out-of-fold predictions, 14.0 weeks:

| threshold | linear flags | per week | HGB flags | per week | agree on | Jaccard |
|---|---|---|---|---|---|---|
| ≥15% below | 315 | 22.3 | 235 | 16.7 | 180 | 0.486 |
| ≥20% below | 223 | 15.8 | 159 | 11.3 | 122 | 0.469 |
| **≥25% below** | **131** | **9.3** | **105** | **7.4** | **81** | **0.523** |
| ≥30% below | 82 | 5.8 | 76 | 5.4 | 57 | 0.564 |
| ≥40% below | 29 | 2.1 | 30 | 2.1 | 18 | 0.439 |

The two models agree on the point price closely — median difference 744 Kč (6.8% of the median
ad), correlation 0.977 on the log scale. But at the 25% threshold they **agree on only 52% of
the union of their flags**, and the linear model raises **25% more alerts per week** (9.3 vs
7.4) because its residual sd is 11% wider (0.2193 vs 0.1974 log points).

Whether those ~2 extra alerts/week are false positives still cannot be measured. When this was
written the database recorded no outcome for any listing; since 2026-09-17 it records
`Ad.removed_at`, which is a *confounded* proxy - expiry looks identical to a sale - and the
`AdOutcome` logbook that would calibrate it is empty
([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §6). **The cost of the accuracy gap is
therefore still known in volume and unknown in value**, and that asymmetry is itself an argument
against paying a permanent deployment price for it today.

## 11. Recommendation

**Ship the linear model. Do not put a tree ensemble on the Pi for this.**

1. **The gap is real, and it is small.** ΔR² −0.026 [−0.044, −0.012], ΔMedAPE +1.43 pp
   [+0.22, +2.80] — not fold noise, and this report does not claim otherwise. In money that is
   a typical miss of 1 112 Kč rather than 935 Kč on the median 10 990 Kč ad: **177 Kč, 1.6% of
   the asking price.**
2. **The deployment cost is permanent and the benefit is unpriceable.** A linear model exports
   as `intercept + Σ coef·feature`, reviewable in a git diff, with no version-skew surface. A
   GBM means numpy + scikit-learn on an ARM64 image, *or* a hand-written tree serializer, *plus*
   a conformal calibration stage it cannot ship without (§9). Against that: 1.4 pp of median
   error whose downstream value cannot be measured until the pipeline records *calibrated*
   outcomes. [`PROMPTS.md`](../backlog/PROMPTS.md) P24 has shipped and the pipeline now records
   `Ad.removed_at`, but that proxy conflates a sale with an expiry and its `AdOutcome` logbook
   is empty, so nothing yet prices a false alert. Paying a permanent, load-bearing cost for an
   unmeasurable benefit is still the wrong order of operations.
3. **The specific model to ship**: ridge on the log price with **`year` as a 15-level
   categorical** — one dummy per model year 2013…2026 plus an `na` level — `log2(RAM)` and
   `log2(SSD)` with median imputation and missing indicators, screen size, one-hot family /
   `chip_key` / region, and the 14 boolean text flags. 63 columns, α = 0.1 (OLS is
   statistically identical; keep the small α for numerical stability against rare one-hot
   levels). Scores **R² 0.866 / MedAPE 10.37%** against unseen sellers and **0.885 / 8.57%**
   past→future, against the v1 artifact's 0.861 / 11.72%. ✅ **Shipped** - the retrained
   manifest reads 0.8604 / 10.14% on 2 258 rows (§1).

   **Every one of those is already an existing manifest `kind`.** `year` moves from
   `{"kind": "num", "name": "year", "fill": 2020.0}` plus its `missing` companion to a set of
   `{"kind": "cat", "name": "year_s", "level": "2019"}` entries — no new evaluator code, and
   the `na` level absorbs the missing indicator. The spline and hinge forms score the same
   (§3.2 rows 8–9) but would each need a new feature kind in `bazos/pricing/features.py`; there
   is no accuracy reason to pay for one.
4. **Do the extractor work first, and keep doing it.** Two regex fixes were worth +0.036 R² to
   the linear model — more than the entire model-class decision (§3.1). 19.6% of ads still have
   no parseable model year and their MedAPE is 13.8% against 8.8% for fully-parsed ads. That is
   where the next 0.02 R² is, and unlike a GBM it costs nothing to deploy.
5. **What would change this answer.** (a) Outcome data that *prices* a false alert - if 2
   extra alerts/week turn out to be expensive, 25% more of them is worth a numeric stack. P24
   has shipped and `Ad.removed_at` exists, but until `AdOutcome` carries enough rows to say how
   often "disappeared" means "sold", that price is still unknown.
   (b) Extending to a category with far fewer ads: at ~267 training rows the gap is 0.052 R²,
   not 0.026 (§6). (c) If a tree ensemble is ever deployed anyway, **use the random forest** —
   it is statistically indistinguishable from the boosting (ΔR² CI includes zero, §4), and one
   fewer hyperparameter to hand-tune.
6. **Two cheap follow-ups inside the linear family, both no-cost to ship.** Median (L1)
   regression trades ~0.015 R² for a few tenths of a point of MedAPE — worth a look if the
   alert threshold, not the point estimate, is what is being consumed, though on the repaired
   features it no longer beats the year-categorical ridge. And the median-by-exact-config
   lookup remains an excellent *ensemble partner*, not a replacement: 10.16% MedAPE on the 81%
   it covers, with a completely different failure mode from the regression — and it is the one
   model that is *worse* than useless where the chip is unidentified (R² −0.37, §5), so any
   ensemble must gate on that.

## 12. Limits

- **One category, one marketplace, 98 days.** Notebooks are unusually dealer-heavy. None of
  this transfers to `naradi` or `iphone` without re-measurement, and §6 says small corpora are
  exactly where the linear model is weakest.
- **The price distribution is censored** at the query's 5 000–100 000 Kč bounds. 23 ads sit at
  exactly the 5 000 floor and every model is nonsense on them; anything below 5 000 Kč was
  never collected, so the model has no basis for pricing the bottom of the market and a
  low-priced prediction is extrapolation.
- **Asking price, not realised price.** Every number here predicts what a seller asks. What a
  machine sells for is not in the database at all.
- **No causal reading of §8.** These are partial coefficients on observational listing text
  with chip and year near-collinear. "A year of age costs 8%" is a description of the corpus,
  not an intervention.
- **The 81% coverage of the config-median baseline** counts an "unknown RAM" bucket as a valid
  configuration. Measured with all four specs required to parse it covers **62.2%** of the
  corpus, reproducing the 63% quoted in
  [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §3.1.
- **Bootstrap intervals assume sellers are exchangeable**, which the dealer/private split
  strains. They are indicative, not exact.
- **The extractor comparison in §3.1 is not a controlled experiment.** The repair changed 44
  chip assignments and 4 RAM values at once; the two fixes are not separated, and both are
  confounded with whatever else those 48 rows have in common.
- **§8's coefficients come from a single full-corpus fit.** They are for reading, not for
  scoring — every accuracy figure in this document is out-of-fold, and none of them was
  produced by that fit.

## 13. Reproducing this

Working scripts are in [`experiments/price_model/`](../../experiments/price_model/) —
throwaway analysis, excluded from ruff and mypy. They need pandas / numpy / scikit-learn,
which are not app dependencies: `poetry install --with ml`. The corpus pickle they read is
not committed (seller names, publisher ids); rebuild it with `build_ds.py`.

| Script | What it does |
|---|---|
| `bm_features.py` | design matrices — `raw_frame()` derives the columns, `prep(kind)` builds the leak-free preprocessor (`lin` / `spline` / `hinge` / `yearcat` / `rich` / `config` / `tree`), `InteractDesign` the per-chip-family slope blocks |
| `bm_models.py` | the 25-model ladder with its parameter grids, plus `ConfigMedian`, the non-ML lookup baseline |
| `bm_eval.py` | the protocols — `nested_group_cv` (A), `plain_group_cv` (reconciliation), `time_split_eval` (B), `metrics`, `cluster_bootstrap_delta` |
| `bm_run_ladder.py` | runs the whole ladder under all three protocols → `mb/bench_results*.json`, `mb/bench_oof*.npz`. `--fix` switches to the repaired features |
| `bm_compare.py` | §4 paired bootstrap, §3.3 reconciliation, §3.1 before/after |
| `bm_diag.py` | §5 segments, §6 learning curve, §7 residual diagnostics |
| `bm_coef.py` | §8 coefficients with the cluster bootstrap, §9 conformal vs naive intervals |
| `bm_ops.py` | §10 alert funnel and model agreement |
| `mbfeat_fix.py`, `build_ds_fix.py` | the repaired extractor and the rebuild → `mb/ds_fix.pkl` |

Inputs are `mb/ds.pkl` (as-given) and `mb/ds_fix.pkl` (repaired); `seller_base.py` and
`mbfeat.py` are reused unchanged from the earlier analysis. Full run: about 25 minutes per
ladder pass, dominated by the tuned GBM.
