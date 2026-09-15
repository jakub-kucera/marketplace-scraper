---
title: Desktop PC price prediction — feasibility on the Počítače corpus
status: reference
updated: 2026-09-12
verified: 2026-09-12
---

# Desktop PC price prediction — feasibility on the Počítače corpus

> Written 2026-08-29 from a read-only pull of query 9 (`PC, Počítače`, no text): **1 668 ads,
> 2025-12-13 → 2026-08-29**. Research and local experimentation only — nothing here is wired
> into the pipeline.
>
> **Re-measured 2026-09-12 at 2 856 ads**, same query, read-only from the same CSV export.
> Four things changed and one was withdrawn. (a) **§5.2 is retracted** — the published
> linear-vs-tree gap measured a design-matrix error, not a model class (§5.2). (b) The corpus
> is **not** 273 days of history: it is 45 collection dates in two blocks 214 days apart, under
> two different query price floors, and every decision below rests on block B (§2.1). (c) P27
> item 1 (re-measure extraction once full descriptions accumulate) **arrived early and is
> answered**: storage clears its gate, GPU+CPU+RAM does not (§4.1). (d) An audited extractor
> repair is worth more than the model-class choice, again (§4.4), and a new §7 prices what a
> desktop deal alert would actually cost.
>
> The question was whether the MacBook work ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md))
> transfers to desktops. It partly does, but this is a **harder problem for reasons that are
> about the market, not the method** — and after re-measurement, about the *threshold*, not the
> model.
>
> Standing caveat on every figure below: **`Ad.modified` never advances past `Ad.created`, so the
> database records ZERO outcomes** — no sold flag, no time-to-disappear. Every precision number
> here is a composition audit plus a cross-validated fit statistic, never a measurement of whether
> a flagged listing was a deal ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md) §6, restated
> with its consequences in §8).

## 1. Summary

| Question | Answer |
|---|---|
| Is a desktop a different market from a MacBook? | **Yes, and more so than in August.** 1 336 sellers for 2 447 desktops, 77.5% of them appearing exactly once; DPH vocabulary 2.0% against 32% on MacBooks |
| Is this 273 days of history? | **No. 45 collection dates in two blocks 214 days apart**, under two different price floors and two different text budgets. Pool them and you average two markets (§2.1) |
| Can specs be extracted from listing text? | Much better than published, after an audited repair: on block B storage **39.0% → 66.1%**, CPU 84.9%, GPU 68.1%, all four 46.7% (§4.1) |
| Does P27's coverage gate pass? | **Half of it.** Storage clears the ~60% bar for the first time (66.1%); GPU+CPU+RAM is **58.4% against ~70%** and clears only on block B × full description × ≥10 000 CZK (81.4%, n=505) |
| Is "linear is not sufficient here" still true? | **No — §5.2 is retracted as unsafe.** A correctly encoded ridge closes the published 3.7 pp gap on the study's own rows; the encoding is worth four to six times it, and what the published run actually ran is unrecoverable from the repo. Corrected, equal effort: ridge 0.868 / 14.63% vs nested-tuned HGB 0.886 / 13.27% (n=1 284), ΔR² +0.018 (CI +0.004…+0.035) |
| Is price predictable on the gate that would be used? | R² **0.806 / MedAPE 13.2%** (tree) and 0.747 / 16.4% (linear) on 4/4 specs + no damage + ≥10 000 CZK, n=634 — against the shipped MacBook artifact's 8.71% on the rows it actually scores |
| Would the shipped −25% threshold work here? | **No.** −25% is **0.97σ** on that gate against **2.92σ** for a MacBook dealer, and fires **18.5×/week**. `z ≤ −2` is a 45% discount and ~3/week (§7.3) |
| What is actually in the flagged tail? | Of the top 12 gated flags: **6 extraction failures, 1 bait listing, 4 over-predictions, at most 1 candidate deal** (§7.4) |
| Does a name→spec lookup help? | **No — still redundant** (§6, not re-measured). But *stated* VRAM is the strongest single GPU feature (+11.4% per 4 GB), which qualifies §4 |
| Ship it? | **Shadow-ship a gated linear artifact. Do not enable the rule. Do not ship a flat −25% threshold at all** (§8) |

## 2. The corpus is not one market

`kind` is inferred from the title and description. Three extractor generations are compared
throughout this document and it is worth fixing the names once:

- **v1** — [`experiments/price_model/pc/pcfeat.py`](../../experiments/price_model/pc/) as
  committed, the extractor the published figures were measured on.
- **v2** — an afternoon of regex widening during the re-measurement. Not carried forward; §4.4
  says why.
- **v3** — the audited repair. Scratch code, not committed, not the shipped serving path.

| kind | published (n=1 668) | v1 (n=2 856) | v3 (n=2 856) | what it is |
|---|---|---|---|---|
| `desktop` | 1 411 | 2 447 | **2 281** | the actual subject |
| `apple_desktop` | 127 | 218 | 216 | iMac / Mac mini / Mac Studio — a different price curve, and they almost never name a discrete GPU |
| `laptop` | 116 | 168 | 167 | notebooks posted in the desktop category |
| `server` / NAS | — | — | **84** | new class: PowerEdge, ProLiant, Synology, Xeon Gold, ECC. v1 calls all 84 a desktop |
| `aio` | — | — | **40** | new class: all-in-ones that are not Apple |
| `not_pc` | 13 | 22 | 61 | ASIC miners, retro Amiga/Spectrum, consoles, Raspberry Pi, POS terminals |
| `wanted` | — | — | **6** | a `koupím` ad is not a machine for sale — and it is where `nefunkční` lives |
| `monitor` | 1 | 1 | 1 | |

**Not-a-desktop is 20.1% of the category** (575 of 2 856) against the 16% published. The
`server` and `wanted` classes are new only in the sense that the old 10 000 CZK floor hid
them; v1 silently prices a 768 GB ECC Xeon as a gaming tower. Any model here has to classify
first, and the classifier has to be re-audited whenever the query's price bounds move.

### 2.1 …and it is not 273 days of history

This is the correction that governs every other number, and the opening blockquote of the
published version implied the opposite.

| | block A | gap | block B |
|---|---|---|---|
| dates | 2025-12-13 … 2026-01-05 | 214 days, zero ads | 2026-08-22 … 2026-09-12 |
| collection dates | 21 | — | 22 |
| ads (all kinds) | 452 | — | 2 402 |
| minimum observed price | **10 000 CZK** | — | **1 800 CZK** |
| rows with a full description | **0.0%** | — | **57.0%** |
| sd(log price) | **0.386** | — | **0.927** |
| median price | 18 000 CZK | — | 14 500 CZK |

45 distinct collection dates in total (21 + 22, plus two stray rows dated 2026-08-07 and
08-11 — whether "block B" starts at 08-07 or 08-22 moves n by two and nothing else).
A further 916 of block B's 2 402 ads arrive on **2026-08-24 alone**: a backfill burst, not a
day of market activity.

Three consequences, all load-bearing:

- **Never compare R² across the two corpora.** sd(log price) went from 0.386 in block A to
  0.927 in block B because the query's own `price_lower` fell — 31.7% of block B is priced
  below the old floor. R² rises when the target spreads out even if nothing about the model
  improved, which is exactly what happened between the published 0.635 and the re-measured
  0.788 on the same features.
- **Pooled coverage averages two incomparable regimes.** Block A parses GPUs *better*
  (84.3% against block B's 68.1%) purely because a 10 000 CZK floor excludes the office boxes
  that have no discrete card to name. Read that as "the old floor hid a stratum", never as
  "the parser used to be better".
- **Any per-week rate divided by the 273-day calendar span is wrong by ~14×.** Steady state
  (2026-08-27 onward, after the floor settles and the backfill ends) is 472 desktops/week
  against the ~5.4/day the published version measured.

This is the same event the MacBook artifact work identified as the way a shipped price model
silently mis-calibrates: the training support moves because a query's bounds were edited in the
admin, and nothing records it. Query 9 has now done it too, inside its own study window. **A
desktop artifact must record the price support it was trained on**, or the next floor edit
re-runs this whole confound in production instead of in a notebook.

## 3. Market structure — the opposite of the MacBook corpus

| | Desktops, published (n=1 411) | Desktops, now (v1, n=2 447) | MacBooks |
|---|---|---|---|
| ads / sellers | 1 411 / **848** | 2 447 / **1 336** | 2 038 / 499 |
| median ads per seller | **1** | **1** | — |
| share from top 10 sellers | 16.5% | **14.1%** | **56%** |
| sellers appearing exactly once | 49.6% ¹ | **77.5%** | — |
| ads from one-off sellers | 49.6% ¹ | 42.3% | 21% |
| ads mentioning DPH / faktura | — | **2.0% / 7.0%** | 32% |
| residual σ, all rows | 0.398 | 0.452 (HGB, v3, block B) | 0.20 |

¹ the published row did not distinguish the two figures; the current values bracket it.

The market got **more** private, not less — the lower floor imported office refurbs and private
one-offs, and the top-10 concentration fell further. This inverts the central finding of the
MacBook work. There, two thirds of apparent underpricing was persistent dealer pricing and the
fix was a per-seller baseline. Here there is **no seller history to build a baseline from**.

> ⚠️ A between/within-seller variance decomposition returns **89.9%** on this corpus, and it is
> still **meaningless**: a singleton seller has zero within-variance by construction. Restricted
> to sellers with ≥3 ads (n=1 050, 133 sellers) it is 80.4%, still inflated. Neither number is
> comparable to the MacBook 67% and neither should be quoted.

The seller-aware z-score from `MACBOOK_PRICE_MODEL.md` §5.7 therefore **does not transfer**.
Sigma has to come from listing characteristics — chiefly spec completeness — and §5.1 now
measures that it does.

One methodological note that distinguishes this corpus from the thinner queries: the seller key
is populated on **100%** of desktop rows (email or phone publisher id, never a per-row-unique
fallback), so `GroupKFold` here is a real grouping. But with 77% singletons it is close to
plain `KFold`, so "held-out shop" is a milder test here than the same words mean on the
dealer-heavy MacBook corpus.

## 4. Extraction

Titles are unusually spec-dense — `Herní PC | Ryzen 7 5800x, RX 6700 XT, 32GB, 1TB SSD` is
the house style — and the vocabulary is standardised: **116 distinct GPU tokens and 300 CPU
tokens** over the v2 pass's 2 336 desktops (the published figures were 140 and 271 on 1 411).
The tail is thin either way: 44 of the 116 GPU levels and 150 of the 300 CPU levels appear
fewer than three times, which is why rare-level pooling is not optional here (§9).

**The design decision worth keeping: GPU and CPU tier and generation are parsed out of the
model name, not looked up.** `rtx 3070` already encodes vendor, generation (30) and tier (70)
positionally, and the naming has been stable for a decade, so an ordinal feature falls out
with no table to maintain. Measured on complete-spec rows in the published study:

| GPU encoding | R² |
|---|---|
| name-derived tier + generation ordinal | **0.515** |
| one dummy per GPU model | 0.370 |
| both together | **0.628** |

The ordinal beats per-model dummies because it **interpolates to models never seen in
training** — with 116 models over 2 300 ads a dummy for an unseen card is just the intercept.
§6 adds one qualification the 2026-08 run could not see: it is *stated VRAM*, not the tier
step, that carries the GPU's price signal once both are in the design.

### 4.1 Coverage — P27 item 1, answered

First the pure extractor delta, with the population held fixed at v3's 2 281 desktops so that
reclassification cannot flatter the repair:

| field | v1 | v2 | **v3** | v3 − v1 |
|---|---|---|---|---|
| CPU model | 79.9% | 85.0% | **84.8%** | +5.0 pp |
| RAM | 81.1% | 81.1% | 80.4% | **−0.7 pp** |
| GPU model | 69.5% | 70.9% | **70.8%** | +1.2 pp |
| GPU known (model, pro, or a stated absence) | 70.3% | 74.8% | **74.4%** | +4.1 pp |
| DDR generation | 44.6% | 44.6% | 44.8% | +0.1 pp |
| GPU VRAM | 27.7% | 27.7% | **38.3%** | **+10.6 pp** |
| **Storage** | 54.4% | 64.1% | **65.3%** | **+10.9 pp** |
| GPU + CPU + RAM | 55.9% | 60.6% | 59.9% | +4.0 pp |
| **all four** | 36.8% | 45.8% | **47.5%** | **+10.7 pp** |

**A coverage *drop* can be a correctness gain.** v3's RAM is 0.7 pp below v1's: on 40 audited
rows where the two disagree, v3 is right in 34, unverifiable in 5, and arguably worse in 1 —
v1 was systematically reading a card's VRAM (`rtx 5060 ti 16gb` → 16 GB of system RAM) and SSD
capacities as memory. Never read a coverage delta for a field without auditing the rows where
the two versions disagree.

Now the same extractor split by block, which is the table a decision must rest on:

| field (v3) | pooled | block A | **block B** | B + full desc | B, no full desc | B + full + ≥10k |
|---|---|---|---|---|---|---|
| n (desktops) | 2 281 | 375 | **1 904** | 1 090 | 814 | 505 |
| CPU model | 84.8% | 84.5% | 84.9% | 87.5% | 81.3% | 91.3% |
| RAM | 80.4% | 77.3% | 81.0% | 90.7% | 67.9% | 94.9% |
| GPU model | 70.8% | 84.3% | 68.1% | 65.5% | 71.5% | 85.7% |
| DDR | 44.8% | 30.1% | 47.6% | 56.9% | 35.1% | 74.9% |
| GPU VRAM | 38.3% | 28.5% | 40.2% | 46.9% | 31.2% | 59.6% |
| **Storage** | 65.3% | 61.3% | **66.1%** | **83.4%** | 43.0% | 88.7% |
| **GPU + CPU + RAM** | 59.9% | 67.5% | **58.4%** | 62.3% | 53.1% | **81.4%** |
| all four | 47.5% | 51.5% | 46.7% | 58.1% | 31.6% | 75.6% |

**P27's gate, in its own terms**: *"if GPU+CPU+RAM coverage clears ~70% (from 51.9%) and storage
clears ~60% (from 39.0%), the completeness gate stops throwing away most of the corpus and a
shadow-mode deployment becomes arguable. If it does not move, the honest answer is that desktop
listings simply do not state enough, and this line of work should stop."*

Answered on block B: **storage PASSES for the first time (66.1% ≥ 60%)** and **GPU+CPU+RAM
still FAILS (58.4% against ~70%)**. It clears only on block B × has-full-description × ≥10 000
CZK — 81.4%, n=505. So neither branch of P27's rule fires cleanly: the line of work does not
stop, and the deployment is arguable only on a scoped segment, which is what §7 prices.

Block B v1 → v3 for the record, since the repair and the corpus growth are separable and both
happened: storage 55.1 → 66.1% (+11.0 pp), GPU VRAM 28.6 → 40.2% (+11.6 pp), CPU 79.4 → 84.9%
(+5.5 pp), all four 35.5 → 46.7% (+11.3 pp).

**Storage is no longer the weak field, and that closes the published §8 item 1.** What replaced
it as the binding coverage constraint is GPU identification — and a large part of *that* is not
an extraction failure at all: the GPU-miss rate is **58.8% in the cheapest price quartile
(below 9 000 CZK) against 21–22% in the top two**, because the lower floor imported office SFF
machines that have no discrete card to name, and 13.9% of the misses say so in words. Hence the
conceptual fix the repair makes: **"no discrete GPU" and "GPU failed to parse" are different
facts and must be different values.** Giving a stated absence its own value is worth +2.9 pp of
GPU-known coverage at an audited 2.5% false-positive rate.

### 4.2 Full descriptions are worth much more here than on MacBooks — replicated at 7× the n

The published version measured this on the 166 desktops that then had one. The re-measurement
has 1 188 rows carrying one, and re-runs the same **within-row** ablation — the same listing
parsed with and without its full text, which is the only comparison that is not confounded:

| field | short only | with full | gain, n=1 188 | published gain, n=166 |
|---|---|---|---|---|
| DDR | 26.8% | 55.6% | **+28.9 pp** | +22.3 pp |
| Storage | 40.9% | 67.4% | **+26.5 pp** | +18.7 pp |
| RAM | 74.7% | 90.0% | **+15.2 pp** | +11.4 pp |
| HDD | 11.3% | 23.3% | +12.0 pp | +17.5 pp |
| GPU model | 48.3% | 59.5% | +11.2 pp | +12.7 pp |
| CPU model | 70.5% | 80.6% | +10.1 pp | — |
| GPU VRAM | 20.5% | 29.9% | +9.3 pp | — |
| GPU + CPU + RAM | 36.0% | 53.0% | **+17.0 pp** | — |
| all four | 17.7% | 40.6% | **+22.9 pp** | — |

**The n=166 result replicates and is larger, not smaller** — the usual direction for a small
sample is the other way. The gain scales with how much the seller wrote: all-three coverage
runs 21.0% for descriptions ≤200 chars, 32.3% at 200–400, 55.1% at 400–800, 63.9% at
800–1 500 and **84.5% above 1 500** (n=1 188).

⚠️ **Do not use the cross-row version of this comparison.** Full-description availability is
perfectly confounded with price and date on this corpus (Dec 0%, Jan 0%, Aug 26.5%, Sep 100%;
100% of sub-5k ads have one against 28.3% of 10–20k ads), so a naive "rows with full text vs
rows without" reports GPU coverage as *worse* with a full description (59.5% vs 70.7%). That is
the floor change, read backwards.

### 4.3 Parser traps found

- **Delimiters must survive normalisation.** `rx 6700 xt, 32gb` is a GPU followed by system
  RAM. Flattening the comma turns 32 GB of RAM into 32 GB of VRAM on the card — corrupting
  two features at once. Commas, slashes and pipes are barriers.
- **Suffixes are written unspaced and abbreviated.** `rtx 2080s` is a Super and `rx 580x` is
  an XT. Requiring a word boundary after the digits dropped both entirely.
- **Radeon is often named without `rx`** (`radeon 9060 xt`, `radeon 570x`), and workstation
  cards (`quadro`, `radeon pro`, `w5700`) follow no consumer tier scheme at all — they get a
  `gpu_pro` flag rather than a fake tier.

Fixing these plus the Apple/laptop split moved GPU coverage 63.4% → 69.4%, GPU+CPU+RAM 47.4%
→ 51.9%, and the overall model R² 0.594 → 0.635 (MedAPE 20.3% → 17.8%) on the 2026-08 corpus.

### 4.4 The repair, and the false-positive audit that decides what it was worth

This is [`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md) §3.1 happening a second time —
extractor work outweighing the model-class decision — with one addition that section did not
have to make: **two extractors with the same coverage number can differ by the entire size of
the repair.**

| version | storage coverage | hand-audited FP rate on newly-parsed values | model effect (ΔR² vs v1) |
|---|---|---|---|
| v2 (widened windows) | 64.1% | **35.0%** (14/40, Wilson CI 22.1–50.5%) | **+0.002** (CI −0.011…+0.015) |
| v3 (audited) | 65.3% | **7.5%** (3/40, CI 2.6–19.9%) | **+0.027** (CI +0.014…+0.041) |

(HistGradientBoosting on log price, GroupKFold(5) on the seller, pooled OOF, n=2 281 desktops /
1 230 sellers; paired seller-cluster bootstrap, 400 replicates. v3 − v2 is +0.025, CI
+0.012…+0.042.)

**Coverage bought at a high false-positive rate is not coverage.** A wrong spec is not a
neutral miss — it produces a wrong prediction, and a wrong prediction lands in the underpriced
tail by construction, which is precisely where an alert reads. v2's +11 pp of storage bought
nothing measurable because a third of what it added was wrong.

The defect neither v1 nor v2 saw, and the single largest one: **86% of rows carrying a full
description repeat the short description verbatim inside it** (1 173 of 1 368). One pass over
`name || short || full` therefore counts every drive twice — `ssd: intel 512gb nvme, hdd:
seagate 1tb` came out as 1 024 GB + 2 000 GB. Twelve of v2's fourteen audited false positives
are this one bug. Sum within a text segment, take the max across segments, and strip the
title's own text out of the description, because sellers paste it as the first line.

Four more findings from the repair, each of which generalises past this corpus:

- **RAM, VRAM and storage must be resolved jointly, not by three independent regexes.** Running
  separate patterns over the same text lets one `64 gb` be claimed as RAM by one and as a disk
  by another: v2 had 19 rows with `ssd_gb == ram_gb`, v1 had 40 rows of `ram_gb = 256` that
  were really a 256 GB SSD. Parse every `<number> <unit>` span once and assign it to at most
  one of ram/vram/storage by nearest cue inside its clause. That single change is 11 of the 13
  points of all-four coverage gain and all 10.6 points of VRAM.
- **In the Czech house style a `label:` is a clause barrier, exactly like a comma.**
  `ram: hyperx 16 gb -ssd: 256 gb` binds the 16 GB to `ssd` (two characters right) rather than
  `ram` (fifteen characters left, across a brand name) unless labels cut the clause.
- **The negated-form trap is a family, not a word list.** `bez poškození` was only the first
  instance; this corpus also has `možné přidat HDD` (a disk you *could* add), `lze vylepšit na
  2TB` / `až 32GB` (upgrade offers and ceilings parsed as installed specs), `ryzen 7800x3d
  (+4000 kč)` (a price-list option parsed as the installed CPU) and `nemá integrovanou grafiku`
  (parsed as *has* integrated graphics).
- **Measure the sign of every condition flag against price before trusting it.** v1's `defect`
  flag fires on 56 desktops with a **median price of 19 745 CZK against 15 000 for everything
  else**, +0.147 in mean log price — "damaged" ads reading as ~16% *more* expensive, because
  `bez poškození`, `pojištěním proti poškození` and `v případě funkční vady` all contain the
  vocabulary. Negation-aware matching brings it to 12 rows at a median of 9 250 CZK (−0.444 in
  mean log price, ≈ −36%). A flag whose
  sign is inverted is worse than no flag: it manufactures fake underpricing on exactly the ads
  that deserve a discount. Likewise v1's `prebuilt` flag was 68% bare `dell` and 93 rows of
  `hyperx` (a RAM brand); split into `office_oem` (n=195, median 3 199 CZK, −25% in the fitted
  model) and `gaming_brand` (n=51, median 15 000 CZK, statistically indistinguishable from the
  corpus), it turns out the "gaming prebuilt" it was named for carries no independent signal.

Known residual defects in v3, so the next pass does not rediscover them: a stated total in the
title still double-counts against an itemisation in the description when the two live in
different segments; `2x1tb` is not expanded; the ssd/hdd *label* is ~7.5% wrong even when the
capacity is right; warranty boilerplate still trips `defect` on 4 of its 12 rows; and the
positional generation ordinal collides across vendors (`geforce 650` → gen 60 sorts above an
RTX 3070's gen 30, and AMD's `rx 580` → gen 50 collides with the RTX 50 series). A tree
separates those with `gpu_vendor`; a linear model does not.

## 5. What the model can do

The component decomposition below was measured 2026-08-29 on 1 411 desktops and has **not**
been re-run; it is kept because the *ordering* is the durable finding and the ordering is
confirmed by every segment in §5.1.

| feature set | R² | MedAPE |
|---|---|---|
| GPU only | 0.480 | 19.8% |
| CPU only | 0.435 | 24.7% |
| RAM + storage only | 0.320 | 31.3% |
| GPU + CPU | 0.566 | 19.0% |
| + memory | 0.585 | 20.2% |
| **everything (incl. condition flags)** | **0.635** | **17.8%** |

**GPU is the single biggest driver**, which matches how these machines are actually sold.

The current ladder, on block B only (v3 features, n=1 906 desktops / 1 100 sellers, protocol A
= `GroupKFold(5)` on the seller × 3 shuffled repeats, pooled out-of-fold, ridge α by an inner
`GroupKFold(3)` inside each training fold). Δ is a paired seller-cluster bootstrap, 2 000
replicates, **each model minus the HGB — negative is worse than the tree**:

| model | R² | MedAPE | σ | ΔR² vs HGB | 95% CI |
|---|---|---|---|---|---|
| global median | −0.012 | 50.3% | 0.951 | −0.785 | −0.860…−0.721 |
| median by exact config, ≥3 comparables | 0.640 | 23.2% | 0.569 | −0.133 | −0.174…−0.094 |
| **ridge, ordinal-encoded categoricals** (the §5.2 form) | **0.590** | **31.0%** | 0.604 | −0.185 | −0.235…−0.143 |
| ridge, one-hot, small categoricals only | 0.731 | 22.9% | 0.492 | −0.043 | −0.077…−0.019 |
| **ridge, one-hot incl. per-GPU/CPU-model dummies** | **0.736** | **21.1%** | 0.487 | −0.037 | −0.064…−0.016 |
| …+ pre-expanded per-series tier×gen columns | 0.734 | 20.5% | 0.490 | −0.040 | −0.069…−0.017 |
| random forest (400 trees) | 0.765 | 18.6% | 0.459 | −0.007 | −0.021…+0.005 |
| **HistGradientBoosting (incumbent params)** | **0.773** | **18.0%** | 0.452 | — | — |

⚠️ **These R² values are not comparable to the published 0.635.** sd(log price) is 0.927 on
block B against 0.659 implied by the 2026-08 study; the target got ~40% more spread when the
query's floor fell, and R² rises with the denominator. MedAPE and σ *are* comparable, and they
say the model got slightly **worse** in absolute terms (17.8% → 18.0%, σ 0.398 → 0.452), which
is the honest reading: the lower floor imported a cheap, thinly-described stratum.

The random forest is statistically indistinguishable from the boosting here, reproducing
`PRICE_MODEL_BENCHMARK.md` §4 on a completely different corpus. If a tree ensemble is ever put
on the Pi, it should be the forest.

### 5.1 The error is concentrated, not spread — and σ is keyed on completeness

| segment (block B, protocol A OOF) | n | ridge R² | ridge MedAPE | HGB R² | HGB MedAPE |
|---|---|---|---|---|---|
| all four specs parse | 891 | 0.863 | 16.7% | **0.892** | **14.0%** |
| something missing | 1 015 | 0.650 | 27.0% | 0.692 | 23.0% |
| GPU identified | 1 298 | 0.832 | 17.2% | 0.879 | 14.2% |
| — GPU **not** identified | 608 | 0.515 | 36.3% | 0.548 | **31.1%** |
| office OEM (the refurb stratum) | 188 | 0.601 | 27.0% | 0.650 | 23.3% |

Like-for-like against the published §5.1 definition (GPU+CPU+RAM parsed, storage not required):
**n=1 366 against the published 733 — up 86% — at HGB R² 0.883 / MedAPE 13.9%** against the
published 0.853 / 13.4%. MedAPE is essentially unchanged on 86% more rows; the R² difference is
the spread caveat above, not an improvement.

§3 predicted that sigma would have to come from spec completeness rather than seller maturity.
It does, cleanly:

| specs parsed (of 4) | n | ridge σ | HGB σ | −25% expressed in σ (ridge) | % of that bucket firing at a flat −25% |
|---|---|---|---|---|---|
| 0 | 162 | **1.021** | 1.001 | 0.28σ | **34.0%** |
| 1 | 90 | 0.731 | 0.792 | 0.39σ | 24.4% |
| 2 | 223 | 0.489 | 0.445 | 0.59σ | 24.2% |
| 3 | 540 | 0.414 | 0.323 | 0.70σ | 19.8% |
| 4 | 891 | 0.316 | 0.281 | 0.91σ | 13.4% |
| 4 + no damage + ≥10 000 CZK | 634 | **0.296** | 0.259 | **0.97σ** | 9.8% |

**A zero-spec ad is 3.2× noisier than a fully-parsed one** — the same shape as the MacBook's
4.5× first-time-seller-vs-dealer spread, keyed on a different variable. This is the desktop
analogue of `MACBOOK_PRICE_MODEL.md` §5.6, and it needs no schema work to ship:
`Manifest.sigma_for()` already takes an integer key with lower-bound semantics, so
`{0: 1.021, 1: 0.731, 2: 0.489, 3: 0.414, 4: 0.316}` drops into the existing
`seller_sigma_prior` slot — only the argument the estimator passes changes.

### 5.2 ~~Linear is not sufficient here~~ — **retracted**

> ⚠️ **This section's finding is withdrawn.** What it published, on 2026-08-29:
>
> | model | all rows | complete-spec rows |
> |---|---|---|
> | HistGradientBoosting | 0.635 / 17.8% | 0.853 / 13.4% |
> | Ridge | 0.535 / 21.2% | **0.769 / 17.1%** |
>
> …and concluded from the 3.7 pp MedAPE gap that "GPU tier interacts with generation and with
> the rest of the build in ways a linear model in these features cannot express."

**The Ridge row is not reproducible from the repo.**
[`experiments/price_model/pc/pcmodel.py`](../../experiments/price_model/pc/) imports `Ridge`
and never instantiates it — its only `run()` fits HistGradientBoosting — so the published
figure came from code that was never committed. And every linear design its committed `make_X`
*can* produce hands the categoricals to the linear model as **ordinal integers**: `make_X`
ordinal-encodes `gpu_model`, `cpu_model`, `gpu_series`, `gpu_suffix`, `gpu_vendor` and
`cpu_vendor` and passes the same matrix to whichever estimator runs, so a ridge receives the
GPU *name* as an integer 0…139 and is asked to fit a slope through it.

Reconstructed on the study's own rows (v1 features, 3-field complete-spec, `created` ≤
2026-08-29, n=694 against the study's 733):

| design reachable from the committed `make_X` | R² | MedAPE |
|---|---|---|
| `make_X` + HistGradientBoosting | 0.823 | 13.8% |
| `make_X` + Ridge, categoricals as **ordinal integers** | 0.723 | 15.4% |
| `make_X(cat=[])` + Ridge, no categoricals at all | 0.656 | 17.6% |
| **one-hot + standardised + nested-α Ridge, same rows** | **0.796** | **13.3%** |

Every linear design the file can produce lands at **R² 0.656–0.725 / MedAPE 15.2–17.6%**, and a
correctly encoded ridge on those identical rows reaches **0.796 / 13.3% — a better median error
than the published HGB's 13.4%.** **So the published 3.7 pp is an encoding gap, not a model-class
gap** — on the study's own rows the encoding choice is worth four to six times it. The corpus
growing from 733 to 1 284 complete-spec rows is *not* the explanation and must not be offered as
one.

What cannot be established is that the published run made that specific mistake — the ridge run
is not in the repo or its history. What *is* established is that the encoding choice is worth
four to six times the gap the section concluded from, which makes the conclusion unsafe
whichever arm it used.

**The corrected comparison**, equal effort on both sides (v1 features, the published
complete-spec definition, n=1 284 / 697 sellers, `GroupKFold(5)` on the seller × 3 repeats,
pooled OOF, nested hyperparameter selection for *both* models):

| model | R² | MedAPE | σ |
|---|---|---|---|
| one-hot, standardised, nested-α ridge with gen/tier as per-level dummies | 0.868 | 14.63% | 0.276 |
| **nested-tuned HistGradientBoosting** | **0.886** | **13.27%** | 0.257 |

Tree minus ridge: ΔR² **+0.018** (95% CI +0.004…+0.035), ΔMedAPE **−1.30 pp** (CI
−2.85…+0.15), paired seller-cluster bootstrap — note the sign convention is the reverse of the
ladder table above. So the tree keeps a small, statistically resolvable R² edge and a
median error that cannot be told apart. **"Indistinguishable" is too strong; "within 0.02 R²
and tied on MedAPE" is right.** Note that *tuning the tree* is itself worth ΔR² +0.009
(CI +0.003…+0.014) — the easy mistake here is to compare a searched ridge against an unsearched
tree, which flatters the linear arm by half the remaining gap.

**Which basis moved**, in decreasing order of size, since four moved at once:

| basis | what changed | worth |
|---|---|---|
| **design matrix** | ordinal → one-hot categoricals | **+0.140 to +0.234 R²** to the linear arm |
| **extractor** | v1 → v3 | +0.075 R² (linear, all desktops), +0.036 (linear, complete-spec), +0.063 (tree) |
| **corpus** | 1 411 → 2 281 desktops; floor 10 000 → 2 000 CZK from 2026-08-27 (minimum *observed* 1 800); ~5 → ~66 desktops/day | R² not comparable (§2.1); MedAPE ≈ flat |
| **protocol** | one non-shuffled `GroupKFold(5)` → 5×3 shuffled pooled OOF with nested α | ~0.01 R², the direction `PRICE_MODEL_BENCHMARK.md` §3.3 documents |

Three things qualify the retraction rather than following from it:

- **On UNGATED desktop rows the tree's advantage is large and unambiguous**: ΔR² **+0.124**
  (CI +0.096…+0.153), ΔMedAPE −6.1 pp, n=2 447. A linear manifest is arguable **only behind the
  completeness gate**, which keeps 52.5% of v1 desktops (34.4% if storage must parse too).
- **The tree's residual edge on complete-spec rows is carried almost entirely by a `days`
  feature** encoding this corpus's two-block collection history. Remove it and ΔR² is
  **−0.004** (CI −0.019…+0.014). A shipped desktop manifest must not carry a time index built
  out of a collection artefact — the tree is splitting on the backfill day, not on the market.
- **What closes the linear gap is not what P27 assumed.** Pre-expanded per-GPU-series slope
  columns buy +0.007 R² (CI +0.000…+0.019); entering gen/tier as **one dummy per level** buys
  +0.024 (CI +0.001…+0.063) — the same "stop treating a number as a number" finding as
  `PRICE_MODEL_BENCHMARK.md` §1, and already a supported `cat` kind. The implied manifest is
  238 coefficient rows (16 num, 9 missing, 9 bool, 204 cat) against the shipped MacBook
  manifest's 40, and needs **no change to `bazos/pricing/artifacts.py`** — only a desktop
  feature extractor. Worse, pre-expanded interactions actively harm the tail: the
  interaction-expanded ridge's worst over-prediction on the gated segment is **29.3× the asking
  price** against 7.2× for the plain ridge and 5.1× for the tree.

**What this changes for P27.** Its closing note — "gradient boosting clearly beats ridge here …
so if this ever ships, either pre-expand the interactions or accept a different serving story"
— rests on the retracted row, and its suggested fix is measured above as the wrong one. The
serving blocker named in §5.2 is gone. The blocker in §8 is not.

### 5.3 The calibration argument for linear does **not** transfer

[`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md) §9 calls interval honesty "the clearest
operational argument for the linear model in the whole document": on MacBooks a naive
`pred ± z·σ` interval built from the GBM's training residuals covers **39.8%** at a nominal 80%,
because the tree fits its training set far too closely. Measured here (block B,
`GroupKFold(5)`):

| model | nominal | naive coverage | conformal coverage |
|---|---|---|---|
| ridge, one-hot | 80% | 83.6% | 81.3% |
| ridge, one-hot | 90% | 89.6% | 90.6% |
| **HistGradientBoosting** | 80% | **75.0%** | 80.7% |
| HistGradientBoosting | 90% | 82.8% | 90.8% |

**75.0%, not 39.8%.** This corpus is noisy enough relative to the model's capacity that the
tree barely overfits, and split conformal repairs what is left exactly. The MacBook document's
decisive operational argument for shipping linear is therefore **unavailable on desktops**, and
must not be repeated for this category. The case for a linear artifact here rests on §5.2's
retraction and on the two arguments that stand on their own — no numeric stack on an ARM64 Pi
and a manifest reviewable in a git diff ([`ML_PRICE_SCORING.md`](../proposals/ML_PRICE_SCORING.md)
§4.1) — neither of which is about accuracy.

## 6. The name→spec lookup idea, tested — it is redundant

(Measured 2026-08-29; not re-run. The mechanism is arithmetic, not corpus-dependent.)

The intuition is that mapping GPU and CPU names to their real specs (VRAM, core counts,
clocks) should add information the name alone does not carry. Tested with a lookup built
**from the corpus itself** rather than asserted, so it is verifiable:

- 37 GPU models have ≥3 stated VRAM values. **25 are unambiguous, 12 are not** — `rtx 3060 ti`,
  `rtx 5060 ti`, `rx 9070 xt` and others genuinely ship in two capacities.
- Filling missing VRAM from that lookup raised coverage **22.8% → 60.5%**.
- Model effect: R² 0.635 → 0.635, MedAPE 17.8% → **18.4%, slightly worse**.

**No gain, because the lookup is a function of the GPU model and the model is already a
feature.** It adds a column that is collinear with what is there. Worse, the 12 ambiguous
cards are exactly the ones where stated VRAM carries real information, and filling them with a
median destroys the distinction between an 8 GB and a 16 GB card.

The generalisable rule: **a spec table only pays where the name does not determine the spec.**
Core counts fail this test the same way — they are a deterministic function of the CPU model,
so the 31% of ads that state them add nothing the model name did not already say.

**One qualification the re-measurement adds.** In the fitted linear model, *stated* VRAM is the
strongest GPU feature (**+11.4% per 4 GB**, CI +8.1…+14.7) while the positional tier step is
**not identified** once VRAM and the series dummies are present (+1.2%, CI −0.1…+2.5). That is
the most plausible destination of v3's +10.6 pp of VRAM coverage, and it sharpens rather than
contradicts §4: the *name-derived ordinal is what to have when VRAM is absent*, not what to
prefer when it is present. It also sharpens the null above — filling VRAM from a median is not
merely redundant, it degrades the feature that turns out to carry the most signal.

Still not tested: an **external performance benchmark** (3DMark / PassMark) as a single
ordinal. That is genuinely not derivable from the name — it would place `rx 6700 xt` against
`rtx 3060 ti` on one scale — and remains the only version of this idea worth trying. It is P27
item 2 and nothing in this re-measurement touched it.

## 7. What a deal alert would look like

Every rate in this section is computed on the **steady-state window, 2026-08-27 → 09-12** —
after the query's floor settles and excluding the 916-ad backfill day — which runs at 472
desktops/week. Over the whole of block B the same gate yields 122/week, so read the gated 162
as the top of a 122–162 range; the window is part of the number.

### 7.1 Candidate gates

| gate | n (block B) | % of desktops | scored/wk | HGB R² / MedAPE / σ | ridge R² / MedAPE / σ | config-median MedAPE |
|---|---|---|---|---|---|---|
| 4/4 specs | 891 | 46.7% | 270 | 0.892 / 14.0% / 0.281 | 0.863 / 16.7% / 0.316 | 18.3% |
| 4/4 + no damage | 884 | 46.4% | 267 | 0.893 / 13.9% / 0.279 | 0.866 / 16.6% / 0.313 | 18.3% |
| **4/4 + no damage + ≥10 000 CZK** | **634** | **33.3%** | **162** | **0.806 / 13.2% / 0.259** | **0.747 / 16.4% / 0.296** | 14.9% |
| 4/4 + no damage + ≥6 000 CZK | 739 | 38.8% | 206 | 0.846 / 13.5% / 0.262 | 0.802 / 16.7% / 0.297 | 15.5% |
| ≥3/4 + no damage + ≥10 000 CZK | 968 | 50.8% | 201 | 0.775 / 14.4% / 0.271 | 0.658 / 16.6% / 0.331 | 16.5% |

R² falls as the price floor rises because conditioning on price destroys the denominator — read
MedAPE and σ across these rows, not R². Loosening to ≥3/4 buys +54% of scored volume and costs
the linear model 0.105 R² and 0.035 of σ; it is the wrong trade, and §5.1's table says why.
**The 4/4 gate is affordable at all only because storage coverage moved** (§4.1).

In money, on the recommended gate (median ask 20 745 CZK): the tree's typical miss is
**2 738 CZK**, the ridge's **3 402 CZK**, the config-median lookup's 3 091 CZK. The model-class
gap is **664 CZK — 3.2% of the asking price**, against 177 CZK / 1.6% on MacBooks. The house
benchmark to compare against is the shipped MacBook artifact's **8.71% on the rows it actually
scores** (its published 10.14% is a mixed-population figure that includes 673 rows its own gates
refuse, where it runs at 16.04%).

### 7.2 The funnel

| threshold | HGB gated/wk | ridge gated/wk | HGB % of gated pop | ridge % of gated pop | ridge **ungated**/wk |
|---|---|---|---|---|---|
| −15% | 27.0 | 38.8 | 16.6% | 23.9% | 182.0 |
| −20% | 16.4 | 29.5 | 10.1% | 18.2% | 158.0 |
| **−25%** | **11.4** | **18.5** | 7.0% | **11.4%** | 127.7 |
| −30% | 5.5 | 11.4 | 3.4% | 7.0% | 109.5 |
| −40% | 3.8 | 5.1 | 2.3% | 3.1% | 78.8 |
| −50% | 1.3 | 1.7 | 0.8% | 1.0% | 54.8 |
| **z ≤ −2** (= −45% ridge / −40% HGB) | ≈2.6 | **3.1** | 1.6% | 1.9% | — |

The MacBook reference is 2.6–3.2 gated alerts/week at the shipped threshold
(`MACBOOK_PRICE_MODEL.md` §5.7). **Only the `z ≤ −2` row lands in that regime.**

### 7.3 The threshold, not the model, is what blocks an alert

| | desktop, gated | MacBook, 50+ ad dealer | MacBook, private seller |
|---|---|---|---|
| residual σ | 0.296 (ridge) / 0.259 (HGB) | 0.098 | 0.302 |
| what a flat −25% means | **0.97σ** | **2.92σ** | 0.95σ |
| discount needed for z ≤ −2 ¹ | **45%** (ridge) / 40% (HGB) | 18% | 45% |
| discount needed to match a dealer's 2.92σ | **58%** (ridge) / 53% (HGB) | 25% | 59% |

¹ computed from the raw residual σ in the first row; `MACBOOK_PRICE_MODEL.md` §5.7 quotes 14%
and 44% for the same two tiers because its σ is shrunk against a seller-maturity prior.

**A desktop ad at −25% is ordinary noise, and the shipped threshold would say it is a deal
18.5 times a week.** This is the same arithmetic `MACBOOK_PRICE_MODEL.md` §5.3 used to show a
flat percentage is four different standards of evidence wearing one number — and the row this
corpus lands on is the worst of the four. **In σ terms the desktop gated segment *is* the
MacBook private-seller tier** (0.296 against 0.302), the tier that document identifies as where
a flat rule spends its whole alert budget on noise. The difference is that on MacBooks it is
one tier of four with the dealers supplying a price reference; here it is the entire category.
The fix is the same and it is §5.1's σ ladder: standardise the residual against a
completeness-keyed σ, and the threshold becomes one standard of evidence at MacBook-comparable
volume.

### 7.4 What the flagged tail is actually made of

Hand audit of the **top 12 unique gated flags** (ridge, block B). This is the extreme tail,
where extraction failures concentrate by construction — it is not an estimate of the
false-positive rate at the threshold.

| # | discount | ask / predicted CZK | listing | verdict |
|---|---|---|---|---|
| 1 | 86% | 17 000 / 122 464 | RTX 5080 / Ryzen 7 9850X3D / 128 GB / 6 TB | specs parsed **correctly** — a bait listing. Model right, action wrong |
| 2 | 67% | 45 000 / 138 081 | LYNX Challenger 9900X3D, 64 GB, **bez GK** | extraction: ad says *without graphics card*; the RTX 5090 was read out of a pasted alza.cz URL |
| 3 | 58% | 20 000 / 47 683 | PC R7 7800X3D 64 GB | extraction: `RTX 4090 … originál-**prodáno**` — the GPU is already sold |
| 4 | 53% | 26 000 / 54 922 | 5800X3D / 32 GB / 4 TB | extraction: the title total `4TB` summed on top of the itemised 2 TB SSD |
| 5 | 52% | 15 000 / 31 467 | Ryzen 5 5600, RX 6600 32 GB/2 TB/512 GB SSD | extraction ×2: VRAM 32 GB on an 8 GB card; a 2 TB HDD counted as SSD |
| 6 | 49% | 13 499 / 26 709 | Ryzen 5 3600 / 32 GB / RTX 2060 Super | extraction: RAM 128 GB taken from `deska … podpora až 128GB RAM` |
| 7 | 48% | 11 999 / 23 040 | `2x SSD 28x 64 GB RAM vlaknovývh jader Xeon 5500XT 8GB` | extraction — **the exact listing the published §7 already named**, relisted 7× |
| 8 | 47% | 27 500 / 51 636 | RX 7900 XT 20 GB / 7800X3D / 32 GB / 2 TB | specs correct — **plausible genuine deal (the only one)** |
| 9 | 46% | 48 000 / 88 643 | Herní PC 7800X3D + RTX 5070 Ti | specs correct; the ask is at or above market — model over-prediction |
| 10 | 43% | 30 000 / 52 302 | 7800X3D + RTX 4070 Super + 32 GB | model over-prediction |
| 11 | 40% | 19 000 / 31 860 | i7-10700KF + RTX 3070 + 32 GB | model over-prediction (and SSD 2 800 GB double-counts a 1.8 TB HDD) |
| 12 | 39% | 20 500 / 33 462 | RTX 5060 / Ryzen 7 5800X / 32 GB | model over-prediction |

Tally: **6 extraction failures, 1 bait listing, 4 over-predictions on correctly-parsed specs,
at most 1 candidate deal.** The published §7 said "inspection of the top flags still shows parse
failures surviving the gate"; on the *repaired* extractor, at the top of the list, it is one in
two — and the garbled Xeon listing it named by name is still there, still passing the 4/4 gate,
relisted seven times by one seller and supplying four of the top ten flags for **both** model
classes. Nothing in the pipeline suppresses a re-flagged relisting; 16.9% of the gated
population is a repeat of a listing already seen.

The systematic counterpart, which is the number to quote for the whole flagged set (n=62
flagged against 572 not):

| mechanical red flag | in the −25% gated tail | elsewhere | enrichment |
|---|---|---|---|
| **any** red flag | 43.5% | 20.6% | 2.1× |
| impossible VRAM for the card's tier | 3.2% | 0.3% | **9.2×** (18.8× at −30%) |
| RAM ≥ 128 GB | 4.8% | 0.5% | **9.2×** |
| SSD ≥ 4 000 GB | 11.3% | 3.0% | 3.8× |
| an alza/czc/heureka URL in the body | 4.8% | 1.4% | 3.5× |
| text stating no discrete GPU | 3.2% | 0.9% | 3.7× |
| a relisting of an earlier (name, price) | 24.2% | 15.7% | 1.5× |

⚠️ Both tables share a neighbourhood: the enrichment denominators are computed on the same 634
gated rows the 12 audited flags come from. Read them as one piece of evidence, not two.

**The four guards this implies**, all cheap, all landing before any alert is enabled:

1. **VRAM plausibility against the card's own tier** — an RX 6600 cannot have 32 GB, and v3's
   whitelist admits it (9.2× enriched, 18.8× at −30%).
2. **A RAM-capability guard** — `deska … podpora až 128GB RAM` is what the *motherboard*
   supports, and a nearest-cue rule prefers it over the title's real figure because the
   capability sentence puts `RAM` adjacent to the number (9.2×).
3. **A stated-absence guard** — `bez GK` is not in the no-GPU vocabulary, and a component
   described as `prodáno` / `rezervováno` is still counted as present (3.7×).
4. **A URL guard** — a GPU model read out of a pasted alza.cz product link is a real, repeated
   failure mode (3.5×).

## 8. Assessment

**Shadow-ship a gated linear artifact. Do not enable the rule on any query. Do not ship a flat
−25% threshold at all.** The honest position, item by item against the published §8:

1. ~~**Storage coverage (39%) is the binding constraint.**~~ **Closed.** 66.1% on block B,
   83.4% on rows with a full description (§4.1). The 4/4 completeness gate is affordable now.
2. ~~**Enable `load_full_description` and re-measure.**~~ **Done, and it was the right call** —
   +26.5 pp of storage and +22.9 pp of all-four coverage on the rows that have one (§4.2), and
   the highest-value cheap change in this document by a wide margin.
3. **Classification comes first** — and it got *worse*, not better: 20.1% of the category is
   not a desktop now that the floor admits servers, all-in-ones and `koupím` ads (§2).
4. **The threshold is the binding constraint now, and it is quantified rather than estimated.**
   −25% is **0.97σ** against a MacBook dealer's 2.92σ (§7.3). The published version put this at
   "~1.9σ here versus ~3σ there" — half again too generous, and generous even against its own
   §5.1 σ of 0.224, which implies 1.28σ. The current figure rests on a gated σ of 0.296,
   measured on a corpus whose floor no longer truncates the cheap tail.
5. **The seller-aware machinery still does not transfer** (§3) — but its replacement is
   measured: σ keyed on spec completeness, 3.2× from zero specs to four, shipping into the
   existing `Manifest.sigma_for()` slot with no schema change (§5.1).
6. **§5.2's serving blocker is retracted** (§5.2). A linear manifest is viable *behind the
   gate* — 238 coefficient rows, every one an existing feature kind. It is not viable ungated:
   ΔR² +0.124 there.

Two operational facts that must be settled *before* a desktop artifact is registered, neither
of which is a modelling question:

- **Registry ordering already decides this, and it is live.** `get_price_model` returns the
  first model in `MODEL_REGISTRY` whose `applies_to` claims the ad, and `MacbookPriceModel`
  already claims **83 ads inside query 9**, 38 of which pass its gates. One of them is a
  *motherboard* — "Základní deska Apple MacBook 820-01041 A1990" at 6 000 CZK, which the MacBook
  model claims and prices at 8 814 CZK, z −1.59. It never reached the price-model rule only
  because a location filter rejected it first; `applies_to` is the gate that was supposed to
  stop it, and it did not. Registering a desktop model with a loose `applies_to` would contest
  a much larger pool (`product_kind` is `unknown` for 5 055 Bazos ads) and dict literal order
  would settle it.
- **The artifact must record its training price support.** Query 9's own floor moved from
  10 000 to ~2 000 CZK *inside* this study's window (§2.1), which is the same event that
  mis-calibrates a shipped model against ads it has no basis for pricing.

⚠️ **The standing caveat applies to everything above.** `Ad.modified` never advances past
`Ad.created`, so the database records **zero outcomes** — no sold flag, no time-to-disappear.
Every figure in §7 is a composition audit plus a cross-validated fit statistic, never a
measurement of whether a flagged listing was a deal. The cost of the model-class gap is known
in volume (7 extra flags/week at −25%) and unknown in value, which is the same asymmetry
`PRICE_MODEL_BENCHMARK.md` §10 names and the reason [`PROMPTS.md`](../backlog/PROMPTS.md) P24
gates calibrating any threshold here.

The most valuable next experiments are, in order: the four extractor guards in §7.4; P27 item 2
(the external GPU benchmark ordinal, still untouched); and a re-measurement on a block-B-only
corpus once September is a majority, which is the first slice with 100% full descriptions and
no floor change inside it.

## 9. Reproduction

Read-only against the production Postgres export; nothing was written. Scripts in
[`experiments/price_model/pc/`](../../experiments/price_model/pc/) — throwaway analysis,
excluded from ruff and mypy, needing `poetry install --with ml`. The corpus is not committed
(seller names, publisher ids). The shared protocol lives in
[`experiments/price_model/common/ph.py`](../../experiments/price_model/common/ph.py), which
*is* committed: one grouped-CV harness for every category, so the numbers in
`docs/research/*_PRICE_MODEL.md` are comparable rather than each script inventing its own split.

| script | what it does |
|---|---|
| `pcfeat.py` | the v1 extractor — kind classification, GPU/CPU name parsing, memory and storage, condition flags |
| `pcmodel.py` | design matrix, the grouped-CV harness, the component decomposition |

⚠️ **`pcmodel.py` no longer runs on the current corpus**, and P27 item 1's instruction to
"re-run `pcfeat.py` coverage and `pcmodel.py`" will fail as written:

- `make_X` passes `cpu_model` at cardinality **275** to `HistGradientBoostingRegressor`, and
  sklearn refuses native categorical features above 255 —
  `ValueError: Categorical feature 'cpu_model' is expected to have a cardinality <= 255`. Pool
  rare levels before anything else.
- It reads `pc/pc_feat.pkl`, and **no committed script builds that file** — the build step was
  never committed.
- Separately, sklearn's binner raises `ValueError: window shape cannot be larger than input
  array shape` whenever a numeric column is constant within a subset, which bites as soon as
  the corpus is sliced by completeness. Drop single-valued columns per subset.

The v2/v3 extractors and the benchmark ladder of §5 and §7 were run from scratch code that was
deliberately not committed; this document is the durable artifact, as it was the first time.

```sql
COPY (SELECT a.*, d.status FROM bazos_ad a
      JOIN bazos_addelivery d ON d.ad_id = a.id WHERE d.query_id = 9) TO STDOUT WITH CSV HEADER;
```
