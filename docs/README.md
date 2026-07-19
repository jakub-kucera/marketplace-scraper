# Docs Index

Planning and research notes for the scraper. Runtime/architecture docs live in the root
[`CLAUDE.md`](../CLAUDE.md) — everything here is forward-looking design or historical record.

## `refactor/` — pipeline decoupling (scraper → filter → sender)

| Doc | What it's for |
|---|---|
| [`PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) | **Start here.** The live, authoritative stage-by-stage plan (Stages 1–9). Checkmarks are kept in sync with the code. |
| [`STAGE8_VINTED_DESIGN.md`](refactor/STAGE8_VINTED_DESIGN.md) | Design doc for Stage 8 (VintedScraper + multi-marketplace `Query`), referenced from Stage 8 above. |
| [`PROMPTS.md`](refactor/PROMPTS.md) | Ready-to-run prompts for implementing not-yet-done stages, ordered by dependency. |
| `archive/` | Superseded drafts, kept for history only — see banners in each file. |

**Current stage status** (verified against code, 2026-07-19):

| Stage | Status |
|---|---|
| 1–3 · DB status machine, `run_filter`, `run_sender` | ✅ done |
| 4 · Price history (`PriceChange` model) | not started |
| 5 · Query priority | not started |
| 6–7 · Marketplace abstraction (`external_id`/`marketplace` rename, `MarketplaceScraper`/`Sendable` protocols) | ✅ done |
| 8 · VintedScraper | not started (design ready, see `STAGE8_VINTED_DESIGN.md`) |
| 9 · Real filter rules (only `PassthroughRule` exists) | not started |

## `bazos-api/` — Bazos's undocumented mobile JSON API

Reverse-engineered from the decompiled Android app. Read in this order:

| Doc | What it's for |
|---|---|
| [`BAZOS_HIDDEN_API_RESEARCH.md`](bazos-api/BAZOS_HIDDEN_API_RESEARCH.md) | Endpoint inventory, request/response shapes, live-validated findings, and the recommendation to migrate `BazosScraper` to this API. |
| [`BAZOS_API_USER_AGENT.md`](bazos-api/BAZOS_API_USER_AGENT.md) | How the app builds its `User-Agent` header and how to reproduce it — referenced from the research doc §2.2. |
| [`BAZOS_API_DISCOVERY_PIPELINE.md`](bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md) | Builds on the research doc: a broader category-scoped discovery pipeline plus downstream enrichment workflows (seller reputation, scam/dealer detection, repost detection) the API newly makes cheap. |

This body of work is independent of the `refactor/` pipeline stages — it's about *how* Bazos
is scraped, not the PENDING→APPROVED→SENT pipeline. Not yet wired into `PIPELINE_REFACTOR.md`'s
stage list as a decision has not been made to pursue it.
