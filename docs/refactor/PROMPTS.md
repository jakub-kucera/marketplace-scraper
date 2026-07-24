# Ready-to-Run Prompts

Copy-paste any of these when you have tokens to burn.
Ordered roughly by dependency — earlier prompts unblock later ones.

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
> Promoted from `BACKLOG_IDEAS.md` #6 — see there for full rationale. No dependencies, no new
> data collection; ready to run today.

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

### P15 — True AND/OR query probe
> Promoted from `BACKLOG_IDEAS.md` #7 — see there for full rationale. This is a probe/spike,
> not a design — small and self-contained, kills an unconfirmed claim either way.

```
Confirm or refute whether Bazos's search (HTML form or hidden API `query` param) supports
real boolean AND/OR operators, as issue #52 claimed but BAZOS_HIDDEN_API_RESEARCH.md never
tested.

Steps:
1. Using the same live-probe methodology as BAZOS_HIDDEN_API_RESEARCH.md §7 (curl with a
   faithful app User-Agent, see BAZOS_API_USER_AGENT.md), try plausible AND/OR syntaxes
   against `api/v1/ads.php?query=...` — e.g. `"macbook" OR "imac"`, `macbook|imac`,
   `macbook AND pro` — and compare `x-total-count`/results against known single-term baselines.
2. Also check the HTML search form (`hledat=` param) for the same behavior, since the two
   scrapers could differ.
3. Document the result (confirmed/unconfirmed, and exact syntax if it works) in
   BAZOS_HIDDEN_API_RESEARCH.md, following its existing "confirmed live" citation style.
4. Only if confirmed: sketch how this would reduce Query row sprawl (e.g. one query for
   "macbook" OR "imac" OR "ipad" instead of three rows) — as a follow-up idea, not part of
   this prompt's scope.
```

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

If you only have time for a few:
1. ~~**P1** (price history)~~ — done
2. ~~**P5** (real filter rules)~~ — done
3. ~~**P17** (per-query filter registry)~~ — done
4. **P3** (Query extra_params) — 15 min, unblocks Vinted
5. **P10** (coverage audit) — quick wins on confidence

Cheapest independent wins if you want a break from the pipeline stages:
6. **P14** (interval tuning) — zero new data, zero dependencies
7. **P15** (AND/OR probe) — ~1hr, just closes an unknown
