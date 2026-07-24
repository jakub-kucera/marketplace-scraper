# Pipeline Refactor Plan

> This is the live, authoritative stage plan for the pipeline refactor — its ✅
> checkmarks are kept in sync with the code. Superseded alternate drafts live in
> [`archive/`](./archive/). See [`docs/README.md`](../README.md) for the full doc index.
>
> Orthogonal to these stages: [`docs/bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`](../bazos-api/BAZOS_HIDDEN_API_RESEARCH.md)
> proposes replacing `BazosScraper`'s HTML scraping with Bazos's hidden JSON API —
> a change to *how* Bazos is scraped, not to this pipeline's stage sequence. Worth
> reading before starting new Bazos-scraper work.
>
> [`LLM_AD_REVIEW_DESIGN.md`](./LLM_AD_REVIEW_DESIGN.md) (proposal, not scheduled) builds
> directly on Stage 9 below (✅ done) — its §1 per-query rule registry generalizing `RuleEngine`
> is also ✅ done (`PROMPTS.md` P17, `bazos/filters.py`'s `RULE_REGISTRY`/`build_rule_engine`).
> Only the LLM-judge stage proposed to follow it remains unscheduled.

## Problem

The current architecture is a single synchronous loop:

```
scrape → deduplicate → [filter?] → send → log → sleep
```

Everything blocks everything else. Discord rate-limit retries stall scraping. Logging webhooks compete with notification webhooks. There's no place to plug in filtering without making the loop even more complex.

---

## Proposed Architecture: DB State Machine + Separate Processes

Use **PostgreSQL as the coordination layer** between three independent processes, each a Django management command.

```
┌─────────────────┐       ┌──────────────────┐       ┌────────────────┐
│  run_scraper    │  DB   │   run_filter      │  DB   │  run_sender    │
│                 │──────>│                  │──────>│                │
│  Discovers ads  │       │  Applies rules   │       │  Sends to      │
│  Saves PENDING  │       │  → APPROVED      │       │  Discord, etc  │
│                 │       │  → REJECTED      │       │  → SENT/FAILED │
└─────────────────┘       └──────────────────┘       └────────────────┘
```

**Invariant**: the scraper is fully functional (ads discovered, notifications flowing) at every step boundary.

---

## ✅ Stage 1 — Model: Ad Status State Machine

Add `status` and supporting fields to `Ad`:

```python
class AdStatus(models.TextChoices):
    PENDING       = "PENDING"       # scraped, awaiting filter
    APPROVED      = "APPROVED"      # passed filters, awaiting send
    REJECTED      = "REJECTED"      # dropped by a filter rule
    SUPPRESSED    = "SUPPRESSED"    # deliberately not sent (e.g. ignore_first_run)
    PRICE_CHANGED = "PRICE_CHANGED" # re-enters pipeline for price update notification
    SENT          = "SENT"          # successfully delivered
    FAILED        = "FAILED"        # send failed after retries
```

Additional fields on `Ad`:
- `filter_reason: str | None` — why the ad was approved or rejected (audit trail)
- `sent_at: datetime | None` — when it was delivered
- `send_attempts: int` — retry counter for the sender

Migration backfills all existing rows to `SENT` (they were already processed).

**Files**: `bazos/models.py`, `bazos/migrations/0016_ad_status_fields.py`

---

## ✅ Stage 2 — Scraper: Write Status

`BazosQueryRunner` populates the status field but **still sends directly**. No user-visible behaviour change.

1. New ads are saved with `status=PENDING`
2. `send_to_senders()` is called as before
3. After a successful send: set `status=SENT`, `sent_at=now()`

**Files**: `bazos/scraping/bazos_query_runner.py`

---

## ✅ Stage 3 — Pipeline: `run_filter` + `run_sender` + Cut-over

Introduce both new processes and remove the direct send from the scraper in one deployment.

**Deploy order**: start `run_filter` and `run_sender` first, then deploy new scraper code.

---

### ✅ 3a. `RateLimitError`

Create `senders/exceptions.py`:

```python
class RateLimitError(Exception):
    pass
```

Update `DiscordSender._send` in `senders/services/discord_sender.py`. Currently `HTTPError` retries forever in a `while True` loop. Replace with a single raise:

```python
# current (remove the loop around HTTPError):
except HTTPError as e:
    logger.warning("DiscordSender: rate limit reached, retrying")
    sleep(uniform(1, 5))

# becomes:
except HTTPError as e:
    raise RateLimitError() from e
```

The `run_sender` process owns the retry policy now — `DiscordSender` just signals the failure.

---

### ✅ 3b. Constants

Add to `bazos/const.py` (alongside existing `NEW_PRODUCT_LOAD_MAX`):

```python
FILTER_BATCH_SIZE: Final[int] = 50
FILTER_POLL_INTERVAL: Final[int] = 30   # seconds
SENDER_BATCH_SIZE: Final[int] = 50
SENDER_POLL_INTERVAL: Final[int] = 10   # seconds
MAX_SEND_ATTEMPTS: Final[int] = 5
```

---

### ✅ 3c. Filter rule design

```python
# bazos/filters.py
from enum import Enum
from typing import Protocol
from bazos.models import Ad

class FilterResult(Enum):
    APPROVE = "approve"
    REJECT  = "reject"
    PASS    = "pass"    # neutral, next rule decides

class FilterRule(Protocol):
    name: str
    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]: ...

class PassthroughRule:
    """Default rule — approves everything. Replace with real rules in Stage 9."""
    name = "passthrough"

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        return FilterResult.APPROVE, None

class RuleEngine:
    def __init__(self, rules: list[FilterRule]):
        self.rules = rules

    def apply(self, ad: Ad) -> tuple[FilterResult, str | None]:
        for rule in self.rules:
            result, reason = rule.apply(ad)
            if result != FilterResult.PASS:
                return result, reason
        return FilterResult.APPROVE, None  # default approve if no rule decides
```

---

### ✅ 3d. `run_filter` management command

`bazos/management/` and `bazos/management/commands/` directories already exist with `__init__.py` files. Create `bazos/management/commands/run_filter.py`. Use `run_scraper.py` as a structural reference for the `Command` class boilerplate.

`order_by("created")` — `created` is the auto timestamp from `TimeStampedModel` (django-extensions), not `created_at`.

`select_for_update(skip_locked=True)` must be inside `transaction.atomic()` — Django raises `TransactionManagementError` otherwise.

```python
from time import sleep
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from bazos.const import FILTER_BATCH_SIZE, FILTER_POLL_INTERVAL
from bazos.filters import FilterResult, PassthroughRule, RuleEngine
from bazos.models import Ad, AdStatus

rule_engine = RuleEngine(rules=[PassthroughRule()])

class Command(BaseCommand):
    help = "Polls PENDING ads and applies filter rules"

    def handle(self, *args, **options):
        while True:
            with transaction.atomic():
                ads = list(
                    Ad.objects
                    .select_for_update(skip_locked=True)
                    .filter(status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED])
                    .select_related("query")
                    .order_by("created")[:FILTER_BATCH_SIZE]
                )
                for ad in ads:
                    result, reason = rule_engine.apply(ad)
                    ad.status = AdStatus.APPROVED if result != FilterResult.REJECT else AdStatus.REJECTED
                    ad.filter_reason = reason
                    ad.save(update_fields=["status", "filter_reason"])

            if not ads:
                sleep(FILTER_POLL_INTERVAL)
```

Note: `ads` must be evaluated inside `atomic()` (hence `list(...)`) so the `select_for_update` lock is held for the duration of the updates.

---

### ✅ 3e. `run_sender` management command

Create `bazos/management/commands/run_sender.py`:

```python
from time import sleep
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from bazos.const import MAX_SEND_ATTEMPTS, SENDER_BATCH_SIZE, SENDER_POLL_INTERVAL
from bazos.models import Ad, AdStatus
from senders.exceptions import RateLimitError
from senders.services.discord_sender import DiscordSender

class Command(BaseCommand):
    help = "Polls APPROVED ads and delivers them"

    def handle(self, *args, **options):
        while True:
            with transaction.atomic():
                ads = list(
                    Ad.objects
                    .select_for_update(skip_locked=True)
                    .filter(status=AdStatus.APPROVED)
                    .select_related("query__sender")
                    .order_by("created")[:SENDER_BATCH_SIZE]
                )
                for ad in ads:
                    try:
                        sender = DiscordSender.from_model(ad.query.sender)
                        sender.send_sendable([ad])
                        ad.status = AdStatus.SENT
                        ad.sent_at = now()
                    except RateLimitError:
                        ad.send_attempts += 1
                        if ad.send_attempts >= MAX_SEND_ATTEMPTS:
                            ad.status = AdStatus.FAILED
                        # else: leave as APPROVED, retried next poll
                    ad.save(update_fields=["status", "sent_at", "send_attempts"])

            if not ads:
                sleep(SENDER_POLL_INTERVAL)
```

---

### ✅ 3f. Scraper cut-over (`bazos_query_runner.py`)

Remove `_send_and_mark_sent`, `send_to_senders`, and the `senders` list from `BazosQueryRunner`. Remove the `DiscordSender` import. `_handle_new_product` becomes:

```python
def _handle_new_product(self, product: Ad):
    logger.info("New product %s", product)
    self.new_product_counter += 1
    product.status = AdStatus.PENDING
    product.save()
    if self.query.load_full_description:
        self.scraper.load_full_description(product)
        product.save()
```

The scraper now only discovers and saves. All notification is handled by `run_filter` + `run_sender`.

Current state of `_handle_new_product` for reference (Stage 2):

```python
def _handle_new_product(self, product: Ad):
    logger.info("New product %s", product)
    self.new_product_counter += 1
    product.status = AdStatus.PENDING
    product.save()
    self._send_and_mark_sent(product)   # ← remove this and the two methods it calls
    if self.query.load_full_description:
        self.scraper.load_full_description(product)
        product.save()
```

---

**Files**: `senders/exceptions.py` (new), `bazos/filters.py` (new), `bazos/management/commands/run_filter.py` (new), `bazos/management/commands/run_sender.py` (new), `bazos/const.py`, `bazos/scraping/bazos_query_runner.py`, `senders/services/discord_sender.py`

---

## ✅ Stage 4 — Enrichment: Price History

Track price changes on already-known ads. Scraper re-enters the pipeline for changed prices.

### 4a. Add `PRICE_CHANGED` to `AdStatus`

Add to the `AdStatus` enum in `bazos/models.py` and generate a migration:

```python
PRICE_CHANGED = "PRICE_CHANGED"  # re-enters pipeline for price update notification
```

### 4b. New `PriceChange` model

```python
class PriceChange(TimeStampedModel):
    ad        = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.CharField(max_length=30)
    new_price = models.CharField(max_length=30)
```

Use `TimeStampedModel` (already the base for `Ad`) so `created` / `modified` are available for free. No need for an explicit `changed_at` field.

### 4c. Refactor `_is_known` → `_get_known`

Currently `_is_known(product) -> bool`. Price comparison requires the actual DB object, so refactor to:

```python
def _get_known(self, product: Ad) -> Ad | None:
    return Ad.objects.filter(query=self.query, bazos_id=product.bazos_id).first()
```

Update `run_existing_query` accordingly:

```python
def run_existing_query(self):
    for product in self.scraper.run_query(self.query):
        existing = self._get_known(product)
        if existing is None:
            product.query = self.query
            self._handle_new_product(product)
        else:
            if existing.price_raw != product.price_raw:
                PriceChange.objects.create(
                    ad=existing,
                    old_price=existing.price_raw,
                    new_price=product.price_raw,
                )
                existing.price_raw = product.price_raw
                existing.status = AdStatus.PRICE_CHANGED
                existing.save(update_fields=["price_raw", "status"])
            logger.debug("Product already exists %s", existing)
            if product.topped:
                logger.debug("TOP product — continuing")
            else:
                logger.debug("Regular product — breaking")
                break
```

`run_filter` already polls `PRICE_CHANGED` (Stage 3 loop). The filter and sender can treat price-change ads differently — different message format, different rules (e.g. `PriceDropRule` in Stage 9).

**Files**: `bazos/models.py`, new migration, `bazos/scraping/bazos_query_runner.py`

---

## Stage 5 — Enrichment: Query Priority

### 5a. Model

```python
class QueryPriority(models.IntegerChoices):
    LOW    = 1
    NORMAL = 2
    HIGH   = 3

class Query(Model):
    priority = models.IntegerField(choices=QueryPriority.choices, default=QueryPriority.NORMAL)
```

### 5b. How priority flows into `DiscordSender`

`run_sender` currently calls `DiscordSender.from_model(ad.query.sender)`, which sets `self.notify` from the `Discord` webhook model (`Discord.notify` is a DB flag). Priority lives on `Query`, not on `Discord`.

Pass priority as an argument to `send_sendable` — keep `DiscordSender` stateless with respect to priority:

```python
# run_sender loop change:
sender.send_sendable([ad], priority=ad.query.priority)

# DiscordSender:
def send_sendable(self, sendables: list[Sendable], priority: int = QueryPriority.NORMAL):
    for s in sendables:
        self._send(self._format_product_message(s, priority))

def _format_product_message(self, sendable: Sendable, priority: int) -> str:
    ping = ""
    if priority == QueryPriority.HIGH:
        ping = "@here \n"
    elif priority == QueryPriority.NORMAL and self.notify:
        ping = "@here \n"
    # LOW → no ping
    message = ping + self.wrap_multi_line(sendable.message)
    message += self._format_link(sendable.link)
    return message
```

Import `QueryPriority` from `bazos.models` in `senders/services/discord_sender.py`.

**Files**: `bazos/models.py`, new migration, `bazos/management/commands/run_sender.py`, `senders/services/discord_sender.py`

---

## ✅ Stage 6 — Marketplace Abstraction: Rename + Fields

Purely additive migration — no behaviour change.

### 6a. Model changes

- `migrations.RenameField(model_name='ad', old_name='bazos_id', new_name='external_id')` — Django handles the column rename cleanly, no manual data migration needed.
- Add `Ad.marketplace = models.CharField(max_length=20, default="bazos")`
- Add `Query.marketplace = models.CharField(max_length=20, default="bazos")`

`EmailPublisher` / `PhonePublisher` remain Bazos-specific and nullable for Vinted ads.

### 6b. `BazosScraper.extract_product`

`extract_product` in `bazos/scraping/bazos/bazos_scraper.py` constructs `Ad` objects. Add `marketplace` there:

```python
return Ad(
    external_id=parsed['bazos_id'],  # field renamed
    marketplace="bazos",             # new field
    ...
)
```

### 6c. `_get_known` filter update

After the rename, `_get_known` in `bazos_query_runner.py` becomes:

```python
def _get_known(self, product: Ad) -> Ad | None:
    return Ad.objects.filter(
        query=self.query,
        marketplace=product.marketplace,
        external_id=product.external_id,
    ).first()
```

**Files**: `bazos/models.py`, new migration, `bazos/scraping/bazos/bazos_scraper.py`, `bazos/scraping/bazos_query_runner.py`

---

## ✅ Stage 7 — Marketplace Abstraction: Protocol + SendableMixin

Structural refactor only — no behaviour change.

### 7a. `MarketplaceScraper` protocol

Create `scraping/marketplace.py`:

```python
from typing import Iterator, Protocol
from bazos.models import Ad, Query

class MarketplaceScraper(Protocol):
    marketplace: str
    def run_query(self, query: Query) -> Iterator[Ad]: ...
    def load_full_description(self, ad: Ad) -> str: ...
    def check_blacklisted(self) -> bool: ...
```

`BazosScraper` already satisfies this interface — no changes to it needed, just update type annotations in the runner.

Runner dispatch (in `BazosRunner` / `BazosQueryRunner`): select scraper based on `query.marketplace`:

```python
SCRAPERS: dict[str, MarketplaceScraper] = {
    "bazos": BazosScraper(session),
    # "vinted": VintedScraper(session),  # added in Stage 8
}
scraper = SCRAPERS[query.marketplace]
```

### 7b. Replace `SendableMixin` with `Sendable` Protocol

Current `bazos/mixins.py`:

```python
class SendableMixin(Model):
    class Meta:
        abstract = True

    @property
    def message(self):
        raise NotImplementedError

    @property
    def link(self):
        raise NotImplementedError
```

Replace with a Protocol in `bazos/protocols.py` (or `scraping/marketplace.py`):

```python
class Sendable(Protocol):
    @property
    def message(self) -> str: ...
    @property
    def link(self) -> str: ...
```

`Ad` already implements `message` and `link` — remove `SendableMixin` from its inheritance. Update all sites that reference `SendableMixin`:

- `DiscordSender.send_sendable(self, sendables: list[SendableMixin])` → `list[Sendable]`
- `DiscordSender._format_product_message(self, sendable: SendableMixin)` → `Sendable`
- `senders/services/sender.py` if it references `SendableMixin`

Delete `bazos/mixins.py` once all references are removed.

**Files**: `scraping/marketplace.py` (new), `bazos/protocols.py` (new), `bazos/models.py`, `bazos/mixins.py` (delete), `bazos/scraping/bazos_runner.py`, `bazos/scraping/bazos_query_runner.py`, `senders/services/discord_sender.py`

---

## Stage 8 — VintedScraper

New scraper behind the `MarketplaceScraper` interface. Vinted has an unofficial REST JSON API — no BeautifulSoup needed.

📄 **Full design & decision log**: [STAGE8_VINTED_DESIGN.md](./STAGE8_VINTED_DESIGN.md)

### Key decisions (summary)

- **Library**: `vinted-scraper` v3.1.1 (Giglium) — handles cookie management automatically.
- **Tor / session**: Vinted bans proxies. `VintedScraper` ignores the Tor session and manages its own.
- **Query model**: Option C — keep one `Query` table, add `extra_params = JSONField(default=dict)`. Vinted-specific search params (e.g. `catalog_ids`) go in `extra_params`. The `section`/`category` FKs remain Bazos-only and are `null` for Vinted queries.
- **`url` property**: returns `https://www.vinted.cz` (or whichever domain is in `extra_params["base_url"]`) when `marketplace="vinted"`.
- **Publisher FKs**: `EmailPublisher` / `PhonePublisher` will be `null` for Vinted ads — Vinted doesn't expose contact info.
- **`topped`**: always `False` for Vinted (no promoted-listing concept in the search API).

### Open questions (see design doc)

- Czech (`vinted.cz`) vs Slovak (`vinted.sk`) domain — per-query or Django setting?
- Stopping logic for existing queries — Vinted has no `topped` equivalent to skip over.
- Rate-limiting back-off strategy.

**Files**: `bazos/scraping/vinted/vinted_scraper.py` (new), `bazos/models.py`, migration `0019_query_extra_params`

---

## ✅ Stage 9 — Real Filter Rules

With the Stage 3 plumbing proven, implement actual rules.

### 9a. `price_raw` parsing

`price_raw` is a raw string scraped from Bazos. Possible values include `"1 000 Kč"`, `"Dohodou"`, `"V textu"`, `"Nabídněte"`. `PriceRangeRule` and `PriceDropRule` need to parse it. Recommended approach:

```python
import re

def parse_price(price_raw: str) -> int | None:
    """Returns price as integer CZK, or None if non-numeric (Dohodou, V textu, etc.)."""
    digits = re.sub(r'\D', '', price_raw)
    return int(digits) if digits else None
```

Rules that depend on a numeric price should return `FilterResult.PASS` (not `REJECT`) when `parse_price` returns `None` — non-numeric prices can't be range-checked.

### 9b. Keyword storage

Add JSON fields to `Query` for per-query keyword config (requires a migration):

```python
class Query(Model):
    filter_blocklist  = models.JSONField(default=list, blank=True)  # ["spamer", "vadne"]
    filter_required   = models.JSONField(default=list, blank=True)  # ["macbook", "apple"]
```

`BlocklistKeywordRule` and `RequiredKeywordRule` read `ad.query.filter_blocklist` / `ad.query.filter_required`. Empty list → rule returns `PASS`.

### 9c. Publisher blocklist

Add a `blocked` flag to `EmailPublisher` and `PhonePublisher` (requires a migration):

```python
class PhonePublisher(TimeStampedModel):
    blocked = models.BooleanField(default=False)

class EmailPublisher(TimeStampedModel):
    blocked = models.BooleanField(default=False)
```

`PublisherBlocklistRule` rejects if `ad.email_publisher.blocked` or `ad.phone_publisher.blocked`. Mark spammers via Django admin.

### 9d. Rule implementations

| Rule | Logic | Returns `PASS` when |
|------|-------|---------------------|
| `PriceRangeRule` | Reject if parsed price outside `query.price_lower/upper` | price is non-numeric, or `price_lower == price_upper == 0` (no range set) |
| `BlocklistKeywordRule` | Reject if `name` or `short_description` contains any blocked phrase | `filter_blocklist` is empty |
| `RequiredKeywordRule` | Reject if `name` and `short_description` contain none of the required keywords | `filter_required` is empty |
| `PublisherBlocklistRule` | Reject if either publisher is flagged | publisher FK is null |
| `PriceDropRule` | For `PRICE_CHANGED` ads only: reject if price didn't drop | `ad.status != PRICE_CHANGED` |

**Files**: `bazos/filters.py`, `bazos/models.py`, new migration

**Done** (2026-07-24): all five rules are implemented in `bazos/filters.py` exactly as
above, wired into `run_filter`'s `RuleEngine` in place of `PassthroughRule`
(`PassthroughRule` itself stays in `filters.py` as a no-op baseline, used only by tests
now). Migration `0021_emailpublisher_blocked_phonepublisher_blocked_and_more.py` adds
`Query.filter_blocklist`/`filter_required` and `EmailPublisher.blocked`/`PhonePublisher.blocked`.
Admin exposes `blocked` (list_display/list_filter + block/unblock actions on both
publisher admins); `Query`'s new JSON fields show on the default change form since
`QueryAdmin` sets no restrictive `fields`/`fieldsets`. Unit tests in `bazos/tests/test_filters.py`.

---

## Migration Path (implementation steps)

Each step is independently deployable. The scraper remains fully functional throughout.

### ✅ Step 1: Add `Ad.status` fields
`AdStatus` enum + `status`, `filter_reason`, `sent_at`, `send_attempts` on `Ad`. Backfill existing rows to `SENT`.

### ✅ Step 2: Scraper writes status
Set `status=PENDING` on save, `status=SENT` + `sent_at` after a successful send. No change in notification behaviour.

### ✅ Step 3: Deploy filter + sender, cut over scraper
Start `run_filter` (PassthroughRule) and `run_sender`. Deploy scraper without `send_to_senders()`. Scraper is now send-free.

### ✅ Step 4: Add `PriceChange` model
Price-change detection in the dedup loop; `PRICE_CHANGED` re-enters the filter/sender pipeline.

### Step 5: Add `Query.priority`
Priority-aware message formatting in `run_sender`.

### ✅ Step 6: Rename `bazos_id → external_id`, add `marketplace`
Data migration on `Ad` and `Query`. BazosScraper sets `marketplace="bazos"`.

### ✅ Step 7: Extract protocols (`MarketplaceScraper`, `Sendable`)
Structural refactor — no behaviour change.

### Step 8: Implement `VintedScraper`
New scraper behind the shared interface. Add Vinted queries.

### ✅ Step 9: Add real filter rules
Replace `PassthroughRule` with actual rule implementations.

---

## What This Does NOT Change

- `BazosScraper` (HTTP + parsing) — untouched until Step 7
- IP rotation logic — untouched
- URL generation, model constraints — untouched
- Docker Compose infrastructure — no new services needed
- The `first_run` / `new_query` / `ignore_first_run` flags — still handled by scraper
