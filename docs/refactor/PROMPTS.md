# Ready-to-Run Prompts

Copy-paste any of these when you have tokens to burn.
Ordered roughly by dependency — earlier prompts unblock later ones.

---

## 🔴 Blocked / Missing (pipeline stages not yet implemented)

### P1 — Stage 4: Price History
```
Implement Stage 4 from PIPELINE_REFACTOR.md (Price History).

Steps:
1. Add `PriceChange` model to `bazos/models.py` (FK to Ad, `old_price`/`new_price` CharFields, use TimeStampedModel).
2. The `PRICE_CHANGED` AdStatus value already exists.
3. Refactor `_is_known` → `_get_known` in `bazos/scraping/bazos_query_runner.py` to return `Ad | None` instead of bool.
4. Update `run_existing_query` to detect price changes and create `PriceChange` records.
5. Generate migration `0020_price_change.py`.
6. Add `PriceChange` to Django admin (inline on `AdAdmin`).
7. Write tests for the price-change detection path.

Do not touch Stage 5 yet.
```

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

### P5 — Stage 9: Real Filter Rules
> ⚠️ Depends on P1 (price history) for `PriceDropRule`.

```
Implement Stage 9 filter rules from PIPELINE_REFACTOR.md.

Steps:
1. Add `parse_price(price_raw: str) -> int | None` to `bazos/filters.py`.
2. Add to `Query` model (with migration):
   - `filter_blocklist = models.JSONField(default=list, blank=True)`
   - `filter_required = models.JSONField(default=list, blank=True)`
3. Add `blocked = models.BooleanField(default=False)` to `EmailPublisher` and `PhonePublisher` (with migration).
4. Implement these `FilterRule` classes in `bazos/filters.py`:
   - `PriceRangeRule` — rejects if parsed price outside query.price_lower/upper (PASS when range is 0-0 or price non-numeric)
   - `BlocklistKeywordRule` — rejects if name or short_description contains any blocklist phrase (PASS when list empty)
   - `RequiredKeywordRule` — rejects if name and short_description contain none of the required keywords (PASS when list empty)
   - `PublisherBlocklistRule` — rejects if email_publisher.blocked or phone_publisher.blocked
   - `PriceDropRule` — for PRICE_CHANGED ads only: rejects if price did NOT drop
5. Wire all rules into the `RuleEngine` in `run_filter` management command (replace `PassthroughRule`).
6. Update `QueryAdmin` and `EmailPublisherAdmin`/`PhonePublisherAdmin` to expose the new fields.
7. Write unit tests for each rule in `bazos/tests/test_filters.py`.
```

---

## 🟡 Improvements (not pipeline-blocking, but useful)

### P6 — Sentry integration
```
Add Sentry error monitoring.

Steps:
1. Add `sentry-sdk[django]` to pyproject.toml dependencies.
2. In `scraper/settings.py`, after the LOGGING block, add Sentry init:
   ```python
   import sentry_sdk
   if SENTRY_DSN:
       sentry_sdk.init(dsn=SENTRY_DSN, traces_sample_rate=0.1)
   ```
   (`SENTRY_DSN` is already read from .env in settings.py)
3. Verify it captures unhandled exceptions in `run_scraper`, `run_filter`, `run_sender` management commands.
4. Add `SENTRY_DSN=` (empty) to .env.example.
```

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

## Order recommendation

If you only have time for a few:
1. **P1** (price history) — unlocks PriceDropRule in Stage 9
2. **P3** (Query extra_params) — 15 min, unblocks Vinted
3. **P5** (real filter rules) — highest user-visible value
4. **P10** (coverage audit) — quick wins on confidence
