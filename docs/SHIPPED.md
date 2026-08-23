---
title: Shipped
status: active
updated: 2026-08-23
verified: 2026-08-23
---

# Shipped

**What has actually been implemented, and where to read why.** One row per piece of work. This
file is the single answer to "is that done?" — if something is listed here, it must not also be
listed as open in [`refactor/PROMPTS.md`](refactor/PROMPTS.md) or
[`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md).

Verified against migrations, code and `git log` on **2026-08-23**. Newest first.

| Shipped | What landed | Migration / commit | Designed in |
|---|---|---|---|
| 2026-08-23 | **Blacklist handling reworked — most of P20 and P21a Part 2.** The pre-flight `check_blacklisted()` probe is **deleted** on both scrapers: it hit one fixed `search.php` URL while Bazos's block is path-scoped, so it reported "clear" moments before the query's own page 403'd. The query attempt is now the probe — `BazosRunner._run_query_with_rotation` catches `BazosBlacklistedError` from the real request, rotates, and retries up to `MAX_BLACKLIST_RETRIES=3`. `QueryRun.exit_ip` records the egress per attempt so IP reputation can be told apart from a rate limit. `check_ip_local()` moved to once per pass. `tor.py`'s second unbounded `while True` is bounded by `MAX_RENEW_ATTEMPTS=5` and re-signals NEWNYM each round. Request pacing added throughout (`BAZOS_PAGE_WAIT_TIME`, `BAZOS_DETAIL_WAIT_TIME`, `BAZOS_QUERY_WAIT_TIME`). | `0034` | [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P20 cases (a)/(b) and P21a Part 2 |
| 2026-08-23 | **E2E record-and-replay tests** — `vcrpy` 7.0 cassettes for the Bazos transport layer and a scrape→filter→send golden master, plus `--once` on `run_filter`/`run_sender` (the blocker the research named). 16 cassettes under `bazos/tests/cassettes/`. | `60a7873` (#63) | [`refactor/E2E_REPLAY_TESTING_RESEARCH.md`](refactor/E2E_REPLAY_TESTING_RESEARCH.md) |
| 2026-08-23 | **Numeric price — P22.** `Ad.price` (`BigIntegerField`, indexed, nullable) + `Ad.price_type` (`PriceType` enum), `PriceChange.old_price_amount`/`new_price_amount`, `parse_price_and_type()`. `PriceRangeRule` reads `ad.price` instead of re-parsing `price_raw` at filter time. | `0032`, `0033` · `2082075` | [`refactor/PRICE_PARSING_RESEARCH.md`](refactor/PRICE_PARSING_RESEARCH.md) |
| 2026-08-22/23 | **`Ad` / `AdDelivery` split** — all four stages. `Ad` holds scraped facts, unique on `(marketplace, external_id)`; `AdDelivery` holds per-`(ad, query)` pipeline state. `Ad.status`/`filter_reason`/`sent_at`/`send_attempts`/`query` no longer exist. Filter rules take an `AdDelivery`. | `0026`–`0028`, `0031` · `9d20b91`, `6b298be`, `b21f35c` | [`refactor/AD_DELIVERY_SPLIT_SPEC.md`](refactor/AD_DELIVERY_SPLIT_SPEC.md) — the executable form of [`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) #1 |
| 2026-08-22 | **`SbazarScraper` (Stage 10)** — `Marketplace.SBAZAR`, `bazos/scraping/sbazar/`, unauthenticated `/api/v1/items/search`, registered in `_build_scrapers()`. Includes the post-review `dedup_break_streak` fix: Sbazar sorts by edit time, so the dedup walk breaks after N consecutive known ads, not one. | `0030` · `3344399` | [`refactor/STAGE10_SBAZAR_SPEC.md`](refactor/STAGE10_SBAZAR_SPEC.md), measured in [`marketplaces/SBAZAR.md`](marketplaces/SBAZAR.md) |
| 2026-08-22 | **`VintedScraper` (Stage 8)** — `Marketplace.VINTED`, `Query.extra_params` JSONField, `Ad.external_id` → `BigIntegerField`, `publish_date`/`view_count` nullable. Built against `vinted-scraper` **4.0.0** after a live probe. | `0029` · `2b1cfbf`, `a2f6555` | [`refactor/STAGE8_VINTED_SPEC.md`](refactor/STAGE8_VINTED_SPEC.md) (supersedes `PROMPTS.md` P3/P4), design in [`refactor/STAGE8_VINTED_DESIGN.md`](refactor/STAGE8_VINTED_DESIGN.md) |
| 2026-08-22 | **Marketplace study** — 13 candidates assessed live, two tracks, verdict *build Sbazar next*. Not code, but it closed the "which marketplace" question and the `BACKLOG_IDEAS.md` #4 Heureka research gap. | `deeec15` | [`marketplaces/`](marketplaces/RECOMMENDATION.md) |
| 2026-08-21 | **Zero-results canary — P19.** `BazosRunner._check_zero_results_canary` + `BazosQueryRunner.rows_seen_counter`; alerts on consecutive passes that parse no rows, with a separate high threshold for "rows but no new ads". | `739815c` | [`refactor/archive/P19_ZERO_RESULTS_CANARY.md`](refactor/archive/P19_ZERO_RESULTS_CANARY.md) |
| 2026-08-16 | **Database backups.** One-shot `backup/` container (`FROM postgres:15.2`) → `./backups/` → optional `restic`, behind a compose `profiles: ["backup"]` key, scheduled by a systemd timer on the Pi with `Persistent=true`. Pre-migration `pg_dump` gates the deploy. | `1cb0178` | [`BACKUPS.md`](BACKUPS.md) — was the ⚠️⚠️ "do first" row in both backlogs |
| 2026-08-09/10 | **Seller identity & history — `BACKLOG_IDEAS.md` #11.** Transitive `(email_id, phone_id)` resolution to a fixpoint (`SellerAdCounts`, `MAX_IDENTITY_ROUNDS=5`), per-seller counts in the admin and in the Discord message, publisher partner tables with block/unblock. Migration `0025` removed the `bazos_id=0` sentinel that had merged 6.7% of ads into one fake seller. | `0025` · `e5ccf76`, `713b79e`, `e814741`, `0d927b0` | [`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) #11 |
| 2026-08-09 | **Sentry gated out of pytest — P6 follow-up.** Sentry initialises only when `SENTRY_DSN` is set *and* not running under pytest. | `a52ca9c` | [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P6 |
| 2026-08-08 | **`QueryRun` survives a crash — P18.** `QueryRun` is always saved, including on failure, with `success` and `error`. Previously a raising query lost its run row entirely. | `0023` · `54854bb` | [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P18 |
| 2026-08-08 | **`Marketplace` `TextChoices`** — one enum typing `Query.marketplace` *and* `Ad.marketplace` and keying the scraper registry, replacing free-text strings. | `0024` · `03b3546` | [`refactor/PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) Stage 6 |
| 2026-07-27 | **AND/OR query probe — P15 / `BACKLOG_IDEAS.md` #7.** Probed live: `OR` is real, `AND` is fake (plain SQL substring `LIKE`, not FULLTEXT boolean mode). Answered the question rather than building on a false premise. | `5a49079` | [`bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`](bazos-api/BAZOS_HIDDEN_API_RESEARCH.md) §4.1a–4.1b |
| 2026-07-25 | **Per-query filter rule registry — P17.** `RULE_REGISTRY` + `build_rule_engine(query)`, `Query.filter_rule_names` (empty = all), rendered as checkboxes in the admin. Independently arrived at by [`refactor/LLM_AD_REVIEW_DESIGN.md`](refactor/LLM_AD_REVIEW_DESIGN.md) §1. | `0022` · `079abb2`, `6025901` | [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P17 |
| 2026-07-24 | **Real filter rules (Stage 9) — P5.** `PriceRangeRule`, `BlocklistKeywordRule`, `RequiredKeywordRule`, `PublisherBlocklistRule`, `PriceDropRule` replace `PassthroughRule` in `run_filter`. | `0021` · `862cf7e` | [`refactor/PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) Stage 9 |
| 2026-07-24 | **Price history (Stage 4) — P1.** `PriceChange` model, `_is_known` → `_get_known`, `PRICE_CHANGED` status re-entering the filter stage. | `0020` · `5195c4c` | [`refactor/PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) Stage 4 |
| 2026-07-24 | **`BazosApiScraper` (hidden-API Stage B).** A second `MarketplaceScraper` over Bazos's mobile JSON API, registered under `Marketplace.BAZOS_API` **for validation only** — no `Query` uses it, so production `run_scraper` is still HTML-only. Compare with `python manage.py compare_bazos_scrapers`. *Stage C (select it in production) is still open — see `PROMPTS.md` P21a.* | `8ec261a` | [`bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`](bazos-api/BAZOS_HIDDEN_API_RESEARCH.md) §8 |
| 2026-07-03 | **Marketplace abstraction (Stages 6–7).** `bazos_id` → `external_id`, `Ad.marketplace`/`Query.marketplace`, `MarketplaceScraper` Protocol, `SendableMixin` → `Sendable` Protocol. | `0018` · `5298de0`, `efe7a09` | [`refactor/PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) Stages 6–7 |
| 2026-07-03 | **Sentry — P6.** Error tracking wired up, no perf tracing. | `0e1167c` | [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P6 |
| 2026-06-27/29 | **Pipeline decoupling (Stages 1–3).** `AdStatus` state machine, `run_filter` + `run_sender` as separate polling processes, scraper cut over to write-only. The refactor the whole `refactor/` directory is named after. | `0016`, `0017` · `193ebfa`, `840d7dd` | [`refactor/PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) Stages 1–3 |
| 2026-06-21 | **`print()` → `logging`.** App loggers (`bazos`, `senders`, `ip_changer`) to console + DB via `django-db-logger`. | `5b9b752` | [`refactor/archive/REFACTOR_PLAN.md`](refactor/archive/REFACTOR_PLAN.md) Step 0 |

## Also done, no longer tracked anywhere

The nine items in [`refactor/archive/REFACTOR_SUGGESTIONS.md`](refactor/archive/REFACTOR_SUGGESTIONS.md)
— dead-code deletion, `extract_product` split, mutable-default fix, IP-changer selection moved out
of the class body, ASCII-encode centralisation, page-break fix, `Sendable` Protocol, `DiscordSender`
retry cap, dedup-check extraction. That file is a completed changelog and is kept only for history.

## Partially done — read the caveat before assuming

- **P21a (latency, free half)** — Part 2 (the guard work) is done and then some; **Parts 1 and 4a
  — the tunable API page size, the production cutover and the interval drop — have not
  happened.** `BazosApiScraper` exists but no `Query` selects it, and the interval is unchanged,
  so **none of the latency win has actually been realised yet**.
- **P20 (IP guards)** — cases (a) and (b) are done. Case (c) is not: there are still **no request
  timeouts anywhere in `ip_changer/`**, and two call sites (`check_ip_local()` in `run()`,
  `change_ip()` on the rotation fall-through) can still raise and cost a whole pass.
- **P9 (admin UX)** — several items landed with the seller-identity work; the rest of the list in
  `PROMPTS.md` P9 is still open.
- **Bazos hidden API** — Stages A and B done, **Stage C (select in production) and Stage D
  (model follow-ups) open**. This is the same thing as P21a's cutover.
