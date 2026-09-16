---
title: Docs Index
status: active
updated: 2026-09-07
verified: 2026-08-29
---

# Docs Index

Planning and research notes for the scraper. Runtime/architecture docs live in the root
[`CLAUDE.md`](../CLAUDE.md); **[`SHIPPED.md`](SHIPPED.md) is the single source of truth for what
is implemented.** If a doc here describes something as future work and `SHIPPED.md` lists it,
`SHIPPED.md` wins — fix the doc rather than trusting it.

## How these docs work

Every file under `docs/` opens with a YAML front-matter block:

```yaml
---
title: Sbazar.cz — feasibility assessment
status: reference
updated: 2026-08-22
verified: 2026-08-22
---
```

`status` is one of exactly five values — the table below is a view over them:

| status | meaning |
|---|---|
| 🟢 `active` | open work; claims are kept in sync with the code |
| 💡 `proposal` | designed, no decision taken, **nothing built** |
| 📐 `reference` | measured findings about the outside world; durable regardless of code state |
| ✅ `shipped` | what it describes is implemented; kept for the rationale. Carries `shipped_in:` (migration and/or commit) |
| 🗄 `superseded` | replaced. Carries `superseded_by:` |

`updated` is the last substantive edit; **`verified` is the last time the claims were checked
against the code or a live probe** — the two are different, and the second is the one that tells
you whether to trust a number. `bazos/tests/test_docs.py` enforces all of this, plus that every
doc appears in the table below exactly once and that no relative link is broken.

**Naming**: `SCREAMING_SNAKE_CASE.md`, subject first. No lifecycle or phase affixes in filenames
— the directory and `status:` carry those.

## The docs

### Root — strategy, operations, and the shipped register

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`SHIPPED.md`](SHIPPED.md) | 🟢 active | 2026-08-23 | **What is actually implemented**, newest first, with the migration and commit that landed each item. Start here before believing any other doc's status. |
| [`MONETIZATION.md`](MONETIZATION.md) | 🟢 active | 2026-08-23 | Can this be turned into money — data sales, flipping, subscriptions, selling the capability. **§6 is the legal section that constrains everything else** (Bazos ToS API-consent clause, sui generis database right / *Innoweb v Wegener*, GDPR Art 14, Act 480/2004). **§7.1 argues detection latency, not features, is the binding constraint** on the whole project. |
| [`QUERY_COMPOSITION.md`](QUERY_COMPOSITION.md) | 🟢 active | 2026-08-26 | **How a `Query` becomes results, and what it can't express.** Bazos has no phrase search and one implicit-AND word bag; our side gives exactly **one positive OR-group** (`filter_required`) plus unlimited exclusions. §5 works "M3 Pro or better, ≥32GB, ≥1TB" — not exactly expressible — into the approximation that is, and §3.2 has the two traps (substring collisions like `8gb` ⊂ `48gb`, and Czech negation defeating a blocklist). |
| [`BACKUPS.md`](BACKUPS.md) | ✅ shipped | 2026-08-23 | Dump options, destinations, cost, and the retention/GDPR interaction (a PII purge that doesn't reach the backups isn't a purge). **§9 is the restore runbook** — the live part of this doc. |

### `backlog/` — open work

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`PROMPTS.md`](backlog/PROMPTS.md) | 🟢 active | 2026-08-23 | **The backlog.** Ready-to-run prompts for work that is *not* done, ordered by dependency; the order recommendation at the bottom is the sequence to actually work in. Numbers are stable, gapped, and never reused — shipped ones moved to `SHIPPED.md`. |
| [`PRICE_MODEL_DEFECTS.md`](backlog/PRICE_MODEL_DEFECTS.md) | 🟢 active | 2026-09-12 | **Nine defects in `bazos/pricing/`, found by trying to add a second model.** Ordered by risk, each with a file:line and a priced fix. The three that bite today: an artifact records **nothing about what it was trained on**, so query 8's floor moving 5 000 → 3 000 CZK went unnoticed for 12 days; **a stale price score survives a price change**, so a listing that drops 30% is re-filtered against its pre-drop residual; and `seller_prior_ads` counts only the email publisher, so a missing seller identity widens sigma — which on the one **inverted** rule means REJECT. §11 records what is true in production right now, including that shadow mode is **off** against a shipped default of `True`. |
| [`API_CUTOVER.md`](backlog/API_CUTOVER.md) | 🟢 active | 2026-09-07 | **The spec for [`PROMPTS.md`](backlog/PROMPTS.md) P21a Parts 1 + 4a.** §1 corrects the cadence model that every latency claim rests on — `PROXY_ROTATION.md` §5 omits pass duration, so the real cycle is **42 min measured, not 30**, and today's median latency is ~21 min. §2 is the reason to read it before cutting over: the API's thin payload drops `short_description`, the postcode and the publisher ids, and **all three degrade their filter rules to permissive, silently**. §7 makes "confirm parity" testable. |
| [`BACKLOG_IDEAS.md`](backlog/BACKLOG_IDEAS.md) | 🟢 active | 2026-08-23 | Deeper analysis of ideas mined from the issue tracker that aren't numbered stages — async scraping, images, CV, interval tuning, `AdOutcome`, distance scoring. Not sequenced; the priority table at the top is. |

### `proposals/` — designed, not scheduled, not built

None of these is scheduled. Each is grounded in what the code actually does rather than a generic
write-up, and each names what would have to be true before it's worth starting.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`DISCORD_BOT.md`](proposals/DISCORD_BOT.md) | 💡 proposal | 2026-07-24 | Replace webhook-only notifications with a real gateway bot — per-ad watch/mute/blocklist buttons, seller lookups, query control from Discord. §1 explains why gateway and not a public HTTP endpoint. |
| [`JOB_QUEUE.md`](proposals/JOB_QUEUE.md) | 💡 proposal | 2026-07-26 | Generalise the `run_filter`/`run_sender` polling pattern into a `Job` model + registry + one worker, so new recurring work stops meaning a new compose service and a hand-rolled sleep loop. |
| [`LLM_AD_REVIEW.md`](proposals/LLM_AD_REVIEW.md) | 💡 proposal | 2026-08-07 | An LLM ad judge as its own pipeline stage, and draft-only seller outreach. **Explicitly recommends against auto-sending messages to sellers.** §2f has free-tier cost figures and the Gemini EEA data-terms carve-out. |
| [`ML_PRICE_SCORING.md`](proposals/ML_PRICE_SCORING.md) | 💡 proposal | 2026-08-26 | How a price estimator becomes a deployable part of the pipeline: scoring enriches `Ad`, alerting stays a `FilterRule` on `AdDelivery`. **Extends [`PROMPTS.md`](backlog/PROMPTS.md) P23 rather than superseding it** — P23's median-of-comparables becomes one entry in the model registry. §1.2 is why it is not a fourth pipeline stage. |
| [`PRICE_REFERENCE_SERVICE.md`](proposals/PRICE_REFERENCE_SERVICE.md) | 💡 proposal | 2026-09-16 | Two new apps: `llm/` (provider-agnostic LLM layer, `NULL` by default) and `refprice/` (Zboží reference prices + price history), invoked **explicitly** from the admin. §1 is app-not-microservice and the extraction seam; §4 the six-status result shape; §5 the cost ladder that puts the LLM on *candidate adjudication*, not blind extraction. |
| [`PUBLIC_AD_PAGES.md`](proposals/PUBLIC_AD_PAGES.md) | 💡 proposal | 2026-08-24 | A self-hosted page per ad, linked from every notification. The admin-link half **shipped**; this is the deferred rest. §3 is why the Discord-unfurl argument is empty without ad images, §4 why the seller-identity data rules out an unauthenticated page, §5 the two settings that block any internet exposure. |

### `research/` — measured findings about the outside world

These stay true as the code changes: they describe marketplaces, transports and price semantics,
not our schema. Re-verify against a live probe, not against the repo.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`PRICE_PARSING.md`](research/PRICE_PARSING.md) | 📐 reference | 2026-08-23 | All four marketplaces sampled live. **Three of them encode "zero" differently**, and `re.sub(r"\D","")` is correct for Bazos only — Vinted is 72% non-integer float, Aukro is int *or* float unstably within one response, Sbazar's `0` means free or negotiable depending on a flag. §1 is historical (P22 shipped); §2 onward is current. |
| [`MACBOOK_PRICE_MODEL.md`](research/MACBOOK_PRICE_MODEL.md) | 📐 reference | 2026-08-24 | **The measured basis for `MONETIZATION.md` §4.2 and P23.** 2,038 Bazos MacBook ads modelled end to end: asking price predicts at R² 0.87 from listing text alone, but **70% of a naive underpricing alert is damage, parse failures and price-floor artifacts**, and **67% of residual variance is between sellers**. §6 is the blocker — the DB records no outcomes at all, so precision cannot be measured. §2's two parsing traps are what a productionised extractor must handle. |
| [`PC_PRICE_MODEL.md`](research/PC_PRICE_MODEL.md) | 📐 reference | 2026-09-12 | **Does the MacBook work transfer to desktops? Partly, and one published number is retracted.** Re-measured 2026-09-12 at 2 856 ads (from 1 668). **§5.2's "linear is not sufficient here" does not survive**: `pcmodel.py` imports `Ridge` and never calls it, and its `make_X` hands categoricals to a linear model as *ordinal integers* — the encoding is worth four to six times the linear-vs-tree gap it was read as. §4 answers [`PROMPTS.md`](backlog/PROMPTS.md) P27 item 1 early: on block B storage clears its bar (66.1%) and GPU+CPU+RAM still does not (58.4%). §3 still holds — desktops are a *private-seller* market, so the seller-aware threshold does not transfer, and §6's name→spec lookup is still **redundant**. Verdict: shadow-ship a gated linear artifact, and never a flat −25% threshold (it is 0.97σ here against 2.92σ for a MacBook dealer). |
| [`PRICE_MODEL_BENCHMARK.md`](research/PRICE_MODEL_BENCHMARK.md) | 📐 reference | 2026-08-26 | **Does the price model need to be a GBM? No — but the gap is real, not noise.** 25 models, nested CV, grouped by seller *and* past→future. The GBM beats the best linear model by ΔR² 0.026 (CI 0.012–0.044) and 1.4 pp of MedAPE — measured, not hand-waved — and that does **not** justify putting numpy on the Pi. §3.1 is the headline: **two extractor regexes were worth +0.036 R², more than the whole model-class choice.** §9 is the other one: the GBM's naive interval covers **39.8%** at a nominal 80%. §11 is the shippable feature spec.
| [`IPHONE_PRICE_MODEL.md`](research/IPHONE_PRICE_MODEL.md) | 📐 reference | 2026-09-13 | **The model works and the alert does not — and those are not in tension.** Ridge R² 0.937 / MedAPE 9.95% on 94.2% of query 19, the strongest fit in the project on its own corpus, yet a 150-ads/day feed turns it into **41 gated flags a week against MacBook's 3.2**. §3.1 completes the ordinal rule: a generation+tier ordinal beats 43 per-model dummies by ΔR² +0.081 and by +0.404 vs −7.18 on a held-out generation — it works where the name encodes generation *positionally*, which is why it also worked for GPUs and failed for bike groupsets. **§7.1 is the one to read**: going deeper makes precision *worse*, monotonically (bait 20% of flags at −25%, 50% at z ≤ −3.0) because a fake price is bounded only by what gets clicks while a real bargain is bounded by the seller's option of selling at market. §5.1: a frozen `cat` generation level goes **0.0%-blind** to the next generation the day it ships. |
| [`CATEGORY_PRICE_MODELS.md`](research/CATEGORY_PRICE_MODELS.md) | 📐 reference | 2026-09-12 | **Does the MacBook recipe carry to other categories? No — for all five tried.** Headphones, mountain bikes, skis and golf measured end to end (desktops have their own doc). **§2 is the durable part**: one category-agnostic probe, calibrated against the two published models, predicts modelability from **rarefied vocabulary breadth** (≤215 types per 900 title tokens promising, ≥273 not — no overlap across eleven corpora) and title spec density, while seller concentration, description coverage and corpus size predict **nothing** — so MacBook's dealer-heaviness is not what makes it modelable. §4 is a refuted claim worth reading: the groupset ordinal fails on *encoding*, not because bikes lack a spec grammar. **§7 generalises a MacBook fact to every corpus** — ads on the query's own price floor are 3.0–14.0× enriched in the underpriced tail, and the gate `_gates_pass` documents is not implemented. |
| [`CROSS_MARKETPLACE_MACBOOK.md`](research/CROSS_MARKETPLACE_MACBOOK.md) | 📐 reference | 2026-09-12 | **Can Bazos, Sbazar and Vinted MacBook data go into one model?** Re-measured 2026-09-12 at 5.6× the Vinted rows. **§6.2's "+3.5%" Sbazar premium is withdrawn** — it is +1.3% (CI −1.1…+3.0) once both sides clear query 14's 10 000 CZK floor; the old interval had no clustering and the point estimate was half truncation. **§5.4 is the new trap and it is bigger than the old one**: ~73% of the Vinted corpus is not priced in CZK by the seller but is a PLN price converted at Vinted's drifting daily rate, so `Ad.price` there is non-stationary in a way no marketplace fixed effect can absorb — and it manufactures `PriceChange` rows for listings nobody edited. §5.1's fee formula (`ask × 1.05 + 18 CZK`) is **confirmed from the corpus**, by a different argument than the doc originally gave. |

#### `research/marketplaces/` — which marketplace to add next

**Study completed 2026-08-22.** 13 candidates assessed live under hard per-site request caps, in
two tracks: Track A (marketplaces to scrape) and Track B (reference-price sources). **Verdict:
build Sbazar next** — which then happened, see [`SHIPPED.md`](SHIPPED.md). Aukro is the open
question. `pass1/` holds the triage that preceded the two full workups.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`RECOMMENDATION.md`](research/marketplaces/RECOMMENDATION.md) | 📐 reference | 2026-08-22 | **Start here.** The ranked answer for both tracks, with the counter-argument that would flip it stated plainly. §3.4 records the three probes that decide Aukro (they were run). §6 lists the five methodology corrections the study produced. |
| [`SUMMARY_TABLE.md`](research/marketplaces/SUMMARY_TABLE.md) | 📐 reference | 2026-08-22 | One page: all 13 candidates with verdict, measured scale, new capability, effort, legal posture — plus the vantage-point table. |
| [`AUKRO.md`](research/marketplaces/AUKRO.md) | 📐 reference | 2026-08-22 | **VIABLE, and the only source that closes the realised-price gap** — ended auctions readable unauthenticated ≥2.75 years back. §6a.1 tempers it: only ~11% of sampled ended items had bids, and §4.1.1 confirms **Tor is blocked**. |
| [`SBAZAR.md`](research/marketplaces/SBAZAR.md) | 📐 reference | 2026-08-22 | The measured basis for the shipped scraper: the unauthenticated `/api/v1/items/search` API, the mandatory field-mapping table, and §2.1's bump-rate measurement that the dedup fix depends on. |
| [`ZBOZI_API.md`](research/marketplaces/ZBOZI_API.md) | 📐 reference | 2026-09-16 | **The measured Zboží `/api/v3` surface, and the correction to `HEUREKA_ZBOZI.md`.** A robots-**allowed** join (`/suggestV2?phrase=` → `/api/v3/product/<slug>/`), a `medianPrice` and a `productNo` (MPN) the old file missed, and ⭐ `POST /api/v3/pricetrend/product-v3/<id>` — ~24 months of min/median/max. §1 is the five corrections; §5 is why top-1 is a trap. |
| [`HEUREKA_ZBOZI.md`](research/marketplaces/HEUREKA_ZBOZI.md) | 📐 reference | 2026-08-22 | Heureka/Zboží as a reference-price source, and the study that opened the question. Its own appended correction revised REJECT → **DEFER**; its transport and join findings are **superseded by [`ZBOZI_API.md`](research/marketplaces/ZBOZI_API.md)** — read that first. Heureka.cz itself is still Cloudflare-blocked. |
| [`EBAY.md`](research/marketplaces/EBAY.md) | 📐 reference | 2026-08-22 | eBay sold listings. **No route for a non-partner**: `findCompletedItems` decommissioned 2025-02-05, Insights invitation-only, and 90 days is too short anyway. |
| [`RESEARCH_BRIEF.md`](research/marketplaces/RESEARCH_BRIEF.md) | 📐 reference | 2026-08-22 | The brief the study ran from — methodology, not findings. Still the reference for *how* to assess a marketplace: two passes, hard request caps, measured-vs-assumed discipline, §5b's schema-fit checklist. |
| [`METHOD_CALIBRATION.md`](research/marketplaces/METHOD_CALIBRATION.md) | 📐 reference | 2026-08-22 | **Worth reading on its own.** The brief's new/day method failed twice against Bazos before working: `topped` is the *string* `"true"`, the method is impossible at default page size, and diurnal bias is ~2×. |
| [`pass1/RANKING.md`](research/marketplaces/pass1/RANKING.md) | 📐 reference | 2026-08-22 | The pre-Pass-2 commitment, kept with its corrections visible — two of its three Aukro inferences were later measured false. |
| [`pass1/SBAZAR.md`](research/marketplaces/pass1/SBAZAR.md) | 📐 reference | 2026-08-22 | Sbazar scale triage. §5.1 flags the real tension: the sitemap tree is inside a blanket `Disallow: /`. |
| [`pass1/AUKRO.md`](research/marketplaces/pass1/AUKRO.md) | 📐 reference | 2026-08-22 | Aukro triage from a datacenter IP — everything 403'd. Superseded on the facts by `research/marketplaces/AUKRO.md`; kept because the reversal is the study's sharpest methodology lesson. |
| [`pass1/BAZOS_SISTER_SITES.md`](research/marketplaces/pass1/BAZOS_SISTER_SITES.md) | 📐 reference | 2026-08-22 | `.sk`/`.at`/`.pl` — near-zero engineering, but all three refused an IP `.cz` accepted in the same minute. **Cheap breadth, not a hedge.** |
| [`pass1/MINOR_CLASSIFIEDS.md`](research/marketplaces/pass1/MINOR_CLASSIFIEDS.md) | 📐 reference | 2026-08-22 | Mimibazar, Hyperinzerce, Annonce, Avizo — all rejected on scale or category fit. Annonce's headline "1,568 notebooks" was **1,544 job ads** mentioning a laptop as a perk. |
| [`pass1/VERTICALS.md`](research/marketplaces/pass1/VERTICALS.md) | 📐 reference | 2026-08-22 | TipCars, Sauto, Sreality, Bezrealitky, Remix. Remix serves schema.org `Product` JSON-LD with real typed attributes — the strongest capability signal in the batch, on apparel. |
| [`pass1/FACEBOOK_MARKETPLACE.md`](research/marketplaces/pass1/FACEBOOK_MARKETPLACE.md) | 📐 reference | 2026-08-22 | REJECT. Blanket `Disallow: /` plus a prose notice requiring express written permission — categorically stricter than any other candidate. |

#### `research/bazos-api/` — Bazos's undocumented mobile JSON API

Reverse-engineered from the decompiled Android app. Independent of the pipeline stages — it's
about *how* Bazos is scraped. `BazosApiScraper` exists and is registered, but **no production
`Query` selects it**; making that switch is `backlog/PROMPTS.md` P21a.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`HIDDEN_API.md`](research/bazos-api/HIDDEN_API.md) | 📐 reference | 2026-07-26 | Endpoint inventory, request/response shapes, live-validated findings. **§4.1a–4.1b is the load-bearing bit**: `OR` is a real boolean union, `AND` is fake, and the search is plain SQL substring `LIKE`, not FULLTEXT boolean mode. §5 shows listing and detail are *not* the same payload. |
| [`USER_AGENT.md`](research/bazos-api/USER_AGENT.md) | ✅ shipped | 2026-07-19 | How the app builds its `User-Agent` at runtime and how to reproduce it. Implemented as `bazos/scraping/bazos/user_agent.py`. |
| [`DISCOVERY_PIPELINE.md`](research/bazos-api/DISCOVERY_PIPELINE.md) | 💡 proposal | 2026-08-10 | A broader category-scoped discovery pipeline plus the enrichment workflows the API makes cheap — seller reputation, dealer/scam detection, repost detection. Nothing built. |

#### `research/proxies/` — replacing Tor for Bazos requests

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`PROXY_ROTATION.md`](research/proxies/PROXY_ROTATION.md) | 📐 reference | 2026-07-26 | Why Tor (IP reputation) and a single long-lived VPN (per-IP rate) both failed, and what to use instead. **§4–§5 are live-measured** request/bandwidth volumes including the "run more often" cadence math and the 77+ GB/mo download-all-images scenario. §8 sketches `HttpProxyIPChanger`. **The one thing still unmeasured (§10) is sustained block rate through a real candidate proxy** — that's the gate on `backlog/PROMPTS.md` P21b. |

### `archive/shipped/` — built; kept for the rationale

Each of these describes something that exists in the code today. They are archived so they stop
competing with the backlog for attention, **not** because they stopped being useful: the field
mappings and trap lists are what a change to the corresponding scraper should be checked against.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`PIPELINE_REFACTOR.md`](archive/shipped/PIPELINE_REFACTOR.md) | ✅ shipped | 2026-08-23 | The original stage plan, **9 of 10 stages done**. Only Stage 5 (query priority) is open and it lives as `backlog/PROMPTS.md` P2. Kept for the per-stage rationale. |
| [`AD_DELIVERY_SPLIT.md`](archive/shipped/AD_DELIVERY_SPLIT.md) | ✅ shipped | 2026-08-23 | Splitting `Ad` (scraped facts) from `AdDelivery` (per-`(ad, query)` pipeline state). **§3 pre-decides the six places where the plausible choice is wrong** — notably that the dedup break keys on the *delivery*, or a new query never backfills. Deferred follow-ups are `backlog/PROMPTS.md` P26. |
| [`SBAZAR_SCRAPER.md`](archive/shipped/SBAZAR_SCRAPER.md) | ✅ shipped | 2026-08-22 | How `SbazarScraper` was built, with the exact field mapping. **§6's four traps and §11's dedup fix are the durable part** — Sbazar sorts by *edit* time, so the dedup walk breaks after 40 consecutive known ads, not one. |
| [`VINTED_SCRAPER.md`](archive/shipped/VINTED_SCRAPER.md) | ✅ shipped | 2026-08-23 | How `VintedScraper` was built. **§2's two schema blockers are the lesson**: they crash on Postgres while passing on SQLite (Vinted ids are 4.5× over `int4` max; `publish_date`/`view_count` were NOT NULL). §4.5 pins the decimal trap where `"6307.5"` parses to `63075`. |
| [`VINTED_SCRAPER_DESIGN.md`](archive/shipped/VINTED_SCRAPER_DESIGN.md) | ✅ shipped | 2026-08-21 | The design that preceded the spec. **§1a — the measured `VintedItem` field list — is what to check a scraper change against.** §1–§2 were rewritten from a live probe that falsified four original claims, including the one the design rested on. |
| [`E2E_REPLAY_TESTING.md`](archive/shipped/E2E_REPLAY_TESTING.md) | ✅ shipped | 2026-08-23 | Why `vcrpy` and how. **§4 is the durable part** — the traps measured on this stack: vcrpy must be 7.x (urllib3 v1), cassettes need `decode_compressed_response`, `filter_headers` leaks response `Set-Cookie`, a configured proxy breaks host matching, and Bazos serves page 1 of a category search with a **404**. |
| [`ZERO_RESULTS_CANARY.md`](archive/shipped/ZERO_RESULTS_CANARY.md) | ✅ shipped | 2026-08-21 | The zero-results canary spec, implemented as written plus one fix: a zero-rows pass also resets the zero-new-ads streak. |
| [`REFACTOR_SUGGESTIONS.md`](archive/shipped/REFACTOR_SUGGESTIONS.md) | ✅ shipped | 2026-07-19 | Nine small cleanups, all done. A completed changelog. |

### `archive/superseded/` — replaced, kept only as history

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`REFACTOR_PLAN.md`](archive/superseded/REFACTOR_PLAN.md) | 🗄 superseded | — | Consolidated Phase 1/2/3 framing. Its progress markers went stale; `archive/shipped/PIPELINE_REFACTOR.md`'s are the ones that were kept in sync. |
| [`PIPELINE_REFACTOR_B.md`](archive/superseded/PIPELINE_REFACTOR_B.md) | 🗄 superseded | — | Fully merged into `archive/shipped/PIPELINE_REFACTOR.md`. No unique content remains. |

The throwaway benchmark `research/proxies/PROXY_ROTATION.md` references lives at [`experiments/bench_proxy.py`](../experiments/bench_proxy.py).
