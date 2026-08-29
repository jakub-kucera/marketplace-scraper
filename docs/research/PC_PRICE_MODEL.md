---
title: Desktop PC price prediction — feasibility on the Počítače corpus
status: reference
updated: 2026-08-29
verified: 2026-08-29
---

# Desktop PC price prediction — feasibility on the Počítače corpus

> Written 2026-08-29 from a read-only pull of query 9 (`PC, Počítače`, no text, 2 000–200 000
> CZK): **1 668 ads, 2025-12-13 → 2026-08-29**, 259 days. Research and local experimentation
> only — nothing here is wired into the pipeline.
>
> The question was whether the MacBook work ([`MACBOOK_PRICE_MODEL.md`](MACBOOK_PRICE_MODEL.md))
> transfers to desktops. It partly does, but this is a **harder problem for reasons that are
> about the market, not the method**.

## 1. Summary

| Question | Answer |
|---|---|
| Is a desktop a different market from a MacBook? | **Yes, fundamentally.** 848 sellers for 1 411 ads, half of them one-offs — a private-seller market, where MacBooks are a dealer market |
| Can specs be extracted from listing text? | Partly. GPU 69%, CPU 77%, RAM 74%, **storage only 39%** |
| Is price predictable? | **Overall R² 0.635 / MedAPE 17.8%** — much worse than MacBooks' 0.87 / 8% |
| …where the specs actually parse? | **R² 0.853 / MedAPE 13.4%** (n=733). The binding constraint is extraction, not the model |
| Which component carries the price? | GPU (R² 0.480 alone), then CPU (0.435), then RAM+storage (0.320) |
| Does a name→spec lookup help? | **No — it is redundant.** See §6; this was worth testing and the answer is counterintuitive |
| Do full descriptions help? | **Yes, materially**: +12.7pp GPU, +18.7pp storage, +22.3pp DDR on rows that have one |
| Ship it? | **Not yet.** §8 — one alert in six is a parse failure, and storage coverage has to move first |

## 2. The corpus is not one market

`kind` is inferred from the title and description:

| kind | n | what it is |
|---|---|---|
| `desktop` | 1 411 | the actual subject |
| `apple_desktop` | 127 | iMac / Mac Pro / Mac mini — a different price curve, and they almost never name a discrete GPU |
| `laptop` | 116 | notebooks posted in the desktop category |
| `not_pc` | 13 | Bitmain/Antminer ASIC miners, phones |
| `monitor` | 1 | |

**8% of the category is Apple desktops and another 8% is laptops.** Before they were split
out they read as "a desktop whose GPU could not be identified", which is the single largest
class of extraction failure and entirely spurious. Any model here has to classify first.

## 3. Market structure — the opposite of the MacBook corpus

| | Desktops | MacBooks |
|---|---|---|
| ads / sellers | 1 411 / **848** | 2 038 / 499 |
| median ads per seller | **1** | — |
| share from top 10 sellers | **16.5%** | **56%** |
| one-off sellers | **49.6%** | 21% |
| residual σ | **0.398** | 0.20 |

This inverts the central finding of the MacBook work. There, two thirds of apparent
underpricing was persistent dealer pricing and the fix was a per-seller baseline. Here there
is **no seller history to build a baseline from** — half the sellers appear exactly once, and
they never appear again.

> ⚠️ A between/within-seller variance decomposition on this corpus returns 87%, but that
> number is **meaningless**: a singleton seller has zero within-variance by construction, so
> with half the corpus appearing once the decomposition is degenerate. It is not comparable
> to the MacBook 67% and should not be quoted.

The seller-aware z-score from `MACBOOK_PRICE_MODEL.md` §5.7 therefore **does not transfer**.
Sigma would have to come from listing characteristics — chiefly spec completeness — rather
than from seller maturity.

## 4. Extraction

Titles are unusually spec-dense — `Herní PC | Ryzen 7 5800x, RX 6700 XT, 32GB, 1TB SSD` is
the house style — and the vocabulary is standardised: **140 distinct GPU tokens, 271 CPU
tokens** across the corpus.

**The design decision worth keeping: GPU and CPU tier and generation are parsed out of the
model name, not looked up.** `rtx 3070` already encodes vendor, generation (30) and tier (70)
positionally, and the naming has been stable for a decade, so an ordinal feature falls out
with no table to maintain. Measured on complete-spec rows:

| GPU encoding | R² |
|---|---|
| name-derived tier + generation ordinal | **0.515** |
| one dummy per GPU model | 0.370 |
| both together | **0.628** |

The ordinal beats per-model dummies because it **interpolates to models never seen in
training** — with 140 models over 1 411 ads the tail is thin, and a dummy for an unseen card
is just the intercept.

### 4.1 Coverage, on the 1 411 desktops

| field | title only | + short desc | + full desc |
|---|---|---|---|
| CPU model | 50.2% | 73.7% | **77.0%** |
| RAM | 52.1% | 73.7% | **73.8%** |
| GPU model | 50.8% | 62.1% | **69.4%** |
| DDR generation | 11.4% | 31.6% | **35.2%** |
| **Storage** | 24.6% | 37.8% | **39.0%** |
| GPU VRAM | 11.5% | 20.0% | **22.8%** |

GPU + CPU + RAM together: **51.9%**. All four including storage: **~26%**.

**Storage is the weak field and it is not a parser problem** — sellers frequently do not state
capacity at all, or write "SSD" with no number.

### 4.2 Full descriptions are worth much more here than on MacBooks

Measured only on the 166 desktops that have one (`load_full_description` was enabled on query
9 partway through, so most rows predate it):

| field | short only | with full | gain |
|---|---|---|---|
| DDR | 28.3% | 50.6% | **+22.3pp** |
| Storage | 32.5% | 51.2% | **+18.7pp** |
| GPU model | 39.8% | 52.4% | **+12.7pp** |
| RAM | 80.1% | 91.6% | +11.4pp |
| HDD | 9.6% | 27.1% | +17.5pp |

For MacBooks the equivalent gain was 10–15pp on a corpus that was already well covered. Here
it lands on the two weakest fields. **Full descriptions are the highest-value cheap change.**

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
→ 51.9%, and the overall model R² 0.594 → 0.635 (MedAPE 20.3% → 17.8%).

## 5. What the model can do

`HistGradientBoostingRegressor` on log price, 5-fold grouped by seller:

| feature set | R² | MedAPE |
|---|---|---|
| GPU only | 0.480 | 19.8% |
| CPU only | 0.435 | 24.7% |
| RAM + storage only | 0.320 | 31.3% |
| GPU + CPU | 0.566 | 19.0% |
| + memory | 0.585 | 20.2% |
| **everything (incl. condition flags)** | **0.635** | **17.8%** |

**GPU is the single biggest driver**, which matches how these machines are actually sold.

### 5.1 The error is concentrated, not spread

| segment | n | R² | MedAPE |
|---|---|---|---|
| GPU + CPU + RAM all parsed | 733 | **0.853** | **13.4%** |
| something missing | 678 | 0.475 | 27.0% |
| — of which no GPU identified | 432 | 0.336 | **38.7%** |

Residual σ is **0.224** on complete rows against **0.524** on incomplete ones. This is the
MacBook lesson again, sharper: the model is decent where it can see the machine and near
useless where it cannot, and the two are separable *before* scoring.

### 5.2 Linear is not sufficient here

| model | all rows | complete-spec rows |
|---|---|---|
| HistGradientBoosting | 0.635 / 17.8% | **0.853 / 13.4%** |
| Ridge | 0.535 / 21.2% | 0.769 / 17.1% |

This is the opposite of the MacBook result, where the gap was 177 CZK on the median ad and
[`PRICE_MODEL_BENCHMARK.md`](PRICE_MODEL_BENCHMARK.md) recommended shipping linear. Here the
gap is **3.7pp of MedAPE on the complete-spec rows** — GPU tier interacts with generation and
with the rest of the build in ways a linear model in these features cannot express.

**That matters for deployment.** The shipped serving path evaluates a JSON manifest as
`intercept + Σ coef·feature` specifically so the ARM64 image carries no numeric stack
([`ML_PRICE_SCORING.md`](../proposals/ML_PRICE_SCORING.md) §4.1). A desktop model good enough
to act on would either not fit that path, or would need the interactions pre-expanded into
explicit features — which is worth trying before concluding the path is unusable.

## 6. The name→spec lookup idea, tested — it is redundant

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

Not tested: an **external performance benchmark** (3DMark / PassMark) as a single ordinal.
That is genuinely not derivable from the name — it would place `rx 6700 xt` against
`rtx 3060 ti` on one scale — and remains the only version of this idea worth trying.

## 7. What a deal alert would look like

Over the 259-day window, ads below predicted by the given margin:

| threshold | all desktops | complete-spec only |
|---|---|---|
| ≥20% | 322 (8.7/wk) | 95 (2.6/wk) |
| ≥25% | 241 (6.5/wk) | 54 (1.5/wk) |
| ≥30% | 187 (5.1/wk) | 33 (0.9/wk) |

Gating on complete specs cuts volume by ~75%, and given §5.1 that is the right trade. But
inspection of the top flags still shows parse failures surviving the gate — one reads
`2x SSD 28x 64 GB RAM vlaknovývh jader Xeon 5500XT 8G`, which is garbled beyond rescue.

## 8. Assessment

**Do not wire this up yet.** The honest position:

1. **Storage coverage (39%) is the binding constraint.** It is the weakest field and one of
   the four the completeness gate depends on, so it halves usable volume on its own.
2. **Enable `load_full_description` and re-measure before anything else** — §4.2 says it is
   worth +18.7pp on storage and +12.7pp on GPU, and it is a flag flip. Query 9 already has it
   on; the corpus just needs to accumulate. **Revisit in ~2 months** when most rows have one.
3. **Classification comes first.** 16% of the category is not a desktop.
4. Even at its best this is MedAPE 13.4% against MacBooks' 4.7% on comparable rows. A −25%
   alert threshold is ~1.9σ here versus ~3σ there, so the same rule is far weaker evidence.
5. The seller-aware machinery does not transfer (§3); sigma must come from spec completeness.

The most valuable next experiment is not a better model — it is the external GPU benchmark
scale from §6, plus re-running §4.1 once full descriptions have accumulated.

## 9. Reproduction

Read-only against the production Postgres; nothing was written. Scripts in
[`experiments/price_model/pc/`](../../experiments/price_model/pc/) — throwaway analysis,
excluded from ruff and mypy, needing `poetry install --with ml`. The corpus is not committed
(seller names, publisher ids).

| script | what it does |
|---|---|
| `pcfeat.py` | the extractor — kind classification, GPU/CPU name parsing, memory and storage, condition flags |
| `pcmodel.py` | design matrix, the grouped-CV harness, the component decomposition |

```sql
COPY (SELECT a.*, d.status FROM bazos_ad a
      JOIN bazos_addelivery d ON d.ad_id = a.id WHERE d.query_id = 9) TO STDOUT WITH CSV HEADER;
```
