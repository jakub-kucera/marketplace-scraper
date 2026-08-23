---
title: Docs Index
status: active
updated: 2026-08-23
verified: 2026-08-23
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
| [`BACKUPS.md`](BACKUPS.md) | ✅ shipped | 2026-08-23 | Dump options, destinations, cost, and the retention/GDPR interaction (a PII purge that doesn't reach the backups isn't a purge). **§9 is the restore runbook** — the live part of this doc. |

### `refactor/` — the pipeline, its backlog, and the specs that built it

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`PROMPTS.md`](refactor/PROMPTS.md) | 🟢 active | 2026-08-23 | **The backlog.** Ready-to-run prompts for work that is *not* done, ordered by dependency; the order recommendation at the bottom is the sequence to actually work in. Numbers are stable, gapped, and never reused — shipped ones moved to `SHIPPED.md`. |
| [`BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) | 🟢 active | 2026-08-23 | Deeper analysis of ideas mined from the issue tracker that aren't numbered stages — async scraping, images, CV, interval tuning, `AdOutcome`, distance scoring. Not sequenced; the priority table at the top is. |
| [`PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) | ✅ shipped | 2026-08-23 | The original stage plan, **9 of 10 stages done**. Only Stage 5 (query priority) is open and it lives as `PROMPTS.md` P2. Kept for the per-stage rationale. |
| [`AD_DELIVERY_SPLIT_SPEC.md`](refactor/AD_DELIVERY_SPLIT_SPEC.md) | ✅ shipped | 2026-08-23 | Splitting `Ad` (scraped facts) from `AdDelivery` (per-`(ad, query)` pipeline state). **§3 pre-decides the six places where the plausible choice is wrong** — notably that the dedup break keys on the *delivery*, or a new query never backfills. Deferred follow-ups are `PROMPTS.md` P26. |
| [`STAGE10_SBAZAR_SPEC.md`](refactor/STAGE10_SBAZAR_SPEC.md) | ✅ shipped | 2026-08-22 | How `SbazarScraper` was built, with the exact field mapping. **§6's four traps and §11's dedup fix are the durable part** — Sbazar sorts by *edit* time, so the dedup walk breaks after 40 consecutive known ads, not one. |
| [`STAGE8_VINTED_SPEC.md`](refactor/STAGE8_VINTED_SPEC.md) | ✅ shipped | 2026-08-23 | How `VintedScraper` was built. **§2's two schema blockers are the lesson**: they crash on Postgres while passing on SQLite (Vinted ids are 4.5× over `int4` max; `publish_date`/`view_count` were NOT NULL). §4.5 pins the decimal trap where `"6307.5"` parses to `63075`. |
| [`STAGE8_VINTED_DESIGN.md`](refactor/STAGE8_VINTED_DESIGN.md) | ✅ shipped | 2026-08-21 | The design that preceded the spec. **§1a — the measured `VintedItem` field list — is what to check a scraper change against.** §1–§2 were rewritten from a live probe that falsified four original claims, including the one the design rested on. |
| [`E2E_REPLAY_TESTING_RESEARCH.md`](refactor/E2E_REPLAY_TESTING_RESEARCH.md) | ✅ shipped | 2026-08-23 | Why `vcrpy` and how. **§4 is the durable part** — the traps measured on this stack: vcrpy must be 7.x (urllib3 v1), cassettes need `decode_compressed_response`, `filter_headers` leaks response `Set-Cookie`, a configured proxy breaks host matching, and Bazos serves page 1 of a category search with a **404**. |
| [`PRICE_PARSING_RESEARCH.md`](refactor/PRICE_PARSING_RESEARCH.md) | 📐 reference | 2026-08-23 | All four marketplaces sampled live. **Three of them encode "zero" differently**, and `re.sub(r"\D","")` is correct for Bazos only — Vinted is 72% non-integer float, Aukro is int *or* float unstably within one response, Sbazar's `0` means free or negotiable depending on a flag. §1 is historical (P22 shipped); §2 onward is current. |
| [`LLM_AD_REVIEW_DESIGN.md`](refactor/LLM_AD_REVIEW_DESIGN.md) | 💡 proposal | 2026-08-07 | An LLM ad judge as its own pipeline stage, and draft-only seller outreach. **Explicitly recommends against auto-sending messages to sellers.** §2f has free-tier cost figures and the Gemini EEA data-terms carve-out. |
| [`DISCORD_BOT_DESIGN.md`](refactor/DISCORD_BOT_DESIGN.md) | 💡 proposal | 2026-07-24 | Replace webhook-only notifications with a real gateway bot — per-ad watch/mute/blocklist buttons, seller lookups, query control from Discord. §1 explains why gateway and not a public HTTP endpoint. |
| [`JOB_QUEUE_DESIGN.md`](refactor/JOB_QUEUE_DESIGN.md) | 💡 proposal | 2026-07-26 | Generalise the `run_filter`/`run_sender` polling pattern into a `Job` model + registry + one worker, so new recurring work stops meaning a new compose service and a hand-rolled sleep loop. |
| [`archive/P19_ZERO_RESULTS_CANARY.md`](refactor/archive/P19_ZERO_RESULTS_CANARY.md) | ✅ shipped | 2026-08-21 | The zero-results canary spec, implemented as written plus one fix: a zero-rows pass also resets the zero-new-ads streak. |
| [`archive/REFACTOR_SUGGESTIONS.md`](refactor/archive/REFACTOR_SUGGESTIONS.md) | ✅ shipped | 2026-07-19 | Nine small cleanups, all done. A completed changelog. |
| [`archive/REFACTOR_PLAN.md`](refactor/archive/REFACTOR_PLAN.md) | 🗄 superseded | — | Consolidated Phase 1/2/3 framing. Its progress markers went stale; `PIPELINE_REFACTOR.md`'s are the ones that were kept in sync. |
| [`archive/PIPELINE_REFACTOR_B.md`](refactor/archive/PIPELINE_REFACTOR_B.md) | 🗄 superseded | — | Fully merged into `PIPELINE_REFACTOR.md`. No unique content remains. |

### `marketplaces/` — which marketplace to add next

**Study completed 2026-08-22.** 13 candidates assessed live under hard per-site request caps, in
two tracks: Track A (marketplaces to scrape) and Track B (reference-price sources). **Verdict:
build Sbazar next** — which then happened, see [`SHIPPED.md`](SHIPPED.md). Aukro is the open
question.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`RECOMMENDATION.md`](marketplaces/RECOMMENDATION.md) | 📐 reference | 2026-08-22 | **Start here.** The ranked answer for both tracks, with the counter-argument that would flip it stated plainly. §3.4 records the three probes that decide Aukro (they were run). §6 lists the five methodology corrections the study produced. |
| [`SUMMARY_TABLE.md`](marketplaces/SUMMARY_TABLE.md) | 📐 reference | 2026-08-22 | One page: all 13 candidates with verdict, measured scale, new capability, effort, legal posture — plus the vantage-point table. |
| [`AUKRO.md`](marketplaces/AUKRO.md) | 📐 reference | 2026-08-22 | **VIABLE, and the only source that closes the realised-price gap** — ended auctions readable unauthenticated ≥2.75 years back. §6a.1 tempers it: only ~11% of sampled ended items had bids, and §4.1.1 confirms **Tor is blocked**. |
| [`SBAZAR.md`](marketplaces/SBAZAR.md) | 📐 reference | 2026-08-22 | The measured basis for the shipped scraper: the unauthenticated `/api/v1/items/search` API, the mandatory field-mapping table, and §2.1's bump-rate measurement that the dedup fix depends on. |
| [`RESEARCH_BRIEF.md`](marketplaces/RESEARCH_BRIEF.md) | 📐 reference | 2026-08-22 | The brief the study ran from — methodology, not findings. Still the reference for *how* to assess a marketplace: two passes, hard request caps, measured-vs-assumed discipline, §5b's schema-fit checklist. |
| [`pass1/METHOD_CALIBRATION.md`](marketplaces/pass1/METHOD_CALIBRATION.md) | 📐 reference | 2026-08-22 | **Worth reading on its own.** The brief's new/day method failed twice against Bazos before working: `topped` is the *string* `"true"`, the method is impossible at default page size, and diurnal bias is ~2×. |
| [`pass1/RANKING.md`](marketplaces/pass1/RANKING.md) | 📐 reference | 2026-08-22 | The pre-Pass-2 commitment, kept with its corrections visible — two of its three Aukro inferences were later measured false. |
| [`pass1/SBAZAR_pass1.md`](marketplaces/pass1/SBAZAR_pass1.md) | 📐 reference | 2026-08-22 | Sbazar scale triage. §5.1 flags the real tension: the sitemap tree is inside a blanket `Disallow: /`. |
| [`pass1/AUKRO_pass1.md`](marketplaces/pass1/AUKRO_pass1.md) | 📐 reference | 2026-08-22 | Aukro triage from a datacenter IP — everything 403'd. Superseded on the facts by `AUKRO.md`; kept because the reversal is the study's sharpest methodology lesson. |
| [`pass1/TRACKB_HEUREKA.md`](marketplaces/pass1/TRACKB_HEUREKA.md) | 📐 reference | 2026-08-22 | Heureka/Zboží as a reference-price source. **REJECT — and the blocker is on our side**: `Ad` has no brand/model field to join *from*. Closes `BACKLOG_IDEAS.md` #4. |
| [`pass1/TRACKB_EBAY.md`](marketplaces/pass1/TRACKB_EBAY.md) | 📐 reference | 2026-08-22 | eBay sold listings. **No route for a non-partner**: `findCompletedItems` decommissioned 2025-02-05, Insights invitation-only, and 90 days is too short anyway. |
| [`pass1/BAZOS_SISTER_SITES_pass1.md`](marketplaces/pass1/BAZOS_SISTER_SITES_pass1.md) | 📐 reference | 2026-08-22 | `.sk`/`.at`/`.pl` — near-zero engineering, but all three refused an IP `.cz` accepted in the same minute. **Cheap breadth, not a hedge.** |
| [`pass1/MINOR_CLASSIFIEDS_pass1.md`](marketplaces/pass1/MINOR_CLASSIFIEDS_pass1.md) | 📐 reference | 2026-08-22 | Mimibazar, Hyperinzerce, Annonce, Avizo — all rejected on scale or category fit. Annonce's headline "1,568 notebooks" was **1,544 job ads** mentioning a laptop as a perk. |
| [`pass1/VERTICALS_pass1.md`](marketplaces/pass1/VERTICALS_pass1.md) | 📐 reference | 2026-08-22 | TipCars, Sauto, Sreality, Bezrealitky, Remix. Remix serves schema.org `Product` JSON-LD with real typed attributes — the strongest capability signal in the batch, on apparel. |
| [`pass1/FACEBOOK_MARKETPLACE_pass1.md`](marketplaces/pass1/FACEBOOK_MARKETPLACE_pass1.md) | 📐 reference | 2026-08-22 | REJECT. Blanket `Disallow: /` plus a prose notice requiring express written permission — categorically stricter than any other candidate. |

### `bazos-api/` — Bazos's undocumented mobile JSON API

Reverse-engineered from the decompiled Android app. Independent of the pipeline stages — it's
about *how* Bazos is scraped. `BazosApiScraper` exists and is registered, but **no production
`Query` selects it**; making that switch is `PROMPTS.md` P21a.

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`BAZOS_HIDDEN_API_RESEARCH.md`](bazos-api/BAZOS_HIDDEN_API_RESEARCH.md) | 📐 reference | 2026-07-26 | Endpoint inventory, request/response shapes, live-validated findings. **§4.1a–4.1b is the load-bearing bit**: `OR` is a real boolean union, `AND` is fake, and the search is plain SQL substring `LIKE`, not FULLTEXT boolean mode. §5 shows listing and detail are *not* the same payload. |
| [`BAZOS_API_USER_AGENT.md`](bazos-api/BAZOS_API_USER_AGENT.md) | ✅ shipped | 2026-07-19 | How the app builds its `User-Agent` at runtime and how to reproduce it. Implemented as `bazos/scraping/bazos/user_agent.py`. |
| [`BAZOS_API_DISCOVERY_PIPELINE.md`](bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md) | 💡 proposal | 2026-08-10 | A broader category-scoped discovery pipeline plus the enrichment workflows the API makes cheap — seller reputation, dealer/scam detection, repost detection. Nothing built. |

### `proxies/` — replacing Tor for Bazos requests

| Doc | Status | Verified | What it is |
|---|---|---|---|
| [`PROXY_ROTATION_RESEARCH.md`](proxies/PROXY_ROTATION_RESEARCH.md) | 📐 reference | 2026-07-26 | Why Tor (IP reputation) and a single long-lived VPN (per-IP rate) both failed, and what to use instead. **§4–§5 are live-measured** request/bandwidth volumes including the "run more often" cadence math and the 77+ GB/mo download-all-images scenario. §8 sketches `HttpProxyIPChanger`. **The one thing still unmeasured (§10) is sustained block rate through a real candidate proxy** — that's the gate on `PROMPTS.md` P21b. |

The throwaway benchmark it references lives at [`experiments/bench_proxy.py`](../experiments/bench_proxy.py).
