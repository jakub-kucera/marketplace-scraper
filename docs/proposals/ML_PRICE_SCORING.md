---
title: ML price scoring — design and deployment
status: shipped
shipped_in: bazos/pricing/, migration 0037 · c3ca486, de41c15, 777c36e, 0d90a42
updated: 2026-09-18
verified: 2026-09-18
---

# ML price scoring — design and deployment

> ✅ **Built, 2026-08-26 - this is now the spec the code was written from, not open work.**
> `bazos/pricing/` (Protocol, `MODEL_REGISTRY`, JSON artifacts, `score_ad`), `AdPriceScore`
> (migration `0037`), the `price_model` rule and `manage.py train_price_model` all exist, and
> `PRICE_MODEL_SHADOW_MODE` still ships `True`. Three things landed differently or later than
> written, each noted inline: §2's model gained a `features` JSON column, §5's
> `PRICE_MODEL_SELLER_KAPPA` was never a constant, and §5's two thresholds are now resolved
> per query → settings → const. §6's caveat was re-based on 2026-09-18 production data: P24 has
> since shipped, and precision still is not measurable, for a different and smaller reason.
> Known defects live in [`PRICE_MODEL_DEFECTS.md`](../backlog/PRICE_MODEL_DEFECTS.md), not here
> - including that shadow mode is **off in production** against the `True` default below.
>
> Turns the offline MacBook price model
> ([`MACBOOK_PRICE_MODEL.md`](../research/MACBOOK_PRICE_MODEL.md)) into a deployable part of
> the pipeline: score a listing against what its specs are worth, persist the number, and
> alert when a listing is far enough below it.
>
> **Relationship to [`PROMPTS.md`](../backlog/PROMPTS.md) P23 — this extends it, it does not
> supersede it.** P23 specifies a median-of-comparables rule; this specifies the *frame* that
> holds any price estimator, and P23's median becomes one registry entry inside it. Every
> P23 requirement is honoured: per-query opt-in via `filter_rule_names` (step 1), a minimum
> sample size below which it PASSes (step 2), honest scoping (step 3), the computed number
> persisted rather than branched on (step 4), the baseline guards (step 5), and shadow mode
> before gating (step 6). If P23 is implemented after this, it should be implemented *as*
> a `PriceModel`, not as a second parallel mechanism.

## 1. Where it belongs

### 1.1 The seam the problem already has

Two different questions are being conflated by "add a price model":

| Question | Scope | Existing home |
|---|---|---|
| *What is this listing worth?* | one **`Ad`** — a fact about a real-world listing, true regardless of who is watching | `Ad` (marketplace-global, per-listing) |
| *Is that cheap enough to tell me about?* | one **`AdDelivery`** — a per-`(ad, query)` decision, and different queries can want different thresholds | `AdDelivery` + `bazos/filters.py` |

That is exactly the `Ad`/`AdDelivery` split CLAUDE.md describes, and the design follows it:
**scoring is an enrichment of `Ad`; alerting is a filter decision on `AdDelivery`.**

### 1.2 The options, weighed

**(a) A `FilterRule` in `bazos/filters.py`** — the JOB_QUEUE objection is worth taking
seriously: `run_filter` holds `select_for_update(skip_locked=True, of=("self",))` across a
batch of `FILTER_BATCH_SIZE = 50`, and [`JOB_QUEUE.md`](JOB_QUEUE.md) rejects putting blocking
work inside that window. But the objection there is aimed at **serial network I/O** (the
per-ad LLM call in `LLM_AD_REVIEW.md`), not at CPU. Model inference here is a dict → feature
vector → one `predict()` on a single row: sub-millisecond, against a process-cached estimator
loaded once at first use. A 50-ad batch adds tens of milliseconds to a transaction that is
already doing 50 rows of DB work. **This does not violate the JOB_QUEUE constraint** — but the
distinction must stay true, so the Protocol in §3 forbids network access in `predict()`, and
that is stated as a contract rather than left to convention.

**(b) A separate pipeline stage** (`run_scorer`, a new status between `PENDING` and the
filter) — architecturally tidiest, and wrong for now. It costs a fourth `docker-compose`
service, a new `AdStatus` member that every stage and every test touching the state machine
must learn, and a new race (two pollers on `PENDING`). It buys isolation that inference does
not need. It becomes the right answer if scoring ever grows network I/O or seconds-scale
latency; §7 says what would trigger the move.

**(c) Enrichment at scrape time** — guarantees a score exists before the filter runs, with no
ordering problem at all. Rejected: `run_scraper` is the latency-critical path
(`MONETIZATION.md` §7.1) and the process whose resilience CLAUDE.md is most protective of. A
model artifact failing to load must not be able to wedge scraping.

**(d) Chosen: (a), with the score persisted as an `Ad`-scoped side effect.** The rule computes
the score if it is missing, writes it to `AdPriceScore`, then decides. Because the score is a
pure function of the ad and the model version, two deliveries of the same ad racing to compute
it converge on the same value; the unique constraint makes the write idempotent.

The ordering problem that (b) and (c) exist to solve **does not arise**, because the rule that
needs the score is also the thing that computes it.

### 1.3 What "sent to the alerts channel" means

`Query.sender` is per query, so a single query cannot route deals to one channel and
everything else to another. The shipping shape is therefore **a dedicated `Query` whose sender
is `bazos-alert`, with `price_model` in its `filter_rule_names`** — on that query the rule
REJECTs anything that is not a deal, so the channel only ever sees deals. Query 15 (the
`M3 Pro`-or-better query) is already set up this way. Splitting one query's output across two
channels would need a per-rule sender, which is out of scope and probably belongs to
[`DISCORD_BOT.md`](DISCORD_BOT.md) instead.

## 2. Where the score is stored

**A new child model of `Ad`, `AdPriceScore`** — not a field on `Ad`, and not on `AdDelivery`.

- **Not `AdDelivery`**: the score does not vary by query. Putting it there would recompute and
  duplicate it per watching query, which is the exact mistake the `Ad`/`AdDelivery` split was
  made to fix.
- **Not a plain field on `Ad`**: one number is not enough. A score is only interpretable
  alongside *which model and which version produced it*, the predicted price, and the gate
  outcomes. `Ad` is also re-read on every pass and rendered on an admin changelist that has
  already had to be tuned for cost (`QueryAdmin.get_queryset`), so widening that row is the
  thing to avoid. And a second model scoring the same ad later would need a second column.
- **A child table** is the pattern `PriceChange` already establishes for exactly this shape:
  append-only detail hanging off `Ad`, queryable, and not in `Ad`'s hot path.

```python
class AdPriceScore(TimeStampedModel):
    ad             = FK(Ad, related_name="price_scores", on_delete=CASCADE)
    model_name     = CharField(64)      # registry key
    model_version  = CharField(32)      # artifact version that produced this
    predicted      = BigIntegerField(null=True)   # CZK; null when the model declined
    residual_log   = FloatField(null=True)        # ln(price) - ln(predicted)
    discount_pct   = FloatField(null=True)        # (1 - price/predicted) * 100, for humans
    z_score        = FloatField(null=True)        # seller-aware, null when no baseline
    declined_reason= CharField(255, null=True)    # why the model returned nothing
    # unique (ad, model_name) — one current score per model per ad
```

**As built**, plus two columns this sketch does not have: `seller_prior_ads` (which sigma prior
was picked) and `features` (JSONField, the parsed inputs the prediction came from). `features`
is JSON rather than columns because the feature set is the *model's* vocabulary, not this
table's, and it is what answers "why did it think this was cheap" - extraction, not model
class, is the measured weak point
([`PRICE_MODEL_BENCHMARK.md`](../research/PRICE_MODEL_BENCHMARK.md) §3.1). It came later, which
exposed the freshness trap `score_ad`'s docstring now carries: the check keys on the *artifact*
version, so a code-written column never backfills on its own and needs `manage.py rescore_ads`.

`unique(ad, model_name)`, not `(ad, model_name, model_version)`: the question asked at read
time is "what does the current model say about this ad", and keeping one row per model per ad
bounds growth. A re-score with a new version overwrites and `model_version` records which one
won. (If score history ever matters — it will, once there are calibrated outcomes to score
against, see §6 — the honest change is to drop the constraint and add an `is_current` flag, not
to bolt history onto this shape.)

## 3. Modularity — the registry

Mirrors the two registries this codebase already has (`MarketplaceScraper`/`_build_scrapers`
and `RULE_REGISTRY`/`build_rule_engine`), because a third bespoke shape would be a worse
answer than a third instance of a proven one.

```python
@dataclass(frozen=True)
class PricePrediction:
    predicted: int              # CZK
    residual_log: float
    z_score: float | None
    seller_prior_ads: int

class PriceModel(Protocol):
    name: str                   # registry key, stored on AdPriceScore.model_name
    version: str                # artifact version, stored on AdPriceScore.model_version

    def applies_to(self, ad: Ad) -> bool:
        """Cheap, no DB, no network. Marketplace + product targeting."""

    def predict(self, ad: Ad) -> PricePrediction | None:
        """None means 'I decline to score this'. MUST NOT perform network I/O."""
```

`applies_to` is what makes a model self-describing rather than needing a config table: a
MacBook model claims `marketplace == BAZOS and looks_like_macbook(ad)`. Adding a model for
another category or marketplace is a new registry entry, exactly like adding a scraper.

```python
MODEL_REGISTRY: dict[str, PriceModel] = {...}

def get_price_model(ad: Ad) -> PriceModel | None:
    """First registered model that claims the ad. Deterministic by insertion order."""
```

**The estimator is swappable by construction.** `MacbookPriceModel` holds an *estimator*
loaded from an artifact; whether that is a linear model, a median lookup or a gradient-boosted
tree is a property of the artifact, not of the code. A parallel benchmark is deciding which
estimator is best; nothing in this design depends on the answer, and a P23-style median
baseline that needs no artifact at all is a legitimate registry entry
(`MedianComparablesModel`) that can ship first and be swapped later.

## 4. Model artifacts and deployment

### 4.1 The constraint that decides it

**There is no `numpy`, `scikit-learn`, `scipy` or `joblib` in `pyproject.toml`'s production
dependencies.** The runtime image is Django + requests + bs4 + psycopg2 and nothing numeric.
Shipping a pickled sklearn estimator therefore does not cost "an artifact" — it costs
**adding the entire scientific Python stack to an ARM64 Raspberry Pi image**, where scipy and
sklearn are among the heaviest wheels to install and the slowest to build if a wheel is
missing. That is a large, permanent increase in image size and build time, taken on behalf of
a model with a few dozen coefficients.

So the decision is not "pickle vs JSON, pick the tidier one". It is:

**Train with sklearn offline; export the fitted model to JSON; serve it with pure Python
arithmetic and no numeric dependencies at all.**

### 4.2 The format

```
bazos/pricing/artifacts/<model_name>/<version>/manifest.json
```

One file. It carries the feature specification and the coefficients as plain numbers, so
inference is a dot product the standard library can do:

```json
{
  "name": "macbook", "version": "2026-08-26", "kind": "linear",
  "target": "log_price",
  "intercept": 8.91,
  "features": [
    {"kind": "num",     "name": "year",     "fill": 2020.0, "coef": 0.0871},
    {"kind": "missing", "name": "year",                     "coef": -0.0412},
    {"kind": "cat",     "name": "chip_key", "value": "apple3_max", "coef": 0.5533},
    {"kind": "bool",    "name": "warranty",                 "coef": 0.0219}
  ],
  "residual_sigma": 0.125,
  "seller_sigma_prior": {"0": 0.294, "1": 0.219, "3": 0.172, "10": 0.143, "50": 0.065},
  "kappa": 12.0,
  "trained_at": "...", "n_train": 2038, "metrics": {"r2_seller_grouped": 0.87}
}
```

Every entry is `(feature spec, coefficient)`, so the model is **reviewable in a diff** — a
retrain shows up as changed numbers in a pull request rather than an opaque binary blob.

### 4.3 Why, against the alternatives

| Option | Verdict |
|---|---|
| **JSON coefficients, pure-Python inference** | ✅ **chosen.** Zero new production dependencies, no pickle-compatibility surface at all, human-reviewable, tiny. Ships atomically with the code via the existing `git tag v*` → `docker build` path. |
| **joblib/pickle of an sklearn estimator** | ❌ **not today.** Requires numpy+scipy+sklearn in the ARM64 image, and sklearn does not guarantee unpickling across versions — the failure mode is often silent degradation rather than an exception. The loader keeps a `kind` field so this can be added later if a non-linear estimator ever earns its cost; the extension point exists, the dependency does not. |
| **ONNX** | ❌ same objection, heavier: `onnxruntime` on a Pi to evaluate a linear model. |
| **A mounted volume** | ❌ breaks the property that makes the current deploy safe — a tag is a complete, reproducible artifact. A model on a volume is unversioned mutable state no rollback reaches. |
| **Re-fit on boot** | ❌ needs sklearn in prod (same objection), makes the same image score differently week to week, and moves training cost into a process that must start reliably. |
| **Coefficients in a DB table** | ❌ decouples the model from the tag that deployed it, so code and model can disagree after a rollback. The repo is already the versioning mechanism. |
| **git-LFS** | ❌ unnecessary at this size and a new tool in the deploy path. |

**This constraint also narrows the estimator choice**, and in a useful direction: any model
that can be written as `intercept + Σ coef·feature` — linear, ridge, lasso, elastic-net — ships
for free. A gradient-boosted tree does not, and would have to justify the whole numeric stack
to earn its place. The parallel benchmark comparing linear against the gradient-boosting
incumbent is therefore not only a question of accuracy: **linear has a large deployment
advantage here that a small accuracy edge would not overturn.** If a tree model wins by a wide
margin, the honest options are (a) accept the dependency cost deliberately, or (b) export the
tree to JSON as thresholds and leaf values, which is mechanical for a small forest — not
(c) quietly add sklearn to prod.

### 4.4 Version skew

Largely designed out: JSON coefficients cannot suffer pickle skew. The manifest still records
`sklearn_version` and `trained_at` for provenance, and the loader validates the manifest
*shape* (required keys, known `kind`, parseable numbers). An artifact that fails validation
makes the model **decline to score** — logged at ERROR — rather than return numbers nobody
should trust. A declining model is inert: the rule PASSes, the pipeline runs, nothing is
wrongly rejected.

### 4.5 Which model produced a score, and rollback

`AdPriceScore.model_version` records it per row, so a bad model is identifiable after the fact
— `AdPriceScore.objects.filter(model_version="...")` is the blast-radius query.

The active version is a setting (`PRICE_MODEL_VERSION`, default `"latest"`, resolving to the
highest version directory present). Rollback has three levers, fastest first:

1. **Drop `price_model` from the query's `filter_rule_names`** — takes effect on the next
   batch, no deploy, no restart.
2. **Set `PRICE_MODEL_VERSION` to the previous version** and restart the filter service —
   seconds, no rebuild, works because artifacts are additive in the repo and old versions stay
   shipped.
3. **Deploy the previous `v*` tag** — the standard path, if the code and not just the artifact
   is at fault.

## 5. The threshold, and what gets sent

Two stages, both from measurements in
[`MACBOOK_PRICE_MODEL.md`](../research/MACBOOK_PRICE_MODEL.md):

**Gates first (§4 of that doc — they removed 70% of what a naive threshold fired on):**

- all four specs parsed (year, chip, RAM, SSD) — MedAPE 4.7% when they are, 12.3% when not
- no damage vocabulary in the listing text
- price strictly above the query's `price_lower` floor (the floor is 9.2× enriched for junk)

Any gate failing ⇒ the model **declines**, the rule PASSes, nothing is rejected on a number
that was never trustworthy.

**Then a seller-aware z-score, not a flat percentage.** A flat −25% is ≈0.95σ for a private
seller but ≈2.92σ for a high-volume dealer — the same rule meaning "ordinary noise" for one
and "genuinely exceptional" for the other. The z-score uses a per-seller residual σ shrunk
toward a prior that depends on seller maturity (a first-time seller is ~4.5× noisier than a
50-ad dealer), so the evidence standard is comparable across seller types.

**Shipping defaults** (`bazos/const.py`):

```python
PRICE_MODEL_SHADOW_MODE      = True    # compute and store, never reject
PRICE_MODEL_Z_THRESHOLD      = -2.0    # ~44% below for an unknown private seller, ~14% for a big dealer
PRICE_MODEL_MIN_DISCOUNT_PCT = 10.0    # and it must also be below market, not just below *this seller*
```

`MIN_DISCOUNT_PCT` exists because the z-score alone answers "cheap **for this seller**", which
a systematically expensive shop can satisfy while still being above market. Requiring both
makes a deal mean cheap on both bases.

**As built**, three corrections to the block above. `PRICE_MODEL_SELLER_KAPPA` is not a
constant and never was: the shrinkage is baked into the artifact, which ships a
`seller_sigma_prior` table (`{0: .3129, 1: .2993, 3: .2414, 10: .1872, 50: .1129}` in
`macbook/2026-08-26`) that `Manifest.sigma_for` reads by lower-bound key - so retuning it is a
retrain, not a setting. Only `PRICE_MODEL_SHADOW_MODE` is env-overridable
(`scraper/settings.py`), alongside `PRICE_MODEL_VERSION` from §4.5; the two thresholds are not.
What they gained instead is a level *above* settings: `Query.filter_price_model_z` and
`Query.filter_price_model_min_discount` resolve **per query → settings → const**, both nullable
so "untuned" stays distinct from "tuned back to the default", and both audited in
`TRACKED_CONFIG_FIELDS`.

## 6. Shadow mode, and what this cannot tell you

`PRICE_MODEL_SHADOW_MODE = True` ships as the default. In shadow mode the rule computes and
persists the score and then always returns `PASS` — nothing is rejected, notifications are
unchanged, and the scores accumulate for analysis. This is P23 step 6, and it is the default
rather than a flag someone remembers to set.

**Precision still cannot be measured, and this design must not be read as implying otherwise.**
The reason has changed since this was written, and only the reason. The original one - the
database records no outcome of any kind, because `Ad.modified` never advances past
`Ad.created` - is obsolete: P24 shipped (`5856bf0`), so `Ad.last_seen_at` / `Ad.removed_at` are
populated by the delisting sweep and `AdOutcome` exists to record what a human actually did.
The conclusion survives anyway, for three narrower reasons, all measured on production
2026-09-18 (30 037 ads):

- **`removed_at` is a confounded proxy, on purpose.** It conflates sold, withdrawn, deleted and
  expired, which is why there is deliberately no `sold` boolean and why an ad past
  `DELIST_MAX_AGE_DAYS` is left NULL as a censored observation. "Disappeared quickly" is not
  "sold quickly" until something says how often the two coincide.
- **The thing that would say so is empty.** `AdOutcome` holds **0 rows**.
- **And the proxy itself is currently corrupt.** `BazosApiScraper.fetch_by_ids` sends a batch of
  210 ids with **no `limit`** - unlike `_fetch_page`, which sends `limit=API_PAGE_SIZE` - so
  `ads.php` returns its default page of 30 and the ~180 ids it leaves out are read as delisted
  and written as removals. Production survivors per minute-bucket are all exact multiples of 30,
  which is that arithmetic in the open: roughly **86% of every batch is falsely marked removed**,
  out of the 19 008 ads that carry a `removed_at`. Nothing corrects it - `due_for_check` skips
  ads that already have a `removed_at` - so the bad rows are permanent and are a hazard for any
  later outcome study. **Open as of 2026-09-18.**

So the gate is no longer "P24 must ship". It is **"fix the sweep, then get rows into the
logbook"**, which is a smaller and more tractable obstacle than a missing feature: one query
parameter, a decision about the rows already written, and then a few dozen honestly-recorded
`AdOutcome` rows are enough to estimate how often a removal was a sale, which is what turns
time-to-disappear into a signal a threshold can be calibrated against. Until then every
quality figure available is still a *composition* audit ("what fraction of what it flags is visibly broken"), not a
measurement of whether it finds deals, and the thresholds above stay a defensible starting
point rather than a tuned one. Leaving shadow mode is a judgement call, not a result.

## 7. Training

`bazos/pricing/training.py` + `python manage.py train_price_model <name> [--version V]`.

- **Training set**: `Ad` rows for the target marketplace/product with `price_type = EXACT`,
  joined to deliveries only to scope by query. Ads with an unparseable spec are kept — their
  missingness is a feature, and dropping them biases the training set toward well-written ads.
- **Validation**: grouped by seller, never random. 56% of the corpus comes from ten dealers
  relisting the same inventory, so a random split reports a model that does not exist
  (R² 0.925 leaky vs 0.873 honest).
- **Output**: writes the artifact directory and `manifest.json`, including the held-out
  metrics, so a model's claimed quality travels with it.
- **Cadence**: manual. Not scheduled, and deliberately not automatic — an automatically
  retrained model that silently drifts is worse than a stale one whose numbers are known.

## 8. What would change this design

- **Scoring grows network I/O or seconds-scale latency** (an LLM judge, an external price
  API) ⇒ move to §1.2(b), a separate stage, and the JOB_QUEUE objection becomes binding.
- **More than a handful of models, or per-query model selection** ⇒ `applies_to` stops being
  expressive enough and model selection wants a DB table.
- ~~**P24 lands**~~ **The outcome logbook fills** ⇒ thresholds become tunable against outcomes,
  and `AdPriceScore` probably needs score history rather than one current row per model. P24
  itself landed on 2026-09-17; what it produced is a *proxy* that is not yet calibrated, so the
  trigger is `AdOutcome` rows rather than the sweep existing - see §6.
