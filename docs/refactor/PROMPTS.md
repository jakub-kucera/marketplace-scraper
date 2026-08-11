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

### ✅ P18 — `QueryRun` is lost whenever a query raises — done
`bazos/scraping/bazos_runner.py::run` now saves the `QueryRun` row **before** the query
executes, wraps the per-query body in `try/except/finally`, records `success=False` +
`error` on failure, and always stamps `run_end` in the `finally`. `QueryRun.success`
(BooleanField, default True) and `QueryRun.error` (nullable TextField) are in
`bazos/models.py` with migration `0023_queryrun_error_queryrun_success.py`. `QueryRunAdmin`
shows both in `list_display` and filters on `success`. Four tests in
`bazos/tests/test_query_run_tracking.py` cover the row surviving a raise, the success path,
one failing query not aborting the pass, and persistence-before-execution.

**One deliberate deviation from the original step 2:** the `except` block `continue`s
instead of re-raising. That's the right call — re-raising would defeat step 3 — so the
prompt's wording, not the implementation, was wrong.

> ⚠️ **Residual gap, not covered by P18 — see P20.** The three IP-guard calls at the top of
> the query loop (`check_bazos_blacklisted`, `change_ip`, `check_ip_local`) sit **outside**
> the new `try`, so an exception there still escapes `run()` and takes down the whole
> runner via `run_scraper`'s 60s-sleep-and-restart handler — losing the rest of the pass
> exactly as before. **This is an observed failure, not a theoretical one** (2026-08-08:
> `RemoteDisconnected` from `get_current_ip()`'s `icanhazip.com` call over a dead Tor
> circuit, crashing at `bazos_runner.py:41` and `:43`). P20 owns this; note that P20 as
> written only covers the guards *returning misleading values*, not *raising* — see its
> own ⚠️ note.

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

### P20 — Three IP-guard failure modes: silent total skip, unbounded retry loop, and raising guards

> **🔶 Partially done 2026-08-09 — case (b) is largely landed.** `renew_ip_bazos_ok` now takes
> a `max_attempts` cap (default `MAX_ATTEMPTS`), raises `BazosBlacklistedError` when
> exhausted, and `BazosRunner.run` catches it via `logger.exception` (not `self.log` — this
> was deliberate: `self.log`'s WARNING level only reaches the Discord log channels, and
> Sentry's logging integration only auto-captures ERROR+, so a plain WARNING here would have
> stayed invisible in Sentry) and **skips that query while keeping the pass**. Two tests cover
> the bounded-retry/pluggable-check behavior in `ip_changer/tests/test_ip_changer.py`
> (`test_renew_ip_bazos_ok_raises_after_max_attempts_exhausted`,
> `test_renew_ip_bazos_ok_uses_custom_is_blacklisted_check`); three more in
> `bazos/tests/test_bazos_runner_blacklist.py` cover the dispatch itself — a `bazos_api`
> query's pre-check hits `BazosApiScraper.check_blacklisted`, a `bazos` query's hits
> `BazosScraper.check_blacklisted`, and a query that exhausts retries is skipped without
> aborting the rest of the pass. The `is_blacklisted` callable is also newly pluggable so a
> query dispatched to `BazosApiScraper` is checked against the API surface rather than the
> HTML one (via `BazosRunner._blacklist_checker`, new) — a correctness improvement beyond
> what step 6 asked for, since the two surfaces block independently; this is what fixed the
> `bazos_api`-marketplace query that was raising `BazosBlacklistedError` every pass in
> production (root-caused 2026-08-08, landed 2026-08-09).
>
> **Still outstanding in this prompt:** case **(a)** entirely; case **(b)** step 7
> (`tor.py:34`'s *second* unbounded `while True:` in `renew_ip_and_check_new`) and step 8
> (backoff between rotation attempts); and **all of case (c)** — there are still no timeouts
> anywhere in `ip_changer/`, and the exposure is actually two call sites now, not one: the
> pre-flight `blacklist_check(query.url)` call in `BazosRunner.run` (`bazos_runner.py:40`) has
> no try/except around it at all, and inside `change_ip` (`bazos_runner.py:102`) only
> `BazosBlacklistedError` is caught — `get_current_ip()`'s bare `session.get(...)`
> (`bazos_runner.py:103` → `ip_changer.py:33`) or a `ConnectionError` surfacing through
> `is_blacklisted(url)` itself would both still escape and kill the runner.

> **⚠️ Scope corrected 2026-08-08 — case (c) added.** As originally written this prompt only
> covered the guards **returning misleading values**. It missed the case that actually
> happened in production: the guards **raising**. Observed crash, twice in one log:
>
> ```
> ip_changer.py:31 get_current_ip → session.get('https://icanhazip.com')
> requests.exceptions.ConnectionError: ('Connection aborted.',
>     RemoteDisconnected('Remote end closed connection without response'))
> ```
>
> reached from `bazos_runner.py:41` (`change_ip`) and `bazos_runner.py:43`
> (`check_ip_local`). Diagnosis: **not** Bazos rate-limiting — the failing host is
> `icanhazip.com`, and `RemoteDisconnected` means no HTTP response arrived at all, unlike a
> 403/429 which `check_bazos_blacklisted` already handles. It is a dead Tor circuit /
> refused exit (`PROXY_ROTATION_RESEARCH.md` §2), compounded by icanhazip being
> Cloudflare-fronted and therefore hostile to Tor exits by default.
>
> Two aggravating factors, both cheap to fix and both in the steps below:
> **no timeouts anywhere** (`grep -rn timeout ip_changer/ bazos/scraping/` is empty and
> `requests` has no default) — the observed hang was **~4 minutes** on one socket; and these
> guard calls sit **outside** P18's new per-query `try`, so the exception still escapes
> `run()` and costs the entire pass.

```
Fix three guard bugs in the IP layer that can each stall the scraper invisibly.

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

Context (c) — the guards RAISE, killing the whole pass: `get_current_ip` (ip_changer.py:33)
and `check_bazos_blacklisted` (:37) do bare `session.get(...)` with NO timeout, over a Tor
SOCKS proxy that regularly drops circuits. When one raises, the exception escapes the
per-query try/except added by P18 (those guard calls are ABOVE it in `BazosRunner.run`), so
`run_scraper` catches at top level, sleeps 60s, and rebuilds the entire runner — losing
every remaining query in the pass. Observed 2026-08-08; see the note above this block. As of
the 2026-08-09 partial fix this is now reachable from two spots in `bazos_runner.py`, neither
guarded: the pre-flight `blacklist_check(query.url)` call (:40, no try/except at all) and
`get_current_ip()` inside `change_ip` (:103, only `BazosBlacklistedError` is caught there).
Note also `tor.py:34`'s SECOND unbounded `while True:` in `renew_ip_and_check_new` — if Tor
keeps returning the same IP it loops forever at 5s/iteration. P20 previously named only
`renew_ip_bazos_ok`'s loop.

Steps — do (c) first; it is ~30 minutes and stops an active production crash loop:
1. For (c): add explicit timeouts to EVERY request in `ip_changer/` — `timeout=(5, 15)`
   (connect, read) on `get_current_ip`, `check_bazos_blacklisted`, and anything else doing
   `session.get`. Prefer setting it once on the session/adapter so new call sites can't
   forget. A 4-minute hang on a dead socket is worse than a fast failure.
2. For (c): make `get_current_ip` resilient rather than trusting one Cloudflare-fronted host
   over Tor — retry with fallbacks (api.ipify.org, ifconfig.me, ident.me) and raise only if
   all fail. Consider skipping the check entirely when IP_CHANGER_TYPE=TOR, where a local
   egress is impossible by construction (socks5h fails closed, it does not fall back to a
   direct connection) — it is currently the most Tor-hostile request in the pipeline and it
   guards against a case that transport makes unreachable.
3. For (c): move the guard calls INSIDE a try/except in `BazosRunner.run` so a guard failure
   costs one query (or one pass), not the whole runner. Record it on the QueryRun row the
   way P18 already does for scraper failures.
4. For (a): treat a local IP as a pass-level fatal condition, not a per-query skip — break
   out of the query loop, log at ERROR (so it reaches the Discord logging channels), and let
   the pass end so the next one retries after the normal sleep. A guard that can silently
   disable all work must be loud.
5. For (a): also count consecutive local-IP detections and escalate (ERROR + longer backoff)
   rather than re-probing at full cadence.
6. For (b): add a max-attempts cap to `renew_ip_bazos_ok` (reuse `MAX_ATTEMPTS` from
   `bazos/const.py`, currently 5), raise `BazosBlacklistedError` when exhausted, and let the
   caller decide — do not loop forever inside the IP layer.
7. For (b): apply the same cap to `tor.py::renew_ip_and_check_new`'s inner `while True:`.
8. For (b): add a bounded backoff between rotation attempts so a fully-blocked pool doesn't
   generate a tight request loop.
9. Write tests: a guard that raises does not abort the pass; timeouts are actually set on
   the session; `check_ip_local` returning True aborts the pass loudly rather than silently
   skipping each query; `renew_ip_bazos_ok` and `renew_ip_and_check_new` both raise after
   MAX_ATTEMPTS rather than hanging.
```

> **Note on the durable fix.** Steps 1–3 are damage control for a transport that is failing
> on reputation, not on anything you're doing wrong — your volume (~6 queries × 3 requests
> per 15–45 min) is nowhere near a rate limit. **P21b** replaces Tor entirely and makes most
> of this moot: `HttpProxyIPChanger.renew_ip` is a no-op, so the icanhazip round-trip that
> crashes here largely stops existing. Do P20 anyway — a guard that can take down the runner
> is worth fixing regardless of transport — but don't expect it to make the 403s go away.

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

### P21 — Cut latency: API cutover + guard collapse + rotating proxy

> **⚠️ Split into P21a / P21b, 2026-08-08.** This was one 3–5 day unit, which hid the fact
> that it bundles **two very different risk profiles**:
>
> - **P21a (Parts 1, 2, 4a)** is pure code. No external dependency, no account, no monthly
>   cost, no unvalidated assumption.
> - **P21b (Part 3, 4b)** needs a paid proxy provider *and* rests on a measurement that has
>   **never been run** — `PROXY_ROTATION_RESEARCH.md` §10 calls the sustained block-rate
>   probe *"the only missing data point."*
>
> **The reason the split is worth making is arithmetic, not tidiness.** Using
> `PROXY_ROTATION_RESEARCH.md` §5's own model (`passes/day = 1200 / interval_minutes`):
>
> | | Bazos req/query/pass | Passes/day | **Bazos req/query/day** | Median latency |
> |---|---|---|---|---|
> | Today (HTML, 3 guards) | 3 | 40 (30 min avg) | **120** | ~15 min |
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

#### P21a — The free 3×: API cutover + guard collapse + interval to ~10 min
> ⚠️ Do P19–P20 first — you want failure visibility *before* you increase cadence.
> (P18 is done.) No external dependency; nothing here costs money.

```
Take detection latency from a ~15 min median to a ~5 min median at UNCHANGED Bazos request
volume. Read ../proxies/PROXY_ROTATION_RESEARCH.md §3 and §5 and
../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md §8 Stage C first — the design decisions are
already made there; this is execution.

Part 1 — tunable API page size (do this first, it's the prerequisite):
1. `BazosApiScraper` currently hardcodes `limit=API_PAGE_SIZE` (210) at
   `bazos/scraping/bazos/bazos_api_scraper.py`. A steady-state dedup probe only needs the
   newest handful. Add a `limit` parameter (default 210 for backfill/deep paging) and use a
   small value (~10) for the routine newest-first pass. Measured effect: the dominant
   request drops from ~15 KB to ~1.1 KB (research doc §4).
2. Keep 210 for `run_new_query` backfill and any bulk `ad_id[]=` path.

Part 2 — collapse the duplicate guards (this is what pays for the extra cadence):
3. Per PROXY_ROTATION_RESEARCH.md §3 there are ~3 Bazos requests per query per pass, and TWO
   of them are redundant blacklist probes: `BazosRunner.run`'s
   `ip_changer.check_bazos_blacklisted(query.url)` and the scraper-level
   `scraper.check_blacklisted(...)`. Collapse to a SINGLE probe ONCE PER PASS (not per
   query) in `BazosRunner.run`, before the query loop.
4. `check_ip_local()` calls icanhazip.com per query — move that to once per pass too. This
   also cuts the blast radius of the observed 2026-08-08 crash (see P20's ⚠️ note) by ~6×,
   since that request is the one that died.
5. Be careful with the interaction with P20: the guards must still be loud on failure, just
   evaluated less often.

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
9. Keep detail-endpoint calls event-driven, per PROXY_ROTATION_RESEARCH.md §5.1 — detail
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
PROXY_ROTATION_RESEARCH.md §2 ("every anti-bot vendor ships the Tor exit list") and the
observed 2026-08-08 crash logged in P20 — Bazos 403'd the exit AND the same dead circuit
killed the icanhazip liveness check. So this prompt may be worth doing on reliability
grounds even if you never lower the interval further.

Part 3 — rotating proxy transport:
1. Implement `ip_changer/http_proxy.py::HttpProxyIPChanger` per the sketch in
   PROXY_ROTATION_RESEARCH.md §8 — `renew_session` points a fresh `requests.Session` at
   `settings.PROXY_URL`; `renew_ip` is a no-op (the provider rotates per request);
   `renew_ip_and_check_new` re-creates the session and returns the new IP.
2. Add `PROXY_URL` to settings/.env (empty default) and an `HTTP_PROXY` branch in
   `BazosRunner.__init__` alongside `DUMMY`/`TOR`, gated on `IP_CHANGER_TYPE`. Nothing
   changes until it's set — do not alter the default.
3. MEASURE BEFORE SWITCHING. Run
   `python experiments/bench_proxy.py --proxy <endpoint> --repeat 30 --query auto` against
   (a) current Tor, (b) a Webshare datacenter trial, (c) a residential-CZ trial, and compare
   success %. This is the one measurement PROXY_ROTATION_RESEARCH.md §10 flags as still
   missing — RECORD THE RESULT IN THAT DOC'S §10. Do not skip this; it is the entire
   evidential basis for spending money here, and §10's recommendation (datacenter first,
   residential only if bans reappear) is unresolved without it.

Part 4b — lower the interval the rest of the way:
4. Step down gradually — 10 min → 5 min → 2 min — watching the P19 canary and the
   blacklist-probe outcome at each step rather than jumping straight to 2 min.
5. Reconsider `NightMultiplier`: at a 2-minute cadence the night ×2 is much less meaningful,
   and BACKLOG_IDEAS.md #6 (now unblocked by the API's real timestamps) is the better
   long-term answer than a flat multiplier.
6. Re-check detail-endpoint volume at the new cadence (PROXY_ROTATION_RESEARCH.md §5.1) —
   the table there shows 300 tracked ads at 5 min is already 72,000 detail req/day, which is
   the documented ban vector. Pool size is what absorbs it.
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
   - Show duration (run_end - run_start).
     STILL OPEN.

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
  `images[]` — see ../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md §5.2, verified live.
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

## Order recommendation

> **Revised 2026-07-29.** The old ordering optimised for "cheapest independent win". That was
> reasonable while the goal was tidying the pipeline, but it doesn't survive contact with what the
> project is *for*: see [`../MONETIZATION.md`](../MONETIZATION.md) §7.1. Latency, then failure
> visibility, then data usability — features after that.

> **Amended 2026-08-08:** P18 is done; P21 is split into P21a/P21b (see its own note for the
> arithmetic); and a **zeroth** item was added that no prompt covered — there is no database
> backup at all, which is a bigger downside than anything below it is an upside.

**Do these first, in this order:**

0. **Database backups** — ~2 hours, ~$0/mo. Not a prompt in this file; see
   [`../BACKUPS.md`](../BACKUPS.md) §8. The archive is the one asset that can't be rebuilt
   ([`../MONETIZATION.md`](../MONETIZATION.md) §7.3) and it currently sits unbacked on a
   single Pi SD card. Every item below assumes it still exists.
1. **P20 case (c)** — ~30 min. Timeouts + resilient `get_current_ip` + guards inside a
   try/except. **Do this immediately**: it is an *active* production crash loop as of
   2026-08-08 (~5 min burned per cycle, no data collected), not a latent defect.
2. **P19–P20** (the rest of the silent-failure defects) — ~1 day. Get failure visibility
   *before* raising cadence, otherwise P21 just fails faster and quieter.
3. **P21a** (free 3×: API cutover + guard collapse + ~10 min interval) — ~2 days, **no cost,
   no external dependency.** ~15 min → ~5 min median latency at *unchanged* Bazos request
   volume. Best value-per-day in this file.
4. **P22** (price → int + `price_type`) — ~1 day. Unblocks everything numeric.
5. **P21b** (rotating proxy → ~1–2 min) — ~1–2 days + ~$3–6/mo. Deliberately *after* P22:
   it's the only item requiring a paid account and an unrun benchmark, so let P21a's
   observed block rate decide whether it's needed. **Note the independent reliability
   argument** — Tor is already failing (see P20's ⚠️), so this may be worth doing on those
   grounds alone.
6. **P24** (delisting / time-to-disappear) — ~1–2 days. The feedback signal for P23 and the
   prerequisite for any valuation or index work.
7. **P23** (`PriceAnomalyRule`) — ~1–2 days, in shadow mode first. The first rule that finds
   deals rather than matching keywords.

**Then, if flipping is the actual goal**, the two cheap items from
[`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) that aren't prompts yet: **#9** (`AdOutcome`, ~half a day —
the only source of ground truth for calibrating P23) and **#10** (distance/travel-cost scoring),
built together with **P16** since all three touch the notification-formatting path.

**Already done:** ~~P1~~ (price history), ~~P5~~ (real filter rules), ~~P17~~ (per-query filter
registry), ~~P6~~ (Sentry), ~~P15~~ (AND/OR probe), ~~P18~~ (`QueryRun` failure tracking).

**Still worthwhile, lower priority:**

- **P3** (Query `extra_params`) — 15 min, unblocks Vinted. Cheap regardless of direction, and
  multi-marketplace is the concentration-risk hedge (`../MONETIZATION.md` §7.4).
- **P10** (coverage audit) — quick wins on confidence.
- **P13** (filter-before-detail-fetch) — matters more once cadence rises.
- **P16** (Discord thumbnail) — best visible payoff; P21 makes it nearly free by putting
  `image_thumbnail` in the production payload, so it's worth doing *after* the cutover rather than
  adding HTML-scraper parsing that P21 obsoletes.
- **P7** / **P8** / **P9** / **P12** — housekeeping, no dependencies.
- **P25** (`load_full_description` drops the publisher name) — ~15 min, no dependencies, but it
  only takes effect on queries with `load_full_description=True`; read its scope note first.
- **P14** (interval tuning) — ⚠️ **blocked**, and it was previously listed here as a zero-dependency
  quick win. It isn't: `extract_date` discards the time component, so `ExtractHour("publish_date")`
  returns 0 for every row. P21 unblocks it by supplying the API's second-resolution `from` field.
  See [`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) #6 for the full correction.
- **P2** (Stage 5 query priority), **P4** (VintedScraper), **P11** (multi-marketplace `Ad.message`)
  — feature work; sequence against whichever direction you pick.
