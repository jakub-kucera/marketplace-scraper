---
title: Price-model defects found while surveying five new categories
status: active
updated: 2026-09-13
verified: 2026-09-13
---

# Price-model defects found while surveying five new categories

> Nine defects in shipped `bazos/pricing/` code, found while assessing five new categories
> (PC, golf, MTB, road bike, ski) as candidates for a second price model. **Scope: a
> read-only pull of the production database on `raspberrypi5.local`, 12,078 delivery rows /
> 11,948 distinct ads across 11 queries, created 2026-05-17 → 2026-09-12**, plus a direct read
> of the production `.env` and `Query` rows on the Pi, plus the repository at `ec52190`.
> Every claim below was re-derived against the shipped modules, not against a reimplementation.
>
> Only some of these are second-model problems. **`PRICE_MODEL_SHADOW_MODE` is `false` in the
> production `.env` against a shipped default of `True` (§12), so `PriceModelRule` is live on
> query 8 and §§3–6 and §8 are acting on real deliveries today.** The order below is risk, not
> effort.
>
> **Update 2026-09-13 — a second category study has now run against this surface.** The iPhone
> model on query 19 ([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md)) was built,
> measured and audited against the shipped modules, on **its own later pull — n=655, created
> 2026-09-09 → 09-12** (§14 carries what that narrower basis costs), and it adds four findings.
> They are **sub-numbered into the sections they belong to**, not appended, so
> every §-reference published elsewhere still points where it did: **§3.6** — a frozen `cat`
> level for a product generation goes blind when the next generation ships, silently and in the
> muting direction; **§4.1** — the damage gate has no negation handling and is the one gate in
> this package with a *measured* false rate; **§4.2** — the same defect running the other way in
> the experimental iPhone extractor, which is the pair that makes the lesson; **§8.1** — the
> registry collision measures at zero today only because Bazos truncates `short_description` at
> 254 characters (§10), not because the predicates are disjoint.
>
> It also changes §13's standing. **The iPhone model *is* the second model items 1–4 were
> written as prerequisites for**, so those four are blocking rather than hypothetical, and the
> study's own gates probe names three more that block *enabling* the rule as opposed to
> registering the model. And it relocates the safety argument: `MacbookPriceModel` declines 47
> of the 88 score rows it has written in production (§12), while a candidate iPhone model would
> score **87.5% of query 19** (573 of 655) — at that decline rate **the gates, not the
> estimator, are the entire safety story**, which is why three of the four new findings are
> about gates.
>
> Standing caveat, unchanged and binding on every number here: **`Ad.modified` never advances
> past `Ad.created`, so the database records ZERO outcomes** — no sold flag, no
> time-to-disappear. Every precision figure in this document is a composition audit, not a
> measurement. Nothing here establishes that a flagged listing is a bargain, or that a
> suppressed one was not ([`MACBOOK_PRICE_MODEL.md`](../research/MACBOOK_PRICE_MODEL.md) §6).

---

## 1. Summary

| Question | Answer |
|---|---|
| Does an artifact record what it was trained on? | **No — twelve keys, none about support.** A query's price floor moved under it and nothing anywhere noticed for 15 days (§3) |
| How bad was that, honestly? | **Disputed magnitude, agreed mechanism.** 13.0% of the feed (76/586) is now below the training floor; only 4–7% of predicted price is attributable to the truncation (§3.3) |
| Does `_gates_pass` implement the gate its docstring cites? | **No.** Three reasons named, two implemented; the floor test does not exist in the code (§4) |
| Is the floor effect MacBook-specific? | **No — 3.0–14.0× enrichment in all eleven corpora, no exception** (§4) |
| What happens when the next product generation ships? | **The model goes blind, silently, in the muting direction.** A held-out generation is under-priced by 73.8% and fires a −25% alert **0.0%** of the time; the shipped manifest has no `apple6_*` level, so an M6 Max would be priced at **27.2%** of its M5 Max sibling (§3.6) |
| Does the damage gate handle negation? | **No, and it is the only gate here with a measured false rate.** It fires on 28 of 655 iPhone rows (4.3%); **6–7 of those 28 (21.4–25.0%)** are ads saying the phone is *undamaged* (§4.1) |
| Which way does that fail? | **Safe — and the experimental iPhone extractor fails the opposite way**, passing cracked phones into 2 of 25 gated alerts. The two halves of one lesson (§4.2) |
| Is the MacBook/iPhone `applies_to` collision really zero? | **Yes, by accident.** The cross-family token is hidden behind the 254-character cut on 19 of the 20 query-8 ads that carry it; one `load_full_description` flip grows the surface ~20× (§8.1) |
| Does a price change invalidate a score? | **No, and nobody had reported it.** A listing that halves is re-filtered against its pre-drop residual — demonstrated end to end (§5) |
| Who lands in the widest sigma bucket? | **18.3% of the population actually scored**, where `z ≤ −2` demands a 46.5% discount — and the rule is inverted, so that is a REJECT (§6) |
| What does pinning one model's artifact version do? | **Disables every other model.** `load_manifest` returns None, `predict` declines, the rule PASSes — on a dedicated alert query, all-PASS means APPROVE (§7) |
| Does registry order already decide anything? | **Yes, today.** `MacbookPriceModel` claims 83 ads inside the PC query, 38 of which pass its gates; a *motherboard* scored at 8,814 CZK (§8) |
| What does the model actually read? | **A 254-character listing preview**, truncated on 75.0% of Bazos ads and 85.9% of query 8's (§10) |
| Does any test load the shipped artifact? | **No.** All three artifact tests monkeypatch `ARTIFACT_ROOT` to `tmp_path` (§11) |
| Is the live risk a muted feed or a noisy one? | **Noisy, bounded to a 40 km circle around Prague** by a distance filter configured on 2026-09-07 — except §5, which mutes (§12) |

---

## 2. Basis, and one trap in it

Three things about the evidence, stated once:

- **The corpus export is delivery-level, not ad-level.** 12,078 rows, 11,948 distinct
  `(marketplace, external_id)` pairs — 130 duplicated ads, 128 of them the query 8 / query 15
  overlap. Pooling queries without deduping inflates MacBook `n` by ~4%: the training-population
  reconstruction gives 2,295 undeduped against 2,255 deduped and the manifest's `n_train` of
  2,258.
- **Two independent runs disagree on one number** (§3.3). Where they do, both are printed and
  the basis difference is named. Where a number here contradicts a previously published one,
  the section says which basis moved.
- **`seller_prior_ads` counts the whole `Ad` table at call time**, so every bucket derived from
  the CSV is an undercount — 44 of 865 MacBook publishers change bucket when counted over all
  Bazos rows rather than MacBook rows only. Every firing rate in this document is therefore a
  **lower bound**.

---

## 3. An artifact records nothing about what it was trained on

`training.py::fit` returns the manifest dict at `bazos/pricing/training.py:141-153`, with its
metrics block built at `:114-119`. What it writes is `n_train`, `r2_seller_grouped`,
`medape_pct`, `estimator` and `trained_at`. What it does not write is **any description of the
population**: no price range, no date range, no contributing queries. The shipped artifact
`bazos/pricing/artifacts/macbook/2026-08-26/manifest.json` has exactly twelve keys —
`name, kind, target, intercept, features, residual_sigma, seller_sigma_prior,
seller_sigma_prior_n, metrics, estimator, trained_at, version` — and not one of them says what
it saw.

So `MacbookPriceModel.predict` (`estimators/macbook.py:70-101`) cannot know it is
extrapolating, and **any edit to any query's `price_lower`/`price_upper` silently moves the
serving distribution out from under every artifact.** There is no error, no log line and no
column anywhere that changes.

### 3.1 It has already happened

| Fact | Value |
|---|---|
| Artifact `trained_at` | **2026-08-26T00:54:46Z** |
| Query 8 min price, every day 2026-05-17 → 2026-08-27 | exactly 5,000 CZK (n=2,851 query-8 ads) |
| First sub-5,000 ad | **2026-08-28** |
| Hard floor of exactly 3,000 from | 2026-08-30 |
| Training rows below 5,000 | **0** (reconstruction n=2,255 vs manifest `n_train` 2,258) |
| Time the mismatch was visible anywhere | **none — 15 days to this audit** |

The reconstruction is `Ad.objects.filter(marketplace=bazos, price_type=EXACT, price>0)` filtered
by `applies_to` and `created <= trained_at`, i.e. `training.py::training_rows` replayed; hitting
`n_train` to within 3 rows is what makes "the support has a hard floor at exactly 5,000"
established rather than inferred. The 3-row gap is unexplained and does not matter: a floor is a
minimum, not a count.

**And it is a recurring operational pattern, not a one-off.** Query 9's floor moved
10,000 → 2,000 CZK on 2026-08-27 (one 1,800 ad on 09-02 is the only row below that since) —
*inside* the window
[`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md) trained and measured on. **Both categories
this project has modelled had their query's floor edited inside, or two days after, the window
they were modelled on.** A price floor is a routine admin edit; a training support is not
something an operator knows they are moving.

### 3.2 What the feed looks like now

Query 8, ads created 2026-08-28 onward, scored with the **shipped** artifact (these ads postdate
`trained_at`, so they are genuinely out-of-sample — stronger than out-of-fold):

| | n | share |
|---|---|---|
| post-change query-8 feed | 586 | — |
| below the training floor | **76** | **13.0%** |
| …of which pass `_gates_pass` and are actually scored | **50** | 15.7% of the 318 scored |
| in-support and scored | 268 | — |

| Measure (scored rows) | sub-floor (n=50) | in-support (n=268) |
|---|---|---|
| median residual | **−0.169 log (−15.6%)** | −0.015 |
| ≥25% below predicted | **26.0%** *(disputed — see §3.3)* | 5.6% |
| firing at query 8's live thresholds (`z ≤ −1.5` & discount ≥ 10%) | **34.0%** | 5.2% |

All three rows are from one run; the paired run gives −0.168 / 20.0% / 28.0% and −0.011 / 4.9% /
4.5%. The firing difference is the `seller_prior_ads` counting basis of §2, which moves sigma
buckets and therefore z.

The comparative claim, seller-clustered (6,000 bootstrap reps, 25 sellers vs 130): the fire-rate
delta is **+24.1pp, 95% CI [+10.9, +41.3]**, and the ≥25%-discount delta is +17.3pp,
CI [+2.7, +41.0] — the second only barely clears zero. The effect is not one bulk dealer: he
contributes 21 of the 50 rows at a median residual of −0.073 and 4.8% at ≥25%; the other 29 rows
run −0.208 and 31.0%.

### 3.3 The magnitude is disputed, and saying so is the point

Two runs evaluated the same 50 rows with the same shipped modules and **agree on the residual to
three decimals (−0.168 vs −0.169) while disagreeing on the ≥25% flag rate: 20.0% against 26.0%,
both n=50.** Since the residuals match on an identical row set, the counts cannot legitimately
differ by 3 rows, and neither side could explain it. Four obvious explanations were tested and
rejected (`disc ≥ 25 AND z ≤ −2` gives 12.0%; `AND z ≤ −1.5` gives 24.0%;
`resid ≤ ln(0.75)` gives exactly 13 rows). A third execution of the run that imports the shipped
modules reproduces 26.0% — but that is the same implementation run again, which establishes
reproducibility, not correctness. **Do not quote either figure without this sentence attached.**

### 3.4 The honest diagnosis is narrower than "mis-calibrated"

Measured on the **prediction side only**, so the ads' own prices never enter and the "cheap rows
have negative residuals by construction" tautology is avoided: a model refit **with** the
sub-floor rows included (n=1,952, 427 sellers, pooled OOF R² 0.9237, MedAPE 8.69%) predicts just
**6.5% lower** for those same rows. A better-powered placebo floor at 6,000, which has 193 rows
below it, gives **3.6%**. So roughly **4–7% of predicted price is attributable to the truncated
support** — the remaining −0.101 log is ordinary model error on a thin stratum.

> ⚠️ **Basis correction to the yardstick this comparison uses.** The artifact's published
> `metrics.medape_pct` is **10.14%**, and the first pass compared 6.5% against it. That 10.14%
> is a **mixed-population** number: `training.py:33-42` deliberately keeps incomplete-spec ads
> in training ("Their missingness is a feature") while `_gates_pass` refuses to score them at
> serving. Split by gate — on a replication of the exact pipeline (n=2,255, GroupKFold(5) on
> `email_publisher_id`, `Ridge(alpha=1.0)`, reproducing the manifest to within 0.04pp MedAPE and
> 0.005 R²) — it is **8.71% on the 1,582 rows the model actually scores** and 16.04% on the 673
> it refuses. The cushion is **1.34×, not 1.55×**. The conclusion holds, weakly. The same
> substitution is owed anywhere else in this project that quotes "the MacBook model's ~10%" as
> a house benchmark.

And the sub-floor rows are not what either offered explanation assumed. They are not broken
machines: **2% carry a defect flag**, 8% say "new". They are an **old-Intel cohort** — 90% Intel
with model year ≤ 2017, median year 2015 against 2020 in-support — that training covers well
(480 of 2,255 rows, 21%) **but only above 5,000 CZK** (p25 5,990, median 6,590).

**So the correct sentence is: the floor edit admitted a new price stratum into the alert queue.**
Not: the artifact became badly mis-calibrated. The two lead to different fixes, and the second
one leads to the wrong one — retraining moves the prediction ~6.5%, leaves −0.101 log on the
table, and has to be redone after every query-config edit. **The artifact is the wrong place to
track a mutable query parameter.**

### 3.5 The fix

1. A `training_support` block in the manifest — price min/max, `created` range, contributing
   query ids — written by `fit` (~8 lines) and carried on the `Manifest` dataclass in
   `artifacts.py`, plus one retrain.
2. A decline when the ad's price is outside that recorded support. This is exactly the contract
   the package already states — every uncertain path is neutral, never rejecting — and it
   degrades to "no opinion" rather than to a guess, which is what keeps working after the *next*
   query edit.

Note what this fix can and cannot reach: `PriceModel.predict` receives an `Ad` and nothing else
(`base.py:66`), so a model can only test its **own recorded support**. The *query's* floor is
filter-layer knowledge, and that is §4.

### 3.6 A frozen `cat` level goes blind when the next product generation ships

§3.1–§3.5 are about the *price* support moving out from under an artifact. This is the same
mechanism on the artifact's **feature vocabulary**, it needs no admin edit to fire, and the date
it fires is set by Apple rather than by anyone here.

`evaluate`'s `cat` branch (`artifacts.py:132-133`) contributes `coef` when the ad's value equals
the level's `value` and **0.0 otherwise**. There is no "unseen level" branch and no error. So a
generation the manifest has never heard of is scored as if that feature were switched off —
while `_gates_pass` waves the ad through, because the feature *parsed*.

Measured on iPhone, holding out a whole generation and scoring it with frozen one-hot generation
levels — the exact shape the shipped MacBook manifest uses — against a **live `gen_age_m`**
numeric the extractor computes at scoring time from a launch-date table
([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §5.1):

| held-out generation | n | frozen: bias | frozen: MedAPE | frozen: −25% flag rate | live: bias | live: MedAPE | live: flag rate |
|---|---|---|---|---|---|---|---|
| **17 (newest tested)** | 129 | **under-prices by 73.8%** | **74.2%** | **0.0%** | −3.1% | 10.1% | 4.7% |
| 16 | 78 | under-prices by 68.5% | 68.5% | 1.3% | +2.5% | 9.0% | 3.8% |
| 13 | 112 | under-prices by 26.0% | 26.0% | 2.7% | +0.8% | 14.3% | 9.8% |
| 11 (oldest tested) | 37 | **over**-prices by 26.0% | 43.3% | **64.9%** | +5.5% | 11.3% | 8.1% |

**The failure is silent and asymmetric.** An unseen *new* generation is under-priced by three
quarters, so its ads read as *dearer* than predicted, which on the inverted rule is a
`REJECT` — the model stops seeing the most expensive items on the market and calls it "not a
deal". An unseen *old* generation is over-priced and fires on two thirds of its rows. Neither
looks like an outage; nothing logs, nothing errors.

**And this is not an iPhone-only risk — it is already latent in the shipped artifact**, which is
the part §3 did not know. `bazos/pricing/artifacts/macbook/2026-08-26/manifest.json` carries
exactly 19 `chip_key` levels topping out at `apple5_*`, and 16 `year_cat` levels topping out at
`2027`:

| the day it fires | what parses | what the manifest has | the coefficient that goes to 0 | predicted vs the previous generation |
|---|---|---|---|---|
| an **M6** MacBook is listed | `APPLE_CHIP = m([1-9])` (`features.py:74`) matches, `chip_key = "apple6_max"` (`macbook.py:106-109`) | no `apple6_*` level | `apple5_max` **+1.3022** | **27.2%** — under-priced by 72.8% |
| the same, base tier | `chip_key = "apple6_base"` | no level | `apple5_base` +0.7046 | 49.4% |
| calendar **2027**, a 2028 model year | `_MAX_MODEL_YEAR = date.today().year + 1` (`features.py:100`) admits 2028, `year_cat = "2028"` (`macbook.py:115`) | levels stop at `2027` | `2027` +0.1597 | 85.3% |

**72.8% against the iPhone study's measured 73.8% is the same number arriving by two routes**,
and it is the M5-chip failure **one level up**. `APPLE_CHIP` was deliberately widened to `m([1-9])`
rather than bumped to `m([1-5])` so the next chip generation could not silently become
unparseable (`features.py:71-73`) — **but widening the extractor moved the failure into the
manifest, where there is no equivalent widening available.** The manifest cannot carry a level
for a chip that does not exist yet.

Two smaller things fall out of the same table, both counterintuitive:

- **An unknown level is treated worse than a missing one.** `missing` features fire only when
  the value is `None` (`artifacts.py:130-131`), and neither `chip_key` nor `year_cat` is ever
  `None` at that point — `year_cat` is the string `"na"` when the year did not parse
  (`macbook.py:115`). So a 2028 listing gets neither the `2028` level (absent) nor the `na`
  fallback (**+0.1554**, which an *unparsed* year does get). Failing to read the year is worth
  more than reading it correctly.
- The shipped manifest carries **no `missing` feature for `chip_key` at all**, so "chip unknown"
  is not expressible in it. `_gates_pass` covers the `None` case by declining (`macbook.py:129`);
  it does not cover the parsed-but-unknown case, which is the one that fires here.

**The fix costs no schema change and has a precedent in this file.** Carry an age-in-months `num`
feature the extractor computes at scoring time from a launch-date table: `num` already multiplies
a float (`artifacts.py:128-129`), and `features.py:100` already reads `date.today()`, so a
scoring-time computation is an established pattern here rather than a new one. Measured cost in
accuracy: **none** — ΔR² +0.0040, CI −0.0042…+0.0117, i.e. if anything better.

**And key the decline gate on an UNKNOWN generation, not a young one.** A youth gate is a
measured pure loss: declining generations under 12 months drops 21% of the corpus, makes residual
sd *worse* (0.252 → 0.269) and removes 4 of 54 flags, because the newest generation is the
best-modelled one in the corpus (gen 17 residual sd 0.178, flag rate 3.1%). "The extractor
resolved a model number my launch table has never heard of" is one `if`, costs nothing, and fails
closed on exactly the day it matters ([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md)
§5.1).

> The flag rates in the table above are composition, not precision. `Ad.modified` never advances
> past `Ad.created`, so "fires 0.0% of the time" says the alert goes quiet on that cohort, never
> that the cohort held no deals.

---

## 4. `_gates_pass` does not implement the gate its own docstring cites

`estimators/macbook.py:121-132`. The docstring names three reasons to decline, with the
measurement for each: incomplete specs (median error 12.3% → 4.7%), damage words (3.3× enriched
in the underpriced tail), and **"ads sitting exactly on a query's price floor are 9.2×
enriched"**. The body implements the first at `:129-130` and the second at `:131-132`.

**There is no floor test in the code.** The third reason is a sentence.

It is also the one that generalises. Share of ads within 1% of the query floor among the most
underpriced listings, against that corpus's own base rate — **all eleven corpora, no exception**:

| corpus | enrichment | | corpus | enrichment |
|---|---|---|---|---|
| PC (q9) | **14.0×** | | macbook-new (q15) | 7.3× |
| Bazos MacBook (q8) | 12.0× | | MTB (q16) | 5.8× |
| Sbazar MacBook (q14) | 10.2× | | Vinted MacBook (q13) | 5.2× |
| iPhone (q19) | 9.0× | | ski (q18) | 4.1× |
| golf (q11) | 8.6× | | headphones (q12) | 3.8× |
| | | | road bike (q17) | **3.0×** |

Median log-residual for floor ads runs −0.40 (MacBook) to −2.13 (golf, i.e. 88% below
prediction). The share of −25% alerts that *are* floor ads spans **0.9% (Vinted) to 29.8%
(headphones)**, with Bazos MacBook at 8.8% and PC at 7.0% — so this gate removes between a
thirtieth and a third of raw flags depending on the category, and never removes nothing.

**The floor is already known to the filter**: `PriceModelRule.apply` holds `delivery.query`
(`filters.py:272`) and `Query.price_lower` is right there. This is the cheapest precision gain
available in the whole pricing package — no model change, no retrain, no migration.

Two implementation notes, both load-bearing:

- Because `predict(ad)` has no query (§3.5), **the query-floor gate belongs in `PriceModelRule`,
  not in `_gates_pass`** — or `predict` grows a query argument, which changes the protocol for
  every model. Do not "fix the docstring's gate" where the docstring is without deciding that.
- `price_lower = 0` means "no filter" (see `PriceRangeRule`), so the gate must treat 0 as absent
  rather than as a floor everything clears.

> The most quotable line in the source evidence — "ads sitting exactly on the new 3,000 floor
> have a median residual of −0.643 and fire 50% of the time" — is **n=2**. It is a reason to
> build the gate, not a rate.

### 4.1 The damage gate *is* implemented — and it is the one gate here with a measured false rate

The floor gate is the one that is missing. The damage gate is the one that is present and wrong,
and until 2026-09-13 nobody had put a number on it.

`_DAMAGE` (`estimators/macbook.py:29-32`) is a plain substring tuple, tested at `:131-132`
against `norm(f"{ad.name} {ad.short_description or ''}")`. **Its own comment already states the
defect and then stops one word short of fixing it** (`:25-28`): terms with a common negated form
were deliberately excluded, because `bez poskozeni` ("without damage") contains `poskozen`. That
reasoning is right. It was simply not applied to the terms that stayed — `praskl` has exactly the
same negated form, and Czech phone listings use it constantly. Verified against the shipped
`norm` and the shipped tuple:

| listing text | means | `_DAMAGE` hit |
|---|---|---|
| `bez poškození` | without damage | — (correctly excluded) |
| `bez prasklin` | **without cracks** | **`praskl`** |
| `nikde není žádný škrábanec ani prasklina` | **nowhere is there a scratch or a crack** | **`praskl`** |
| `displej ani zadní sklo nejsou prasklé` | **neither the display nor the back glass is cracked** | **`praskl`** |
| `telefon nefunguje` | the phone does not work | — (**a false negative**: `nefunk` does not match `nefunguje`) |

Measured on query 19 (n=655, the iPhone corpus, run through the shipped modules rather than a
reimplementation): the tuple fires on **28 rows = 4.3%**, and of those 28 rows a hand
classification finds **7 negations (25.0%)**. A second, independent hand pass over the **same 28
rows** finds **6 (21.4%, quoted as "21%" in its own note)**. Both bases are identical — same
shipped tuple, same normalisation, same denominator — so the disagreement is **one row's
classification**, and neither pass named which. Print both, as §3.3 does; the defect is not in
dispute at either value.

**Because the rule is inverted, a false decline is harmless on an ordinary query, and that is
worth stating explicitly rather than leaving to inference.** The path:

```
"bez prasklin" -> _gates_pass False (macbook.py:131-132) -> predict returns None (:79-80)
   -> score_ad writes a declined row -> score.z_score is None
   -> PriceModelRule PASSes (filters.py:286-287)
```

A wrongly-declined ad is filtered exactly as if `price_model` were not enabled on that query at
all. One qualification, and only one: on a **dedicated deals-only query**, where
`filter_rule_names` is just `price_model`, all-PASS means APPROVE (§7), so there the same false
decline becomes a false *alert* — noise, not muting. Either way it costs precision, never a real
listing.

Contrast §4.2, which is the same class of defect failing the other way, and is not harmless.

### 4.2 The opposite failure, in the experimental iPhone extractor — and the pair is the lesson

`experiments/price_model/iphone/ipfeat.py:413` — the study's extractor, **not shipped code** —
does handle negation, with `_NEG = r"(?:bez|zadn\w*|nema|neni|nebyl\w*|nikde neni|krome)\s+…"`.
The `zadn\w*` alternative is there for Czech `žádný`/`žádné` ("none"). But `strip_diacritics`
(`bazos/pricing/features.py:26-27`) maps `zadní` (**rear**) and `žádné` (**none**) onto the same
stem, so **"zadní sklo je prasklé" — *the back glass is cracked* — parses as a negation and the
damage flag is suppressed.**

Measured: **6 of 26 crack-word rows missed, 5 of those 6 pass the gate, and 2 of the 25 gated
−25% alert flags are cracked phones the gate exists to stop — 8% of the funnel.**

**The fix is not deletion.** 15 of the 17 `zadn`+damage co-occurrences **are** genuine negations
(`žádné škrábance`), and one row — `displej ani zadní sklo nejsou prasklé` — needs both readings
at once. The disambiguator is the **intervening copula**: `žádný` is followed directly by a noun,
while `zadní X **je** prasklé` puts a verb between. Any real fix needs that test. The committed
copy carries the defect deliberately, under a `⚠️ KNOWN DEFECT` comment at `:400-412`, so the
published figures reproduce.

Put the two side by side, because neither half is the finding:

| | shipped `_DAMAGE` (`macbook.py:29-32`) | experimental `_NEG` (`ipfeat.py:413`) |
|---|---|---|
| negation handling | **none at all** | a regex, with a diacritic collision |
| measured error | fires on 28/655 (4.3%); **6–7 of 28 are negations** | **misses 6 of 26** crack-word rows; 5 pass the gate |
| direction | **over**-declines | **under**-declines |
| consequence | a real listing is not scored → PASS (noise on a deals-only query) | **a cracked phone is scored and alerted — 2 of 25 gated flags** |

**The generalisable point: negation handling in Czech is a correctness property of a gate, not a
nicety — and the two damage gates this project has written fail in opposite directions.** A gate
built by keyword matching over Czech listing text is wrong until someone measures its false rate
in both directions; neither of these two was, before this. Note also that
[`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md) §4.4 found the *same* family on desktops and
found the sign inverted: v1's `defect` flag fired on ads reading ~16% **more** expensive than the
corpus, because `bez poškození` and `pojištěním proti poškození` carry the vocabulary. That is
three independent corpora and three instances.

> The "2 of 25" is a composition audit of a 25-row flag set, and
> [`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §9 records that a single
> reclassification moves that set by 4 pp. `Ad.modified` never advances, so it says what those
> flags *are*, never what they were worth.

---

## 5. A stale price score survives a price change

Nobody reported this one, and it is aimed directly at what a deal alert is *for*.

The path, end to end:

1. `QueryRunner.run_existing_query` sees a re-listed ad whose `price_raw` differs, writes a
   `PriceChange`, updates `Ad.price` **in place**, and flips **every** delivery of that ad to
   `PRICE_CHANGED` (`bazos/scraping/query_runner.py:194-215`).
2. `run_filter` re-evaluates the delivery. `PriceModelRule.apply` calls
   `score_ad(delivery.ad)` — `filters.py:278`, no `refresh`.
3. `score_ad` short-circuits on `(ad, model_name)` when the stored `model_version` matches the
   artifact and **returns the existing row** (`bazos/pricing/scoring.py:41-42`).
4. Nothing invalidates on price. `scoring.py` is the only writer (`:63`), `rescore_ads` is the
   only caller that passes `refresh=True`, and **nothing in the codebase ever deletes an
   `AdPriceScore`.**

Demonstrated against real Postgres with a deterministic artifact (`intercept = ln(40 000)`,
shadow mode off, `filter_price_model_z = -1.5`), scoring an ad at 38,000 CZK and then halving it:

| step | predicted | discount | z | rule verdict |
|---|---|---|---|---|
| first score, price 38,000 | 40,000 | +5.0% | −0.26 | — |
| **after the drop to 19,000, via the real `PRICE_CHANGED` path** | **40,000 (stale)** | **+5.0%** | **−0.26** | **REJECT** — `not a deal: +5.0% vs predicted 40000, z=-0.26 (limits z<=-1.5, discount>=10%)` |
| the same ad with `refresh=True` | 40,000 | **+52.5%** | **−3.72** | would fire |

So a listing that drops 50% is rejected on the residual of the price it no longer has, and stays
that way permanently: `manage.py rescore_ads` is the only escape and must be run by hand.
`PriceDropRule` and `PriceModelRule` can therefore disagree about the same listing **by
construction** — the first sees the drop, the second cannot.

**The line that closes it is `filters.py:278`:**

```python
score = score_ad(delivery.ad, refresh=delivery.status == AdStatus.PRICE_CHANGED)
```

`AdStatus` is already imported (`filters.py:28`), so this is one line and no new import. The
deeper fix is the freshness key at `scoring.py:41-42`, which keys on the artifact version alone;
the docstring above it asserts the score "is a pure function of the ad and the model version",
and it is not — **it also depends on `ad.price` at first-score time and on the DB-wide seller
count at that instant.**

This is also the defect here whose direction of harm is **muting** rather than noise — §3.6,
added later, is the second, and it mutes a whole product cohort rather than one listing. It compounds
with the Vinted FX churn — `VintedScraper._map_item` builds `price_raw` from a converted total
and `query_runner.py:194` compares that **as a string**, so an exchange-rate move writes a
`PriceChange` and re-filters an ad whose seller changed nothing, while the score never moves.
That mechanism is code-confirmed; its scope is not measured.

**Now measured on a second corpus, on the alert it damages.** Re-scoring the iPhone study's 25
gated −25% flags against their *current* prices removes **4 of the 25 — including its single
best clean candidate**, taking the audited composition from 2 clean in 25 to **1 in 22**
([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §7.3). **Repricing moved that
alert's composition further than any threshold change tested against it did.** The standing
caveat still binds — 25 rows, and "clean" is a composition judgement, not an outcome — but the
direction is the one this section predicted from code alone.

---

## 6. `seller_prior_ads` counts one column, and failing means REJECT

`estimators/macbook.py:134-144` returns 0 whenever `ad.email_publisher_id is None`, and 0 selects
the widest sigma bucket. What the shipped manifest's buckets demand of an ad before `z ≤ −2`:

| seller prior ads | sigma | discount `z ≤ −2` demands | who lands here |
|---|---|---|---|
| **0** | **0.3129** | **46.5% below predicted** | unidentified sellers, and anyone with one ad |
| 1–2 | 0.2993 | 45.0% | |
| 3–9 | 0.2414 | 38.3% | |
| 10–49 | 0.1872 | 31.2% | |
| 50+ | **0.1129** | **20.2%** | high-volume dealers |

The same residual yields a z **2.8× smaller** in bucket 0 than in the 50+ bucket. `PriceModelRule`
fires only when `z ≤ z_limit` **and** `discount ≥ pct_limit` (`filters.py:299`), and **the rule is
inverted** — so a wider sigma is not "the z-score is disabled", it is a **REJECT**.

### 6.1 Get the denominator right

> **Basis correction.** The audit first reported "16.7% of the corpus". That is arithmetically
> right — 2,001 of 11,948 rows are `bazos_api`/`vinted`/`sbazar`, 100% null on both publisher
> columns — but it is the **least relevant of four possible denominators, because
> `applies_to` returns False unless `marketplace == BAZOS` (`macbook.py:64-66`), so no
> non-Bazos ad is scored at all today.** The population exposed to the defect is the one that
> gets scored.

| denominator | share in sigma bucket 0 |
|---|---|
| non-Bazos share of the corpus (the original claim) | 16.7% (2,001/11,948) — **but none of it is scored** |
| Bazos ads with no `email_publisher_id` | 7.1% (711/9,947) — **every one of which has a phone id** |
| Bazos MacBooks with no email id | 3.7% |
| **the population actually scored** (gate-passing Bazos MacBooks, n=1,952) | **18.3%** |

Only 3.7pp of that 18.3% is "no publisher id". The remaining ~14.6pp is **"an identified seller
whose only ad in this DB is this one"** — a different state, which the code collapses into the
same bucket as an anonymous seller.

### 6.2 Two fixes of different sizes, and two smaller notes

- **(i) Key the seller `email` else `phone` else none**, matching
  [`PRICE_MODEL_BENCHMARK.md`](../research/PRICE_MODEL_BENCHMARK.md) §2.1 and the analysis
  harness `ph.seller_key`. Measured: recovers an identity for all 711 phone-only Bazos ads and
  moves 2.1pp of MacBook-claimed ads (~62 rows) out of the widest bucket.
- **(ii) For a marketplace with no identity at all, decline or carry a sigma from spec
  completeness** — do **not** silently borrow a seller-maturity prior. The PC study's own sigma
  source is completeness — re-measured, σ runs 1.021 at zero parsed specs to 0.316 at four
  ([`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md) §5.1; the published 0.224/0.524 pair is
  the superseded 2026-08 basis) — because desktops are a private-seller market where the maturity
  machinery does not transfer.
- The `COUNT` is **unscoped by marketplace and category**, so a dealer's 500 phone-accessory
  listings buy their one MacBook the narrowest sigma in the table.
- The `COUNT` is **not time-causal**, while the manifest's buckets were fitted on time-causal
  counts (`training.py:129-139` counts `n_before`). Under `rescore_ads` the serving side uses the
  seller's *total*, so rescoring systematically picks **narrower** sigmas than training assumed,
  which inflates |z| and therefore alert volume. The prior is not estimated on the variable it is
  applied to.

---

## 7. `PRICE_MODEL_VERSION` is one global string

`scraper/settings.py:226`, read by every estimator's `__init__`
(`estimators/macbook.py:41`), and `MODEL_REGISTRY` instantiates its models at import
(`registry.py:14-16`). A second model would resolve its artifact against the same string.

Verified by hand: `load_manifest("macbook", "2026-08-25")` returns **None** — it does not fall
back to a version that exists, it logs one ERROR (`artifacts.py:99-103`) and gives up.

**State the direction of the failure, because that is the part that matters:**

```
mis-pinned version → load_manifest None → predict declines (macbook.py:73-74)
                   → PriceModelRule PASSes (filters.py:286-287)
```

On an ordinary query that is harmless. **On a dedicated deal-alert query — the case the feature
exists for, where `filter_rule_names` is just `price_model` — all-PASS means APPROVE**
(`RuleEngine`, `filters.py:334-339`), so a rollback intended to quiet one model turns the alert
channel into a firehose and silently disables every other model on the way. The package's stated
invariant (`filters.py:267-268`: "a model that cannot score must not be able to silently drop
everything") is safe in exactly one direction, and nobody has written down the other one.

Fix before the second model lands: a dict setting (`{"macbook": "2026-08-26"}`) or a per-model
env var. That keeps [`ML_PRICE_SCORING.md`](../proposals/ML_PRICE_SCORING.md) §4.5's rollback
lever working at N>1.

---

## 8. Registry ordering silently decides which model claims an ad — already, today

`get_price_model` (`registry.py:19-23`) returns the **first** model whose `applies_to` is true. It
logs nothing, and `score_ad` writes one row, so **nothing anywhere records that another model
also claimed the ad.** Reordering the dict literal between deploys re-labels ads with no
migration, no log line and no error.

This is not hypothetical at N=1:

| measure | value |
|---|---|
| ads `MacbookPriceModel.applies_to` claims | **2,954 / 11,948 (24.7%)** |
| …in query 8 / query 15 / **query 9 (the PC query)** | 2,740 / 131 / **83** — ad-level, so each of the 128 ads both MacBook queries deliver is counted once |
| of those 83, passing its gates — i.e. scored the moment query 9 enables the rule | **38** |
| ads matching ≥2 of seven plausible category patterns | 206 (1.7%); `pc × macbook` 88 |
| claimed only because of dealer boilerplate in `short_description` | 22 (0.7%) — Dell XPS 15, ThinkPad T14, Surface Pro 11, EliteBook |

**A live gate-contamination example, in production:** the listing *"Základní deska Apple MacBook
820-01041 A1990"* — a **bare logic board**, 6,000 CZK — is claimed by `MacbookPriceModel`, passes
its gates, and scores at **predicted 8,814 CZK, discount +31.9%, z −1.59** on the production
seller bucket (the same residual is z −1.23 in bucket 0 — §6's bucket choice is worth 0.36 of z
on this one ad). At query 8's live thresholds (`z ≤ −1.5`, discount ≥ 10%) that **fires**. It did
not reach Discord only because `location_distance` runs before `price_model` in `RULE_REGISTRY`
(`filters.py:340-347`) and rejected it first. The gate that should have caught it is a product
gate, not a price gate, and no product gate exists.

Fix, ~20 lines: a `marketplaces: frozenset[str]` attribute on the `PriceModel` protocol
(`base.py:42-68`) that `get_price_model` checks **before** calling `applies_to`, plus a registry
test asserting that no two registered models claim the same fixture ad and that insertion order
is the documented tiebreak. That converts a silent reassignment of 3.5% of a query into a test
failure.

> Note for P23's re-scoped catch-all: registering a broad model last converts "unclaimed" into
> "claimed and declined" for everything, taking `AdPriceScore` writes from 24.7% of new ads to
> **100%**, each inside `run_filter`'s `select_for_update` transaction, and taking
> §6's unscoped `COUNT` with it.

### 8.1 At N=2 the collision measures at **zero** — and only because of §10's 254-character cut

The iPhone gates probe measured this section's question directly, in both directions — the
corpus-wide rows over §2's 11-query / 11,948-ad pull, the query-19 row over the iPhone study's
own later 655-ad pull (§14; §10's table counts 613 q19 rows in the earlier one):

| direction | claims |
|---|---|
| `MacbookPriceModel.applies_to` on query 19 | **0 of 655 (0.0%)** — not one q19 row carries a `macbook` token in `name + short_description` |
| a naive iPhone `applies_to` (iPhone token, `marketplace == BAZOS`), corpus-wide | 620 of 11,948 (5.2%) — 3 in q8, 5 in q9, 1 in q17 |
| …of which `MacbookPriceModel` **also** claims | **7 ads, double-claimed today** |

So at N=2 the answer looks reassuring. **It is not a property of the predicates; it is a property
of the preview.** On the 788 query-8 ads that carry a `full_description`, the cross-family token
is visible inside the 254-character teaser for **1 ad (0.1%)** and in the full text for **20
(2.5%)** — **19 ads (2.4%) hide it behind the cut**. A `load_full_description` flip on either
query grows the cross-family surface by roughly **20×**, and §10 is explicit that the flag is
**per-query configuration, not code**: one admin checkbox, on a query whose operator has no
reason to connect it to a registry. [`CATEGORY_PRICE_MODELS.md`](../research/CATEGORY_PRICE_MODELS.md)
§8 already recommends turning that flag on for other queries. **The exclusivity fix has to land
before the flag flips, not after.**

Two things this settles about the fix above, rather than repeating it:

- **Registration order is the wrong question; mutual exclusivity is the right one.** With the
  naive predicate, registering `macbook` first resolves all 7 double-claims to `macbook` — right
  for the 2 real MacBooks in the set, **wrong for the iPad and wrong for the 4 PCs**. Ordering
  cannot express "neither of us should claim this".
- The fix is cheap and measured: adding `NON_IPHONE` + `OTHER_BRAND` exclusions to an iPhone
  `applies_to` drops the overlap to **0**, refusing 3 rows that all deserve refusal. Ship the
  exclusion, and make insertion order a **documented tiebreak nobody relies on** — which is what
  the registry test in the paragraph above is for. The fixtures it wants now exist: the iPad
  Magic Keyboard ad, the `Na iPhone je záruka` MacBook Air, and the four-road-bike lot whose
  description ends `Možný swap v kombinaci s Apple iPhone`
  ([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §8).

---

## 9. Two read paths ignore `model_name`

- `Ad.price_score_summary` — `bazos/models.py:623-628` — takes
  `.exclude(predicted__isnull=True).order_by("-created").first()`, with **no `model_name`
  filter**. This is what Discord prints.
- `AdAdmin.get_queryset`'s `price_discount` / `price_z` subqueries — `bazos/admin.py:553-561` —
  build `AdPriceScore.objects.filter(ad=OuterRef("pk"), predicted__isnull=False).order_by("-created")`,
  same omission. This is what the changelist sorts by.

Harmless today: one model is registered, `score_ad` writes only for the model that claims an ad,
and `AdPriceScore` is unique on `(ad, model_name)` (`models.py:733-738`), so an ad has at most
one row.

**State the trigger precisely.** It breaks when a second model is registered **and** an ad
accumulates rows from both — which happens whenever registry order changes over time (model A
scored it last month; model B is registered ahead of A and scores it today). `created` is set at
first write and `update_or_create` never refreshes it, so `-created` then surfaces whichever
model scored the ad **later**, which need not be the model that governed the filter decision.

Compounding it: **nothing in the codebase ever deletes an `AdPriceScore`** — `rescore_ads` does
not delete, and its `--model` flag only selects which ads to re-run. So renaming `macbook` to
`macbook_v2` leaves every old row in place forever, with stale numbers and a `model_version`
pointing at an artifact nobody serves. Because both read paths *exclude* declined rows, the
retired model's prediction surfaces in Discord and in the admin **exactly when the live model
declines** — that is, on the ads the live model distrusts most.

Fix: filter both reads by the model the current registry would pick, or add
`manage.py rescore_ads --retire <model_name>` to delete orphans. Do the read-path fix first; it
is the one that can present a wrong number to a human.

---

## 10. The shipped extractor reads a 254-character truncated preview

`features.extract(name, desc)` (`bazos/pricing/features.py:259-270`) is called with
`ad.name` and `ad.short_description` and nothing else (`estimators/macbook.py:105`). And
`short_description` is **Bazos's own listing preview**, not the listing:

| measure (Bazos ads, n=9,947 deduped) | value |
|---|---|
| maximum observed length | **exactly 254 characters**; 0 rows longer |
| rows ending in the truncation ellipsis | **7,456 — 75.0%** |
| length of a truncated row | 99.8% land in 237–254 (2,712 at 254, 1,270 at 250, 703 at 252, 368 at 253) — the cut stops on a word boundary |
| median length of an untruncated row | 139 |

> **Basis note.** An earlier pass described this as "hard-cut at exactly 254 characters: 7,515
> rows exactly 254 long, 22 at 252, 7 at 253". Re-derived from the same export, the count that
> reproduces is **"ends in the truncation marker" (7,456)**, not "is exactly 254 characters"
> (2,712). The cap is real and is 254; the cut is not fixed-width. Count the marker, never the
> length — [`CATEGORY_PRICE_MODELS.md`](../research/CATEGORY_PRICE_MODELS.md) §4 carries the same
> correction, because a bike study was about to build on the mis-stated version.

Truncated share and full-description coverage, **counted per query** (an ad delivered to two
queries counts in both, so these are query populations rather than the deduped 9,947):

| query | ads | truncated | `full_description` |
|---|---|---|---|
| q8 macbook | 2,851 | **85.9%** | 27.6% |
| q9 PC | 2,856 | **87.1%** | 47.9% |
| q11 golf | 390 | 80.0% | **0%** |
| q15 macbook-new | 182 | 73.6% | 100% |
| q16 MTB | 2,343 | 57.0% | **0%** |
| q17 road bike | 715 | 51.9% | **0%** |
| q18 ski | 127 | 66.9% | 38.6% |
| q19 iPhone | 613 | 62.2% | **0%** |

**This was found while looking at bikes and it is not a bike finding** — it is the input to every
model this project will ever ship, including the one already deployed.

Measured cost on the shipped path: among the 863 Bazos MacBook ads that *do* carry a full
description, gate-pass rises **56.4% → 65.4% (+8.9pp**, +11.3pp on the truncated subset) if the
full text is used. It is a **coverage** defect, not an accuracy one: on the 479 ads that pass the
gates either way, the predicted price moves more than 5% for 12.3% of them but the firing
decision flips on **one**.

And it is **per-query configuration, not code**: `Query.load_full_description` is the switch, and
the cost of turning it on is one paced detail GET per new ad. Nobody has measured what it buys a
bike model, which is the actual decision in front of the operator for q16/q17.

---

## 11. Test coverage gaps that N=2 will exercise

The pricing suite passes: **151 passed / 676 deselected in 12.49 s** against real Postgres
(`pytest bazos/tests/ -k "pric or score"` — `test_pricing.py` 43, `test_filters.py` 28,
`test_rescore_command.py` 8, plus scraper tests matching the pattern). Two gaps:

- **Nothing ever loads the shipped artifact.** All three artifact tests monkeypatch
  `artifacts.ARTIFACT_ROOT` to `tmp_path` (`bazos/tests/test_pricing.py:118, 131, 143`) and the
  `model` fixture replaces the `manifest` property outright (`:164-174`). A corrupt
  `bazos/pricing/artifacts/macbook/2026-08-26/manifest.json` would reach production as a
  **silent decline** — §7's failure, arriving by a different route. One test per registered model
  asserting `load_manifest(name)` is not None, and that every feature name it references is
  producible by that model's `extract()`, also catches the classic "retrained with a renamed
  feature" skew.
- **Nothing pins registry semantics with more than one model.** Nothing asserts first-match
  ordering, nothing asserts two models cannot claim the same ad, nothing covers the
  rename/orphan case of §9. Both gaps are cheap, and both are exactly what a second model
  exercises on day one.

**"Day one" is now dated.** [`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §8 is a
fitted second model — not yet registered, and correctly so until these land — whose own
recommendation is *register it, do not enable it*, so both bullets above stopped being
anticipatory on 2026-09-13. The second one no longer needs fixtures
invented either — §8.1 supplies real ones: the iPad Magic Keyboard ad, the `Na iPhone je záruka`
MacBook Air, the four-road-bike swap lot, plus one plain iPhone and one plain MacBook Air as the
positive cases. And note §3.6 adds a third assertion worth the same test file: that every `cat`
level a model's `extract()` can produce **exists in the manifest it ships against** — the M6 case
is exactly a `chip_key` the extractor emits and the artifact has never heard of.

---

## 12. What is true in production right now

Read directly from the Pi and from the `Query` table on 2026-09-12, not inferred:

| Fact | Value |
|---|---|
| `PRICE_MODEL_SHADOW_MODE` in the production `.env` | **`false`** |
| Shipped default (`bazos/const.py:114`, `scraper/settings.py:228`, and CLAUDE.md) | `True` |
| Query 8 `filter_rule_names` | includes **`price_model`** |
| Query 8 `filter_price_model_z` | **−1.5** (shipped default −2.0, `const.py:117`) |
| Query 8 `filter_location_center` / `_radius` | 11000 / 40 km, configured **2026-09-07** |
| Query 8 delivery rejections, total | **151** |
| …`location_distance` | **101** |
| …`price_model` ("not a deal: …") | **37** |
| `AdPriceScore` rows for `macbook/2026-08-26` | **88**, of which **47 declined** |

**So `PriceModelRule` is live on query 8.** Everything in §3–§8 that reads as a latent risk is,
on this one query, not latent. Note also that **47 of the 88 score rows are declines** — the two
implemented gates are doing most of the work already, and §4 is the third gate missing from that
set.

**The 2026-09-07 SENT→REJECTED flip is the distance filter, not the price model.** This study
made that mis-attribution and corrected it, which is worth recording so it is not made again:
the first pass established "the price-model rule is live" using a control restricted to *"the 25
locations that produced a SENT query-8 ad"* — a **collider** on precisely the variable the
concurrent change acts on — and it produced a 2.3% rejection rate for model-declined ads against
an unrestricted **56.6% (56/99)**. The concurrent change was then identified from the data
(query 8: Brno 602 00 is 17/17 rejected while every Praha location is 0% rejected among declined
ads; q16 39/42, q17 7/7, q19 27/28 of locations with ≥5 ads are pure-one-status), and confirmed
by reading the `Query` row. A collider-free redo — locations chosen using **only** declined-ad
outcomes, then gate-pass vs declined inside them, 8/10 vs 0/22 rejected, Fisher p=4.3e-6 —
preserves the conclusion. **The conclusion survived; the evidence offered for it did not.**

Two consequences worth carrying:

- **The direction of harm is false-positive alerts, and the distance filter bounds the blast
  radius.** The inverted rule REJECTs non-deals, so an over-predicting model makes sub-floor ads
  look like deals and they are APPROVED and sent — but only if they are also within 40 km of
  11000. The four highest-discount scored ads on query 8 were all SENT, and three of the four are
  priced at 4,000 / 3,000 / 3,999 CZK, i.e. in the stratum §3 says the floor change admitted.
  (§5 is the exception: its harm is muting, and no distance filter bounds that.)
- **Rule order explains the score-count gap nobody could account for.** 88 `AdPriceScore` rows
  exist against ~180 model-claimed query-8 ads created since 2026-09-07. `location_distance`
  precedes `price_model` in `RULE_REGISTRY` (`filters.py:340-347`) and the engine is
  first-non-PASS-wins, so the 101 distance rejections never reached scoring. There is no second
  mystery here.

---

## 13. The work list

**Before the second model is registered — and that model has now been built and measured.** These
four were written as prerequisites for a hypothetical N=2.
[`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §8 is a fitted iPhone artifact whose
own recommendation is *register it, do not enable it*, and its gates probe names all four of these
by number as the condition for registering. `MODEL_REGISTRY` still holds one model and
`bazos/pricing/estimators/` still holds one module, so **nothing here is late — it is next, and
it is blocking rather than anticipatory.** Each converts a silent failure into a loud one, and
none is more than a morning:

1. **§8 — `marketplaces` on the protocol + a registry test.** ~20 lines. Ordering already decides
   83 ads; make it a decision rather than a dict literal. **§8.1 sharpens this into mutual
   exclusivity**: order cannot express "neither of us should claim this", the measured overlap is
   7 double-claimed ads, and the zero that looks reassuring today is an artifact of §10's
   254-character cut.
2. **§7 — per-model artifact version.** A one-model rollback must not disable the others,
   especially in the direction that APPROVEs everything. Concretely at N=2: pinning `macbook`
   silently disables `iphone`.
3. **§9 — key both read paths by `model_name`.** Do this before a rename is ever possible; it is
   the one that shows a wrong number to a human.
4. **§11 — a test that loads the real shipped artifact**, one per registered model, plus registry
   semantics with two models. Fixtures now exist rather than needing invention (§8.1).

**Before the rule is *enabled* on that second query — three more, and the distinction matters.**
Registering is safe on its own: query 19's `filter_rule_names` is empty, which `build_rule_engine`
resolves to `DEFAULT_RULE_NAMES`, which excludes `price_model`, so a registered artifact scores
nothing until someone edits that field by hand. What follows blocks the edit, not the
registration:

- **(a) A negation-aware damage gate (§4.1–§4.2).** Neither the shipped `_DAMAGE` tuple unmodified
  — 6–7 of its 28 declines on query 19 are ads saying they are undamaged — nor a naive `_NEG`,
  which passes cracked phones into 2 of 25 gated alerts. Measure the false rate in **both**
  directions before shipping either.
- **(b) An iPhone-fitted `seller_sigma_prior`, never the MacBook ladder.** The maturity ladder
  does not replicate: 0.232 / 0.253 / 0.137 / 0.184 / 0.090 against the shipped 0.3129 / 0.2993 /
  0.2414 / 0.1872 / 0.1129 — **the 1–2 bucket is wider than the never-seen bucket**. Borrowing a
  monotone ladder onto a non-monotone corpus is not conservative, it is arbitrary: on identical
  residuals it moves alert volume by **32%** in a direction nobody chose
  ([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §6). §6(ii)'s rule applies —
  key sigma on spec completeness, and record the overlapping CIs next to the point estimates.
- **(c) §4's query-floor gate**, which this document already covers and which item 6 below
  schedules anyway.

One model-side build requirement travels with the artifact rather than with either list:
**§3.6 — carry generation as a live age-in-months `num` feature rather than frozen `cat` levels,
and decline on an UNKNOWN generation.** It costs no schema change and no measured accuracy
(ΔR² +0.0040, CI −0.0042…+0.0117); getting it wrong is invisible until the day a new generation
ships, and then mutes the most expensive items in the feed.

**Regardless of a second model — these are live on query 8 today**, cheapest first:

5. **§5 — `refresh=delivery.status == AdStatus.PRICE_CHANGED` at `filters.py:278`.** One line. It
   is the only defect live on query 8 today that mutes a real deal, and price drops are what the
   alert is for. Re-scoring a second corpus's flags moved its composition further than any
   threshold change tested against it (§5).
6. **§4 — the query-floor gate in `PriceModelRule`.** No retrain, no migration, 3.0–14.0×
   enriched in every corpus measured. Either build it or delete the claim from the docstring.
7. **§3 — `training_support` in the manifest + an out-of-support decline.** ~12 lines and one
   retrain. Do **not** treat retraining alone as the fix.
8. **§6(i) — seller key `email` else `phone`.** Recovers 711 Bazos ads; small, self-contained,
   and correct today. §6(ii) (decline where there is no identity) is **not** independently
   shippable — nothing off Bazos is scored until a model claims it.

**Safe to leave:**

- **§10's truncation.** It is a per-query flag, not a code defect, and the measured effect is
  coverage (+8.9pp gate-pass) rather than accuracy (one flipped decision in 479). Turn
  `load_full_description` on where it pays; do not rewrite the extractor for it. **One new
  ordering constraint: §8.1 shows the flag is also what holds the cross-family `applies_to`
  overlap at zero** — flipping it on query 8 or 19 grows that surface ~20×, so item 1 lands
  first. "Safe to leave" is not "safe to change in either direction".
- **§6's unscoped, non-time-causal `COUNT`.** Real, but it moves sigma buckets, not verdicts, and
  the honest fix is tied to whatever sigma source the *next* model uses.
- **Splitting `features.py`** into `text.py` + `features_<cat>.py`. Worth doing with model #2,
  pointless before it.
- **Pre-expanding interactions in the MacBook manifest.** Measured worthless: ΔR² **+0.0007**,
  CI −0.0036…+0.0058 (n=2,999, 876 sellers). The desktop case is **disputed and belongs to P27,
  not here**: one pass measured pre-expanded per-GPU-series slope columns at +0.023
  (CI +0.004…+0.052, n=1,284) with whole-frame preprocessing and a fixed α; a verification pass
  with nested α and all preprocessing inside the fold gets **+0.007 (CI +0.000…+0.019)** on the
  same segment and finds that what closes the linear gap is gen/tier as one dummy per level,
  +0.024 (CI +0.001…+0.063) — [`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md) §5.2.

Related backlog items: [`PROMPTS.md`](PROMPTS.md) **P23** (the catch-all model — read §8's note
first), **P24** (outcomes, which is what would let any threshold here be calibrated rather than
argued), **P27** (desktop model). Nothing in this document is blocked on any of them, and none of
them is safe to start before items 1–4.

---

## 14. Reproduction

Read-only over SSH against the production Postgres for the configuration facts in §12; nothing
was written. Everything else is re-derivable from the corpus export and the repository:

- The shared harness is [`experiments/price_model/common/ph.py`](../../experiments/price_model/common/ph.py),
  which lands in the repo with this study alongside the rest of
  [`experiments/price_model/`](../../experiments/price_model/) — throwaway analysis, excluded
  from ruff and mypy, needing `poetry install --with ml`. `ph.seller_key` is the
  `email → phone → per-row` fallback §6(i) asks for.
- The serving path must be **replicated by importing `bazos.pricing.features` and
  `bazos.pricing.artifacts`**, not by reimplementing them; the runs that disagree in §3.3 both
  did, which is why the disagreement is interesting rather than explainable.
- §5 was verified with a throwaway `pytest` module against real Postgres, driving the actual
  `PRICE_CHANGED` write from `query_runner.py:194-215` and then `PriceModelRule().apply()`.
  Reproducing it needs nothing but `docker compose up -d postgres`.
- The corpus CSV is deliberately not committed — it carries seller names and publisher ids, the
  same rule [`MACBOOK_PRICE_MODEL.md`](../research/MACBOOK_PRICE_MODEL.md) §9 states. Mind §2's
  delivery-level trap when re-pulling it.
- **§3.6, §4.1, §4.2 and §8.1 come from the iPhone study** and inherit its basis rather than
  §2's: query 19 only, **n=655, created 2026-09-09 → 09-12 — a 3.30-day window with no Sunday
  and no Monday in it**, of which day 1 is a 132-row `new_query` backfill
  ([`IPHONE_PRICE_MODEL.md`](../research/IPHONE_PRICE_MODEL.md) §9). Its extractor
  ([`experiments/price_model/iphone/`](../../experiments/price_model/iphone/)) was written by
  reading those same rows, so its coverage and gate-rate figures are in-sample with respect to
  it. Two things in this document are **not** from that study and need no such caveat: §4.1's
  negation table, which is the shipped `_DAMAGE` tuple run through the shipped `norm` and
  reproducible in four lines, and §3.6's shipped-manifest columns, which are arithmetic over the
  19 `chip_key` and 16 `year_cat` levels in
  `bazos/pricing/artifacts/macbook/2026-08-26/manifest.json`.
