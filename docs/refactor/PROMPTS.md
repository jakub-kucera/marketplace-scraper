# Ready-to-Run Prompts

Copy-paste any of these when you have tokens to burn.

**Sections are ordered by priority, not by prompt number** — P18–P24 (added 2026-07-29) sit above
the older P6–P17 improvements because they're defects and prerequisites rather than enhancements.
See [Order recommendation](#order-recommendation) at the bottom for the actual sequence to work in.

---

## 🔴 Blocked / Missing (pipeline stages not yet implemented)

### ✅ P1 — Stage 4: Price History — done
`PriceChange` model, `_get_known` (renamed from `_is_known`, returns `Ad | None`), price-change
detection in `run_existing_query`, migration `0020_price_change.py`, `PriceChangeInline` on
`AdAdmin`, and tests are all in place. Nothing left to do here.

---

### P2 — Stage 5: Query Priority
```
Implement Stage 5 from PIPELINE_REFACTOR.md (Query Priority).

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

### P3 — Stage 8: VintedScraper (Query model prep)
```
Implement the Query model changes needed for Stage 8 (see STAGE8_VINTED_DESIGN.md).

Steps:
1. Add `extra_params = models.JSONField(default=dict, blank=True)` to `Query` in `bazos/models.py`.
2. Update the `url` property on `Query`: if `marketplace == "vinted"`, return the value from
   `self.extra_params.get("base_url", "https://www.vinted.cz")`.
3. Generate migration `0020_query_extra_params.py` (or next available number after P1/P2).
4. Update `QueryAdmin` to expose `extra_params` and add `marketplace` to list_display if not already there.
5. Write a test that a Vinted query with `extra_params={"base_url": "https://www.vinted.sk"}` returns the correct URL.

Do not implement VintedScraper itself yet — that is a separate prompt (P4).
```

---

### P4 — Stage 8: VintedScraper implementation
> ⚠️ Requires P3. Also requires `vinted-scraper` added to pyproject.toml first.

```
Implement VintedScraper for Stage 8 (see STAGE8_VINTED_DESIGN.md).

Prerequisite: `vinted-scraper` package must already be installed (`pip install vinted-scraper`).

Steps:
1. Create `bazos/scraping/vinted/__init__.py` (empty).
2. Create `bazos/scraping/vinted/vinted_scraper.py` implementing `MarketplaceScraper`:
   - `marketplace = "vinted"`
   - `__init__(self)` — instantiates `VintedScraper(base_url)` from the `vinted_scraper` package internally
   - `run_query(query: Query) -> Iterator[Ad]`:
     - Builds params dict from `query.text`, `query.price_lower/upper`, and `query.extra_params`
     - Calls `self._client.search(params)`
     - Maps each `VintedItem` to an `Ad` (external_id=item.id, marketplace="vinted", name=item.title,
       price_raw=str(item.price), url=item.url, short_description=item.description or "",
       topped=False, publish_date=None, view_count=None)
   - `load_full_description(ad: Ad) -> Ad` — no-op, return ad unchanged
   - `check_blacklisted(url: str = "") -> bool` — always return False
3. Uncomment `"vinted": VintedScraper()` in `_build_scrapers` in `bazos_query_runner.py`.
4. Write tests mocking `vinted_scraper.VintedScraper.search` — test field mapping and empty-result handling.
5. Add a `marketplace_vinted` service to `docker-compose.yml` running `run_scraper` filtered to Vinted queries (or confirm the existing scraper handles all marketplaces).
```

---

### ✅ P5 — Stage 9: Real Filter Rules — done
All five rules (`PriceRangeRule`, `BlocklistKeywordRule`, `RequiredKeywordRule`,
`PublisherBlocklistRule`, `PriceDropRule`) plus `parse_price` are in `bazos/filters.py`. Migration
`0021_emailpublisher_blocked_phonepublisher_blocked_and_more.py` adds
`Query.filter_blocklist`/`filter_required` and `EmailPublisher.blocked`/`PhonePublisher.blocked`,
admin exposes them (block/unblock actions on both publisher admins), and
`bazos/tests/test_filters.py` covers each rule. Nothing left to do here. (`run_filter` no longer
uses a fixed `RuleEngine([PassthroughRule()])`/`RuleEngine([...five rules])` — see P17 below,
also done, for how rule selection is now per-query.)

---

## 🐛 Silent-failure defects

> Added 2026-07-29. These are **not ideas** — they are things quietly broken today, each with a
> known fix. Common theme: **the pipeline cannot currently distinguish "nothing to find" from
> "not working"**, so every failure mode below looks like a quiet market. Do these before any
> feature work; they're ~1 day in total and they protect the value of everything else.

### P18 — `QueryRun` is lost whenever a query raises
```
QueryRun rows silently vanish on failure, so there is no coverage metric.

Context: in `bazos/scraping/bazos_runner.py::run`, the QueryRun is constructed in memory,
then `query_runner.run()` is called, and only afterwards are `run_end`/`new_ads_count` set
and `.save()` called. Any exception from `query_runner.run()` means the row is never
persisted at all. Combined with `run_scraper`'s default mode (which catches everything at
the top level, logs, sleeps 60s and restarts the whole runner), the result is that a
repeatedly-failing query leaves no trace in QueryRun — you cannot answer "was this category
actually watched for the last 48 hours?".

Steps:
1. Save the `QueryRun` row immediately after constructing it (so it exists even if the run
   dies), then update it with `run_end`/`new_ads_count` in a `finally` block.
2. Add a nullable `error` (TextField) and a `success` (BooleanField) to `QueryRun`; on
   exception, record the exception string and re-raise. Generate the migration.
3. Wrap the per-query body in try/except/finally so one failing query does not abort the
   whole pass (today an exception propagates out of the `for query in queries` loop and
   kills the remaining queries in that pass — confirm this and fix it deliberately).
4. Surface it: add `success`/`error` to `QueryRunAdmin` (see P9) and to the list filters.
5. Write tests: a scraper that raises still produces a QueryRun row with success=False and
   a populated error, and subsequent queries in the same pass still execute.
```

---

### P19 — No zero-results canary (parser drift is invisible)
```
A Bazos HTML change would silently zero the deal flow and look identical to a quiet market.

Context: `BazosScraper._parse_product` depends on hardcoded CSS class names
(`inzeratynadpis`, `nadpis`, `velikost10`, `popis`, `inzeratycena`, `inzeratylok`,
`inzeratyview`, `inzeratyakce`) and an `assert int(bazos_id) == product_id`. If Bazos
renames a class, parsing fails or yields nothing, `run_scraper`'s outer handler swallows it,
and the logs show a scraper that keeps running and finding no new ads — which is exactly what
a genuinely quiet period looks like. There is no alert for this today.

Steps:
1. Add a check after each pass in `BazosRunner.run`: track consecutive passes in which the
   total new-ad count across all queries was zero.
2. When that counter crosses a threshold (make it a setting, default e.g. 6 consecutive
   passes), emit a WARNING via `self.log` — which already fans out to the `for_logging`
   Discord channels — and reset the counter after alerting so it doesn't spam every pass.
3. Consider a second, stronger signal: a pass where every query returned zero *parsed rows*
   (not just zero *new* ads) is much more suspicious than zero new ads, since a live listing
   page essentially always parses to >0 rows. Prefer this if `run_query` can cheaply report
   rows-seen alongside new-ads-found.
4. Do NOT make this fatal — it's an alert, not a crash. A genuinely dead category at 3am
   should not stop the scraper.
5. Write tests for the counter/threshold/reset logic with a mocked scraper returning zero rows.
```

---

### P20 — Two IP-guard failure modes: silent total skip, and an unbounded retry loop
```
Fix two guard bugs in the IP layer that can each stall the scraper invisibly.

Context (a) — silent total skip: `BazosRunner.run` does
`if self.ip_changer.check_ip_local(): self.log(...); continue`. `continue` skips the query.
If `check_ip_local()` is persistently True — a misconfigured `LOCAL_IP_SUBNET`, or Tor down
so the session egresses from the local network — then EVERY query is skipped on EVERY pass,
forever, while each pass reports completing normally. Total silent failure.

Context (b) — unbounded loop: `IPChanger.renew_ip_bazos_ok` is `while True:` with no attempt
cap — it rotates and re-probes until Bazos stops returning 403. If Bazos is blocking the
whole exit-node pool (the documented Tor reputation problem, see
../proxies/PROXY_ROTATION_RESEARCH.md §2), this spins indefinitely, hammering both Tor's
control port and Bazos.

Steps:
1. For (a): treat a local IP as a pass-level fatal condition, not a per-query skip — break
   out of the query loop, log at ERROR (so it reaches the Discord logging channels), and let
   the pass end so the next one retries after the normal sleep. A guard that can silently
   disable all work must be loud.
2. For (a): also count consecutive local-IP detections and escalate (ERROR + longer backoff)
   rather than re-probing at full cadence.
3. For (b): add a max-attempts cap to `renew_ip_bazos_ok` (reuse `MAX_ATTEMPTS` from
   `bazos/const.py`, currently 5), raise `BazosBlacklistedError` when exhausted, and let the
   caller decide — do not loop forever inside the IP layer.
4. For (b): add a bounded backoff between rotation attempts so a fully-blocked pool doesn't
   generate a tight request loop.
5. Write tests: `check_ip_local` returning True aborts the pass loudly rather than silently
   skipping each query; `renew_ip_bazos_ok` raises after MAX_ATTEMPTS rather than hanging.
```

---

## ⚡ Latency & data-quality prerequisites

> Added 2026-07-29. **P21 is the highest-value item in this file.** The rationale is commercial
> and lives in [`../MONETIZATION.md`](../MONETIZATION.md) **§7.1**: the current 15–45 min interval
> gives a **~15 minute median detection latency** while competing services poll every 60 s and
> good listings are gone in minutes — so the deal-capture premise of the whole project fails on
> this one number. The technical groundwork is already done in
> [`../proxies/PROXY_ROTATION_RESEARCH.md`](../proxies/PROXY_ROTATION_RESEARCH.md) §8 and
> [`../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`](../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md) §8;
> this prompt is the missing executable version. It also unblocks
> [`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) #6, which needs the API's second-resolution timestamps.

### P21 — Cut latency ~30×: production API cutover + guard collapse + rotating proxy
> ⚠️ Do P18–P20 first — you want failure visibility *before* you increase cadence.

```
Take detection latency from a ~15 min median to a ~2 min cadence. Three changes, one goal.
Read ../proxies/PROXY_ROTATION_RESEARCH.md §5 and §8 and ../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md
§8 Stage C first — the design decisions are already made there; this is execution.

Part 1 — tunable API page size (do this first, it's the prerequisite):
1. `BazosApiScraper` currently hardcodes `limit=API_PAGE_SIZE` (210). A steady-state dedup
   probe only needs the newest handful. Add a `limit` parameter (default 210 for
   backfill/deep paging) and use a small value (~10) for the routine newest-first pass.
   Measured effect: the dominant request drops from ~15 KB to ~1.1 KB (research doc §4).
2. Keep 210 for `run_new_query` backfill and any bulk `ad_id[]=` path.

Part 2 — collapse the duplicate blacklist check:
3. Per PROXY_ROTATION_RESEARCH.md §3 there are ~3 Bazos requests per query per pass, and TWO
   of them are redundant blacklist probes: `BazosRunner.run`'s
   `ip_changer.check_bazos_blacklisted(query.url)` and the scraper-level
   `scraper.check_blacklisted(...)`. Collapse to a SINGLE probe ONCE PER PASS (not per
   query) in `BazosRunner.run`, before the query loop.
4. `check_ip_local()` calls icanhazip.com per query — move that to once per pass too.
5. Be careful with the interaction with P20: the guards must still be loud on failure, just
   evaluated less often.

Part 3 — rotating proxy transport:
6. Implement `ip_changer/http_proxy.py::HttpProxyIPChanger` per the sketch in
   PROXY_ROTATION_RESEARCH.md §8 — `renew_session` points a fresh `requests.Session` at
   `settings.PROXY_URL`; `renew_ip` is a no-op (the provider rotates per request);
   `renew_ip_and_check_new` re-creates the session and returns the new IP.
7. Add `PROXY_URL` to settings/.env (empty default) and an `HTTP_PROXY` branch in
   `BazosRunner.__init__` alongside `DUMMY`/`TOR`, gated on `IP_CHANGER_TYPE`. Nothing
   changes until it's set — do not alter the default.
8. Validate with the existing tool before switching production:
   `python bench_proxy.py --proxy <endpoint> --repeat 30 --query auto` and compare success %
   against the current Tor baseline. This is the one measurement PROXY_ROTATION_RESEARCH.md
   §10 flags as still missing — record the result in that doc's §10.

Part 4 — cut over and lower the interval:
9. Switch ONE canary `Query` to `marketplace="bazos_api"`, run
   `python manage.py compare_bazos_scrapers`, confirm parity, then migrate the rest.
10. Only after parity: lower `INTERVAL_LOWER`/`INTERVAL_UPPER` (they are already env-driven,
    no code change). Step down gradually — e.g. 15 min → 5 min → 2 min — watching the P19
    canary and the blacklist-probe outcome at each step rather than jumping straight to 2 min.
11. Reconsider `NightMultiplier`: at a 2-minute cadence the night ×2 is much less meaningful,
    and BACKLOG_IDEAS.md #6 (now unblocked by the API's real timestamps) is the better
    long-term answer than a flat multiplier.
12. Keep detail-endpoint calls event-driven, per PROXY_ROTATION_RESEARCH.md §5.1 — detail
    volume, not query count, is what re-creates the old single-IP ban.
```

---

### P22 — `Ad.price_raw` → real integer + `price_type`
> Unblocks P23, and BACKLOG_IDEAS.md #10 (distance/margin scoring).

```
`Ad.price_raw` is a CharField holding strings like "12 500 Kč", "Dohodou", "V textu",
"Nabídněte" — so no median, percentile, index, or margin arithmetic is possible. This is
already flagged as a TODO in `bazos/models.py` on the price_raw field.

Note `parse_price(price_raw) -> int | None` ALREADY EXISTS in `bazos/filters.py` and is used
by PriceRangeRule/PriceDropRule — reuse it, don't write a second parser.

Steps:
1. Add `price` (IntegerField, null=True, db_index=True) and `price_type` (CharField with
   TextChoices: EXACT / NEGOTIABLE ("Dohodou") / IN_TEXT ("V textu") / MAKE_OFFER
   ("Nabídněte") / FREE / UNKNOWN) to `Ad`. KEEP `price_raw` — it's the audit trail and the
   source for backfill.
2. Extend the parsing in `bazos/filters.py` (or move it to a shared helper both filters and
   scrapers import) so it returns BOTH the amount and the detected type, rather than just
   `int | None`. Keep the existing `parse_price` signature working for current callers.
3. Populate both new fields at scrape time in `BazosScraper` and `BazosApiScraper`. The API
   path can do better than parsing: the detail endpoint returns a real `price_type` field
   (BAZOS_HIDDEN_API_RESEARCH.md §5.2) and listings carry `currency` — prefer those when
   available and fall back to string parsing for the HTML path.
4. Write a data migration backfilling `price`/`price_type` from existing `price_raw` values.
   Log/count rows that fail to parse rather than silently leaving them null.
5. Update `PriceRangeRule` and `PriceDropRule` to use `ad.price` directly (keeping their
   current PASS-on-unparseable behaviour, which is still correct when `price is None`).
6. `PriceChange.old_price`/`new_price` are also CharFields — decide deliberately whether to
   migrate them too (recommended: yes, same treatment, or price history stays unusable for
   the same reasons).
7. Tests: parsing of each price form incl. thousands separators and non-numeric variants;
   the backfill migration; both filter rules still behaving identically on edge cases.
```

---

### P23 — `PriceAnomalyRule` — the first rule that actually finds deals
> ⚠️ Requires P22 (needs a numeric price). Design rationale already written:
> [`../bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md`](../bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md)
> §1 stage 2 ("Cheap filter pass — zero extra API calls"). This prompt is the promotion of
> that design, not a new idea. Distinct from BACKLOG_IDEAS.md #4, which compares against
> *external* retail prices; this one compares against *your own accumulated Bazos history*.

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
> [`../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`](../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md)
> §6.4a and §8 Stage D. This prompt is the promotion of that design.

```
You currently record ASKING prices only, never realised ones. The closest available proxy is
time-to-disappear plus last-seen price — and it's cheap, because `ads.php` accepts up to 210
`ad_id[]=` values in ONE request and silently omits ids that no longer exist, while
`ad-detail-2.php` returns HTTP 410 {"status":"deleted"} for a removed ad.

This is the single most valuable field the DB doesn't have: it's the feedback signal for
P23's anomaly model (a genuinely underpriced item should disappear fast — see
../bazos-api/BAZOS_API_DISCOVERY_PIPELINE.md §3.4 "deal-velocity"), and it's the prerequisite
for any price-index or valuation work (../MONETIZATION.md §4.1b, §7.2c).

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
   ../proxies/PROXY_ROTATION_RESEARCH.md §5.1 before choosing an interval — detail-endpoint
   volume is the documented ban vector. Once per hour or few hours is plenty for a
   time-to-sell signal; do not run it every pass.
5. Do NOT create a `Job` model for this yet — one recurring job doesn't justify
   JOB_QUEUE_DESIGN.md's generic machinery. A management command plus a docker-compose
   service matches the existing pattern. Revisit if a third such job appears.
6. Tests: batching at the 210 boundary; absent ids marked removed; present ids refreshed;
   410 handling on the detail path; idempotency when run twice.
```

---

## 🟡 Improvements (not pipeline-blocking, but useful)

### ✅ P6 — Sentry integration — done
`sentry-sdk[django]` is in `pyproject.toml`, and `scraper/settings.py` initializes it behind
`SENTRY_DSN` (empty disables it, per `CLAUDE.md`'s Environment section). Nothing left to do here.

---

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
  (a) Delete `generate_random_queries`, `randomly_generated`, and the `update(enabled=False)` at loop start in `BazosRunner.run`, or
  (b) Document what they are for with a proper comment.

Also check: the `location_center = randint(10000, 99999)` line generates a random postcode — is this intentional?
```

---

### P9 — Admin UX improvements
```
Polish the Django admin for the current pipeline state.

1. `AdAdmin`:
   - Add `filter_reason` to the list display (short, truncated).
   - Add a custom action `mark_as_pending` that resets status to PENDING (useful for re-running the filter on an ad).
   - Add `price_history` inline (PriceChange, once Stage 4 is done).

2. `QueryAdmin`:
   - Add `last_run` display (latest `QueryRun.run_start` for this query).
   - Show `new_ads_count` sum from recent runs.

3. `QueryRunAdmin`:
   - Register it if not already registered.
   - Show duration (run_end - run_start).
```

---

### P10 — Test coverage audit
```
Run the test suite with coverage and identify gaps.

Steps:
1. Install `pytest-cov` if not already present.
2. Run: `pytest --cov=bazos --cov=senders --cov=ip_changer --cov-report=term-missing`
3. Identify any file or branch below 70% coverage.
4. Write targeted tests for the gaps (focus on `run_filter.py`, `run_sender.py`, `bazos_runner.py`, `filters.py`).
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
1. In `bazos/scraping/bazos_query_runner.py::_handle_new_product`, before calling
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
> real posting time (`../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md` §4.3). Also note P21 reduces the
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
   the same interface `BazosRunner.get_next_interval` already calls.
3. Decide a reasonable minimum/maximum multiplier bound so a genuinely dead hour doesn't
   produce an absurdly long sleep.
4. Write tests for the new density-based multiplier logic (mock/fixture `Ad` timestamps).
5. Consider logging the computed multiplier per pass for visibility during rollout.
```

---

### ✅ P15 — True AND/OR query probe — done
Probed live 2026-07-26 against both `api/v1/ads.php?query=` and HTML `search.php?hledat=`
(identical totals on both, confirming shared backend). **`OR` confirmed real** — boolean
union, case-insensitive, works with 3+ terms, quoting/parens optional
(`iphone OR traktor` = 18481 vs. 6940+11542=18482 baseline sum, near-exact since the two
terms barely overlap). **`AND` confirmed fake** — not a parsed operator, just an additional
literal required word; `macbook AND pro` = 71 vs. `macbook pro`'s already-implicit-AND 1101,
a 15x drop from requiring literal "and" text too. Full evidence and probe commands in
`BAZOS_HIDDEN_API_RESEARCH.md` §4.1a. Follow-up (not done here): actually using `OR` to
consolidate `Query` rows is a separate, un-started idea — see `BACKLOG_IDEAS.md` #7.

---

### P16 — Discord thumbnail embed
> Promoted from `BACKLOG_IDEAS.md` #3a — see there for full rationale (including why this is
> low-risk unlike #3b's image mirroring). One open sub-question below before starting.

```
Attach a thumbnail image to the Discord notification instead of plain text.

Open question to resolve first: get the thumbnail URL from BazosApiScraper's listing
payload (`image_thumbnail`, already parsed at zero extra request cost per
BAZOS_HIDDEN_API_RESEARCH.md §5.1) — but that scraper isn't wired into production yet
(marketplace="bazos_api" is validation-only, see BAZOS_HIDDEN_API_RESEARCH.md §8 Stage B) —
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

### ✅ P17 — Per-query filter rule registry — done
`RULE_REGISTRY` (name → rule instance for all five Stage 9 rules) and `DEFAULT_RULE_NAMES` are
in `bazos/filters.py`, along with `build_rule_engine(query)` — empty `filter_rule_names` applies
all default rules, a subset (e.g. `["price_range"]`) applies only those, and an unknown name
raises `ValueError` (fail loudly on a typo). `Query.filter_rule_names` (migration
`0022_query_filter_rule_names.py`) exposes it — shows on `QueryAdmin`'s default form (raw JSON
widget, per the original "fine for a first pass" note; no multi-select built yet). `run_filter`'s
loop now calls `build_rule_engine(ad.query)` per ad instead of a module-level singleton. Tests in
`bazos/tests/test_filters.py` cover the registry, the default/subset/unknown-name cases, and that
a scoped rule set doesn't apply rules outside its list. Nothing left to do here.

---

## Order recommendation

> **Revised 2026-07-29.** The old ordering optimised for "cheapest independent win". That was
> reasonable while the goal was tidying the pipeline, but it doesn't survive contact with what the
> project is *for*: see [`../MONETIZATION.md`](../MONETIZATION.md) §7.1. Latency, then failure
> visibility, then data usability — features after that.

**Do these first, in this order:**

1. **P18–P20** (silent-failure defects) — ~1 day total. Get failure visibility *before* raising
   cadence, otherwise P21 just fails faster and quieter.
2. **P21** (latency chain) — ~3–5 days, **highest-value item in this file.** ~30× latency
   improvement for ~$3–6/mo, using a scraper that's already built and tested.
3. **P22** (price → int + `price_type`) — ~1 day. Unblocks everything numeric.
4. **P24** (delisting / time-to-disappear) — ~1–2 days. The feedback signal for P23 and the
   prerequisite for any valuation or index work.
5. **P23** (`PriceAnomalyRule`) — ~1–2 days, in shadow mode first. The first rule that finds
   deals rather than matching keywords.

**Then, if flipping is the actual goal**, the two cheap items from
[`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) that aren't prompts yet: **#9** (`AdOutcome`, ~half a day —
the only source of ground truth for calibrating P23) and **#10** (distance/travel-cost scoring),
built together with **P16** since all three touch the notification-formatting path.

**Already done:** ~~P1~~ (price history), ~~P5~~ (real filter rules), ~~P17~~ (per-query filter
registry), ~~P6~~ (Sentry), ~~P15~~ (AND/OR probe).

**Still worthwhile, lower priority:**

- **P3** (Query `extra_params`) — 15 min, unblocks Vinted. Cheap regardless of direction, and
  multi-marketplace is the concentration-risk hedge (`../MONETIZATION.md` §7.4).
- **P10** (coverage audit) — quick wins on confidence.
- **P13** (filter-before-detail-fetch) — matters more once cadence rises.
- **P16** (Discord thumbnail) — best visible payoff; P21 makes it nearly free by putting
  `image_thumbnail` in the production payload, so it's worth doing *after* the cutover rather than
  adding HTML-scraper parsing that P21 obsoletes.
- **P7** / **P8** / **P9** / **P12** — housekeeping, no dependencies.
- **P14** (interval tuning) — ⚠️ **blocked**, and it was previously listed here as a zero-dependency
  quick win. It isn't: `extract_date` discards the time component, so `ExtractHour("publish_date")`
  returns 0 for every row. P21 unblocks it by supplying the API's second-resolution `from` field.
  See [`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) #6 for the full correction.
- **P2** (Stage 5 query priority), **P4** (VintedScraper), **P11** (multi-marketplace `Ad.message`)
  — feature work; sequence against whichever direction you pick.
