---
title: Refactor Plan — Consolidated
status: superseded
updated: 2026-07-19
superseded_by: PIPELINE_REFACTOR.md
---

# Refactor Plan — Consolidated

> **Archived — superseded by [`PIPELINE_REFACTOR.md`](../shipped/PIPELINE_REFACTOR.md).**
> This doc's Phase 1 progress markers went stale (several unchecked steps are
> actually implemented); `PIPELINE_REFACTOR.md`'s Stage checkmarks are the ones
> kept in sync with the code. Kept here for the Phase 1/2/3 framing, not as a
> live reference.

Synthesises `PIPELINE_REFACTOR.md` (Plan A) and `PIPELINE_REFACTOR_B.md` (Plan B) into a single,
staged execution plan.

> Marketplace abstraction (Vinted, `external_id`, `MarketplaceScraper` protocol) is intentionally
> deferred to Phase 3. Everything in Phases 1–2 works without it.

---

## What the plans agree on

Both documents describe the same end-state:

```
run_scraper  →[DB: PENDING]→  run_filter  →[DB: APPROVED]→  run_sender
```

Three independent processes communicating only through `Ad.status`. No Redis, no Celery —
PostgreSQL is the message bus.

The disagreement is just sequencing: Plan A focuses on the pipeline skeleton, Plan B layers on
marketplace abstraction and feature additions (price history, priority). The plan below separates
those concerns cleanly.

---

## Phase 1 — DB State Machine + Decoupled Pipeline

**Goal:** The scraper no longer blocks on Discord. Sending and filtering happen in separate processes.

Incremental — each step is independently shippable and safe to roll back.

---

### Step 0 · Configure logging + convert `print()` → `logging` ✅

**Files:** `scraper/settings.py`, `bazos/scraping/bazos_runner.py`,
`bazos/scraping/bazos_query_runner.py`, `bazos/scraping/bazos/bazos_scraper.py`,
`senders/services/discord_sender.py`

This step has **no new dependencies** — pure stdlib `logging` module.

Add a `LOGGING` dict to `settings.py`:
- Root logger at `WARNING` (Django internals stay quiet)
- App loggers (`bazos`, `senders`, `ip_changer`) at `INFO` → stdout via `StreamHandler`
- Format: `"{asctime} {levelname:<8} [{name}] {message}"` — timestamp prefix, same info
  as the old `print()` but structured
- `SENTRY_DSN` env var read here (empty by default) so Step 7 only needs the SDK init

Log level conventions used across the codebase:

| Level | Used for |
|-------|----------|
| `INFO` | Operational events (running query, new product, found N ads, sleeping) |
| `DEBUG` | Per-item chatter (page URL, sleep duration, TOP product, already exists) |
| `WARNING` | Notable but handled (blacklisted, rate limit, connection error, request failed) |
| `ERROR` / exception | Unhandled failures — let Sentry catch these |

`BazosRunner.log()` gains an optional `level` parameter so blacklisted/local-IP
conditions can be logged at `WARNING` while also being sent to the Discord logging webhook.
`self.loggers` renamed to `self.discord_loggers` to avoid shadowing the module-level `logger`.

**Tests:** all existing tests still pass (already verified).

---

### Step 1 · Add `Ad.status` and supporting fields

**Files:** `bazos/models.py`, new migration

Add to `Ad`:

```python
class AdStatus(models.TextChoices):
    PENDING  = "PENDING"    # scraped, awaiting filter
    APPROVED = "APPROVED"   # passed filters, awaiting send
    REJECTED = "REJECTED"   # dropped by filter rule
    SENT     = "SENT"       # successfully delivered
    FAILED   = "FAILED"     # send failed after retries

status        = models.CharField(choices=AdStatus, default=AdStatus.PENDING, db_index=True)
filter_reason = models.CharField(max_length=200, null=True, blank=True)
sent_at       = models.DateTimeField(null=True, blank=True)
send_attempts = models.IntegerField(default=0)
```

Migration default: existing ads → `SENT` (they were already processed). New ads default to `PENDING`.

Tests: model field validation, status value coverage.

---

### Step 2 · Scraper writes `PENDING` (no behaviour change yet)

**Files:** `bazos/scraping/bazos_query_runner.py`

Set `ad.status = AdStatus.PENDING` before `ad.save()` in both `run_new_query` and
`run_existing_query`. The `send_to_senders()` call stays in place — this is a no-op change from
the user's perspective, it just starts populating the field.

**Open question — `load_full_description`:** Currently this is triggered inside the scraper loop.
It can stay there (it's still part of discovery) or move to the filter stage (if the full
description is only needed for content-based filter rules and is expensive). Decide at
implementation time.

What must stay in the scraper regardless:
- IP rotation
- Deduplication (`_is_known`)
- `QueryRun` metrics
- Discord *operational* logging (run start/end messages in `BazosRunner.log()`) — these are
  not notifications and can stay synchronous or be made fire-and-forget

Tests: existing deduplication tests still pass. Add assertion that saved ads have `status=PENDING`.

---

### Step 3 · `run_filter` command — pass-through first

**Files:**
- `bazos/filters.py` (new)
- `bazos/management/commands/run_filter.py` (new)

#### `bazos/filters.py`

```python
class FilterResult(Enum):
    APPROVE = "approve"
    REJECT  = "reject"
    PASS    = "pass"   # neutral, let next rule decide

class FilterRule(Protocol):
    name: str
    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]: ...

class RuleEngine:
    def __init__(self, rules: list[FilterRule]): ...
    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]: ...
    # First REJECT wins; if no rule rejects → APPROVE
```

#### `run_filter` polling loop

```python
while True:
    ads = (
        Ad.objects
        .select_for_update(skip_locked=True)   # safe for multiple filter workers
        .filter(status=AdStatus.PENDING)
        .select_related("query")
        .order_by("created")
        [:BATCH_SIZE]
    )
    for ad in ads:
        result, reason = engine.apply(ad)
        ad.status = AdStatus.APPROVED if result != FilterResult.REJECT else AdStatus.REJECTED
        ad.filter_reason = reason
        ad.save(update_fields=["status", "filter_reason"])
    if not ads:
        sleep(FILTER_POLL_INTERVAL)  # e.g. 30 s
```

`select_for_update(skip_locked=True)` ensures multiple filter worker processes don't
double-process the same ad.

At this stage the engine has no rules — everything is approved automatically.
Verify `PENDING → APPROVED` transitions in DB before proceeding.

Tests: `RuleEngine` unit tests with mock rules (approve-all, reject-all, first-reject-wins).

---

### Step 4 · `run_sender` command

**Files:** `bazos/management/commands/run_sender.py` (new)

Polls `APPROVED` ads, delivers them, marks `SENT` or increments `send_attempts`.
On network/rate-limit error: leave as `APPROVED` for next poll.
After `MAX_SEND_ATTEMPTS` consecutive failures → mark `FAILED`.

Key improvements over the current in-loop sender:
- **Non-blocking retries** — no `while True` inside send; DB state drives retry timing
- **Batch by webhook** — group approved ads by `query.sender` before sending, to minimise the
  number of separate webhook calls
- **Separate logging webhook path** — `BazosRunner.log()` calls (operational messages) go through
  a different code path than ad notifications and must not share the same retry counter or
  rate-limit logic with the sender process

```python
MAX_SEND_ATTEMPTS = 5

while True:
    ads = (
        Ad.objects
        .select_for_update(skip_locked=True)
        .filter(status=AdStatus.APPROVED)
        .select_related("query__sender")
        .order_by("created")
        [:BATCH_SIZE]
    )
    for ad in ads:
        try:
            DiscordSender.from_model(ad.query.sender).send_sendable([ad])
            ad.status = AdStatus.SENT
            ad.sent_at = now()
        except (URLError, HTTPError):
            ad.send_attempts += 1
            if ad.send_attempts >= MAX_SEND_ATTEMPTS:
                ad.status = AdStatus.FAILED
            # else: stay APPROVED, retry next poll
        ad.save(update_fields=["status", "sent_at", "send_attempts"])
    if not ads:
        sleep(SENDER_POLL_INTERVAL)  # e.g. 10 s
```

At this point both paths are live (scraper still calls `send_to_senders()`).
Monitor for several days before cutting over.

Tests: sender loop with mocked `DiscordSender` — success path, rate-limit retry, permanent
failure after max attempts.

---

### Step 5 · Cut over — remove direct send from scraper

**Files:** `bazos/scraping/bazos_query_runner.py`

Remove `send_to_senders()` and the `self.senders` list from `BazosQueryRunner`.
Scraper is now send-free.

Tests: assert `BazosQueryRunner` no longer instantiates `DiscordSender`.

---

### Step 6 · Add real filter rules

**Files:** `bazos/filters.py`, `bazos/models.py` (for `filter_config` field)

#### Built-in rules (simple, no new DB models needed)

| Rule | Logic |
|------|-------|
| `BlocklistKeywordRule` | Reject if name/description matches a blocked phrase |
| `PriceRangeRule` | Re-check price against `query.price_lower/upper` post-scrape |
| `PublisherBlocklistRule` | Reject if `phone_publisher` or `email_publisher` is flagged |
| `RequiredKeywordRule` | Reject if a required keyword is absent |

#### Complex / external rules (opt-in per query)

Some queries need heavy filtering (ML classification, external API lookup, Selenium screenshot).
These register as optional rules via a `Query.filter_config` JSON field and run *after* all cheap
rules:

```python
# bazos/models.py
class Query(Model):
    ...
    filter_config = JSONField(default=dict)
    # e.g. {"require_keywords": [".."], "blocklist": [".."], "enable_ml_filter": true}
```

The rule engine checks `filter_config` to decide which complex rules to instantiate for a given
query. Complex rules are only invoked if the query requests them.

Tests: each built-in rule as a pure unit test against a fabricated `Ad` (no DB needed).
Integration test: rule engine correctly skips complex rules when `filter_config` is empty.

---

### Step 7 · Sentry hookup

**Files:** `scraper/settings.py`, `pyproject.toml` (add `sentry-sdk[django]`), `.env.sample`

> Do this **after** `run_filter` and `run_sender` exist, so Sentry monitors all three processes
> from day one.

```python
# scraper/settings.py  (add after LOGGING dict)
import sentry_sdk

if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[],   # Django integration auto-detected by sentry-sdk[django]
        traces_sample_rate=0.0,  # error tracking only, no performance tracing
    )
```

Add to `.env.sample`:
```
SENTRY_DSN=  # Leave empty to disable
```

The `LOGGING` dict in `settings.py` already has the `SENTRY_DSN` env var read in place
(Step 0), so this step is just adding the SDK init and the dependency.

Sentry captures automatically:
- Unhandled exceptions in all three management commands
- The re-raised `URLError` from `DiscordSender._send` after max retries
- Any unexpected crash in the filter or sender polling loop

The Discord operational logging in `BazosRunner.log()` is **not replaced** — it stays.
Sentry = error alerting; Discord = operational heartbeat. Complementary.

**Tests:** not needed — SDK init is conditional on `SENTRY_DSN` being set, which is empty
in the test environment.

---

## What Phase 1 does NOT change

- `BazosScraper` (HTTP + HTML parsing) — untouched
- IP rotation logic — untouched
- URL generation, model constraints — untouched
- Docker Compose — no new services needed (no Redis, no Celery)
- `first_run` / `new_query` / `ignore_first_run` flags — still handled by the scraper, which
  sets the appropriate initial `status` on each ad

---

## Phase 2 — Feature Additions

**Goal:** Ship the features from Plan B that don't require marketplace abstraction.
These are independent of each other and can be done in any order after Phase 1 is complete.

---

### Step 8 · Price History

**Files:** `bazos/models.py`, `bazos/scraping/bazos_query_runner.py`, new migration

New model:

```python
class PriceChange(Model):
    ad         = ForeignKey(Ad, related_name="price_history")
    old_price  = CharField()
    new_price  = CharField()
    changed_at = DateTimeField(auto_now_add=True)
```

New status value added to `AdStatus`: `PRICE_CHANGED` — re-enters the filter/sender pipeline.

In `run_existing_query`, before breaking on a known ad, compare prices:

```python
if existing_ad.price_raw != scraped_ad.price_raw:
    PriceChange.objects.create(
        ad=existing_ad,
        old_price=existing_ad.price_raw,
        new_price=scraped_ad.price_raw,
    )
    existing_ad.price_raw = scraped_ad.price_raw
    existing_ad.status = AdStatus.PRICE_CHANGED
    existing_ad.save()
```

The filter stage treats `PRICE_CHANGED` similarly to `PENDING` but can apply different rules
(e.g. only notify if price dropped >10%).

Tests: price-change detection with a mocked scraper; `PRICE_CHANGED` ads flow through the filter
and sender processes correctly.

---

### Step 9 · Query Priority

**Files:** `bazos/models.py`, sender code, new migration

```python
class QueryPriority(models.IntegerChoices):
    LOW    = 1
    NORMAL = 2
    HIGH   = 3

class Query(Model):
    priority = IntegerField(choices=QueryPriority, default=QueryPriority.NORMAL)
```

Sender reads `ad.query.priority` when formatting the message:

| Priority | Behaviour |
|----------|-----------| 
| `HIGH` | Always include `@here` / `@everyone` ping, regardless of `Discord.notify` |
| `NORMAL` | Respect `Discord.notify` as before |
| `LOW` | Never ping, just post |

This supersedes the current binary `Discord.notify` flag for per-query control.
Existing `notify=True` webhooks map naturally to `NORMAL` — no behaviour change for existing data.

Tests: message formatting per priority level.

---

## Phase 3 — Marketplace Abstraction (deferred)

**Goal:** Add a second marketplace (Vinted) without duplicating the pipeline.
Only pursue when there is a concrete plan to ship Vinted.

Steps (from Plan B):

1. Rename `Ad.bazos_id → external_id`, add `Ad.marketplace` and `Query.marketplace` fields
2. Extract `MarketplaceScraper` Protocol; `BazosScraper` implements it implicitly
3. Runner dispatches via protocol — no hardcoded class per marketplace
4. Implement `VintedScraper` (unofficial REST API, JSON only — no BS4 needed)
5. Add Vinted queries to DB

Deduplication query changes to:
`filter(query=q, marketplace="bazos", external_id=Y)`

`EmailPublisher` / `PhonePublisher` are Bazos-specific — keep them nullable on `Ad`,
do not try to force Vinted sellers into them.

---

## What is intentionally out of scope

| Item | Reason |
|------|--------|
| Celery / Redis | Polling on PostgreSQL is simpler and sufficient for 15–45 min cadence; can migrate to Celery tasks later with minimal changes |
| Scrapy | `requests` + BS4 works fine for a single-site scraper |
| MongoDB | PostgreSQL + `JSONField` covers price history without a second DB |
| NLTK / ML classification | Premature — needs a large labelled backlog first |
| Discord bot commands | High cost, low payoff — Django admin covers the same ground |
| Heureka price comparison | Explicitly a separate project |
| Reddit / avmania / Twitter / iskam.cz | Separate project scope — each would be its own scraper |
| External uptime monitoring | Out of scope |

---

## File changes summary

### Phase 1

| File | Change |
|------|--------|
| `scraper/settings.py` | Add `LOGGING` dict + `SENTRY_DSN` env var read (Step 0 ✅); SDK init (Step 7) |
| `bazos/scraping/bazos_runner.py` | `print()` → `logging`, rename `self.loggers` → `self.discord_loggers` (Step 0 ✅) |
| `bazos/scraping/bazos_query_runner.py` | `print()` → `logging` (Step 0 ✅) |
| `bazos/scraping/bazos/bazos_scraper.py` | `print()` → `logging` (Step 0 ✅) |
| `senders/services/discord_sender.py` | `print()` → `logging` (Step 0 ✅, also already fixed retry ✅) |
| `bazos/models.py` | `AdStatus` enum, `status` / `filter_reason` / `sent_at` / `send_attempts` on `Ad` |
| new migration | default existing ads to `SENT` |
| `bazos/scraping/bazos_query_runner.py` | Set `status=PENDING` on save; then later remove `send_to_senders()` |
| `bazos/filters.py` | New: `FilterRule` protocol, `RuleEngine`, built-in rules |
| `bazos/models.py` | Add `Query.filter_config` JSONField for opt-in complex rules |
| `bazos/management/commands/run_filter.py` | New: filter polling loop |
| `bazos/management/commands/run_sender.py` | New: sender polling loop |
| `pyproject.toml` | Add `sentry-sdk[django]` (Step 7) |
| `.env.sample` | Add `SENTRY_DSN=` (Step 7) |

### Phase 2

| File | Change |
|------|--------|
| `bazos/models.py` | `PriceChange` model, `PRICE_CHANGED` status, `Query.priority` field |
| new migrations | two migrations |
| `bazos/scraping/bazos_query_runner.py` | Price-check in `run_existing_query` (Step 8) |
| sender code | Priority-aware message formatting (Step 9) |

### Phase 3

| File | Change |
|------|--------|
| `bazos/models.py` | Rename `bazos_id → external_id`, add `marketplace` field |
| new migration | data rename |
| `scraping/marketplace.py` | New: `MarketplaceScraper` Protocol |
| `bazos/scraping/bazos_scraper.py` | Add `marketplace = "bazos"` attribute |
| `scraping/vinted_scraper.py` | New: Vinted implementation |
