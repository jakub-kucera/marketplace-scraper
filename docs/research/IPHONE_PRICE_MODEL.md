---
title: iPhone price prediction — the model works and the alert does not
status: reference
updated: 2026-10-15
verified: 2026-09-13
---

# iPhone price prediction — the model works and the alert does not

> **Shipped 2026-10-15, as §8 recommends: registered, not enabled.** `bazos/pricing/estimators/iphone.py`
> carries the three model-side decisions below — generation as a live age in months (§5.1), σ on spec
> completeness (§6), and a decline on an unknown generation — and `MODEL_REGISTRY` now holds two models.
> Re-fitted on a **5.5-week** corpus rather than this document's 3.3-day window: **6 300 ads,
> R² 0.930 seller-grouped, MedAPE 9.40%, σ 0.222 (battery stated) / 0.263 (not stated)**, against
> 0.9373 / 9.95% / 0.1998 on the 602 rows here. The newer figure is on a superset that keeps damaged
> phones as a trained feature rather than gating them, which is where most of the difference sits;
> §2's warning against comparing R² across corpora applies to these two numbers as well.
> **§7's conclusion is unchanged and nothing here enabled the rule.** The safe state is *not* shadow
> mode — production runs `PRICE_MODEL_SHADOW_MODE=false` — it is that query 19's `filter_rule_names`
> is `[]`, which resolves to `DEFAULT_RULE_NAMES`, which excludes `price_model`.
>
> Two things this document asked for that the shipped code does **not** inherit. The `_NEG` defect
> §7 describes is **fixed here but deliberately left in the experiment**: the disambiguator is the
> intervening copula, so `zadne skrabance` reads as a denial and `zadni sklo je prasklé` does not.
> And the resold-pre-order class, which post-dates this window, turned out to be the largest single
> defect on the larger corpus — 4.2% of the category, and it had to become a gate.
>
> Written 2026-09-13 from a read-only pull of the production database on `raspberrypi5.local`:
> **655 Bazos ads from query 19 (`iphone`, 1 000–70 000 CZK), created 2026-09-09 15:14 →
> 2026-09-12 22:25 UTC — a window of 3.30 days**. 639 of them classify as a whole iPhone for
> sale and are the modelled set. Query 8's 2 854 MacBook rows come from the same pull and are
> used only as a comparison arm.
>
> This is the category [`CATEGORY_PRICE_MODELS.md`](CATEGORY_PRICE_MODELS.md) §8 recommended
> building, and it is the first of those five recommendations to be carried through to a
> shippable artifact. **Nothing here is wired into the pipeline.** `MODEL_REGISTRY` still holds
> one model; query 19's `filter_rule_names` is empty, which resolves to `DEFAULT_RULE_NAMES`,
> which excludes `price_model` — so nothing in production scores an iPhone today and nothing in
> this document changes that on its own (§8).
>
> Standing caveat, binding on every number below and **re-based 2026-09-18**: outcomes now exist
> and cannot yet be read as outcomes. P24 shipped on 2026-09-17, after this window closed, so
> `Ad.removed_at` is populated on 19 008 of 30 037 production ads; but a missing `limit` in the
> sweep's bulk id fetch means it asks about 210 ads and is answered about 30, so ~86 % of those
> rows are ads that are still listed, and nothing re-checks a removed ad (open as of 2026-09-18).
> `removed_at` also conflates sold with withdrawn, deleted and **expired**, and `AdOutcome` holds
> **zero rows**. Every precision figure
> here is therefore still a composition audit, never a measurement of whether a flagged listing
> was a deal ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §6).

## 1. Summary

| Question | Answer |
|---|---|
| Can an iPhone's asking price be predicted from listing text? | **Yes, and this is the tightest fit in the project on its own corpus.** Ridge R² 0.9373 / MedAPE 9.95% / σ 0.1998, seller-grouped, on the 602 complete-spec rows of 334 sellers |
| Is it "the best model this project has built"? | **No — that claim is struck.** It compares R² across corpora, which [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §2.1 forbids: sd(log price) is 0.811 here against 0.622 on MacBook (§2) |
| Does the name-derived ordinal beat per-model dummies? | **Yes, and this is the cleanest instance in the project.** ΔR² +0.081 (CI +0.045…+0.123) seller-grouped; +0.404 against −7.18 with a whole generation held out (§3) |
| Does PC §4's "both together wins" transfer? | **No.** Here "both" is *worse* than the pure ordinal, ΔR² −0.005 (CI −0.011…−0.000). The 43 dummies are pure manifest cost (§3) |
| Is there extractor work left? | **No, not on the features that matter.** Generation misses 1 real row in 655; of the 37 iPhone rows with no storage, **zero contain a GB/TB token anywhere** (§3) |
| Does linear beat the tree? | **No — that was an unequal-tuning-budget artifact, caught before publication.** Nested-tune the tree and the gap collapses to ΔR² −0.0028 (CI −0.0099…+0.0042). Ship the ridge for serving, not for accuracy (§4) |
| Does a config-median lookup suffice? | **No, and for a different reason than on MacBook.** It is level on MedAPE but 18% wider on the tail an alert reads (σ 0.229 vs 0.194) and blind to 18.6% of rows (§4) |
| Was the iPhone 17 launch the confound? | **No. The 17 is ~12 months old.** The window straddles the pre-ship week of the iPhone **18**, of which zero units exist in the corpus (§5) |
| What is the real launch risk, then? | **The encoding, not a time trend.** Frozen generation levels under-price a held-out gen 17 by 73.8% and it becomes invisible to a −25% alert (0.0% flag rate) (§5) |
| Does the MacBook seller-maturity σ ladder replicate? | **No.** 0.232 / 0.253 / 0.137 / 0.184 / 0.090 — non-monotone. σ keys on spec completeness instead, with overlapping CIs (§6) |
| Would a −25% alert work? | **No. 41.3 gated flags/week against MacBook's 3.2** — 12.9×, and 2.2× worse than desktops', already judged unusable (§7) |
| Does going deeper into the tail fix that? | **No — precision gets monotonically worse.** Bait rises 20% → 50% from −25% to z ≤ −3.0, and clean candidates fall to zero (§7) |
| Can any threshold be calibrated? | **No**, and [`PROMPTS.md`](../backlog/PROMPTS.md) P24 landing did not change it: `Ad.removed_at` is a confounded proxy and the `AdOutcome` logbook is empty (§8) |

**One-line answer: the model is the best fit in the project on its own corpus and the alert is
the worst one measured, and those are not in tension — a 150-ads/day feed turns a good model
into 41 flags a week.**

## 2. The corpus, and why its R² is not comparable to MacBook's

| | iPhone (q19) | MacBook (q8) |
|---|---|---|
| ads / modelled | 655 / **639** | 2 854 |
| window | **3.30 days** (4 calendar dates) | 118.2 days |
| arrival | 193.7 iPhone-ads/day observed; **147.3/day** on days 2–4 | 24.1/day |
| sellers | 379 | 861 |
| sellers appearing once | **80.5%** | 77.2% |
| ads from one-off sellers | **46.6%** | 23.3% |
| ads from sellers with ≥10 ads | 25.2% | **60.4%** |
| top-10 seller share | 28.5% | 49.7% |
| distinct titles | 87.2% of rows | 52.9% |
| `full_description` coverage | **0%** (`load_full_description` is off) | 27.6% |
| rows ending in the 254-char truncation marker | 62.6% | 85.9% |
| median price | 10 499 CZK | — |
| **sd(log price)** | **0.8116** | **0.6218** |

The window is four calendar dates, **Wednesday to Saturday**, with no Sunday and no Monday in
it. **Day 1 carries 197 of the 639 modelled rows, and 132 of those arrived inside a
thirty-second `new_query` backfill pass** (125 of them `SUPPRESSED`). The remaining three
calendar days carry 442 rows — 147.3/day, which is the steady-state figure every projection
below rests on, and the reason the funnel in §7 is quoted at a round 150/day rather than at the
window's own 193.7.

**R² must not be compared across these two corpora, and the headline claim that was struck is
exactly that comparison.** iPhone's target has 1.7× MacBook's log-variance, so an identical
model reads higher here by construction — the same trap [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md)
§2.1 states in terms ("R² rises when the target spreads out even if nothing about the model
improved"). On the metrics that *are* comparable, MacBook wins: complete-spec σ 0.138 and
MedAPE 4.7% ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §3) against **0.200 and
10.48%** here.

### 2.1 The size-matched ordering that recommended this category is withdrawn

[`CATEGORY_PRICE_MODELS.md`](CATEGORY_PRICE_MODELS.md) §2.5 ranked iPhone above MacBook at
matched n. That table subsamples **by whole sellers**, which gives a 359-ad dealer the same
draw probability as a one-off seller and therefore strips dealer inventory out of a
dealer-heavy corpus. Re-measured at n=655: MacBook draws carry **7.7** sellers of ≥10 ads and
score **R² 0.764** under whole-seller sampling, against **11.5** and **0.799** under row
sampling — **0.035 R² of pure instrument**, all of it charged to MacBook. iPhone's full corpus
scores **0.787 either way**, because it has almost no dealer mass to lose.

**The ordering reverses and the two corpora become indistinguishable.** §2.5 carries the
correction in place and should be read there rather than restated. What survives is the
recommendation itself, on different evidence: the two screening statistics — rarefied
vocabulary 148 types per 900 title tokens, and 64.1% of titles carrying a model token — called
this corpus modelable, and they were right.

## 3. Extraction, and the structural bet

Regex over `name` + `short_description`, standard library only, 0.379 ms/ad. Coverage on the
639 modelled rows, title alone against title + the 254-character preview:

| field | title only | + preview | gain |
|---|---|---|---|
| generation | 99.5% | **100.0%** | +0.5 pp |
| tier | 99.5% | **100.0%** | +0.5 pp |
| storage | 82.5% | **94.2%** | +11.7 pp |
| colour | 48.0% | 65.9% | +17.8 pp |
| **battery health %** | 23.0% | **58.7%** | **+35.7 pp** |
| warranty months | 16.3% | 26.6% | +10.3 pp |
| generation + tier + storage jointly | 82.5% | **94.2%** | +11.7 pp |

**This extractor is at its information ceiling, and that is the unusual finding.** Generation
fails on 6 of 655 rows; five of those are contamination (a parts listing, three want-to-buy
ads, an Apple Watch) and the sixth is a real phone whose seller wrote `APPLE Iphone Pro,256 GB`
and named no generation — a **true miss rate of 1/655 = 0.15%**. Storage fails on 37 modelled
rows and **not one of them contains a GB, TB or G token anywhere in title or preview**. 94.2%
is what the text contains, not what the regex can reach.

Contrast desktops, where the same question had a very different answer: storage coverage moved
39.0% → 66.1% on an audited repair and a further **+26.5 pp** on the rows carrying a full
description ([`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4.1–§4.2). Desktop listings were being
under-read; iPhone listings are being read out.

The 254-character cap **is** binding, but for exactly one field. Battery coverage climbs
35.0% → 77.5% with visible preview length and then **falls back to 55.8% in the 250–255 bin** —
the signature of a cap cutting the text before the battery line. Storage climbs 75% → 97% over
the same bins because it lives in the title. So `load_full_description` on query 19 buys battery
and essentially nothing else: ΔR² **+0.0045** (CI +0.0011…+0.0091) for one paced detail GET per
new ad at 150 ads/day.

Contamination is **2.29%** (15 of 655): 6 want-to-buy, 5 parts/for-repair, 3 accessories, 1
Apple Watch. A 60-row random hand audit found **0 classifier errors** (Wilson 95% [0.0, 6.0]%),
and so did all 14 flagged rows. Both bounds must travel together: at a 2.3% base rate a 60-row
sample holds ~1.4 contaminated rows, so it constrains false *negatives* weakly — the binding
evidence is a targeted 99-row risk screen inside the iPhone class, which found exactly one miss.
**Want-to-buy is the class that matters most**: six rows whose price is a *bid*, not an ask, at
22 000–27 500 CZK, i.e. at the top of the distribution where they drag predictions up.

### 3.1 The ordinal test — the cleanest instance of it in the project

Generation as a float and tier as a rung, against one dummy per generation × tier (43 levels).
Ridge on one-hot, `GroupKFold(5)` on the seller × 3 repeats, pooled OOF, n=602 / 334 sellers;
CIs are a paired seller-cluster bootstrap over 800 replicates.

| encoding | R² | MedAPE | Δ vs dummies |
|---|---|---|---|
| **ordinal** (generation float + tier rung) | **0.913** | 10.6% | **+0.081 [+0.045, +0.123]** |
| per-model dummies (43 levels) | 0.833 | 11.8% | — |
| both together | 0.908 | 9.9% | **both − ordinal: −0.005 [−0.011, −0.000]** |
| ordinal + log₂ storage | 0.917 | 9.7% | +0.061 [+0.036, +0.092] |

Hold out an **entire generation** — the one-hot vocabulary built on training rows only, so the
held-out dummy genuinely does not exist at fit time — and the gap becomes the whole result:

| held-out generation | n | ordinal R² | dummies R² | ordinal MedAPE | dummies MedAPE |
|---|---|---|---|---|---|
| 11 | 45 | +0.381 | −3.03 | 24.6% | 101.8% |
| 13 | 111 | +0.429 | −0.99 | 12.6% | 36.3% |
| 15 | 96 | +0.441 | −2.70 | 9.7% | 39.1% |
| 16 | 74 | +0.272 | −19.69 | 7.3% | 58.0% |
| 17 | 129 | +0.521 | −22.41 | 6.7% | 70.0% |
| **mean over 7** | 573 | **+0.404** | **−7.18** | **12.5%** | 54.5% |

The dummies collapse to the intercept. Read the *direction* as the finding; the magnitude is an
artifact of how far a held-out generation's price level sits from the training mean.

Two qualifications, both load-bearing:

- **The win lives entirely on the generation axis.** Generation alone: ordinal 0.862 against
  dummies 0.841. Tier alone: **dummies 0.464 against ordinal 0.423 — the dummies win**. Tier is
  a small closed set that is always seen, so it has nothing to interpolate along. Encode
  generation ordinally; encode tier however is convenient.
- **[`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §4's "both together wins" does not transfer.**
  Adding the dummies on top of the ordinal costs ΔR² −0.005 (CI −0.011…−0.000) on ordinary CV
  and poisons the ordinal's coefficients out-of-generation (+0.241 against +0.404). Ship the
  ordinal alone.

**Put the project's three ordinal results side by side and the rule falls out.** PC's GPU
ordinal worked because `rtx 3070` encodes vendor, generation and tier positionally. The bike
groupset ordinal failed ([`CATEGORY_PRICE_MODELS.md`](CATEGORY_PRICE_MODELS.md) §4.1) because
`Deore` names a rung on a ladder re-cut every few years and shared with an incompatible
competitor — **the name carries no generation at all**. iPhone works best of the three because
an iPhone's name is *almost nothing but* generation and tier: `iPhone 15 Pro 256GB` is three
ordered numbers and a rung, and the market prices them monotonically (Spearman(generation,
log price) = **+0.938**, n=602).

The price ladder that underwrites it — median asking price by generation, on the classified
iPhone rows:

| generation | 17 | 16 | 15 | 14 | 13 | 12 | 11 |
|---|---|---|---|---|---|---|---|
| median CZK | 25 945 | 17 990 | 12 700 | 9 500 | 5 994 | 4 500 | 3 100 |
| n | 126 | 77 | 98 | 70 | 110 | 56 | 38 |

(Counts are on the classified set; a different extractor generation moves an individual count
by one or two rows. Monotone, no inversion.)

## 4. The model ladder

Protocol A throughout: `GroupKFold(5)` on the seller × 3 shuffled repeats, pooled out-of-fold,
ridge α chosen by an **inner** `GroupKFold(3)` inside each training fold, one-hot vocabulary,
median fills and z-scaling all refitted per fold. n=602 complete-spec rows / 334 sellers unless
stated.

| model | coverage | R² | MedAPE | residual σ |
|---|---|---|---|---|
| global median (train-fold) | 100% | −0.033 | 53.15% | 0.804 |
| median by gen × tier, k≥3 | 95.5% | 0.907 | 9.86% | 0.234 |
| **median by gen × tier × storage, k≥3** | **85.7%** | **0.909** | **8.80%** | 0.225 |
| median by gen × tier × storage, k≥5 | 78.6% | 0.915 | 8.29% | 0.211 |
| ridge: generation ordinal alone | 100% | 0.862 | 17.65% | 0.297 |
| ridge: + tier ordinal | 100% | 0.913 | 10.55% | 0.235 |
| ridge: + log₂ storage | 100% | 0.917 | 9.59% | 0.230 |
| ridge: per-model dummies | 100% | 0.837 | 10.78% | 0.322 |
| ridge: + battery % | 100% | 0.927 | 10.81% | 0.216 |
| **ridge: FULL (ship candidate)** | **100%** | **0.9373** | **9.95%** | **0.1998** |
| ridge: FULL + colour | 100% | 0.936 | 9.91% | 0.201 |
| ridge: FULL + gen × tier dummies | 100% | 0.934 | 10.50% | 0.205 |
| HGB, ordinal, **fixed** hyperparameters | 100% | 0.906 | 10.07% | 0.244 |
| HGB, FULL, **fixed** hyperparameters | 100% | 0.919 | 10.41% | 0.226 |
| **HGB, FULL, nested-tuned** | 100% | **0.9346** | **9.87%** | 0.2039 |
| ridge + tuned-HGB ensemble (50/50) | 100% | **0.9408** | **9.30%** | **0.1941** |

The ship candidate reads **R² 0.9307 / MedAPE 10.32% / σ 0.214** on all 639 modelled rows. It
serialises to a `linear` manifest of 17 features at **1 177 bytes** of JSON, whose pure-Python
evaluation matches sklearn to 3.6 × 10⁻⁶ and costs 0.0005 ms/ad — negligible against the
extractor's own 0.379 ms.

### 4.1 The correction: "linear beats the tree" is a tuning-budget artifact

The build pass published HGB − ridge ΔR² **−0.0182** (CI −0.0301…−0.0077) and read it as the
first corpus where a linear model wins outright. **It gave the ridge a nested inner-fold α
search and gave the tree one fixed hyperparameter set.** Give the tree the same courtesy — six
configurations, inner `GroupKFold(3)` inside every training fold, identical outer folds:

| comparison | ΔR² | 95% CI | ΔMedAPE |
|---|---|---|---|
| HGB (fixed hp) − ridge | −0.0182 | −0.0301 … −0.0077 | — |
| **HGB (nested-tuned) − ridge** | **−0.0028** | **−0.0099 … +0.0042** | −0.29 pp [−1.42, +0.80] |
| tuning the tree, alone | **+0.0154** | +0.0090 … +0.0232 | — |
| ridge + tuned-HGB ensemble − ridge | +0.0035 | +0.0002 … +0.0071 | −0.83 pp [−1.63, −0.12] |

**Tuning the tree is worth more than the entire published linear-vs-tree gap.** Both CIs on the
corrected comparison straddle zero and MedAPE points the tree's way. The honest sentence is
that **ridge and a nested-tuned tree are statistically indistinguishable on this corpus — the
same verdict as the corrected desktop result** ([`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §5.2,
which already records "tuning the tree is itself worth ΔR² +0.009"), **not a reversal of it.**

This is the same error class that got PC §5.2 retracted — there an encoding asymmetry, here a
tuning-budget asymmetry — caught this time before publication rather than after. The general
rule is one sentence: **compare a searched model only against another searched model.**

Ship the ridge anyway, on the grounds
[`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md) §11 already gives and which are not
about accuracy: it serialises to a 1.2 KB JSON coefficient manifest that evaluates in pure
Python on an ARM64 Pi, and a tree does not. **The ridge is the best *servable* model here, not
the best model** — the ensemble beats it with a CI clear of zero.

### 4.2 Against the config-median baseline

The [`PROMPTS.md`](../backlog/PROMPTS.md) P23 "start with a plain ORM aggregate" baseline, learned on the training
fold only:

| | R² | MedAPE | σ | coverage |
|---|---|---|---|---|
| median by generation × tier × storage, k≥3 (all 639 rows) | 0.908 | **8.84%** | 0.229 | **81.4%** |
| ridge, same 639 rows | 0.9307 | 10.32% | 0.214 | 100% |
| median, on the 520 rows it can score | 0.908 | 8.80% | **0.229** | — |
| **ridge, those same 520 rows** | **0.934** | 9.94% | **0.194** | — |

Paired seller-cluster bootstrap on those 520 rows, ridge − median: **ΔR² +0.0261
[+0.0106, +0.0436]**, ΔMedAPE **+0.99 pp [−0.70, +2.57]**.

**Unlike [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §3.1, where the median was
statistically level and lost only on coverage, here it also loses on the tail** — 18% wider
residual sd, which is the quantity a threshold divides by. It is level on the *typical* listing
and worse on the one an alert reads, and it still cannot score 18.6% of rows or any row of a
generation it has never seen. A backed-off version at 100% coverage (gen|tier|storage → gen|tier
→ gen → global) reads R² 0.8264 / MedAPE 10.62% / σ 0.3362.

**A hybrid is worse than pure ridge**: ΔR² −0.0184 (CI −0.0309…−0.0071). Do not ship one.

### 4.3 What deployment would actually face

MedAPE 9.95% is the protocol-A pooled figure. Under **simultaneous** time and seller
separation — train on the past, test only on sellers never seen — it is **11.5–12.5%** (time
70/30 on unseen sellers, n=148: R² 0.9120 / 12.46% / σ 0.2225; days 1–3 → day 4 on unseen
sellers, n=102: 0.9466 / 11.66% / σ 0.1802). σ is essentially unchanged, which is the number
the alert arithmetic uses, so §7 is unaffected. Note the contrast with MacBook, where the
chronological protocol runs ~+0.02 R² *above* the seller-grouped one because the dealers'
history is known: here only 22.9% of test rows come from a seller seen in training, so there is
no dealer-history advantage to be had.

## 5. The launch window — the premise inverts

The expected confound was that a model trained inside an iPhone 17 launch would be poisoned by
a cohort still price-discovering. **The iPhone 17 is ~12 months old.** Apple ships annually and
the 17 landed in September 2025; the corpus proves it internally three ways:

| instrument | evidence |
|---|---|
| a dated invoice in the listing body | *"Koupeno 19. 9. 2025 přímo na Apple.cz, faktura k dispozici … 94%, 383 cyklů"* — a 17 Pro Max 512 GB at 28 000 CZK |
| battery cycle counts on gen-17 rows | 383, 193, 117, 80, 60, 8, 1, 1, 0, 0 — 383 cycles is not a week old |
| derivatives already in used stock | iPhone 17e (n=5, a ~Feb-2026 model) and iPhone Air (n=8) |

77% of gen-17 rows are used, with real cycle histories, and 37.9% of gen-17 battery claims are
below 100%. **What the window actually straddles is the pre-ship week of the iPhone 18**: zero
units offered, and exactly one mention in 655 listings — a seller giving *"přechod na iPhone 18
Pro"* as the reason for selling their 17 Pro. That is n=1, and it establishes only that the
window sits before a launch ships.

> ⚠️ An earlier pass wrote a caveat saying the window "sits days after the iPhone 17 launch".
> **That is wrong and must not be reproduced.** The contradiction was found and resolved against
> the three corpus-internal instruments above. The same premise would have shipped a fraud
> signal against an entirely honest listing: *"Telefon je starý přibližně 1 rok"* on an iPhone
> 17 is **consistent**, not a lie.

**No time trend is measurable in 3.30 days and nothing should be claimed.** Cluster-robust OLS
(n=589, 324 seller clusters, R² 0.930) puts the day coefficient at **−0.49%/day, 95% CI
−2.41…+1.47** — over a month that is −52% to +55%. Day dummies against day 1 are +3.26%, +1.90%,
−2.07%, all straddling zero. Adding a `days` feature earns nothing: ridge ΔR² **−0.0004**
(CI −0.0007…−0.0001). That is a second data point for the
[`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §5.2 warning rather than a contradiction of it — there
a `days` feature carried a tree's entire apparent edge by encoding collection history; on a
3.3-day corpus there is no history to encode, so it is simply noise. And when a corpus is three
days long, composition drift is the live alternative hypothesis: inside gen 17 the sealed share
went 29.7% → 22.2% → 26.9% → 13.8% while the Pro Max share went 29.7% → 44.8% over the same four
days.

### 5.1 The real risk is the encoding, not a time-varying intercept

Hold out a whole generation and score it with **frozen one-hot generation levels** — the shape
the shipped MacBook manifest uses — against a **live `gen_age_m`** numeric the extractor computes
at scoring time from a launch-date table:

| held-out gen | n | frozen: bias | frozen: MedAPE | frozen: −25% flag rate | live: bias | live: MedAPE | live: flag rate |
|---|---|---|---|---|---|---|---|
| **17** | 129 | **under-prices by 73.8%** | **74.2%** | **0.0%** | −3.1% | 10.1% | 4.7% |
| 16 | 78 | under-prices by 68.5% | 68.5% | 1.3% | +2.5% | 9.0% | 3.8% |
| 15 | 100 | under-prices by 57.7% | 57.7% | 0.0% | +1.7% | 10.6% | 6.0% |
| 13 | 112 | under-prices by 26.0% | 26.0% | 2.7% | +0.8% | 14.3% | 9.8% |
| 11 | 37 | **over**-prices by 26.0% | 43.3% | **64.9%** | +5.5% | 11.3% | 8.1% |

**The failure is silent and asymmetric, and that is what makes it dangerous.** An unseen *new*
generation is under-priced by three quarters and therefore **never alerts at all**; an unseen
*old* generation is over-priced and alerts on two thirds of its rows. Neither looks like an
outage. Swapping in `gen_age_m` costs nothing in-sample (ΔR² +0.0040, CI −0.0042…+0.0117 — if
anything better) and needs **no manifest-schema change**: `num` already multiplies a float, and
`bazos/pricing/features.py` already reads `date.today()` for `_MAX_MODEL_YEAR`.

A **youth gate is a measured pure loss**: declining generations younger than 12 months drops 21%
of the corpus, makes residual sd *worse* (0.252 → 0.269) and removes 4 of 54 flags — because the
newest generation is the best-modelled one in the corpus (gen 17 residual sd 0.178, the tightest
of any generation with n>50, flag rate 3.1%; the 17-family is **depleted** in the underpriced
tail at 0.35×). **The gate should key on an UNKNOWN generation, not a young one** — "the
extractor resolved a model number my launch table has never heard of" is one `if`, costs
nothing, and fails closed on exactly the day it matters.

**This is the M5-chip failure one level up.** `APPLE_CHIP = r'\bm([1-4])\b'` made every M5
MacBook invisible to the extractor ([`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md)
§3.1); a frozen generation vocabulary makes every iPhone 18 invisible to the *model*, on the day
the 18 ships, with the most expensive phones on the market landing in the bucket the model is
least able to price. [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §8 is the same shape a
third time: a product with no comparables produces large residuals and the model cannot tell
"underpriced" from "unpriceable".

Staleness is then a backstop rather than the mechanism. Applying the cross-sectional gradient
(−2.34%/month at generation age 12 months, t=−12.8, flat across the ladder) to a manifest nobody
retrains: gated −25% goes 41/wk fresh → 61/wk at three months → 99/wk at six → ~273/wk at twelve,
at which point the rule calls roughly a quarter of the feed a deal. **A 3.30-day window can
bound that decay only by the cross-section, never measure it** — the direction is certain, the
rate is not.

## 6. Segments, and where sigma comes from

**The MacBook seller-maturity ladder does not replicate.** Residual σ by a production-shaped
`seller_prior_ads` proxy:

| seller prior ads | 0 | 1–2 | 3–9 | 10–49 | 50+ |
|---|---|---|---|---|---|
| iPhone σ | 0.232 (n=303) | **0.253** (104) | 0.137 (61) | 0.184 (148) | 0.090 (23, one seller) |
| MacBook σ (shipped ladder) | 0.3129 | 0.2993 | 0.2414 | 0.1872 | 0.1129 |

**The 1–2 bucket is wider than the never-seen bucket**, and the 10–49 bucket — a quarter of the
corpus — is wider than both. Three independent cuts agree it is non-monotone. 80.3% of the
modelled set's sellers are one-offs, so this is the desktop situation
([`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §3), not the MacBook one, and
[`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §5.7's "if only one piece is built, build
this one" does not transfer. Borrowing MacBook's monotone ladder rather than fitting one is not
conservative, it is arbitrary — on identical residuals it moves alert volume by **32%** in a
direction nobody chose.

Sigma keys on spec completeness instead — but with an honest error bar the build pass did not
attach:

| bucket | n | sellers | σ | seller-cluster 95% CI | −25% in σ |
|---|---|---|---|---|---|
| complete spec + battery stated | 363 | 200 | 0.1755 | [0.1567, 0.1955] | 1.64 [1.47, 1.84] |
| complete spec, battery not stated | 239 | 147 | 0.2316 | [0.1802, 0.2813] | 1.24 [1.02, 1.60] |
| storage not parsed | 37 | 34 | 0.3708 | [0.2516, 0.4557] | 0.78 [0.63, 1.14] |

**Buckets 2 and 3 overlap heavily and the bottom bucket is 37 rows.** Its interval places −25%
anywhere from ordinary noise to mildly unusual. The completeness ladder is directionally right
and better behaved than the maturity one; it is **three point estimates with overlapping
intervals, not a calibrated ladder**, and a shipped manifest should say so.

Other segments worth carrying (ridge FULL, protocol A OOF, n=639): by tier, pro max σ 0.176 /
pro 0.188 / base 0.215 / mini 0.222 / **SE 0.385, the worst rung in the corpus** (n=23, and its
CI clears pro max's, so that one survives its n). Air (n=7) and Plus (n=13) do **not** survive
theirs and nothing about them should be quoted. By price band, MedAPE runs 17.2% below 5 000
CZK, 8.7% at 5–10k, 10.8% at 10–20k, 9.9% above 20k.

### 6.1 Battery health is real, confounded, and commercially near-dead

Battery % correlates +0.270 with log price and is worth **+3.26%/point on its own** — but
stated batteries are good batteries and old phones are cheap phones, so the marginal figure is
part composition. Under generation fixed effects it survives at **+1.27%/point, CI
[+0.69, +1.62]**, clear of zero, and generation explains only R² 0.076 of `battery_pct`. The
missingness itself is informative: "battery not stated" is worth **−9.1%** (CI −14.7…−3.4).

**Two things qualify it.** The proposed manifest's coefficient is **+0.58%/point — under half
the within-generation estimate**, which is what a marginal fit on a ceiling-censored,
self-selected sample produces (45.3% of stated values are exactly 100%, minimum stated 70%).
And it is **near-dead where it matters commercially**: for generation ≥17 the stated values have
sd 2.24 and **64% sit at exactly 100%**, so on the most expensive phones in the feed the feature
carries almost no variation to price with.

One MacBook coefficient fails to replicate and the failure is instructive: "new battery predicts
a *lower* price, −15.8%" ([`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md) §8.4) is
**−3.0% (CI −14.2…+10.3)** here. The raw marginal is −44% and it is pure composition — batteries
get replaced on old cheap phones. Measure every condition flag's sign *conditionally*.

## 7. The alert — the part that does not work

An independent audit reproduced the study headline exactly (R² 0.9373, MedAPE 9.95%, σ 0.1998,
n=602 / 334 sellers) and then attacked the alert. The gate is: generation + tier + storage all
parsed, no damage or scratch vocabulary, above the 1 000 CZK query floor. **79.2% of modelled
rows pass it.**

| threshold | in σ | ungated | gated | gated /week @150 ads/day |
|---|---|---|---|---|
| −15% | 0.81 | 93 (14.55%) | 60 (9.39%) | 98.5 |
| −20% | 1.12 | 62 (9.70%) | 38 (5.95%) | 62.7 |
| **−25%** | **1.44** | 45 (7.04%) | **25 (3.91%)** | **41.3, seller-clustered CI [22.6, 63.0]** |
| −30% | 1.78 | 38 (5.95%) | 22 (3.44%) | 36.3 |
| −40% | 2.56 | 16 (2.50%) | 11 (1.72%) | 18.1 |

At the window's own observed 193.7 ads/day that is **53.1/week**. Against the reference points:
**12.9× MacBook's 3.2/week, and even the CI lower bound is 7.1×. It is 2.2× worse than the
desktop query's 18.5/week, which [`PC_PRICE_MODEL.md`](PC_PRICE_MODEL.md) §7.2 already judged
unusable.** Note the mechanism: the threshold is a *sharper* instrument here than on MacBook
(1.44σ against 1.15σ) and the alert is still far worse, because query 19 runs at ~6× the arrival
rate and fires at 2.6× the rate per ad. **Discrimination is not the binding constraint; volume
is.**

### 7.1 Going deeper makes precision worse, monotonically

This is the finding that refutes the remedy the build pass proposed (route deals to a dedicated
alert at z ≤ −3.0). Classifying every gated flag at each depth:

| threshold | n | bait / scam | clean candidates |
|---|---|---|---|
| −25% gated | 25 | 5 (20%) | 2 |
| −30% gated | 22 | 5 (23%) | 2 |
| −40% gated | 11 | 4 (36%) | **0** |
| z ≤ −2.5 | 11 | 5 (45%) | **0** |
| **z ≤ −3.0** (the study's own recommendation) | **6** | **3 (50%)** | **0** |
| top 5 by residual | 5 | 3 (60%) | 0 |

**The mechanism generalises well beyond iPhones: a fraudulent price is bounded only by what gets
clicks, while a genuine bargain is bounded below by the seller's own option of selling at
market.** So the deeper the tail, the larger the share of it that is structurally not a real
ask. Every "tighten the threshold until the volume is readable" instinct in this project runs
into that, and on this corpus it runs out of clean candidates before it runs out of volume.

Two flags, verbatim, to make the shape concrete:

- **id 24260** — `IPhone 17 pro 256gb`, **7 000 CZK against a 20 646 prediction** (z −4.67),
  peer median 25 490 over 51 same-config peers. The body: *"Bohužel mě při jídle na telefon
  spadly zákusky a odmítám utírat tu špínu"* — pastries fell on the phone during dinner and the
  seller refuses to wipe the filth off.
- **id 24845** — `Apple iPhone 17 Pro Max 256 GB – Cosmic Orange`, described as new and sealed,
  **14 600 CZK against a peer minimum of 25 000** over 27 peers. A one-ad account, three views,
  and its delivery status is **SENT** — it reached Discord.

Composition of all 25 gated −25% flags (19 distinct sellers, 23 distinct listings):

| bucket | n / 25 | base rate | enrichment |
|---|---|---|---|
| **bait / scam / not a real ask** | 5 (20%) | 0.78% | **25.6×** |
| dealer low-end price level | 5 (20%) | 41.3% | 0.5× |
| thin-rung over-prediction (comps disagree) | 5 (20%) | 8.3% | 2.4× |
| a defect the gate misses | 4 (16%) | 4.1% | 3.9× |
| duplicate relisting | 2 (8%) | 4.23% | 1.9× |
| no usable text | 2 (8%) | — | — |
| **genuinely cheap candidate** | **2 (8%)** | — | — |

**The dominant failure class is new: bait, at 25.6× its base rate.** It does not appear in the
MacBook or desktop studies, where the tail was broken machines and parse failures. On a phone
market the underpriced tail is made of listings that are not real asks — a joke, two ads from
one seller carrying an "email me your offer" price anchor, a sealed current flagship at 52% of
the cheapest peer. **A damage gate does not reach any of them**, and neither does a deeper
threshold.

### 7.2 The low prices are real — they are just not bargains

The build pass never checked its flags against the market directly, only against its own model.
Doing it model-free: **18 of the 22 flags that have ≥3 same-config peers from other sellers are
also ≥25% below that peer median.** So the residuals are not an artifact of a mis-fitted line —
these listings genuinely ask far less than identical phones. That is precisely why the
composition table above is the decision-relevant one rather than the funnel: the question was
never whether the model finds cheap listings.

### 7.3 Three more things the audit changes

- **The battery coefficient in the proposed manifest is under-fitted.** +0.58%/point against a
  within-generation estimate of +1.27%/point, CI [+0.69, +1.62] (§6.1).
- **Repricing moves the answer more than any threshold does.** Re-scoring the flags against
  their current prices removes **4 of the 25**, including the best clean candidate — clean falls
  from 2/25 to **1/22**. This is [`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md)
  §5 (a stale score survives a price change) measured on the alert it damages.
- **Three heuristics that look obvious are dead or backwards here.** `usa_region` fires on
  **0.00%** of modelled rows. Of 7 multi-unit matches, **6 are false positives** (`2ks obalu` is
  two *cases*). And of the 5 rows matching iCloud/carrier-lock vocabulary, **all 5 are
  denials** — *"telefon není blokovaný"*. **Zero rows in 655 admit to being locked**, which is
  the worst possible shape for a gate: a locked phone is priced low, reads as a bargain, and
  nothing in the text can see it.

## 8. Assessment — what to do

**Register the artifact. Do not enable the rule. Do not route it to a dedicated alert either.**

1. **Registering is safe and changes nothing by itself.** Query 19's `filter_rule_names` is
   empty, which `build_rule_engine` resolves to `DEFAULT_RULE_NAMES`
   (`bazos/filters.py:358, :385`; cited as `:354, :363` when this was written, before
   `register_rule` landed above them), and that list is *everything except* `price_model`. Scoring
   only happens inside `PriceModelRule.apply`, so a registered `iphone` artifact scores nothing
   and writes no `AdPriceScore` rows until someone edits that field by hand. **That is the
   correct safe state and it should be left in it.**
2. **Do not add `price_model` to query 19.** Production runs `PRICE_MODEL_SHADOW_MODE=false`
   ([`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md) §12) and the rule is
   **inverted** — it REJECTs anything it does not consider a deal. At the gated −25% operating
   point that is **~96% of a 150-ads/day feed rejected overnight**. (`location_distance`, at
   30 km around 11000, currently rejects 62.5% of query 19's filtered deliveries and runs
   first — that bounds the blast radius, but it is an unrelated admin setting, not a safety
   property, and it disappears the day someone widens the radius.)
3. **Do not route deals to a dedicated alert query at z ≤ −3.0.** That recommendation rests on
   six listings, whose weekly rate is known only to within a factor of 6.6 (9.9/wk, CI
   [2.9, 19.2]) — and §7.1 measures that at that depth, three of the six are bait and none is a
   clean candidate. On a deals-only query where `filter_rule_names` is just `price_model`,
   all-PASS means **APPROVE**, so the failure mode there is a firehose, not silence
   ([`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md) §7).
4. **Prerequisites, unchanged and still binding.**
   [`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md) §13 items 1–4 are written as
   prerequisites for *any* second model and this is that second model: `marketplaces` on the
   protocol plus a registry test (§8); a **per-model artifact version** (§7 — one global
   `PRICE_MODEL_VERSION` means pinning MacBook silently disables iPhone); both `AdPriceScore`
   read paths keyed by `model_name` (§9); and a test that loads the real shipped artifact (§11).
   Before *enabling* anything, add §4's query-floor gate and §5's one-line
   `refresh=delivery.status == AdStatus.PRICE_CHANGED`. The registry collision §8 warns about
   does **not** bite this pair on measurement — `MacbookPriceModel.applies_to` claims 0 of 655
   query-19 ads, and an iPhone rule claims 1 of 2 854 query-8 ads — but that measurement is a
   property of the 254-character preview: in query 8's *full* text the cross-family token appears
   20× more often (2.5% against 0.1%), so the exclusivity fix must land **before** anyone turns
   `load_full_description` on.
5. **Two model-side decisions the evidence settles.** Carry generation as a live `gen_age_m`
   numeric rather than frozen levels (§5.1), and decline on an *unknown* generation. Key σ on
   spec completeness, never on the MacBook maturity ladder (§6), and record the overlapping CIs
   alongside the point estimates.

**The honest operational claim is narrow: the model can be built, and its threshold cannot be
calibrated until outcome data exists *and is calibrated*.** Every figure in §7 says what the
flagged listings *are*, never what they were worth. [`PROMPTS.md`](../backlog/PROMPTS.md) P24
shipped on 2026-09-17 and made disappearance observable (`Ad.removed_at`), but a disappearance
is not a sale, and until `AdOutcome` carries rows saying how often it is one, an
`AdPriceScore` back-history has nothing to be calibrated *against*. That back-history is still
worth accumulating; it still does not buy a threshold. ⚠️ Note that accumulating it is no
longer what shadow mode does here: production runs `PRICE_MODEL_SHADOW_MODE=false` (point 2
above), so on a query that names `price_model` the rule scores *and rejects*.

## 9. Limits

- **The window is the binding limit and it is four calendar dates.** 2026-09-09 → 09-12,
  **Wednesday to Saturday, with no Sunday and no Monday in it**, of which day 1 carries a
  132-row backfill pass. Day-of-week variation is therefore **zero-measured, not
  zero** — [`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §7 finds listing volume is a
  Friday–Saturday business on a corpus long enough to see it. Daily gated flag counts are
  **5 / 9 / 7 / 4**, which is all the week-to-week stability evidence that exists.
- **Nothing here measures depreciation, seasonality or a price trend.** The +28.1%/release-year
  gradient (and the −2.34%/month restatement of it) is a **cross-section across generations
  4→17 read on one day**. It cannot separate "a phone loses 22% a year" from "the 2019 cohort is
  permanently cheaper". Resolving a −2%/month trend at 2 SE needs ~32 days and ~5 700 ads.
- **n=25 is the entire evidence base for the composition claim**, and a single-row
  reclassification moves it by 4 pp. The audit's "2 clean candidates" and the build pass's "0
  clean" are **not statistically distinguishable**; what *is* distinguishable is the monotone
  rise of bait with depth (§7.1), because that is a trend across five nested thresholds rather
  than one count.
- **Every classification rests on truncated text.** `load_full_description` is off for query 19,
  62.6% of previews end in the 254-character truncation marker, and **9 of 20 audited rows end
  in "…"**. A defect, a lock or a bait phrase past the cut is invisible to the audit exactly as
  it is to the model.
- **The comparables check in §7.2 is within-corpus.** "≥25% below the peer median" means below
  the median of other query-19 listings of the same generation, tier and storage in the same
  four days — not below a market price established anywhere else.
- **The extractor was written on these same 655 rows**, so both the coverage figures and the
  covered-set R² are optimistic with respect to it. A chronological-half test shows the *data*
  does not drift much (storage 95.3% → 93.1%, 4.3% novel title tokens), but that measures the
  data, not the regex design, and the distinction cannot be closed retroactively. The 40-row
  hand audit supports "no error found", not a rate.
- **σ was computed on the same out-of-fold predictions used to select the feature set**, and no
  conformal check was run — [`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md) §9's
  naive-versus-conformal comparison has not been reproduced for this corpus.
- **Tier and generation are near-collinear** in a market where newer models skew higher-tier, so
  the split of credit between +28.5%/generation and +11.1%/tier is not independently identified.
  The joint prediction is sound; a single coefficient quoted alone is not.
- **The "bait" verdicts are a reading of Czech listing text**, not verified facts about sellers.
  Five listings share a shape — an implausible price for a current flagship, an
  offer-solicitation template, a joke — and nobody contacted anyone.
- **One proposed manifest coefficient is fitted on almost nothing.** `vat_dph` (+21.4%) fires on
  seven rows from five sellers, four of which are the same iPhone 17 Pro 256 GB and three of
  which are one dealer. That is a "dealer flagship" coefficient wearing a VAT label, and the
  build pass's own "<1.2% of rows" trim rule would have removed it at 1.10%. `swap` (n=19,
  8 sellers) has a CI straddling zero.
- **The backfill shapes the corpus in a way that can be characterised but not corrected.** TOP
  ads are 64.4% of the backfill pass against 11.6% of steady state, because the dedup
  break-streak excludes TOP rows — so the first pass harvests every promoted listing on the
  pages it walks and later passes never see them again. Any corpus assembled this way carries one
  paid-promotion cohort at the front. Dropping it makes the funnel *worse*, not better (gated
  −25% fires on 4.54% of steady-state rows against 3.91% pooled), so §7 is ~15% optimistic in the
  direction that reinforces its own conclusion.

## 10. Reproduction

Read-only against the production Postgres over SSH; nothing was written. The corpus is
**deliberately not committed** — it carries seller names and publisher ids, the same rule
[`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §9 states — and this document is the durable
artifact.

The shared protocol is [`experiments/price_model/common/ph.py`](../../experiments/price_model/common/ph.py):
`grouped_cv()` is the only protocol whose output should be quoted for model comparison, and
`cluster_bootstrap_delta()` produces every CI here. The scripts sit in
[`experiments/price_model/iphone/`](../../experiments/price_model/iphone/) under the same
throwaway convention as the rest of [`experiments/price_model/`](../../experiments/price_model/)
— excluded from ruff and mypy, needing `poetry install --with ml`, and carrying absolute paths
from the scratchpad they were written in, so expect to fix a path or two before anything runs:

| script | what it does |
|---|---|
| `ipfeat.py` | the extractor of §3 — stdlib only, kind classification, generation/tier/storage, battery, condition and seller flags. Its module docstring carries the five load-bearing traps and is the durable artifact, the way `bazos/pricing/features.py`'s is |
| `lib.py` | protocol A/B with nested α and **all** preprocessing inside the fold — the harness every figure in §4 and §6 is measured on |
| `b01_build.py`–`b09_sigma.py` | §4 and §6 — the ladder, segments, the funnel, coefficients, protocol B, the paired bootstrap, the hybrid test and the σ sources |
| `k01_build.py`–`k10_final.py` | §7 — the funnel with seller-clustered CIs, the depth table, the 25-flag classification, the battery re-estimate and the model-free comparables check |

Three further pieces were **not** carried over and must be re-derived rather than re-run: §3.1's
ordinal-versus-dummies and leave-one-generation-out scripts, §5's launch-window and staleness
scripts, and §2.1's sampler audit. All three are short and all three are described in enough
detail above to rebuild.

Three things are worth re-deriving rather than re-reading: **§3.1's ordinal-versus-dummies
result**, because it is the design decision a second category study will want to copy; **§4.1's
equal-tuning-budget comparison**, because getting it wrong is how a finding gets retracted; and
**§7.1's depth table**, because it is the only measurement in this project that contradicts the
obvious remedy for a noisy alert.

Corpus pull — delivery-level, one row per `(ad, query)`:

```sql
COPY (
  SELECT d.query_id, a.id, a.created, a.external_id, a.url, a.name, a.price_raw, a.price,
         a.price_type, a.location, a.view_count, a.publish_date, a.topped,
         a.short_description, a.full_description, a.publisher_name,
         a.email_publisher_id, a.phone_publisher_id, a.marketplace, d.status
  FROM bazos_ad a JOIN bazos_addelivery d ON d.ad_id = a.id
  WHERE d.query_id IN (8, 19)
) TO STDOUT WITH CSV HEADER;
```

The pull is **unfiltered by `AdDelivery.status`** and that is load-bearing: query 19's 655 rows
are 194 `SENT`, 336 `REJECTED` and 125 `SUPPRESSED`, so a SENT-only frame would model the filter
rather than the market ([`CATEGORY_PRICE_MODELS.md`](CATEGORY_PRICE_MODELS.md) §10).
