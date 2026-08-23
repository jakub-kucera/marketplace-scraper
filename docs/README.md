# Docs Index

Planning and research notes for the scraper. Runtime/architecture docs live in the root
[`CLAUDE.md`](../CLAUDE.md) — everything here is forward-looking design or historical record.

**[`SHIPPED.md`](SHIPPED.md) is the single source of truth for what is implemented.** If a doc
here describes something as future work and `SHIPPED.md` lists it, `SHIPPED.md` wins — file an
edit against the doc rather than trusting it.

## Business

| Doc | What it's for |
|---|---|
| [`MONETIZATION.md`](MONETIZATION.md) | Options analysis for turning the project into revenue — data sales, flipping/arbitrage, subscriptions, selling the capability — each with competitor check, financial model, and verdict. Includes the **legal section that constrains the rest** (Bazos ToS API-consent clause + `robots.txt`, sui generis database right / *Innoweb v Wegener*, GDPR Art 14 and the KASPR/Bisnode fines, Act 480/2004 anti-spam, CZ tax/VAT for reselling). **§7.1 argues that detection latency — not features — is the binding constraint** on the whole "find deals" goal, and is cross-referenced from [`refactor/PROMPTS.md`](refactor/PROMPTS.md) P21 and [`refactor/BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md)'s priority table; §7.2 lists three data-model defects that block every data-driven option. **§4.7** analyses the job/gig-post idea — measured Bazos `Práce` volumes (too small), the economics of taking automatable gigs (below contract rate), the Gemini free-tier EEA data carve-out, and the reframe that makes it worth keeping: read job ads as **automation-consulting leads**, not as jobs. |

## Operations

| Doc | What it's for |
|---|---|
| [`BACKUPS.md`](BACKUPS.md) | **There is no backup of the database today** — the only copies are the live `postgres_data/` bind mount on the Pi and a 2.5-year-stale CSV export. Compares the dump options (`pg_dump -Fc` / plain SQL / `pg_dumpall` / Django `dumpdata` / cold copy / PITR / managed / replica), where to run them (compose sidecar vs. host cron vs. the job queue), off-host destinations and cost, and the **retention/GDPR interaction** — a PII purge that doesn't reach the backups isn't a purge. Recommends nightly `pg_dump -Fc` → `restic` to B2, ~2 hours, ~$0/mo. Directly closes the gap in [`MONETIZATION.md`](MONETIZATION.md) §7.3, which calls the archive irreplaceable while it sits unbacked on one SD card. |

## `refactor/` — pipeline decoupling (scraper → filter → sender)

| Doc | What it's for |
|---|---|
| [`PIPELINE_REFACTOR.md`](refactor/PIPELINE_REFACTOR.md) | The stage-by-stage plan (Stages 1–10). **9 of 10 done** — only Stage 5 (query priority) is open, and it lives in executable form as `PROMPTS.md` P2. Kept for the per-stage rationale; [`SHIPPED.md`](SHIPPED.md) is where to look for what's done. |
| [`STAGE8_VINTED_DESIGN.md`](refactor/STAGE8_VINTED_DESIGN.md) | Design doc for Stage 8 (VintedScraper + multi-marketplace `Query`). §3–§5 (the `Query` model fork, Option C) are the durable part. **§1–§2 were rewritten from a live probe on 2026-08-21** — `vinted-scraper` **4.0.0**, not 3.1.1; `description` is **not** in search results (so `load_full_description` is not a no-op); `promoted` maps to `topped`; no date field exists at all; and `vinted.cz` returns mostly Polish listings at FX-converted prices. §8 has a repro script. |
| [`STAGE8_VINTED_SPEC.md`](refactor/STAGE8_VINTED_SPEC.md) | **✅ Built 2026-08-22.** Executable spec for Stage 8, superseding the old `PROMPTS.md` P3/P4 (since retired). Four PRs. Leads with two schema blockers that crash on Postgres while passing on SQLite: `Ad.external_id` is an `IntegerField` and Vinted ids are 4.5× over `int4` max, and `publish_date`/`view_count` are NOT NULL with no default. Also pins the `parse_price` decimal trap (a `"6307.5"` price string parses to **63075**) and the two distinct `load_full_description` failure modes. |
| [`PRICE_PARSING_RESEARCH.md`](refactor/PRICE_PARSING_RESEARCH.md) | **The measured groundwork P22 was built from — all four marketplaces sampled live. ✅ P22 shipped 2026-08-23**, so §1's "there is no numeric price column" is historical; §2 onward is still current, because it describes the marketplaces rather than the schema. Headline: `re.sub(r"\D","")` is correct for **Bazos only** and wrong in a *different* way for each of the other three — Vinted is float with **72% non-integer** (error is 10^dp, so `"9902.82"` → 100× too large), Aukro is `int` **or** `float` *unstably within one response*, and Sbazar is clean int but **`0` can mean free or negotiable** depending on a flag. **Three marketplaces encode "zero" differently.** Also corrects its own first draft: the "48.8% of ads have no price" figure is a `Práce` job-ads artifact (one query = 83% of the corpus and 99.98% of placeholders); goods categories measure **0–9%**. Concludes: normalise at the scraper, not the parser — and adds `Nerozhoduje`, `FREE`→0 and `BigIntegerField` as corrections to P22's proposed enum. |
| [`STAGE10_SBAZAR_SPEC.md`](refactor/STAGE10_SBAZAR_SPEC.md) | **✅ Built 2026-08-22.** Executable spec for Stage 10 (`SbazarScraper`), written to be followed literally — complete code, exact endpoints, verification command per step. Response shape re-verified live before finalising. Leads with a **blocking Tor pre-flight (§1.5)**: every measurement behind it was taken over a direct residential connection, but the scraper runs on the Tor-proxied shared session, so §3.2 carries a Vinted-style escape hatch if that probe fails. §6 pins four silent traps — the price-by-agreement flag that would otherwise reject every negotiable ad, a `short_description` that overflows its column on Postgres but not SQLite, and the reminder that Sbazar's integer prices need **neither** Aukro's float fix nor Zboží's hundredths fix. |
| [`AD_DELIVERY_SPLIT_SPEC.md`](refactor/AD_DELIVERY_SPLIT_SPEC.md) | **Executable spec for [`BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) #1 option B** — split `Ad` (scraped facts, globally unique on `(marketplace, external_id)`) from `AdDelivery` (per-`(ad, query)` pipeline state). Four staged PRs — **all four landed 2026-08-21/22** (`0026`–`0028`); §3 pre-decides the six places where the plausible choice is wrong, notably that the dedup break must key on the **delivery**, not on global `Ad` existence, or a new query never backfills. `Ad.status`/`filter_reason`/`sent_at`/`send_attempts`/`query` no longer exist on `Ad` — pipeline state lives entirely on `AdDelivery`. **Post-merge review found and fixed a blocker** (an interrupted first run of a new query wedged permanently — see `PROMPTS.md` P26) plus several deferred follow-ups, also P26. |
| [`PROMPTS.md`](refactor/PROMPTS.md) | Ready-to-run prompts for the work that is **not** yet done, ordered by dependency. Prompt numbers are stable and gapped: the ones that shipped were removed and recorded in [`SHIPPED.md`](SHIPPED.md), and numbers are never reused — so a reference to "P5" elsewhere in these docs still identifies the same work. |
| [`BACKLOG_IDEAS.md`](refactor/BACKLOG_IDEAS.md) | Deeper dives on ideas mined from the GitHub issue tracker that aren't part of any numbered stage — cross-query dedup, async scraping, images, price/CV enrichment, interval tuning, query syntax. **#11 (done, 2026-08-10)** records the shipped seller-identity work — transitive `(email_id, phone_id)` resolution, per-seller counts in the admin and Discord, and the `bazos_id=0` sentinel discovery that made 6.7% of ads share one fake seller. |
| [`LLM_AD_REVIEW_DESIGN.md`](refactor/LLM_AD_REVIEW_DESIGN.md) | Proposal (not scheduled): an LLM-based ad judge as its own pipeline stage, and draft-only seller-outreach messages via Discord. Explicitly recommends against auto-sending messages to sellers without a separate decision. Its per-query multi-filter mechanism (§1) was independently built — see `PROMPTS.md` P17 (done). §2f now carries researched free-tier cost/ops figures and the Gemini EEA data-terms carve-out that makes a free tier viable for public ad text — added 2026-07-30 from [`MONETIZATION.md`](MONETIZATION.md) §4.7, which independently re-derived §2's "own stage, not a `FilterRule`" conclusion. |
| [`DISCORD_BOT_DESIGN.md`](refactor/DISCORD_BOT_DESIGN.md) | Proposal (not scheduled): replace webhook-only notifications with a real Discord bot (gateway-based, not a public HTTP endpoint — see §1 for why) enabling per-ad watch/mute/favorite/blocklist buttons, seller lookups, on-demand full-description fetch, and query control from Discord. Connects to and partly supersedes `LLM_AD_REVIEW_DESIGN.md` §4.2's outreach delivery mechanism — see its §5 for the full cross-reference map. |
| [`JOB_QUEUE_DESIGN.md`](refactor/JOB_QUEUE_DESIGN.md) | Proposal (not scheduled): generalize `run_filter`/`run_sender`'s DB-polling pattern into a generic `Job` model + registry + `run_jobs` worker, so new recurring/on-demand work (`AdWatch`, full-rescan, seller enrichment, LLM review, ...) becomes a new job type instead of a new hand-rolled process/docker-compose service. Catalogs candidate jobs sourced from `BACKLOG_IDEAS.md` #6/#8, `DISCORD_BOT_DESIGN.md`, `BAZOS_API_DISCOVERY_PIPELINE.md`, and `LLM_AD_REVIEW_DESIGN.md`. |
| [`E2E_REPLAY_TESTING_RESEARCH.md`](refactor/E2E_REPLAY_TESTING_RESEARCH.md) | **✅ Research, then built — all four steps landed 2026-08-23** (`60a7873`): `vcrpy` cassettes for the Bazos transport plus a scrape→filter→send golden master, and the `--once` flags that unblocked it. Record-and-replay E2E tests, starting from the Bazos scraper. Every existing test stops *above* the transport layer, so URL construction, pagination, 403 handling and request *counts* are untested — §1 maps the hole. Recommends `vcrpy` cassettes (T1 transport tests, then T3 scrape→filter→send golden-master) and pins the traps measured live on this repo's stack: **vcrpy 8.x cannot be installed** (`requests 2.28.2` + `selenium 4.8.2` both forbid urllib3 2.x — use 7.0.0), cassettes are unreadable `!!binary` without `decode_compressed_response=True`, `filter_headers` **leaks response** `Set-Cookie`, and a configured **proxy breaks host/port matching** so cassettes must be recorded un-proxied. §5 named the real blocker — `run_filter`/`run_sender` were bare `while True` loops with no `--once` — and that is what got fixed first. |
| `archive/` | Superseded drafts, kept for history only — see banners in each file. |

**Current stage status** (verified against code, migrations and `git log` on **2026-08-23**):

| Stage | Status |
|---|---|
| 1–3 · DB status machine, `run_filter`, `run_sender` | ✅ done |
| 4 · Price history (`PriceChange` model) | ✅ done |
| **5 · Query priority** | **not started — the only open stage.** Executable form is [`PROMPTS.md`](refactor/PROMPTS.md) P2 |
| 6–7 · Marketplace abstraction (`external_id`/`marketplace` rename, `MarketplaceScraper`/`Sendable` protocols) | ✅ done |
| 8 · `VintedScraper` | ✅ done (2026-08-22) — `Marketplace.VINTED` live, migration `0029` |
| 9 · Real filter rules | ✅ done |
| 10 · `SbazarScraper` | ✅ done (2026-08-22) — `Marketplace.SBAZAR` live, migration `0030`, **no `Ad` migrations needed** |

Work that landed outside the numbered stages — the `Ad`/`AdDelivery` split, numeric prices, the
E2E replay harness, database backups, the blacklist rework — is in [`SHIPPED.md`](SHIPPED.md).

## `marketplaces/` — which marketplace to add next

**Study completed 2026-08-22.** 13 candidates assessed live under hard per-site request caps, in
two tracks: Track A (CZ marketplaces to scrape) and Track B (reference-price sources, which produce
no `Ad` rows and are ranked separately). **Verdict: build Sbazar.cz next**, then re-evaluate Aukro
against three cheap probes.

| Doc | What it's for |
|---|---|
| [`RECOMMENDATION.md`](marketplaces/RECOMMENDATION.md) | **Start here.** The ranked answer, both tracks, with the argument for Sbazar-first spelled out *including the counter-argument that would flip it*. §3.4 lists the three probes that decide Aukro; §6 records the five methodology corrections the study produced. |
| [`SUMMARY_TABLE.md`](marketplaces/SUMMARY_TABLE.md) | One-page table of all 13 candidates — verdict, measured scale, new capability, effort, legal posture — plus a technical comparison of the three survivors and the vantage-point table. |
| [`SBAZAR.md`](marketplaces/SBAZAR.md) | **VIABLE — the recommended build.** Full workup: the unauthenticated `/api/v1/items/search` JSON API (no auth, `limit=1000`, **newest-first by default**), the mandatory field-mapping table, and the schema verdict — `id` is an integer, so **zero `Ad` migrations are needed**. |
| [`AUKRO.md`](marketplaces/AUKRO.md) | **VIABLE — the capability play.** Aukro publishes **realised prices**: ended auctions are readable unauthenticated ≥2.75 years back, and `biddersCount > 0` + `price` is what an item actually sold for — the gap [`MONETIZATION.md`](MONETIZATION.md) §7.2c calls the single biggest in the project. §6a.1 tempers it: **~11% of sampled ended items had bids**, and buy-now listings expose no sold signal at all. |
| [`RESEARCH_BRIEF.md`](marketplaces/RESEARCH_BRIEF.md) | The brief the study was run from — methodology, not findings. Still the reference for *how* to assess a marketplace: two passes, hard request caps, measured-vs-assumed discipline, and the §5b schema-fit checklist. |
| [`pass1/`](marketplaces/pass1/) | Per-candidate triage files and the two Track B assessments. [`METHOD_CALIBRATION.md`](marketplaces/pass1/METHOD_CALIBRATION.md) is the one worth reading on its own — see below. [`RANKING.md`](marketplaces/pass1/RANKING.md) is the pre-Pass-2 commitment, kept with its corrections visible. |

**What the study found, in five lines:**

- **Sbazar** clears the bar and is cheap: `stavebnictvi-naradi` holds **26,738** active listings —
  **3.4× Bazos's `naradi`** — behind a clean unauthenticated JSON API needing **no migrations**. It
  adds **no new capability**, and has the **worst legal posture** of the three (`Disallow: /` plus
  `Disallow: /api/`).
- **Aukro** is the bigger prize and the better legal footing (899-byte `robots.txt`, cart/account
  paths only), but its realised-price data is **sparse and auction-only**, it needs
  [`PROMPTS.md`](refactor/PROMPTS.md) **P22 as a hard prerequisite** (its prices are floats —
  `861.0` parses to `8610`, 10× too large), and it may be **incompatible with the Tor stack**.
- **`bazos.sk` / `.at` / `.pl`** work and are near-zero engineering (`.sk` notebook 7,225 = 0.92× `.cz`),
  but all three refused an IP `.cz` accepted *in the same minute* — **cheap breadth, not a hedge**.
- **Track B is premature, with a named unblock condition**: both eBay and Heureka/Zboží fail on the
  *near* side — `Ad` has no brand/model field to join *from*. eBay additionally has no route at all
  (`findCompletedItems` decommissioned 2025-02-05; Insights is invitation-only).
- **Everything else was rejected on measured scale or category fit** — Hyperinzerce, Annonce,
  Mimibazar, Avizo, TipCars, Sauto, Sreality, Bezrealitky, Remix, Facebook Marketplace.

⚠️ **Methodology lessons that outlive the verdicts** — all in
[`pass1/METHOD_CALIBRATION.md`](marketplaces/pass1/METHOD_CALIBRATION.md) and
[`RECOMMENDATION.md`](marketplaces/RECOMMENDATION.md) §6, and worth reading before the next study:

1. The brief's own new/day method **failed twice on Bazos before working** — `topped` is the
   *string* `"true"` (a truthiness check marks 100% of ads promoted), the method is impossible at
   default page size (0 organic ads in 30), and **diurnal bias is ~2×**.
2. **Sitemap `<lastmod>` overstated new/day by ~4×** — it conflates edits with creations.
3. **A vendored third-party API spec is not evidence about the live service.** Pass 1 concluded
   Aukro had no realised prices, reasoning from an Allegro WSDL found on GitHub; two of its three
   inferences were later measured false.
4. **A site's own headline count can be a trap** — Annonce reported 1,568 notebooks, of which
   **1,544 were job ads** mentioning a laptop as a perk.
5. **Vantage point changes answers.** Aukro, Sbazar and `bazos.sk` all refused a datacenter VPN IP
   and cleared instantly from residential — but **eBay blocked the residential line just as hard**.
   A residential IP is not a master key.

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

## `proxies/` — replacing Tor for Bazos requests

| Doc | What it's for |
|---|---|
| [`PROXY_ROTATION_RESEARCH.md`](proxies/PROXY_ROTATION_RESEARCH.md) | Why Tor (IP reputation) and the old single Surfshark VPN (per-IP rate) both failed; the fix (rotating **residential**, CZ-geo); **live-measured** request/bandwidth volumes (via `experiments/bench_proxy.py`) incl. the "run more often" cadence math, the broad **scrape-all** scenario, and the **download-all-images** scenario (77+ GB/mo → split transport: images on cheap datacenter, API on residential); 2026 provider pricing; and an `HttpProxyIPChanger` integration sketch behind `IP_CHANGER_TYPE=HTTP_PROXY`. |

The throwaway benchmark it references lives at [`experiments/bench_proxy.py`](../experiments/bench_proxy.py).

**Status (2026-07-24):** Stage B is implemented — `BazosApiScraper`
(`bazos/scraping/bazos/bazos_api_scraper.py`) is a second `MarketplaceScraper`
registered under `marketplace="bazos_api"` for validation only; the production
`run_scraper` loop is untouched since no `Query` uses that value. Compare it
against the HTML scraper with `python manage.py compare_bazos_scrapers`. See
`BAZOS_HIDDEN_API_RESEARCH.md` §8 Stage B for details.
