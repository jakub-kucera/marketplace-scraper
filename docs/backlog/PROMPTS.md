---
title: Ready-to-Run Prompts
status: active
updated: 2026-08-30
verified: 2026-08-30
---

# Ready-to-Run Prompts

Copy-paste any of these when you have tokens to burn.

**Sections are ordered by priority, not by prompt number** — the defects and prerequisites
(P20–P24) sit above the older improvements (P7–P17) because they're things quietly broken or
blocking, not enhancements. **The section order is now out of step with the priority order**:
P20 has shrunk to a 15-minute logging leftover and P23 was overtaken by what shipped, so
neither still belongs at the top of the file. [Order recommendation](#order-recommendation) at
the bottom is authoritative — read that, not the section order.

**Prompt numbers are stable and gapped on purpose.** P1, P3–P6, P15, P17–P19 and P22 are gone
from this file because they are **done** — they are recorded in [`SHIPPED.md`](../SHIPPED.md)
with the migration and commit that landed them. Numbers are never reused.

---

## 🔴 Blocked / Missing (pipeline stages not yet implemented)

### P2 — Stage 5: Query Priority
```
Implement Stage 5 from docs/archive/shipped/PIPELINE_REFACTOR.md (Query Priority).

Steps:
1. Add `QueryPriority(IntegerChoices)` enum and `Query.priority` field to `bazos/models.py`.
2. Generate migration.
3. Update `run_sender` management command to pass priority to `send_sendable`.
4. Update `DiscordSender.send_sendable` and `_format_product_message` to accept a `priority` param:
   - HIGH → always `@here`
   - NORMAL → `@here` only if `Discord.notify` is True
   - LOW → no ping
5. Update `QueryAdmin` to show/edit priority.
6. Write tests for the new priority-aware formatting.
```

---

### P20 — IP-guard hardening: the log-level and escalation leftover

> **🟢 Cases (a), (b) and (c) are all done as of 2026-08-29. What remains is step 5 only**, and
> it is a visibility nicety rather than something that can cost a pass. P20 was written
> 2026-07-29 against three failure modes; here is where each stands, verified against the tree
> **2026-08-30**:
>
> - **(a) `check_ip_local()` silently skipping every query forever — done, differently than
>   proposed.** It runs **once per pass** at the top of `ScrapeRunner.run` and skips the whole
>   pass rather than `continue`-ing per query.
> - **(b) unbounded rotation loops — done, then deleted outright.** The NEWNYM-and-verify loop
>   this bullet used to describe (`renew_ip_bazos_ok`, `MAX_RENEW_ATTEMPTS`) **no longer
>   exists**: rotation is now a fresh SOCKS credential (`rotate_circuit`), which has no loop to
>   bound. Do not go looking for those symbols — see CLAUDE.md's "IP rotation" note.
> - **(c) the guards raising and killing the whole pass — done.** This was "the whole of this
>   prompt" in the previous revision and it is now closed:
>   - `ip_changer/ip_changer.py:16-18` — `IP_LOOKUP_TIMEOUT = (20, 15)` and
>     `IP_LOOKUP_ATTEMPTS = 3`. The connect half is generous because it has to cover Tor
>     **circuit construction**; a flat 10 s timed out in production right after a rotation.
>   - `bazos/scraping/runner.py:42-49` — `check_ip_local()` is inside the pass-level `try`, so a
>     raise skips the pass instead of escaping `run()` and forcing a 60 s rebuild.
>   - `bazos/scraping/runner.py:160-166` — the `change_ip()` fall-through is wrapped, so one
>     query's failed rotation no longer costs the other queries their turn.

**What is actually left, verified 2026-08-30:**

1. **Step 5 — `check_ip_local` logs at WARNING, not ERROR** (`runner.py:46`), and there is **no
   consecutive-local-IP counter**. A guard that disables all work should reach the Discord log
   channels and Sentry (which auto-captures ERROR+), and a persistent `LOCAL_IP_SUBNET`
   misconfiguration should escalate rather than repeat quietly forever. ~15 minutes.
2. **Step 2's multi-host fallback was not built, and that is now a deliberate open question
   rather than a task.** `get_current_ip` retries **icanhazip three times** rather than falling
   through to `api.ipify.org`/`ifconfig.me`/`ident.me`. Whether the fallback list is still worth
   adding is genuinely unclear: the function's remaining caller is `check_ip_local`, which asks
   "is *any* traffic leaving unproxied" — a property of the transport, not of one destination —
   and it now fails fast and skips the pass rather than hanging. Decide before building.

```
Raise check_ip_local's log level to ERROR in bazos/scraping/runner.py so it reaches the
Discord log channels and Sentry, and count consecutive local-IP passes on ScrapeRunner so a
persistent misconfiguration escalates instead of repeating quietly forever. Mirror the
existing zero-results canary (`_check_zero_results_canary`) rather than inventing a second
escalation mechanism — it already owns the "N consecutive bad passes" shape and its Discord
routing.

Tests: the counter survives across passes; a normal pass resets it; the escalation fires at
the threshold and not before.
```

> **Note on the durable fix.** These were damage control for a transport failing on
> reputation, not on anything you are doing wrong — your volume is nowhere near a rate limit.
> **P21b** replaces Tor entirely and makes most of this moot. The original 2026-08-08 crash
> (`RemoteDisconnected` from icanhazip over a dead Tor circuit, twice in one log) is what
> justified the timeouts that are now in place.

---

## ⚡ Latency & data-quality prerequisites

> Added 2026-07-29. **P21 is the highest-value item in this file.** The rationale is commercial
> and lives in [`MONETIZATION.md`](../MONETIZATION.md) **§7.1**: the current 15–45 min interval
> gives a **~15 minute median detection latency** while competing services poll every 60 s and
> good listings are gone in minutes — so the deal-capture premise of the whole project fails on
> this one number. The technical groundwork is already done in
> [`PROXY_ROTATION.md`](../research/proxies/PROXY_ROTATION.md) §8 and
> [`HIDDEN_API.md`](../research/bazos-api/HIDDEN_API.md) §8;
> this prompt is the missing executable version. It also unblocks
> [`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) #6, which needs the API's second-resolution timestamps.

### P21 — Cut latency: API cutover + rotating proxy

> **⚠️ Split into P21a / P21b, 2026-08-08.** This was one 3–5 day unit, which hid the fact
> that it bundles **two very different risk profiles**:
>
> - **P21a (Parts 1, 2, 4a)** is pure code. No external dependency, no account, no monthly
>   cost, no unvalidated assumption.
> - **P21b (Part 3, 4b)** needs a paid proxy provider *and* rests on a measurement that has
>   **never been run** — `PROXY_ROTATION.md` §10 calls the sustained block-rate
>   probe *"the only missing data point."*
>
> **The reason the split is worth making is arithmetic, not tidiness.** Using
> `PROXY_ROTATION.md` §5's own model (`passes/day = 1200 / interval_minutes`):
>
> | | Bazos req/query/pass | Passes/day | **Bazos req/query/day** | Median latency |
> |---|---|---|---|---|
> | Original (HTML, 3 guards) | 3 | 40 (30 min avg) | **120** | ~15 min |
> | Today (HTML, **probes removed 2026-08-23**) | ~1 (+ detail per new ad) | 40 | **~40** | ~15 min |
> | **After P21a @ 10 min** | ~1 | 120 | **~120** | **~5 min** |
> | After P21a @ 5 min | ~1 | 240 | ~240 (2×) | ~2.5 min |
> | After P21a @ 2 min | ~1 | 600 | ~600 (5×) | ~1 min |
>
> **P21a buys a ~3× latency improvement at unchanged Bazos request volume** — the efficiency
> gains pay for the extra cadence exactly. Bandwidth *falls* at the same time (11.2 KB → 1.1
> KB per request, §4). So the free 3× is available with no ban-risk increase and no spend.
>
> Only the step from ~5 min to ~2 min actually needs a bigger IP pool. Doing P21a first makes
> P21b an **optional, measured** step justified by an observed block rate, instead of a
> prerequisite bought on faith. If P21b never happens, you still keep the 3×.
>
> **This does not change the total work or the conclusion** — P21 in full is still the
> highest-value item in this file. It changes *when you have to spend money and trust an
> unmeasured assumption*, which is the whole point.

---

#### P21a — The free 3×: API cutover + interval to ~10 min
> **📋 Specced in [`API_CUTOVER.md`](API_CUTOVER.md) (2026-09-07) — read that, not this, before
> starting.** The prompt below is still accurate about *what* to change; the spec is what is
> actually true when you start. Two things it establishes that this prompt gets wrong: the
> "~5 min median" target assumes pass duration is zero (measured cycle is 42 min against a
> ~30 min sleep, so a pass costs ~12 min and the realistic landing zone is ~7 min), and step 6's
> "confirm parity" hides **three fields the thin API payload does not carry** — each of which
> turns a filter rule permissive without erroring.
>
> ⚠️ Do P20 first — you want failure visibility *before* you increase cadence.
> No external dependency; nothing here costs money.
>
> **✅ Part 2 (guard collapse) landed 2026-08-23**, and more aggressively than this prompt
> asked: rather than collapsing the two blacklist probes into one per pass, **both were
> deleted** — the query attempt is now the probe (`ScrapeRunner._run_query_with_rotation`), and
> `check_ip_local()` moved to once per pass. That is the request-volume saving this part was
> written to buy, already banked. **Parts 1 and 4a are still open**, and they are what actually
> moves latency: the interval is unchanged.

```
Take detection latency from a ~15 min median to a ~5 min median at UNCHANGED Bazos request
volume. Read docs/research/proxies/PROXY_ROTATION.md §3 and §5 and
docs/research/bazos-api/HIDDEN_API.md §8 Stage C first — the design decisions are
already made there; this is execution.

Part 1 — tunable API page size (do this first, it's the prerequisite):
1. `BazosApiScraper` currently hardcodes `limit=API_PAGE_SIZE` (210) at
   `bazos/scraping/bazos/bazos_api_scraper.py`. A steady-state dedup probe only needs the
   newest handful. Add a `limit` parameter (default 210 for backfill/deep paging) and use a
   small value (~10) for the routine newest-first pass. Measured effect: the dominant
   request drops from ~15 KB to ~1.1 KB (research doc §4).
2. Keep 210 for `run_new_query` backfill and any bulk `ad_id[]=` path.

Part 2 — DONE, do not redo. Both blacklist probes were deleted and check_ip_local moved to
once per pass (2026-08-23). Do NOT reintroduce a pre-flight probe — see CLAUDE.md's
"Blacklist / IP guards" note for why the fixed-URL probe was actively misleading.

Part 4a — cut over and take the free cadence:
6. Switch ONE canary `Query` to `marketplace="bazos_api"`, run
   `python manage.py compare_bazos_scrapers`, confirm parity, then migrate the rest.
7. Only after parity: lower `INTERVAL_LOWER`/`INTERVAL_UPPER` (already env-driven, no code
   change) to ~10 min. STOP THERE in this prompt — per the table above, ~10 min is the point
   where request volume is still at today's level. Going below it is P21b's job and needs
   the bigger pool.
8. Watch the P19 zero-results canary and the blacklist-probe outcome for a few days at the
   new cadence before considering P21b. If block rate is unchanged, you have the 3× for free
   and P21b becomes optional rather than assumed.
9. Keep detail-endpoint calls event-driven, per docs/research/proxies/PROXY_ROTATION.md §5.1 — detail
   volume, not query count, is what re-creates the old single-IP ban. This matters at every
   cadence, including this one.
```

---

#### P21b — Below 5 minutes: rotating proxy transport
> ⚠️ Requires P21a. **Needs a paid provider account (~$3–6/mo) and a measurement that has
> not been taken.** Do not start this until P21a's cadence has run for a few days and you
> have an observed block rate to justify it against.

```
Go from a ~5 min median to a ~1–2 min median by replacing Tor with a rotating pool. This is
the only part of the old P21 that costs money or rests on an unvalidated assumption.

Note the independent motivation, beyond cadence: Tor is ALREADY failing in production. See
docs/research/proxies/PROXY_ROTATION.md §2 ("every anti-bot vendor ships the Tor exit list") and the
observed 2026-08-08 crash logged in P20 — Bazos 403'd the exit AND the same dead circuit
killed the icanhazip liveness check. So this prompt may be worth doing on reliability
grounds even if you never lower the interval further.

Part 3 — rotating proxy transport:
1. Implement `ip_changer/http_proxy.py::HttpProxyIPChanger` per the sketch in
   docs/research/proxies/PROXY_ROTATION.md §8 — `renew_session` points a fresh `requests.Session` at
   `settings.PROXY_URL`; `renew_ip` is a no-op (the provider rotates per request);
   `renew_ip_and_check_new` re-creates the session and returns the new IP.
2. Add `PROXY_URL` to settings/.env (empty default) and an `HTTP_PROXY` branch in
   `ScrapeRunner.__init__` alongside `DUMMY`/`TOR`, gated on `IP_CHANGER_TYPE`. Nothing
   changes until it's set — do not alter the default.
3. MEASURE BEFORE SWITCHING. Run
   `python experiments/bench_proxy.py --proxy <endpoint> --repeat 30 --query auto` against
   (a) current Tor, (b) a Webshare datacenter trial, (c) a residential-CZ trial, and compare
   success %. This is the one measurement docs/research/proxies/PROXY_ROTATION.md §10 flags as still
   missing — RECORD THE RESULT IN THAT DOC'S §10. Do not skip this; it is the entire
   evidential basis for spending money here, and §10's recommendation (datacenter first,
   residential only if bans reappear) is unresolved without it.

Part 4b — lower the interval the rest of the way:
4. Step down gradually — 10 min → 5 min → 2 min — watching the P19 canary and the
   blacklist-probe outcome at each step rather than jumping straight to 2 min.
5. Reconsider `NightMultiplier`: at a 2-minute cadence the night ×2 is much less meaningful,
   and BACKLOG_IDEAS.md #6 (now unblocked by the API's real timestamps) is the better
   long-term answer than a flat multiplier.
6. Re-check detail-endpoint volume at the new cadence (docs/research/proxies/PROXY_ROTATION.md §5.1) —
   the table there shows 300 tracked ads at 5 min is already 72,000 detail req/day, which is
   the documented ban vector. Pool size is what absorbs it.
```

---

### P23 — `PriceAnomalyRule` — the broad-coverage half of price scoring
> ⚠️ Requires P22 (needs a numeric price). Design rationale already written:
> [`DISCOVERY_PIPELINE.md`](../research/bazos-api/DISCOVERY_PIPELINE.md)
> §1 stage 2 ("Cheap filter pass — zero extra API calls"). This prompt is the promotion of
> that design, not a new idea. Distinct from BACKLOG_IDEAS.md #4, which compares against
> *external* retail prices; this one compares against *your own accumulated Bazos history*.

> **🟡 Partly overtaken by what shipped 2026-08-26 — read this before starting.** Price scoring
> exists (`bazos/pricing/`, [`ML_PRICE_SCORING.md`](../proposals/ML_PRICE_SCORING.md),
> `AdPriceScore`, the `price_model` rule, migration `0037`), and it already satisfies steps 1,
> 4 and 6 of the prompt below: registered in `RULE_REGISTRY`, deliberately **excluded** from
> `DEFAULT_RULE_NAMES`, storing the number rather than only branching on it, and shadow-mode by
> default pending calibration.
>
> **What it does not do is cover anything.** `MODEL_REGISTRY` holds exactly one entry —
> `macbook` — so `get_price_model` returns None for every other ad and the rule PASSes. The
> shipped design is *narrow and precise* (a trained linear model over a measured feature spec);
> this prompt is *broad and shallow* (a rolling median over your own history, any category).
> They are complements, not rivals, and `registry.py`'s own comment already names the slot:
> *"a narrower model must be registered before a broader one."*
>
> **So the work below is now re-scoped:** not a second rule competing with `price_model`, but a
> **catch-all `PriceModel` implementation registered last**, whose `applies_to` returns True
> whenever there is enough comparable history and which declines otherwise. Steps 2, 3, 5 and 7
> below are the substance and still apply verbatim; steps 1, 4 and 6 are done — reuse
> `AdPriceScore` and the existing shadow-mode plumbing rather than adding
> `Ad.price_percentile`.
>
> Note the calibration dependency is unchanged and now binding: step 6 wants real outcomes from
> BACKLOG_IDEAS.md **#9** (`AdOutcome`), and `bazos/const.py` says the same thing about **P24**.
> Neither exists, so anything built here stays in shadow mode too.

```
Every rule in `bazos/filters.py` today is a static per-query predicate (price range, keyword
blocklist/required, publisher blocklist, price drop). NONE of them answer "is this cheap
RELATIVE to comparable listings?" — which is the only question that finds a deal rather than
a keyword match. Add that rule.

Steps:
1. Add a `PriceAnomalyRule` to `bazos/filters.py` implementing the FilterRule protocol, and
   register it in `RULE_REGISTRY` (per-query opt-in already works via
   `Query.filter_rule_names`, see P17 — decide whether it belongs in DEFAULT_RULE_NAMES; it
   probably should NOT be on by default until calibrated).
2. Baseline: a rolling median (and a low percentile) of `Ad.price` over comparable ads —
   scoped by category where known, plus a recency window (e.g. trailing 90 days) and a
   minimum sample size below which the rule PASSes rather than guessing. Start with a plain
   ORM aggregate over the existing `Ad` table, NOT a separate ML service — the discovery doc
   §4 explicitly recommends the simple baseline first.
3. Handle the scoping problem honestly: category is only reliably known for category-scoped
   queries (the discovery doc §1 notes section is derivable from the listing URL subdomain
   but category needs a detail call). For text queries, fall back to comparing against ads
   from the same `Query` — narrower, but honest. Do not silently compare across unrelated
   categories; PASS instead.
4. Store the computed signal, don't just branch on it: add `Ad.price_percentile` (or a
   residual-vs-median float) so it's visible in admin, usable in the notification (see
   BACKLOG_IDEAS.md #3a/#10), and analysable later. A rule that only returns
   APPROVE/REJECT/PASS throws away the interesting number.
5. Guard against the obvious failure modes: exclude the ad being scored from its own
   baseline; exclude `price_type != EXACT` from the baseline (a "Dohodou" listing at 1 Kč
   would wreck a median); consider excluding known-dealer publishers once
   `user_ads_count` lands (research doc §5.2).
6. Do NOT wire this to auto-reject initially. Run it in shadow mode — compute and store the
   percentile, notify as usual — and calibrate the threshold against real outcomes from
   BACKLOG_IDEAS.md #9 (`AdOutcome`) before letting it gate anything.
7. Tests: baseline computation with/without enough samples; self-exclusion; non-EXACT price
   exclusion; PASS when category is unknown; the stored percentile value.
```

---

### P24 — Delisting / sold detection (time-to-disappear)
> Design rationale already written:
> [`HIDDEN_API.md`](../research/bazos-api/HIDDEN_API.md)
> §6.4a and §8 Stage D. This prompt is the promotion of that design.

```
You currently record ASKING prices only, never realised ones. The closest available proxy is
time-to-disappear plus last-seen price — and it's cheap, because `ads.php` accepts up to 210
`ad_id[]=` values in ONE request and silently omits ids that no longer exist, while
`ad-detail-2.php` returns HTTP 410 {"status":"deleted"} for a removed ad.

This is the single most valuable field the DB doesn't have: it's the feedback signal for
P23's anomaly model (a genuinely underpriced item should disappear fast — see
docs/research/bazos-api/DISCOVERY_PIPELINE.md §3.4 "deal-velocity"), and it's the prerequisite
for any price-index or valuation work (docs/MONETIZATION.md §4.1b, §7.2c).

Steps:
1. Add `AdStatus.REMOVED` plus `Ad.last_seen_at` and `Ad.removed_at` (nullable). Note the
   status-machine implication: REMOVED is orthogonal to the delivery states
   (PENDING/APPROVED/SENT) — an ad can be SENT and later removed. Decide deliberately whether
   REMOVED is a status value or a separate nullable timestamp field; the timestamp is
   probably cleaner precisely because it doesn't collide with delivery state.
2. Add a management command `check_delisted` that batches known non-removed ads by
   `(marketplace, external_id)` into `ads.php?ad_id[]=...` calls of up to 210 ids, marks
   returned ids with a fresh `last_seen_at`, and marks absent ids as removed. Follow the
   existing `run_filter`/`run_sender` polling pattern (`select_for_update(skip_locked=True)`)
   so it's safe to run alongside everything else.
3. Also refresh `price` from the same response — the bulk form returns `price_formatted` and
   `views` for free, so this doubles as comprehensive price-change detection and largely
   subsumes BACKLOG_IDEAS.md #8's expensive full-listing rescan. Note that explicitly in #8
   if this lands.
4. Cadence: this is bounded by tracked-ad count, not query count. Read
   docs/research/proxies/PROXY_ROTATION.md §5.1 before choosing an interval — detail-endpoint
   volume is the documented ban vector. Once per hour or few hours is plenty for a
   time-to-sell signal; do not run it every pass.
5. Do NOT create a `Job` model for this yet — one recurring job doesn't justify
   docs/proposals/JOB_QUEUE.md's generic machinery. A management command plus a docker-compose
   service matches the existing pattern. Revisit if a third such job appears.
6. Tests: batching at the 210 boundary; absent ids marked removed; present ids refreshed;
   410 handling on the detail path; idempotency when run twice.
```

---

## 🟡 Improvements (not pipeline-blocking, but useful)

### P7 — `price_lower == 0` as "no price" → nullable
```
The `price_lower = 0` and `price_upper = 0` convention for "no price filter set" is implicit and fragile.
Make both fields nullable.

Steps:
1. Change `price_lower` and `price_upper` on `Query` to `IntegerField(null=True, blank=True, default=None)`.
2. Update the `CheckConstraint` (currently `price_lower__lte=price_upper`) to handle nulls.
3. Update `Query.url` property (if it uses these fields for URL generation).
4. Update any place that checks `price_lower == 0` as a sentinel.
5. Generate migration.
6. Update `PriceRangeRule` in Stage 9 accordingly.
```

---

### P8 — `Query.generate_random_queries` cleanup
```
`Query.generate_random_queries` and the `randomly_generated` flag are experimental/dead code.
Confirm whether they are used anywhere in production, then either:
  (a) Delete `generate_random_queries`, `randomly_generated`, and the `update(enabled=False)` at loop start in `ScrapeRunner.run`, or
  (b) Document what they are for with a proper comment.

Also check: the `location_center = randint(10000, 99999)` line generates a random postcode — is this intentional?
```

---

### 🔶 P9 — Admin UX improvements — partially done

> **Status checked against code 2026-08-10.** Three of the seven sub-items have landed,
> across several sessions. What remains is listed in the prompt below — the ticked lines are
> kept for context rather than deleted.
>
> - ✅ `AdAdmin` price-history inline — `PriceChangeInline` is registered on `AdAdmin`.
> - ✅ `QueryAdmin.last_run` — annotated via `Coalesce(Max(run_end), Max(run_start))`.
> - ✅ `QueryRunAdmin` registered — plus `success`/`error` columns and filters from P18.
>
> **Separately, and not part of P9:** `QueryAdmin` gained an **`ad_count`** column
> (2026-08-10) — total `Ad` rows pointing at that query. Note this is *not* item 2's
> "`new_ads_count` sum from recent runs": `ad_count` counts ads that currently exist,
> the sum counts what runs *reported finding*, and the two diverge as ads are deleted or
> re-discovered. Both are worth having; item 2 is still open.

```
Polish the Django admin for the current pipeline state.

1. `AdAdmin`:
   - Add `filter_reason` to the list display (short, truncated).
     STILL OPEN — filter_reason is on the change form (readonly_fields), not in list_display.
   - Add a custom action `mark_as_pending` that resets status to PENDING (useful for re-running the filter on an ad).
     STILL OPEN.
   - ✅ DONE — Add `price_history` inline (PriceChange, once Stage 4 is done).

2. `QueryAdmin`:
   - ✅ DONE — Add `last_run` display (latest `QueryRun.run_start` for this query).
   - Show `new_ads_count` sum from recent runs.
     STILL OPEN — see the note above on why the new `ad_count` column is not this.

3. `QueryRunAdmin`:
   - ✅ DONE — Register it if not already registered.
   - ✅ DONE — Show duration (run_end - run_start). Annotated `run_end - run_start` in
     `get_queryset`; null (crashed / in-flight run) renders blank rather than 0.0 s, and
     `admin_order_field` is an `OrderBy` so the descending click keeps those rows last.

Note when picking this up: `QueryAdmin.get_queryset` already combines aggregates over two
different multi-valued relations (`runs` for last_run, `ads` for ad_count). Any further
aggregate there needs `distinct=True` or it will be inflated by the join multiplication.
```

---

### P10 — Test coverage audit
```
Run the test suite with coverage and identify gaps.

Steps:
1. Install `pytest-cov` if not already present.
2. Run: `pytest --cov=bazos --cov=senders --cov=ip_changer --cov-report=term-missing`
3. Identify any file or branch below 70% coverage.
4. Write targeted tests for the gaps (focus on `run_filter.py`, `run_sender.py`, `runner.py`, `filters.py`).
```

---

### P11 — `Ad.message` property multi-marketplace
```
`Ad.message` was written for Bazos only. With Vinted ads now possible, review and update it.

1. Check what `Ad.message` returns for a Vinted ad (price_raw is a float string, not "1 000 Kč").
2. Normalise price display in `message` — format Vinted prices as "1 000 Kč" or "€12.50" depending on marketplace.
3. Consider whether `link` property needs updating (Vinted URLs are already full URLs, Bazos URLs are too — should be fine).
4. Write a test for the Vinted `message` format.
```

---

### P12 — Docker Compose healthchecks
```
Add healthchecks to the Docker Compose services so that `run_filter` and `run_sender`
restart properly if the DB becomes temporarily unavailable.

1. Add a `healthcheck` to the `postgres` service (if not already present).
2. Add `depends_on: postgres: condition: service_healthy` to `marketplace_filter` and `marketplace_sender` services.
3. Consider adding a simple liveness mechanism to the management commands themselves
   (e.g. write a timestamp to a file every N iterations; a Docker HEALTHCHECK reads it).
```

---

### P13 — Filter-before-detail-fetch ordering
> ✅ P5 (real filter rules) is done — unblocked.

```
Avoid paying for load_full_description() on ads that P5's rules would reject anyway.

Context: none of P5's rules (PriceRangeRule, BlocklistKeywordRule, RequiredKeywordRule,
PublisherBlocklistRule, PriceDropRule) read `full_description` — they only need fields
already present on the Ad before load_full_description() is called (name, short_description,
price_raw, publisher FKs). run_filter is deliberately decoupled from the scraper (no network/
scraper access) — so the fix is a local heuristic pre-check in the scraper stage, NOT moving
detail-fetching into run_filter. run_filter remains the sole authoritative owner of
Ad.status transitions; this only skips a wasted HTTP request.

Steps:
1. In `bazos/scraping/query_runner.py::_handle_new_product`, before calling
   `self.scraper.load_full_description(product)`, run the same `rule_engine` instance from
   `bazos/filters.py` against `product` as a heuristic pre-check.
2. If the pre-check result is REJECT, skip the `load_full_description` call (still save the
   Ad as PENDING — run_filter still runs its own independent, authoritative check).
3. Import/reuse the existing `rule_engine` instance rather than duplicating rule logic.
4. Log when the pre-check's verdict would differ from run_filter's later verdict (should
   never happen today since no rule reads full_description — this is a drift detector for
   if that assumption changes later, e.g. a future rule that does inspect full_description).
5. Write tests: rejected-by-cheap-rules ads don't trigger load_full_description; approved
   ads still do; run_filter's final status is unaffected either way.
```

---

### P14 — Posting-time-of-day → interval tuning
> Promoted from `BACKLOG_IDEAS.md` #6 — see there for full rationale.
>
> ⚠️ **BLOCKED — correction 2026-07-29.** The line below ("no dependencies, ready to run today")
> is **wrong**. `BazosScraper.extract_date` parses only the `[d.m.yyyy]` substring and **discards
> the time**, so every `publish_date` is at midnight and step 1's `ExtractHour("publish_date")`
> returns **0 for every row** — it will appear to work and produce a meaningless flat curve.
> Unblocked by **P21** (the API listing carries `"from": "2026-07-19 09:45:51"`, second
> resolution). When it lands, filter `topped=False` first — topped ads' `from` value is not the
> real posting time (`HIDDEN_API.md` §4.3). Also note P21 reduces the
> value of this work: it tunes *when* a 15–45 min interval fires, where P21 makes it ~2 minutes.
>
> ~~No dependencies, no new data collection; ready to run today.~~

```
Replace NightMultiplier's flat day/night 2x split with a real hourly posting-density curve.

Steps:
1. Query `Ad.objects.annotate(hour=ExtractHour("publish_date"), dow=ExtractWeekDay("publish_date"))`
   (or similar) to bucket ad-discovery volume by hour and weekday from data already collected.
2. Turn that into a lookup (hour/weekday -> relative posting density) that
   `bazos/scraping/interval_multiplier.py`'s `NightMultiplier` can use internally, keeping
   the same interface `ScrapeRunner.get_next_interval` already calls.
3. Decide a reasonable minimum/maximum multiplier bound so a genuinely dead hour doesn't
   produce an absurdly long sleep.
4. Write tests for the new density-based multiplier logic (mock/fixture `Ad` timestamps).
5. Consider logging the computed multiplier per pass for visibility during rollout.
```

---

### P16 — Discord thumbnail embed
> Promoted from `BACKLOG_IDEAS.md` #3a — see there for full rationale (including why this is
> low-risk unlike #3b's image mirroring). One open sub-question below before starting.

```
Attach a thumbnail image to the Discord notification instead of plain text.

Open question to resolve first: get the thumbnail URL from BazosApiScraper's listing
payload (`image_thumbnail`, already parsed at zero extra request cost per
docs/research/bazos-api/HIDDEN_API.md §5.1) — but that scraper isn't wired into production yet
(marketplace="bazos_api" is validation-only, see docs/research/bazos-api/HIDDEN_API.md §8 Stage B) —
or add thumbnail-URL parsing to the production HTML scraper now, independent of the API
migration. Pick one before writing code; don't block this on the API scraper's rollout
unless you're comfortable waiting for it.

Steps:
1. If going the HTML route: add a BeautifulSoup selector for the listing thumbnail `<img>`
   to `bazos_scraper.py::_parse_product`, and an `Ad.thumbnail_url` field (migration).
   If going the API route: read `image_thumbnail` in `bazos_api_scraper.py::extract_product`
   (already parsing the same payload) into the same new field.
2. Check whether `discord_notify` (current dependency) supports embeds; if not, evaluate
   swapping to `discord-webhook` (the package the original issue linked) for `DiscordSender`.
3. Update `DiscordSender._format_product_message` (or add a sibling method) to build an
   embed with the thumbnail instead of a plain-text webhook post.
4. Confirm Discord's own servers fetch the embed image server-side (not the scraper's IP) —
   this is what makes it safe versus #3b's mirroring concern; no code needed, just a sanity
   check against a live test webhook.
5. Write tests for the new message-building path (mock the Discord client, assert the embed
   payload shape).
```

---

### P25 — `load_full_description` drops fields the API already returned

> **Observed in production 2026-08-10.** Every `bazos_api` ad in the DB — **56 of 56** — has
> `publisher_name = ''`, `short_description = ''`, `full_description IS NULL` and no
> email/phone publisher. The detail response for one of them (`222351346`) carries
> `name: 'Aneta'`: a field the code fetches, parses, and throws away.

```
BazosApiScraper.load_full_description reads 3 of ~30 fields from the detail response and
discards one the Ad model has a column for.

Context:
- `bazos_api_scraper.py:166-172` reads only `description`, `email_id`, `phone_id`. The same
  response carries `name` (the publisher name), plus `user_ads_count`, `user_reviews_count`,
  `price`/`price_type`, `zip_code`, `latitude`/`longitude`, `category`/`section` objects and
  `images[]` — see docs/research/bazos-api/HIDDEN_API.md §5.2, verified live.
- `BazosScraper` gets `publisher_name` from the LISTING for free (`bazos_scraper.py:117`). The
  API listing payload has no equivalent field (§5.1), which is why this only shows up on the
  API path.

⚠️ Scope reality check before starting: this method only runs when
`Query.load_full_description=True`. The one production `bazos_api` query has it OFF, so landing
this prompt changes nothing there until the flag is flipped. With the flag off, those ads also
have NULL email/phone publishers — which is why `PublisherBlocklistRule` cannot fire and
`Ad.message` renders "Seller: unknown" for every one of them. This prompt does NOT fix that;
only enabling the flag does, at one extra request per ad. Decide that separately, and note P13
(filter-before-detail-fetch) is the prompt that makes that extra request affordable.

Steps:
1. After the `full_description` assignment, set
   `product.publisher_name = (data.get("name") or "")[:100]`.
   Both guards are load-bearing: `Ad.publisher_name` is a non-null `CharField(max_length=100)`
   (`models.py:271`), so None fails on Postgres and an over-long value raises DataError.
2. Apply the same None-guard reasoning to `full_description` (`data.get("description")` can be
   None; that column is nullable so it's legal, but every consumer concatenates it).
3. Leave the 410 early-return (`bazos_api_scraper.py:159-161`) untouched — a removed ad has
   nothing to read. Delisting handling is P24; do not scope-creep into it here.
4. Add a short comment recording the listing-vs-detail asymmetry from Context above, so the
   next reader doesn't go hunting for an API listing field that doesn't exist.
5. Explicitly OUT of scope, each worth its own task: `user_ads_count`/`user_reviews_count` are
   the true seller volume that `SellerAdCounts`'s own docstring (`models.py:166-171`) says it
   cannot compute — needs new model fields. `price`/`price_type` belong to P22. `images[]`
   belongs to P16 / BACKLOG_IDEAS.md #3a. GPS and category/section objects have no consumer yet.
6. Do NOT try to fill `short_description` from the detail payload. `ads.php` has no description
   text at all (§5.1), so the only source is a per-ad detail call — and when that call happens,
   the text is already in `full_description`. A truncated duplicate in a second column buys
   nothing. If the goal is making keyword filters work on the API path, the fix belongs in
   `filters.py:85,102`, whose haystack is `f"{ad.name} {ad.short_description}"` and should also
   consider `full_description` — that is a separate change with its own tests.
7. Tests: extend the `load_full_description` group in `test_bazos_api_scraper.py` (around :232)
   with — `publisher_name` populated from `name`; `name` absent or None → `""`; a >100-char
   `name` → truncated, not raising. `test_publishers_unset_until_detail_fetch` (:133) pins the
   listing-side emptiness and stays valid as-is.
```

---

### P27 — Desktop PC price model: the two experiments that would unblock it

> **Source**: [`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md), a feasibility study on
> query 9 (`PC, Počítače`, 1 668 ads over 259 days). The conclusion was **not yet** — the model
> reaches R² 0.853 / MedAPE 13.4% where the specs parse, but only 52% of desktops parse that
> far, and storage lands at 39%. This prompt is the two things that would change that answer.
> Neither is a modelling change; both are about seeing the machine.

> ✅ **Item 1 is DONE, early — see [`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md), re-measured
> 2026-09-12 at 2 856 ads.** The corpus arrived ahead of the estimate (1 368 rows now carry a full
> description, against 166 when the study was written), so the wait below no longer applies.
> **The decision rule below is answered: storage PASSES on block B (66.1% ≥ 60%), GPU+CPU+RAM
> still FAILS (58.4% vs ~70%).** Read three things before acting on the rest of this prompt:
>
> - **§5.2 is retracted.** The linear-vs-tree gap this prompt's closing note calls a serving
>   blocker was an *encoding* artifact — `pcmodel.py` imports `Ridge` and never calls it, and its
>   `make_X` hands categoricals to a linear model as ordinal integers. A correctly encoded ridge
>   closes the gap. **So do not treat the JSON manifest path as the obstacle**; the obstacle is
>   the completeness gate and a −25% threshold that is 0.97σ on this corpus against 2.92σ for a
>   MacBook dealer.
> - **`pcmodel.py` no longer runs as step 1 instructs.** `make_X` passes `cpu_model` at
>   cardinality 275 to HistGradientBoosting and sklearn refuses a categorical above 255. Pool rare
>   levels first, or use the shared harness at `experiments/price_model/common/ph.py`.
> - **The corpus is not 273 days.** It is 46 collection days in two blocks with a 214-day gap, and
>   the query's own price floor moved inside them. Decide on block B only.
>
> Item 2 (the external GPU performance scale) is untouched and still worth doing.

```
Two independent experiments. Item 1 is nearly free and waits on data; item 2 is real work.

### 1. Re-measure extraction once full descriptions have accumulated

`load_full_description` is already TRUE on query 9, but it was enabled partway through, so at
the time of the study only 166 of 1 411 desktops had one. On exactly those rows the gain was
large and landed on the weakest fields: storage +18.7pp, DDR +22.3pp, GPU model +12.7pp,
RAM +11.4pp. That is a much bigger effect than the same flag had on MacBooks, because desktop
titles run out of room before they run out of components.

Steps:
- Wait until a clear majority of query-9 desktops carry a `full_description` (check with
  `count(full_description) / count(*)` on the query-9 join; ~2 months from 2026-08-29).
- Re-run `experiments/price_model/pc/pcfeat.py` coverage and `pcmodel.py` and update
  PC_PRICE_MODEL.md §4.1, §4.2 and §5 in place with the new numbers.
- The decision this informs: if GPU+CPU+RAM coverage clears ~70% (from 51.9%) and storage
  clears ~60% (from 39.0%), the completeness gate stops throwing away most of the corpus and
  a shadow-mode deployment becomes arguable. If it does not move, the honest answer is that
  desktop listings simply do not state enough, and this line of work should stop.

### 2. An external GPU performance scale

PC_PRICE_MODEL.md §6 tested the obvious "map component names to their specs" idea and found it
REDUNDANT: a lookup keyed on the GPU model adds nothing when the model name is already a
feature, and filling VRAM from a median made MedAPE slightly WORSE (17.8% -> 18.4%) because it
erased the real 8GB/16GB distinction on the 12 cards that ship both. Do not rebuild that.

What was NOT tested, and is the only version of the idea that can work: a single ordinal
performance score per GPU from an external benchmark (3DMark Time Spy, PassMark G3D). That is
genuinely not derivable from the name -- it is what places `rx 6700 xt` and `rtx 3060 ti` on
one scale, across vendors and generations, which the name-parsed tier/generation ordinal
cannot do.

Steps:
- Build a static `gpu_model -> benchmark_score` table covering the ~40 models that account for
  most of the corpus (140 distinct tokens exist, but the tail is thin). Check the licensing on
  whichever benchmark source you use before committing the table.
- Add it as one numeric feature and re-run the §5 decomposition. The specific thing to compare
  is "GPU tier+gen ordinal" (R² 0.515 on complete-spec rows) against the same with the
  benchmark score added.
- Treat it as a null result worth writing down if it does not beat the ordinal -- that would
  say the naming scheme already encodes performance well enough, which is a useful fact.

Note on model class: unlike the MacBook case, gradient boosting clearly beats ridge here
(0.853/13.4% vs 0.769/17.1% on complete rows). That conflicts with the pure-Python JSON
serving path in `docs/proposals/ML_PRICE_SCORING.md` §4.1, so if this ever ships, either
pre-expand the interactions into explicit features or accept a different serving story.
DO NOT resolve that by adding numpy/sklearn to the runtime image without reading §4.1 first.
```

---

### P26 — `Ad`/`AdDelivery` split: deferred review findings

> **Source**: an independent code review of commit `9d20b91` ("wip AdDelivery"), reproduced
> rather than inferred (scratch-tree checkout, `pytest`/`ruff`/`mypy`/fresh-`migrate` all run
> for real). Its BLOCKER and HIGH findings, plus three MEDIUM ones, were fixed the same day —
> see [`AD_DELIVERY_SPLIT.md`](../archive/shipped/AD_DELIVERY_SPLIT.md)'s status banner and §7 for what
> landed (idempotent `run_new_query`, the `load_full_description` gate, `0028`'s irreversibility
> now documented instead of silently discoverable only by trying it, `show_full_result_count`,
> and the status-precedence collision tie-break in `0027`). What's below is what was
> **deliberately left open**, each with a reason, not an oversight.

> **⚠️ One of these (price-change fan-out) is explicitly NOT a bug to silently patch** — see
> its own note below. Don't fix it as a drive-by while picking up the others.

```
Four independent follow-ups from the AdDelivery-split review. Pick up any subset; none blocks
another.

### 1. Price-change fan-out can overwrite another query's in-flight delivery state

Context: `query_runner.py::run_existing_query` does
`AdDelivery.objects.filter(ad=known_ad).update(status=AdStatus.PRICE_CHANGED)` — unconditional,
unlocked, across EVERY delivery of that ad. If query A's delivery is APPROVED (decided, awaiting
`run_sender`) and query B sees a price bump on the same listing, this flips A to PRICE_CHANGED
too. A then re-enters `run_filter`; if `PriceDropRule` doesn't recognise the change as a genuine
drop (e.g. it went up, not down), A gets REJECTED with "price did not drop" — and A's original
new-ad notification is silently lost. Window is small (filter polls every 30s, sender every 10s)
but real.

⚠️ **Do NOT fix this as a side effect of anything else.** This is not a new bug from the split —
the pre-split code did the identical unconditional flip on a single `Ad.status`; the split's
only change is FAN-OUT (one price change can now perturb multiple queries' deliveries instead of
one). `docs/archive/shipped/AD_DELIVERY_SPLIT.md` §3.2 explicitly decided to preserve this exact "looks wrong"
behaviour for the closely-related SUPPRESSED→PRICE_CHANGED case and recorded fixing it as a
follow-up rather than folding it into the structural refactor. Apply the same discipline here:
this prompt IS that follow-up, a fix here is in scope, but decide the fix deliberately (see
below), don't sneak a narrower change in under a different task.

Steps:
1. Decide the actual fix before writing code — options include: exclude currently-APPROVED
   deliveries from the blind flip (`.exclude(status=AdStatus.APPROVED)` — narrowest, but an
   APPROVED delivery for an ad whose price then drops further never gets the drop
   re-evaluated); or `select_for_update()` the deliveries before flipping, inside a
   transaction, so a concurrent `run_sender` batch is serialized rather than raced (closer to
   correct, more invasive — the query runner has no explicit transaction today). Write down
   the tradeoff you picked and why.
2. Write the regression test first: query A's delivery is APPROVED; a price change arrives via
   query B watching the same ad; assert whatever the chosen fix guarantees (either A stays
   APPROVED, or A correctly re-enters PRICE_CHANGED and is re-evaluated without being lost).
3. Also decide, explicitly, whether the SUPPRESSED→PRICE_CHANGED un-suppression (§3.2's
   original deferred item) should be fixed in the same pass — same root cause, same
   discipline question.

### 2. `_resolve_ad` never refreshes an existing ad's scraped facts

Context: `query_runner.py::run_existing_query`'s known-ad branch only ever writes
`price_raw` back to the `Ad` row:
```python
known_ad.price_raw = product.price_raw
known_ad.save(update_fields=["price_raw"])
```
Every other freshly-scraped field on `product` — `view_count`, `topped`, `url`,
`publisher_name`, `email_publisher`/`phone_publisher` — is silently discarded once an `Ad` is
first discovered. `topped` and `view_count` go stale from the first rediscovery onward. This
predates the split (the old single-`Ad`-row code had the same gap) but compounds it: migration
`0027`'s merge explicitly declined to reconcile these fields across duplicate rows on the
premise that "the ads all get re-scraped on the next pass anyway" — which is only true for
fields this loop actually refreshes. `full_description` already got its own fix (P26's gate
change, see docs/archive/shipped/AD_DELIVERY_SPLIT.md §7) so it's no longer permanently stuck; the rest are
still stuck.

Steps:
1. Decide, per field, whether it should refresh on every rediscovery (`view_count`, `topped`,
   `url` — cheap, no downside) versus only when currently null (`publisher_name`,
   `email_publisher`, `phone_publisher` — a later scrape finding a publisher a former one
   missed is a strict improvement; overwriting a known publisher with a differently-parsed one
   needs more thought, since publisher identity feeds `SellerAdCounts`).
2. Extend the known-ad branch's `update_fields` list and the fields actually copied from
   `product` accordingly.
3. Tests: each refreshed field changes on rediscovery; fields intentionally NOT refreshed
   (decide if any) stay put; a rediscovery that changes nothing doesn't fire a spurious save.

### 3. Test coverage gaps identified by the review, not yet closed

- `bazos/tests/test_run_filter.py` / `test_run_sender.py` reimplement the poll loop by hand
  (`_run_filter_once`/`_run_sender_once`) and never invoke the real management commands. Add at
  least one test per command that calls `Command().handle()` (or extracts the loop body into a
  testable function both the command and the test call) — even on SQLite, where
  `select_for_update(skip_locked=...)` is silently dropped from the SQL, this would still catch
  a bad `select_related`/`filter` construction against `AdDelivery`'s actual shape, which the
  hand-rolled simulations can't.
- No end-to-end test proves the split's headline claim: one `Ad` matching two `Query` rows
  produces two `AdDelivery` rows that BOTH actually get sent (to potentially two different
  `Discord` channels). Today it's tested at the scraper (`test_two_queries_matching_one_listing_
  create_one_ad_and_two_deliveries`) but never carried through `run_filter` + `run_sender`.
  Write that test.
- Migration tests never touch Postgres (root `conftest.py` forces SQLite for the whole suite —
  see CLAUDE.md's Testing section). This is a known, accepted project-wide limitation, not
  specific to this split, but worth naming here since it's exactly what hid `0028`'s
  irreversibility (the test `Ad` table is empty at rollback time) until someone ran it by hand.

### 4. Before actually deploying this split: run the Stage C dry run

Not a code change — a reminder that `docs/archive/shipped/AD_DELIVERY_SPLIT.md` §6 already mandates this and it
has not been done: run the `0027` merge read-only against a restored copy of the production dump
and report the counts (groups merged, delivery collisions resolved, groups with differing
`price_raw`). If the merged-group count is surprisingly large, stop and investigate before
running it for real — `0027` is the migration in this split that is genuinely irreversible in
substance (see `docs/archive/shipped/AD_DELIVERY_SPLIT.md` §7's note on why `0028` inherits that).
```

---

## Order recommendation

> **Revised 2026-08-30.** Earlier revisions optimised for "cheapest independent win"; that
> doesn't survive contact with what the project is *for* (see
> [`MONETIZATION.md`](../MONETIZATION.md) §7.1). The priority is **latency, then failure
> visibility, then data usability** — features after that.
>
> **What changed in this revision, all verified against the tree rather than against the
> previous revision:** P20 dropped from item 1 to item 5 (its remaining case closed
> 2026-08-29 — timeouts, and both unguarded call sites); P23 was rewritten, because price
> scoring shipped 2026-08-26 in a narrower and deeper form than that prompt describes; P24
> was promoted above P21b, since it is what gates using what shipped; and BACKLOG_IDEAS #10's
> radius half shipped 2026-08-30. Everything already done lives in
> [`SHIPPED.md`](../SHIPPED.md), not here.

**Do these first, in this order:**

1. **P21a Parts 1 + 4a** (tunable API page size, then the production cutover and ~10 min
   interval) — ~1–2 days, **no cost, no external dependency.** Part 2 already landed, so this
   is now a smaller prompt than it was: ~15 min → ~5 min median latency. Best value-per-day
   in this file, and it is now the top item because P20 closed.
   ⚠️ **Part 1 has acquired a prerequisite nobody wrote down.** `BazosApiScraper` sets
   `location = item["locality"]`, and the API's *thin* listing payload is `"Praha 10"` with
   **no postal code** — the code is detail-only (`HIDDEN_API.md` §5.1 vs §5.2,
   `DISCOVERY_PIPELINE.md` §1 stage 2 says so outright). The `location_distance` filter parses
   its code out of `Ad.location`, so **cutting over as-is silently disables the distance filter
   on every migrated query** — it degrades to PASS, which is indistinguishable from "no filter
   configured". Fix that in Part 1, before the cutover, not after.
2. **P24** (delisting / time-to-disappear) — ~1–2 days. **Promoted above P21b.** It is the only
   outcome data the system would have, and `bazos/const.py` names it as the specific gate on
   taking price scoring out of shadow mode: `Ad.modified` never advances past `created`, so
   nothing in the DB records whether an ad ever sold. Genuinely unblocked — `Ad.price` exists.
3. **P21b** (rotating proxy → ~1–2 min) — ~1–2 days + ~$3–6/mo. Deliberately last of the
   latency chain: the only item requiring a paid account and an unrun benchmark. **Note the
   independent reliability argument** — Tor is still the transport and still failing (~48% of
   exits 403'd, measured 2026-08-29), so this may be worth doing on those grounds alone.
4. **P23** (broad-coverage price scoring) — ~1–2 days, shadow mode regardless. Re-scoped: the
   registry and the rule shipped 2026-08-26, but `MODEL_REGISTRY` holds one model (`macbook`),
   so every other ad gets no opinion. This is the catch-all model that fills the gap. Read its
   revised header first — half the original steps are already done.
5. **P20's leftover** — ~15 min. `check_ip_local` at WARNING with no consecutive-pass counter.
   Was item 1 in the previous revision; cases (a), (b) and (c) all closed 2026-08-29, and what
   remains cannot cost a pass.

**Then, if flipping is the actual goal**, the cheap item from
[`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) that isn't a prompt yet: **#9** (`AdOutcome`, ~half a
day) — the manual counterpart to P24 and, with it, the only ground truth for calibrating
anything. **#10's radius half shipped 2026-08-30** (see [`SHIPPED.md`](../SHIPPED.md)); its
travel-cost half needs a margin estimate and therefore waits on P23 and P24. **P16** is still
worth building alongside whichever of these touches the notification path.

**Still worthwhile, lower priority:**

- **P26** (`Ad`/`AdDelivery` split — deferred review findings) — four independent follow-ups,
  none blocking another: price-change fan-out overwriting another query's in-flight delivery
  (explicitly NOT a drive-by fix, read its own note first), `_resolve_ad` never refreshing
  `view_count`/`topped`/`url`/publisher facts on rediscovery, two test-coverage gaps, and the
  still-outstanding Stage C dry run. **The dry run is the one with a deadline attached** — it was
  meant to happen *before* deploying the split, and the split is deployed.
- **P25** (`load_full_description` drops the publisher name) — ~15 min, no dependencies, but it
  only takes effect on queries with `load_full_description=True`; read its scope note first.
- **P27** (desktop PC price model) — **item 1 is a re-measurement, not work, and is gated on
  waiting until ~2026-11-01** for full descriptions to accumulate; item 2 (an external GPU
  benchmark scale) is the only untested version of the component-lookup idea. Read
  [`PC_PRICE_MODEL.md`](../research/PC_PRICE_MODEL.md) §6 first — the obvious version of that
  idea was measured and is redundant.
- **P10** (coverage audit) — quick wins on confidence. Cheaper now that the E2E replay harness
  and its cassettes exist.
- **P13** (filter-before-detail-fetch) — matters more once cadence rises, i.e. right after P21a.
- **P16** (Discord thumbnail) — best visible payoff; P21a makes it nearly free by putting
  `image_thumbnail` in the production payload, so it's worth doing *after* the cutover rather than
  adding HTML-scraper parsing that the cutover obsoletes.
- **P7** / **P8** / **P9** / **P12** — housekeeping, no dependencies.
- **P14** (interval tuning) — ⚠️ **blocked**: `extract_date` discards the time component, so
  `ExtractHour("publish_date")` returns 0 for every row. P21a unblocks it by supplying the API's
  second-resolution `from` field. See [`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) #6.
- **P2** (Stage 5 query priority) and **P11** (multi-marketplace `Ad.message`) — feature work.
  **P11 is no longer cosmetic**: Vinted and Sbazar are both live, and every one of their ads
  renders a "0 ads seen" seller summary because both publisher FKs are null.
