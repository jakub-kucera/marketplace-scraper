# Docs Index

Planning and research notes for the scraper. Runtime/architecture docs live in the root
[`CLAUDE.md`](../CLAUDE.md) — everything here is forward-looking design or historical record.

## `refactor/` — pipeline decoupling (scraper → filter → sender)

| Doc | What it's for |
|---|---|
| [`PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) | **Start here.** The live, authoritative stage-by-stage plan (Stages 1–9). Checkmarks are kept in sync with the code. |
| [`STAGE8_VINTED_DESIGN.md`](refactor/STAGE8_VINTED_DESIGN.md) | Design doc for Stage 8 (VintedScraper + multi-marketplace `Query`), referenced from Stage 8 above. |
| [`PROMPTS.md`](refactor/PROMPTS.md) | Ready-to-run prompts for implementing not-yet-done stages, ordered by dependency. |
| [`BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) | Deeper dives on ideas mined from the GitHub issue tracker that aren't part of any numbered stage — cross-query dedup, async scraping, images, price/CV enrichment, interval tuning, query syntax. |
| [`LLM_AD_REVIEW_DESIGN.md`](refactor/LLM_AD_REVIEW_DESIGN.md) | Proposal (not scheduled): an LLM-based ad judge as its own pipeline stage, and draft-only seller-outreach messages via Discord. Explicitly recommends against auto-sending messages to sellers without a separate decision. Its per-query multi-filter mechanism (§1) was independently built — see `PROMPTS.md` P17 (done). |
| [`DISCORD_BOT_DESIGN.md`](refactor/DISCORD_BOT_DESIGN.md) | Proposal (not scheduled): replace webhook-only notifications with a real Discord bot (gateway-based, not a public HTTP endpoint — see §1 for why) enabling per-ad watch/mute/favorite/blocklist buttons, seller lookups, on-demand full-description fetch, and query control from Discord. Connects to and partly supersedes `LLM_AD_REVIEW_DESIGN.md` §4.2's outreach delivery mechanism — see its §5 for the full cross-reference map. |
| `archive/` | Superseded drafts, kept for history only — see banners in each file. |

**Current stage status** (verified against code, 2026-07-24):

| Stage | Status |
|---|---|
| 1–3 · DB status machine, `run_filter`, `run_sender` | ✅ done |
| 4 · Price history (`PriceChange` model) | ✅ done |
| 5 · Query priority | not started |
| 6–7 · Marketplace abstraction (`external_id`/`marketplace` rename, `MarketplaceScraper`/`Sendable` protocols) | ✅ done |
| 8 · VintedScraper | not started (design ready, see `STAGE8_VINTED_DESIGN.md`) |
| 9 · Real filter rules (`PriceRangeRule`, `BlocklistKeywordRule`, `RequiredKeywordRule`, `PublisherBlocklistRule`, `PriceDropRule`) | ✅ done |

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

**Status (2026-07-24):** Stage B is implemented — `BazosApiScraper`
(`bazos/scraping/bazos/bazos_api_scraper.py`) is a second `MarketplaceScraper`
registered under `marketplace="bazos_api"` for validation only; the production
`run_scraper` loop is untouched since no `Query` uses that value. Compare it
against the HTML scraper with `python manage.py compare_bazos_scrapers`. See
`BAZOS_HIDDEN_API_RESEARCH.md` §8 Stage B for details.
