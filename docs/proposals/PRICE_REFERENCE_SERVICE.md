---
title: Reference-price service and provider-agnostic LLM layer
status: proposal
updated: 2026-09-16
verified: 2026-09-16
---

# Reference-price service and provider-agnostic LLM layer

> Designed 2026-09-16 against the live measurements in
> [`ZBOZI_API.md`](../research/marketplaces/ZBOZI_API.md). **Nothing is built.**
>
> Two deliverables that are deliberately separate apps: `llm/`, a reusable provider-agnostic
> LLM layer with no knowledge of prices, and `refprice/`, which answers *"what does this
> listing cost new, and what has it cost over the last two years"* — invoked **explicitly**,
> never on the hot path.

---

## 1. The decision that shapes everything: app, not microservice

**Recommendation: two Django apps in this repo, with a hard seam that permits extraction later.**

The instinct to reach for a microservice is right about the *coupling* and wrong about the
*deployment*. What actually argues it down here:

- **It needs the database it would have to call home for.** The unit of work is `Ad → RefProduct`,
  and the payoff (§6) is a persisted link table that accumulates confirmations. A separate service
  either shares the Postgres (a microservice in name only) or exposes an API that this codebase
  then has to call anyway — with retries, auth and a second failure mode — to write a row it could
  have written directly.
- **The house style is already "separate process, same codebase."** `run_scraper` / `run_filter` /
  `run_sender` are three long-lived processes that communicate through one Postgres column. That is
  the decoupling idiom here, and it has survived. A fourth unit should look like the other three.
- **The deployment target is a Raspberry Pi** running `docker compose` with an ARM64 image built on
  a self-hosted runner. Every new service is another image, another `profiles:` decision, another
  thing `docker compose build` can silently skip — a trap this repo has already been bitten by once
  (the `backup` service). The marginal ops cost is real and the marginal benefit is zero at this
  volume.
- **`admin.py` is the intended UI.** CLAUDE.md calls the admin "a real operational surface, not
  scaffolding". Explicit, human-triggered lookup *is* an admin action. A microservice would need its
  own UI or a proxy view to get back what an app has for free.

**The seam that keeps the option open.** Everything outside `refprice/services.py` talks to exactly
one function with plain dataclasses in and out — no querysets, no Django objects crossing the
boundary:

```python
# refprice/services.py — the entire public surface
def lookup_reference_price(request: ReferenceRequest) -> ReferenceResult: ...
```

`ReferenceRequest` carries strings and ints (`title`, `description`, `category_hint`, `ad_price`),
never an `Ad`. The day this becomes a service, `lookup_reference_price` becomes an HTTP client with
the same signature and nothing above it changes. Persisting the result is a *separate* call the
caller makes, so the pure part stays pure.

```
scraper/
  llm/                       # NEW app — generic, knows nothing about prices
  refprice/                  # NEW app — knows nothing about which LLM
  bazos/, senders/, ip_changer/, facebook/   # unchanged
```

`refprice` depends on `llm`; `llm` depends on nothing. `bazos` depends on neither — the integration
points in §7 all point *inward*, so deleting both apps breaks nothing in the pipeline.

---

## 2. `llm/` — the provider-agnostic layer

This is the fourth instance of the Protocol-plus-registry pattern already used by
`MarketplaceScraper`, `RULE_REGISTRY` and `MODEL_REGISTRY`. Deliberately built first and
deliberately ignorant of prices: the next consumer is not this feature (§10).

```
llm/
  base.py                 # LLMProvider Protocol, LLMResult, LLMDeclined
  registry.py             # PROVIDER_REGISTRY, get_provider()
  providers/
    anthropic.py  openai.py  openrouter.py  ollama.py  null.py
  prompts/
    __init__.py           # load(name, version) -> Prompt
    refprice_query_phrase/v1.md
    refprice_adjudicate/v1.md
  models.py               # LLMCall
  services.py             # complete()
```

### 2a. The protocol

```python
class LLMProvider(Protocol):
    name: str

    def complete(
        self, *, prompt: str, system: str | None, schema: type[T] | None,
        max_output_tokens: int, temperature: float,
    ) -> LLMResult[T]: ...
```

`LLMResult` carries `value: T | None`, `raw: str`, `tokens_in/out`, `cost_usd`, `latency_ms`,
`model`, and `declined_reason: str | None`.

Five contracts the signature does not express, each one a lesson this repo already learned
somewhere else:

- **Declining is normal and is never an exception.** A refusal, a truncated response or a JSON
  parse failure returns `value=None` with a `declined_reason`. This is `PriceModel.predict`'s rule
  ("returning `None` is the normal way to decline") and `bazos/pricing`'s "every uncertain path is
  neutral, never rejecting". A component that cannot answer must not be able to take the caller
  down with it.
- **No network I/O inside a `select_for_update` transaction.** Same prohibition `PriceModel` carries,
  and the reason `refprice` is explicit-only rather than a filter rule (§7).
- **Every call is persisted**, success or failure, to `LLMCall`. This is `QueryRun`'s rule — a run
  row is written even when the run fails — and it is the only way to answer "why did this cost
  $40 this month" or "did prompt v2 actually help".
- **Structured output is validated, not trusted.** `schema` is a dataclass; the provider asks for
  JSON, parses, validates, and declines on mismatch. No `eval`, no regex-scraping prose.
- **Timeouts and a retry budget, like every other transport here.** `LLM_TIMEOUT` connect/read, and
  a small bounded retry on 429/5xx only — never on a refusal.

### 2b. Configuration, and why the default is `NULL`

```python
LLM_PROVIDER      = env("LLM_PROVIDER", default="NULL")     # NULL | ANTHROPIC | OPENAI | OPENROUTER | OLLAMA
LLM_MODEL         = env("LLM_MODEL", default="claude-haiku-4-5-20251001")
LLM_API_KEY       = env("LLM_API_KEY", default="")
LLM_MONTHLY_BUDGET_USD = env("LLM_MONTHLY_BUDGET_USD", default=5.0)
LLM_TIMEOUT       = (10, 60)
```

`NullProvider` always declines and costs nothing — exactly `DummyIPChanger`'s role, and it means
the whole test suite and any dev checkout run with no key and no egress. `IP_CHANGER_TYPE`
establishes the precedent for selecting a transport by env string.

**`LLM_MONTHLY_BUDGET_USD` is a hard stop, not a warning.** `services.complete()` sums the current
month's `LLMCall.cost_usd` and declines above the ceiling. A runaway loop against a metered API is
the one failure mode here that costs real money, and "every uncertain path is neutral" has to
include "we are out of budget".

### 2c. Prompts are versioned artifacts

Prompts live as files under `llm/prompts/<name>/v<N>.md`, loaded by `(name, version)`, and the
resolved version is written to every `LLMCall` row. This is the same discipline as
`bazos/pricing/artifacts/<name>/<version>/manifest.json`, for the same reason: a prompt edit
changes outputs, so an un-versioned prompt makes every historical result unattributable. Editing a
shipped prompt in place is a bug; adding `v2` is the change.

### 2d. Caching

Key: `sha256(provider, model, prompt_name, prompt_version, normalized_input)`. Identical input must
not be billed twice — and because §5 normalizes an ad title down to *brand + line + model code*
before it ever reaches the LLM, the cache hit rate across a category of similar listings is high,
not incidental. Cached hits are still logged (with `cached=True`) so the audit stays complete.

---

## 3. `refprice/` — the domain app

```
refprice/
  providers/
    base.py       # ReferenceProvider Protocol + PROVIDER_REGISTRY
    zbozi.py      # ZboziProvider — the only live one
    heureka.py    # stub; transport-blocked, documented, not wired
  resolution/
    normalize.py  # rule-based phrase reduction (free)
    validate.py   # brand / model-token / bundle / shop-count gates
    ladder.py     # the escalation described in §5
  models.py
  services.py     # lookup_reference_price()
  admin.py
  management/commands/lookup_reference_price.py
```

### The provider protocol

```python
class ReferenceProvider(Protocol):
    name: str
    def suggest(self, phrase: str) -> list[Candidate]: ...
    def fetch(self, slug: str) -> RefProductFacts | None: ...
    def history(self, product_id: str, months_back: int) -> list[PricePoint]: ...
    def search(self, phrase: str) -> list[Candidate]: ...   # may raise NotPermitted
```

`search` is separate from `suggest` **because they have different compliance postures**
(`ZBOZI_API.md` §4): `suggest` is robots-allowed, `search` is the `?q=` route that is not. Keeping
them as distinct protocol members is what lets §5's ladder gate one and not the other, and what
makes the gate visible in the type rather than buried in a flag.

**Units are converted exactly once, at the provider edge.** Zboží reports hundredths of CZK in two
different field spellings (`minPrice`, `minPriceHa`). Every dataclass above the provider is whole
CZK `int`. This is the ×100 trap re-measured in `ZBOZI_API.md` §6; `parse_price` in
`bazos/filters.py` strips non-digits and would land such a value 100× too large.

---

## 4. The result shape — "a better reasonable way"

**The core rule: never return a bare number.** A price with no provenance is unusable for the thing
this is for, because §5's measured failure modes are *confident and wrong* — a 2020 MacBook baselined
at 47 370 Kč from a 2025 M5, a Dell XPS baselined at 262 Kč from a backpack. Any consumer must be
able to see what was matched and decline to believe it.

```python
@dataclass(frozen=True)
class ReferenceResult:
    status: Literal["matched", "ambiguous", "no_market", "no_match", "declined", "error"]

    product:  MatchedProduct | None
    pricing:  PriceSnapshot  | None
    history:  PriceHistory   | None
    match:    MatchEvidence
    cost:     LookupCost
    fetched_at: datetime
```

Six statuses, because collapsing them is what makes a caller believe a number it should not:

| status | meaning | what a caller should do |
|---|---|---|
| `matched` | one candidate passed every gate, `shop_count ≥ 2` | use it |
| `ambiguous` | several plausible candidates, none decisively better | show them, ask a human |
| `no_market` | matched, but `shop_count ≤ 1` — a stale catalogue entry | **do not price from it** |
| `no_match` | nothing in the catalogue resembles the ad | fall back to the internal model |
| `declined` | did not try — budget exhausted, provider off, category unsupported | not evidence of anything |
| `error` | transport failed | retry later |

`no_market` and `no_match` are split deliberately: discontinued goods reach `no_market` (a 2017
MacBook with one stale offer), and that is *different information* from "this product does not
exist" — it tells you the item is old enough that a new-price baseline was never going to help.

```python
@dataclass(frozen=True)
class PriceSnapshot:
    median_czk: int          # the headline. NOT min — see ZBOZI_API.md §6
    min_czk: int
    max_czk: int
    shop_count: int
    availability: str        # in_stock | discontinued | unknown
    category_percentile: float | None   # from productGroup.priceComparsion

@dataclass(frozen=True)
class PriceHistory:
    points: list[PricePoint]          # date, min_czk, median_czk, max_czk
    months_covered: int
    median_now: int
    median_90d_ago: int | None
    median_365d_ago: int | None
    change_90d_pct: float | None
    change_365d_pct: float | None
    trend: Literal["falling", "stable", "rising", "unknown"]
    depreciation_pct_per_year: float | None
    min_ever_czk: int                  # the floor a patient buyer has actually seen

@dataclass(frozen=True)
class MatchEvidence:
    method: Literal["rule", "llm", "manual", "cached"]
    confidence: float                  # 0..1
    phrase_used: str                   # what was actually sent to suggest
    candidates_considered: list[CandidateTrace]   # name, slug, verdict, reject_reason
    rejected_for: list[str]            # "bundle", "wrong_generation", "accessory", "thin_market"
    provider: str
    robots_allowed_path: bool          # False if the ?q= escalation was used

@dataclass(frozen=True)
class LookupCost:
    http_requests: int
    llm_calls: int
    llm_tokens_in: int
    llm_tokens_out: int
    usd: float
```

**`depreciation_pct_per_year` is the field that earns the history**, and it is why the series is not
decoration. Measured in `ZBOZI_API.md` §3c: over 13 months the iPhone 13's median fell **38 %** while
the Makita DHP484Z moved **−8 %**. "70 % of new" means a great deal on the tool and a poor one on the
phone, and only the curve distinguishes them. `min_ever_czk` matters for the same reason — it is the
price the market has actually cleared at, which is a far better floor than a single day's minimum.

### The deal verdict

The comparison against a Bazos asking price is a *separate* dataclass, because it is a different
question with different inputs and it is the part a consumer will want to tune:

```python
@dataclass(frozen=True)
class DealAssessment:
    ad_price_czk: int
    reference_median_czk: int
    ratio: float                  # ad / reference
    discount_pct: float
    verdict: Literal["bargain", "fair", "overpriced", "unknown"]
    caveats: list[str]
```

`caveats` is populated, not cosmetic — `"reference drawn from 2 shops"`, `"matched by LLM, not
confirmed"`, `"reference includes refurbished offers"`, `"product discontinued; new price is not a
fair comparison"`. Thresholds resolve **per query → settings → const**, the three-level pattern
`price_model` already uses, so a per-`Query` override stays distinct from an untuned default.

---

## 5. Resolution: a ladder of escalating cost

Each rung is independently switchable and every rung can decline. Nothing below rung 0 runs if a
cheaper rung already answered.

| # | Rung | Cost | Gate |
|---|---|---|---|
| 0 | **Cache** — `RefProductLink` for this ad, or a `RefProduct` fresh within TTL | free | always |
| 1 | **Rule normalization** — strip capacity/colour/condition/packaging noise to *brand + line + model code* | free | always |
| 2 | **`suggest` + rule validation** — up to 8 candidates, 261 B each | ~3–9 HTTP, ~0.5 s | always |
| 3 | **LLM phrase generation** — `refprice.query_phrase`, when rung 1 produced nothing searchable | 1 call, ~500 in / 60 out | `LLM_PROVIDER != NULL` |
| 4 | **LLM adjudication** — `refprice.adjudicate`, when rung 2 returns several survivors or none | 1 call, ~300 in / 40 out | `LLM_PROVIDER != NULL` |
| 5 | **Full search escalation** — the robots-disallowed `?q=` route | 1 HTTP | **off by default**, opt-in per call |

**Rung 1 is not a formality.** `ZBOZI_API.md` §5 measured that `Apple iPhone 13` returns 15
candidates and `Apple iPhone 13 128GB` returns **zero** — suggest is a typeahead over titles, so
spec noise is fatal. A regex pass that strips `\d+\s?(GB|TB)`, colour words, `stav [A-C]`, `zánovní`,
`s vadou`, warranty and packaging phrases does most of this for nothing.

**Rung 2 is where the design departs from the previous assessment.** Top-1 was wrong in 8 of 17
archetypes, but the correct answer was usually *present* — Samsung S10 at rank 3, a real MacBook at
rank 6. So the validator runs over the whole candidate list:

- brand ∈ `vendorName` (structured, not free text)
- required model tokens ⊆ title tokens, **prefix-tolerant** (`DHP484` must match `DHP484Z`; exact
  equality was measured rejecting the correct Makita)
- reject bundles — Czech `sada`, `set`, `+` between model codes (measured: `DeWalt DCD796` selected
  a two-tool kit at 7 785 Kč)
- reject contrast tokens the query did not ask for (`Tab`, `mini`, `Pro`, `Max`, `Plus`, `FE`)
- reject accessory categories by `categoryId` mismatch against the ad's category hint
- require `shop_count ≥ 2`, else `no_market`

**Rung 4 is the right job for an LLM, and it is a much smaller job than the one previously costed.**
`HEUREKA_ZBOZI.md` §4d priced blind per-ad extraction at $0.0008/ad and then argued — correctly, on
its evidence — that even a perfect extractor would not be sufficient. That argument does not reach
this design, because the LLM is not asked to *invent* an identity. It is handed a real candidate list
from the real catalogue and asked to pick one or decline:

> *Ad title: "Makita DHP484Z aku vrtačka 18V bez baterie, málo používaná"*
> *Candidates: 0) Makita DHP484Z Li-ion 18 V  1) Makita DHP484RFJ  2) Makita DHP489Z bez aku*
> → `{"index": 0, "confidence": 0.93, "reason": "exact model code, bare-tool variant matches"}`

Closed-set adjudication with an explicit `null` option is accurate, auditable and ~340 tokens. The
prerequisite the old file called insufficient is simply not on this path.

**Rung 5 is gated and recorded.** `ZBOZI_API.md` §9.3 measured that the disallowed route reaches
what suggest cannot (`Bosch GSB 18-2-LI` → 33 canonical products vs suggest's 0), so it is worth
having. It is off by default, requires an explicit `allow_disallowed_search=True`, and sets
`MatchEvidence.robots_allowed_path = False` so every result carries how it was obtained. The
operating posture for this project is private, non-commercial research, under which
`MONETIZATION.md` §3 already accepts disregarding an advisory file — but that is a decision to take
per call and leave visible, not to inherit silently.

---

## 6. Persistence — four tables, and why each exists

| Model | Grain | Why |
|---|---|---|
| `RefProduct` | one per `(provider, product_id)` | The catalogue facts + TTL. **Lookups are per-product, not per-ad** — many ads map to one product, which is what makes the whole thing cheap. Stores `product_no` (MPN) so a churned `id` can be re-resolved (`ZBOZI_API.md` §9.2) |
| `RefPricePoint` | one per `(product, date)` | Append-only series, merged on re-fetch. Mirrors `PriceChange` — a child table of the thing it describes, never a JSON blob on the parent, because it is what a changelist sorts by |
| `RefProductLink` | one per `(ad, provider)` | The match itself: `confidence`, `method`, `phrase_used`, `evidence` JSON, and **`confirmed_by_human`** |
| `RefLookup` | one per *attempt* | Audit including failures — `QueryRun`'s rule. A declined lookup is a different fact from no lookup |

`RefPricePoint` is separate from `RefProduct` for the reason `AdPriceScore` splits typed columns
from a `features` JSON blob: the numbers are what you sort and chart by, so they stay columns.

**`confirmed_by_human` is the most valuable column here** and the reason explicit invocation is a
feature rather than a limitation. Every admin confirmation is a labelled `(ad_title → product_id)`
pair. That corpus is what would later justify automation, what makes the LLM cost amortize toward
zero, and it is the same instinct as `BACKLOG_IDEAS.md` #9's `AdOutcome` — the project's own
labelled outcomes beat any external signal. A fully automatic v1 would have generated none of it.

`RefProduct` hangs off nothing in `bazos`; `RefProductLink` is the only FK into `Ad`, and it is
`SET_NULL` with a title snapshot, like `QueryChange.query_label`.

---

## 7. Integration with the Bazos side — explicit now, automatic later

A ladder, in the order it should be built. Rungs 1–2 are the ask; 3–5 cost nothing to leave unwired.

1. **Admin action on `Ad` / `AdDelivery`** — *"Look up reference price"*, an Unfold `actions_list`
   entry, plus an inline showing the cached `RefProductLink`, the price snapshot and a sparkline of
   `RefPricePoint`. Precedent: the existing force-run button. This is the primary UI and it is
   explicit by construction. Confirm/correct buttons here are what populate §6's labelled set.
2. **Management command** — `python manage.py lookup_reference_price --ad 123`, `--query 7 --limit 20`,
   `--refresh-stale`. The batch and scripting path; `--dry-run` prints without writing.
3. **A registered-but-unwired filter rule** — `reference_price` in `RULE_REGISTRY`, deliberately
   **excluded from `DEFAULT_RULE_NAMES`**. This is precisely how `price_model` already ships, for
   precisely the same reason: a rule that rejects what it cannot confirm would mute every existing
   query if it defaulted on. Leaving the rule registered means the automatic path is a one-line
   `filter_rule_names` edit on a single `Query` when the confirmations of §6 justify it — and
   **network I/O in `run_filter` is forbidden** (`PriceModel`'s contract), so this rung may only ever
   read `RefProductLink` rows that a rung-1/2 run already persisted. It must never call Zboží.
4. **Enrichment of the Discord message** — one line appended by `DiscordSender._format_product_message`
   when a confirmed link exists, read with `getattr` and *not* added to the `Sendable` protocol —
   the same call already made for `admin_url`.
5. **A scheduled refresh** — a `--refresh-stale` invocation for products already linked, so the
   history stays current without any new resolution work. Cheap: one pricetrend call per product.

---

## 8. What this costs to run

Per lookup, measured payloads: 1 suggest (~0.5 KB) + up to 8 product fetches (261 B each) + 1
pricetrend (~1 KB) ≈ **10 requests, ~4 KB, under a second**. No Tor, no rotation, no pacing beyond
courtesy — the API did not throttle at ~120 requests (`ZBOZI_API.md` §7).

LLM cost only materializes on rungs 3–4. At Haiku 4.5 pricing an adjudication is ~340 tokens
(~$0.0005); phrase generation ~560 (~$0.0008). Under **explicit invocation**, volume is tens of
calls per month — cents. The old $18–92/month figure assumed a blind per-ad extraction on the full
767 ads/day firehose; per-product caching plus rule-first resolution removes roughly two orders of
magnitude from that, and the budget ceiling in §2b caps whatever is left.

---

## 9. Risks, and the honest ones

- **This is an unsupported private API.** Field names, the `/api/v3` prefix and the pricetrend route
  can change without notice. Mitigation is the provider protocol and a contract test in the spirit
  of `contract-check.yml` — a weekly live job asserting the three endpoints still parse — not
  optimism.
- **Confident wrong matches are the main hazard**, not missing data. §4's six statuses, §5's gates
  and §6's `confirmed_by_human` all exist for this. A design that returned a float would be worse
  than useless.
- **Coverage is genuinely uneven.** Current-production goods resolve well and **tools resolve best**
  — which matters, because tools are the largest measured opportunity on Sbazar (26 492 active,
  3.4× Bazos). Discontinued electronics reach `no_market`, and that is the honest answer rather than
  a failure to paper over.
- **ToS remains undetermined** for both sites (`ZBOZI_API.md` §9.1). robots.txt is not a contract.
- **The internal rolling-median baseline is still the cheaper win.** `DISCOVERY_PIPELINE.md` §2
  Stage 2 needs no external dependency and answers a closely related question; this should not
  displace it. The two compose well — internal median says "cheap for a Bazos listing", this says
  "cheap against what it costs new" — but if only one gets built, build the internal one.

---

## 10. Why `llm/` is worth building even if `refprice/` is never finished

It is a standalone capability this repo has wanted in three other places, all of which become
one-prompt features once the layer exists:

- **`LLM_AD_REVIEW.md`** (2026-07-30) — the proposal that already researched a free tier.
- **Structured spec extraction for the price models.** `PRICE_MODEL_BENCHMARK.md` §3.1 measured that
  *extraction, not model class, is the weak point* — "two extractor regexes were worth more R² than
  the entire choice of estimator". An LLM extractor writing into `AdPriceScore.features` targets the
  measured bottleneck directly.
- **Blocklist/required-keyword suggestions** for `QUERY_COMPOSITION.md`'s §3.2 traps (substring
  collisions like `8gb` ⊂ `48gb`, Czech negation defeating a blocklist) — a prompt that proposes
  filter terms from a query's own rejected ads.

Build `llm/` first, wire `refprice/` rungs 0–2 (no LLM at all), and add rungs 3–4 once the rule-only
path has produced enough confirmed links to show where it actually fails.
