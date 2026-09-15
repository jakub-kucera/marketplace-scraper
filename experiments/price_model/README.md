# Price-model analysis scripts

Throwaway analysis behind the MacBook price-model research, kept because the docs cite it.
Same status as `../bench_proxy.py`: **not runtime code** — `experiments/` is excluded from
ruff and mypy in `pyproject.toml`, and nothing here is imported by the app.

The durable output is the docs; these are here so the numbers can be re-derived.

## Running them

They need pandas / numpy / scikit-learn, which are **not** app dependencies — serving
evaluates a JSON manifest in pure Python (`docs/proposals/ML_PRICE_SCORING.md` §4.1).
Install the optional group:

```bash
poetry install --with ml
```

Most scripts read a corpus pickle (`mb/ds.pkl`) built by `build_ds.py` from a CSV export of
`bazos_ad ⋈ bazos_addelivery`. **That data is deliberately not committed** — it carries
seller names and publisher ids. Re-export it with `xm/export.sql` against a read-only
connection, or point `training_rows()` at the DB instead.

**`common/ph.py` is the exception to everything above**: it takes a query id and reads the CSV
path named at the top of the file, and it is the one module here meant to be imported rather
than run. Paths inside the *other* scripts still assume the flat scratchpad they were written in; expect to
fix a path or two before anything runs.

## What belongs to what

| Script | Doc |
|---|---|
| `mbfeat.py`, `mbfeat_fix.py` | the regex spec extractor, before and after the M5 / `128GB` repairs. The shipped version is `bazos/pricing/features.py` |
| `build_ds.py`, `build_ds_fix.py`, `harness.py`, `seller_base.py` | corpus build, the time-causal replay harness, seller identity |
| `look1.py`–`look3.py`, `model1.py`, `model2.py`, `deals.py`, `conformal.py` | `docs/research/MACBOOK_PRICE_MODEL.md` §2–§4 — extraction coverage, the split-strategy comparison, the underpriced-tail audit, interval calibration |
| `part1.py`–`part3c.py`, `ksweep.py`, `mkbase.py` | same doc §5.3–§5.7 — seller tiers, the dealer scorecard, partial pooling and the κ sweep |
| `score_one.py` | scoring a single live ad against the corpus |
| `bm_*.py` | `docs/research/PRICE_MODEL_BENCHMARK.md` — the 25-model ladder, nested CV, paired cluster bootstrap, diagnostics, coefficients, alert-funnel comparison. Entry point is `bm_run_ladder.py` |
| `xm/` | `docs/research/CROSS_MARKETPLACE_MACBOOK.md` — Vinted/Sbazar coverage, the Vinted fee fit, spec-matched comparison, pooled models |
| `common/ph.py` | `docs/research/CATEGORY_PRICE_MODELS.md` — **the shared feasibility harness, and the only file here written to be reused.** One validation protocol for every category, so the numbers are comparable across corpora instead of each script inventing its own split: `load`, `seller_key`, `design`/`design_ohe`, `grouped_cv`, `time_split`, `metrics`, `cluster_bootstrap_delta`, `alert_funnel`, `coverage`, `market_structure`. Its docstrings carry *why* each default is what it is |
| `pc/pcfeat.py`, `pc/pcmodel.py` | `docs/research/PC_PRICE_MODEL.md`. ⚠️ **`pcmodel.py` no longer runs**: `make_X` hands `cpu_model` to HistGradientBoosting at cardinality 275 and sklearn refuses a categorical above 255. It also imports `Ridge` and never calls it — see that doc's §5.2 retraction before trusting any linear number attributed to this file |
| `iphone/ipfeat.py`, `iphone/b0*.py`, `iphone/k0*.py` | `docs/research/IPHONE_PRICE_MODEL.md` — `ipfeat.py` is the extractor (570 lines, stdlib only: generation/tier/storage/battery and the condition flags); `b0*` are the ladder, segments, funnel, coefficients and bootstrap; `k0*` are the independent skeptic's re-derivation and the hand audit of the flagged tail. ⚠️ `ipfeat.py` ships with a **deliberately unfixed defect** at its `_NEG` definition — see the comment there and that doc's §7; it is left in so the published figures reproduce |
