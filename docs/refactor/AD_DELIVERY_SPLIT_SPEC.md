# `Ad` / `AdDelivery` split — implementation spec

> Executable expansion of [`BACKLOG_IDEAS.md`](BACKLOG_IDEAS.md) #1, **Option B**. The option
> analysis is settled — do not re-open it. This document is the *how*.
>
> **Grounded against the code on 2026-08-21** (HEAD `2fb37f8`). Line references and field lists
> were read from the tree, not from memory.
>
> **⚠️ Status, 2026-08-22: all four stages have landed** — `0026_addelivery.py` (Stage A),
> Stage B's reader/writer moves (no migration — `run_filter`/`run_sender`/
> `bazos_query_runner`/`admin.py` all read/write `AdDelivery` now), `0027_merge_duplicate_ads.py`
> (Stage C), and `0028_drop_ad_pipeline_fields.py` (Stage D — `Ad.status`/`filter_reason`/
> `sent_at`/`send_attempts`/`query` no longer exist on `Ad` at all). Full suite green, `ruff
> check .` and `mypy .` clean, verified against a fresh `migrate` from zero.
>
> **A post-merge review (`PROMPTS.md` P26) found one BLOCKER and several real defects, since
> fixed** — an interrupted first run of a `new_query` used to wedge that query permanently
> (`run_new_query` created `AdDelivery` rows without checking for an existing one, unlike
> `run_existing_query`), migration `0028` was never safely reversible on a populated table (now
> documented in its own docstring and §7 below, not "fixed" — there's nothing to fix), and
> `load_full_description` was gated on the wrong condition. See P26 for the full list, including
> what was deliberately left as a follow-up rather than folded in here. Verify against the tree
> rather than trusting this banner.

---

## 0. Read this first — scope, risk, and how to not break production

This is **the largest single item in the backlog** — `BACKLOG_IDEAS.md` calls it "bigger than any
existing stage in `PIPELINE_REFACTOR.md`", and that is accurate. It touches every consumer of
`Ad.status` / `filter_reason` / `sent_at` / `send_attempts` / `query`:

| Consumer | File |
|---|---|
| Scrape-time dedup + price-change detection | `bazos/scraping/bazos_query_runner.py` |
| Filter stage | `bazos/management/commands/run_filter.py` |
| Send stage | `bazos/management/commands/run_sender.py` |
| All five filter rules | `bazos/filters.py` |
| Admin (`AdAdmin`, `QueryAdmin.ad_count`) | `bazos/admin.py` |
| Tests | `test_deduplication.py` (70 hits), `test_run_sender.py` (44), `test_filters.py` (30), `test_run_filter.py` (29), `test_models.py` (14), `test_admin.py` (7) |

**Rules for doing this safely:**

1. **Four stages, four PRs, four migrations. Do not collapse them.** Each stage below leaves the
   system working and shippable on its own.
2. **Stage C mutates production data irreversibly.** Take a manual backup immediately before
   deploying it: `sudo systemctl start marketplace-backup.service` (or
   `docker compose run --rm backup`), and confirm the dump exists before running `migrate`.
   Backups landed in `1cb0178`; this is the first change that really needs them.
3. **No dual-write phase is needed.** `deploy.yml` does `docker compose down` → `migrate` →
   `up -d`, so old and new code never run concurrently. Do not build dual-write scaffolding —
   it buys nothing here and doubles the surface area.
4. Stage C is the one a human should read line by line before it runs. Stages A, B, D are
   mechanical.

---

## 1. The problem, grounded

`Ad.query` is a single FK (`models.py`, in the `Ad` block), and `BazosQueryRunner._get_known`
scopes its existence check to `query=self.query`:

```python
    def _get_known(self, product: Ad) -> Ad | None:
        return Ad.objects.filter(
            query=self.query,
            marketplace=product.marketplace,
            external_id=product.external_id,
        ).first()
```

So two `Query` rows matching the same real-world listing create **two `Ad` rows** with the same
`(marketplace, external_id)`. Consequences:

- Duplicate Discord notifications, one per matching query.
- Duplicate `load_full_description` fetches when both queries set that flag.
- **Every statistic over `Ad` is silently double-counted** — which is why this is a precondition
  for the analytics direction and for broad category sweeps, not a nicety.
- No row answers "have I ever seen this listing", so price history, repost detection and
  delisting all rest on an identity that doesn't exist.

The `TODO`s at `Ad.external_id` ("requires M:N to queries") and above `Ad.query`
("TODO m:n relationship with Query (+ senders)") are this task.

---

## 2. Target shape

```
Ad          — scraped FACTS about a real-world listing. Globally unique on
              (marketplace, external_id). Updated in place on rediscovery.

AdDelivery  — one row per (ad, query). Owns the pipeline state machine.
              This is what run_filter and run_sender operate on.
```

| Field | After the split |
|---|---|
| `external_id`, `marketplace`, `url`, `name`, `price_raw`, `location`, `view_count`, `publish_date`, `topped`, `short_description`, `full_description`, `publisher_name`, `email_publisher`, `phone_publisher` | stay on **`Ad`** |
| `status`, `filter_reason`, `sent_at`, `send_attempts` | move to **`AdDelivery`** |
| `query` | moves to **`AdDelivery`** (this is the M:N through-table) |
| `PriceChange.ad` FK | stays pointing at **`Ad`** — a price change is a fact about the listing, not about one query's interest in it |

---

## 3. Semantic decisions already made — do NOT re-derive these

These are the six places where a plausible-looking choice is wrong. They are decided.

### 3.1 The dedup break keys on the **delivery**, not on global `Ad` existence

`run_existing_query` walks results newest→oldest and breaks on the first *known* non-topped ad.
After the split, "known" must mean **"this query already has an `AdDelivery` for it"**, not "an
`Ad` row exists".

If you key the break on global `Ad` existence, a brand-new query breaks on page 1 the moment any
*other* query has already seen that listing, and never backfills. This is the single most likely
way to silently break the scraper. It must be an `AdDelivery` lookup scoped to `self.query`.

### 3.2 A price change flips **every** delivery of that ad

A price change is a fact about the `Ad`, so every query watching that listing must re-enter the
filter. Today's code does `existing.status = AdStatus.PRICE_CHANGED` on the single per-query row;
the equivalent is now an update across all deliveries of that ad.

**Preserve today's behaviour exactly, including the parts that look wrong.** Today the flip is
unconditional — it will move a `SUPPRESSED` delivery to `PRICE_CHANGED`, un-suppressing an ad that
`ignore_first_run` deliberately silenced. Keep that. This is a structural refactor; do not smuggle
in a behaviour fix. Record it as a follow-up instead (see §9).

### 3.3 Filter rules take an `AdDelivery`, not an `Ad`

Three of the five shipped rules read `ad.query` (`PriceRangeRule`, `BlocklistKeywordRule`,
`RequiredKeywordRule`) and one reads `ad.status` (`PriceDropRule`). Both attributes leave `Ad`.
So `FilterRule.apply` changes signature:

```python
    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]: ...
```

Rules then read `delivery.ad.name`, `delivery.query.filter_blocklist`, `delivery.status`, and
`delivery.ad.price_history`. `PublisherBlocklistRule` only needs `delivery.ad`. `PassthroughRule`
is test-only and is not wired into `run_filter` — update it anyway so the protocol stays honest.

### 3.4 Row locking moves to `AdDelivery`

`run_filter` and `run_sender` must `select_for_update(skip_locked=True, of=("self",))` against
**`AdDelivery`**. Keep `of=("self",)` — both commands `select_related`, and without it the joined
`Ad` / `Query` / publisher rows get locked too. Note the tests run on SQLite, which silently drops
`select_for_update` from the SQL, so this is **not** covered by the suite — get it right by reading.

### 3.5 `Sendable` stays on `Ad`

`bazos/protocols.py`'s `Sendable` (`.message`, `.link`) is implemented by `Ad` and stays there.
`run_sender` sends `delivery.ad`, and reads its channel from `delivery.query.sender`.

Note `Ad.message` embeds `seller_ad_counts().summary`, which fires several `COUNT` queries — the
existing warning about never calling `.message` in a loop over a large queryset still applies, and
the batch size (`SENDER_BATCH_SIZE = 50`) is what keeps it acceptable.

### 3.6 `on_delete` choices

- `AdDelivery.ad` → `CASCADE`. A delivery is meaningless without its listing.
- `AdDelivery.query` → `PROTECT`. This preserves today's behaviour, where `Ad.query`'s `PROTECT`
  stops a `Query` with ads from being deleted.

---

## 4. Stage A — add the model and backfill (PR 1, inert)

**Nothing changes behaviourally.** After this PR the app still reads and writes `Ad.status`.

### 4.1 The model

Add to `bazos/models.py`, after `Ad`:

```python
class AdDelivery(TimeStampedModel):
    """One query's interest in one ad, and the delivery state machine for it.

    Split out from `Ad` because delivery is a property of (ad, query, sender): the same
    real-world listing matching two queries must notify both channels. `Ad` holds the
    scraped facts; this holds everything the pipeline does about them.
    """
    ad = models.ForeignKey(Ad, on_delete=models.CASCADE, related_name="deliveries")
    query = models.ForeignKey(Query, on_delete=models.PROTECT, related_name="deliveries")

    status = models.CharField(
        max_length=20, choices=AdStatus.choices, default=AdStatus.PENDING, db_index=True
    )
    filter_reason = models.CharField(max_length=255, null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    send_attempts = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Ad delivery"
        verbose_name_plural = "Ad deliveries"
        constraints = [
            models.UniqueConstraint(fields=["ad", "query"], name="unique_delivery_per_ad_query"),
        ]

    def __str__(self):
        return f"{self.ad} → {self.query} [{self.status}]"
```

`db_index=True` on `status` is deliberate: both pipeline stages poll on it every few seconds.

### 4.2 The migration

Two migrations, or one with two operations — either is fine, but the backfill must be a separate
`RunPython` operation that runs **after** `CreateModel`:

```python
def backfill_deliveries(apps, schema_editor):
    Ad = apps.get_model("bazos", "Ad")
    AdDelivery = apps.get_model("bazos", "AdDelivery")

    batch = []
    for ad in Ad.objects.all().iterator(chunk_size=1000):
        batch.append(AdDelivery(
            ad_id=ad.pk,
            query_id=ad.query_id,
            status=ad.status,
            filter_reason=ad.filter_reason,
            sent_at=ad.sent_at,
            send_attempts=ad.send_attempts,
            created=ad.created,
            modified=ad.modified,
        ))
        if len(batch) >= 1000:
            AdDelivery.objects.bulk_create(batch)
            batch = []
    if batch:
        AdDelivery.objects.bulk_create(batch)
```

- Use `.iterator(chunk_size=1000)` — the production table is tens of thousands of rows.
- Copy `created`/`modified` from the `Ad`. Both stages `order_by("created")`, so inheriting the
  ad's timestamp preserves queue ordering exactly. `TimeStampedModel`'s `auto_now_add` would
  otherwise stamp every backfilled row with the migration time and scramble the order.
- Provide a `reverse_code` that deletes all `AdDelivery` rows, so the migration is reversible.

**Migration number:** resolved — this landed as **`0026_addelivery.py`**, with Stage C as
**`0027_merge_duplicate_ads.py`**. The number was briefly contested with
[`STAGE8_VINTED_SPEC.md`](STAGE8_VINTED_SPEC.md) §2.4, which now takes `0028`. That spec had
claimed Vinted needed to land first; it didn't — see the correction recorded there.

### 4.3 Tests for Stage A

- `test_backfill_creates_one_delivery_per_ad` — migration test in the style of
  `bazos/tests/test_sentinel_publisher_migration.py`.
- `test_backfill_copies_pipeline_state` — status, filter_reason, sent_at, send_attempts, created.
- `test_unique_delivery_per_ad_query_constraint` — a second `AdDelivery` for the same
  `(ad, query)` raises `IntegrityError`.

---

## 5. Stage B — move every reader and writer (PR 2)

The behavioural PR. `Ad` still has its old columns and still has `query`; they are simply no
longer read. Duplicate `Ad` rows still exist — each just has exactly one delivery, so the system
behaves exactly as it does today.

### 5.1 `bazos/scraping/bazos_query_runner.py`

Replace `_get_known` with two distinct lookups — they answer different questions (see §3.1):

```python
    def _get_known_delivery(self, product: Ad) -> AdDelivery | None:
        """Has THIS query already seen this listing? Keys the dedup break."""
        return (
            AdDelivery.objects
            .filter(
                query=self.query,
                ad__marketplace=product.marketplace,
                ad__external_id=product.external_id,
            )
            .select_related("ad")
            .first()
        )

    def _get_or_create_ad(self, product: Ad) -> Ad:
        """Global listing identity, shared across queries."""
        existing = Ad.objects.filter(
            marketplace=product.marketplace, external_id=product.external_id
        ).first()
        if existing is not None:
            return existing
        product.save()
        return product
```

`_handle_new_product` becomes: resolve/create the `Ad`, then create the `AdDelivery` for this
query, then optionally fetch the full description **only when the `Ad` was newly created** (a
second query rediscovering a known listing must not re-pay for the detail request).

`run_existing_query`'s loop keys on `_get_known_delivery`. When a delivery exists, compare
`delivery.ad.price_raw` against the freshly scraped `product.price_raw`, and on a difference:

```python
                    PriceChange.objects.create(
                        ad=known_ad, old_price=known_ad.price_raw, new_price=product.price_raw
                    )
                    known_ad.price_raw = product.price_raw
                    known_ad.save(update_fields=["price_raw"])
                    # A price change is a fact about the AD — every query watching it re-enters
                    # the filter. Unconditional, matching today's behaviour (see spec §3.2).
                    AdDelivery.objects.filter(ad=known_ad).update(status=AdStatus.PRICE_CHANGED)
```

`run_new_query`'s `ignore_first_run` branch sets `SUPPRESSED` on the **delivery**, not the ad.

`rows_seen_counter` / `new_product_counter` (P19) stay exactly as they are.

### 5.2 `bazos/filters.py`

Change `FilterRule.apply` and all five rules plus `PassthroughRule` to take `delivery: AdDelivery`
per §3.3. `build_rule_engine(query)` keeps its signature — the caller now passes `delivery.query`.

### 5.3 `run_filter` and `run_sender`

Both switch their queryset to `AdDelivery`:

```python
                deliveries = list(
                    AdDelivery.objects
                    .select_for_update(skip_locked=True, of=("self",))
                    .filter(status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED])
                    .select_related("ad", "query", "ad__email_publisher", "ad__phone_publisher")
                    .order_by("created")[:FILTER_BATCH_SIZE]
                )
```

`run_sender` uses `.filter(status=AdStatus.APPROVED).select_related("ad", "query__sender")`, sends
`[delivery.ad]`, and writes `status` / `sent_at` / `send_attempts` on the delivery.

Keep the `if not deliveries: sleep(...)` idle behaviour and the `update_fields=[...]` saves.

### 5.4 `bazos/admin.py`

- Register `AdDeliveryAdmin` — `list_display` of ad, query, status, filter_reason, sent_at,
  send_attempts, created; `list_filter` on status, query; this becomes the pipeline view.
- Add an `AdDeliveryInline` to `AdAdmin` (alongside the existing `PriceChangeInline`).
- Remove `status` from `AdAdmin.list_display` / `list_filter`, and `status`, `filter_reason`,
  `sent_at`, `send_attempts` from `readonly_fields`. **Leave `query` in place until Stage D.**
- `QueryAdmin.get_queryset` annotates `ad_count=Count('ads', distinct=True)`. Change to
  `Count('deliveries', distinct=True)`. **Keep `distinct=True`** — the comment in that method
  explains why: it aggregates over a second multi-valued relation alongside `Max('runs__...')`,
  and the joins multiply rows.

### 5.5 Tests for Stage B

This is the bulk of the churn. Mechanical but large: `test_deduplication.py`, `test_run_filter.py`,
`test_run_sender.py`, `test_filters.py`, `test_admin.py`. Add these **new** cases, which pin the
behaviour the split exists to fix:

- `test_two_queries_matching_one_listing_create_one_ad_and_two_deliveries`
- `test_second_query_rediscovering_a_known_ad_does_not_refetch_full_description`
- `test_price_change_flips_every_delivery_of_that_ad`
- `test_new_query_backfills_even_when_another_query_already_knows_the_ad` — §3.1's failure mode
- `test_dedup_break_still_stops_on_first_known_non_topped_ad_for_this_query`

---

## 6. Stage C — merge duplicate `Ad` rows, add the unique constraint (PR 3) ⚠️

**This is the irreversible one. Back up first (see §0).**

A data migration that, for each `(marketplace, external_id)` group with more than one `Ad`:

1. Picks the **lowest `pk`** as canonical (first discovered).
2. Repoints `AdDelivery.ad` and `PriceChange.ad` at the canonical row.
3. Deletes the duplicates.
4. Logs counts: groups merged, rows deleted, delivery collisions resolved.

**The collision case you must handle:** two duplicate `Ad` rows could each have a delivery for the
*same* query (shouldn't happen, but the data is years old and has already produced one surprise —
see the `bazos_id=0` sentinel in migration `0025`). Repointing both would violate
`unique_delivery_per_ad_query`. Rule: **keep the lowest-pk delivery, delete the other, and log it.**
Deterministic and boring beats clever here.

**Accepted consequence, log it rather than solving it:** the canonical row's `price_raw` may be
staler than a duplicate's. Do not try to merge field-by-field across duplicates — the ads all get
re-scraped on the next pass anyway. Log how many merges had differing `price_raw` so the size of
the effect is known.

Then, in the same migration and **after** the merge, add:

```python
        models.UniqueConstraint(fields=["marketplace", "external_id"], name="unique_ad_per_marketplace"),
```

to `Ad.Meta.constraints`. Not `unique=True` on `external_id` alone — different marketplaces reuse ids.

**Tests:** duplicates merged to one; deliveries and price history repointed; the collision rule;
idempotency when the migration runs twice; the constraint rejects a new duplicate afterwards.

**Before deploying:** run the merge read-only against a restored copy of the production dump and
report the counts. If the number of merged groups is surprisingly large, stop and investigate
before running it for real.

---

## 7. Stage D — drop the dead columns (PR 4)

Remove from `Ad`: `status`, `filter_reason`, `sent_at`, `send_attempts`, `query`.

Known breakages to fix in the same PR:

- `AdAdmin.list_display` and `list_filter` still reference `query` — replace with a
  `query_count`/deliveries display, or filter through `deliveries__query`.
- Any publisher-admin link that builds a filtered `Ad` changelist on `query`.
- `HasFullDescriptionFilter` is unaffected (it reads `full_description`).
- `bazos/migrations/0016_ad_status_fields.py` does `Ad.objects.all().update(status='SENT')`. It is
  a historical migration operating on a historical model state — **do not edit it.** If it breaks
  under a fresh `migrate` from zero, that means it is using the real model instead of
  `apps.get_model`; fix it that way, not by deleting the migration.

⚠️ **This migration is not safely reversible on a populated database, and there is no fix for
that — only honesty about it.** `RemoveField`'s auto-reverse is `AddField` with the *original*
field definition; `query` was a non-null FK with no default, so reversing against any table with
existing `Ad` rows raises `IntegrityError: NOT NULL constraint failed` (confirmed against both
SQLite and Postgres — the test suite doesn't catch this because the test `Ad` table is empty at
rollback time). There's no default to backfill `query_id` with even if Django could ask for
one: Stage C already deleted the duplicate rows that carried the alternate `query` values, so
that data is gone as of `0027`, not `0028` — this migration only makes the loss visible by being
the first to touch the column. **Do not attempt a `migrate`-based rollback of a deployed Stage D
against production** — see §0's backup instruction and `docs/BACKUPS.md` §9; restore-from-dump is
the only recovery path once this has run against real data.

Full-suite green plus `ruff check .` and `mypy .` is the gate.

---

## 8. Verification (every stage)

```bash
pytest
ruff check .
mypy .
```

Plus, for Stage C only, the read-only dry run against a restored production dump.

---

## 9. Explicitly out of scope — do not do these here

- **Do not fix the `SUPPRESSED` → `PRICE_CHANGED` un-suppression** (§3.2). Real bug, separate PR,
  needs its own decision about whether a suppressed backfill ad should ever re-notify.
- **Do not add `AdOutcome`** (`BACKLOG_IDEAS.md` #9). Different model, different purpose.
- **Do not change `Ad.message` / notification formatting.** That is P11 and P16.
- **Do not add a `sender` FK to `AdDelivery`.** The sender is reachable via `delivery.query.sender`
  today; a per-delivery sender override is a feature, not part of this refactor.
- **Do not touch `PriceChange`'s schema.** Migrating its `CharField` prices is P22.
- **Do not attempt Stages A–D in one PR**, and do not deploy Stage C without a fresh backup.
