---
title: Refactor Suggestions
status: shipped
updated: 2026-09-18
verified: 2026-09-18
shipped_in: all nine items; completed changelog
---

# Refactor Suggestions

> **Archived — completed changelog.** All 9 items below are done (including #7,
> confirmed live in `bazos/protocols.py`). Kept for history,
> not as an open task list. Current planning lives in
> [`PIPELINE_REFACTOR.md`](PIPELINE_REFACTOR.md).
>
> **Audited 2026-09-18.** This is a changelog of a July 2026 state and later work has moved
> three of its endings. `bazos/mixins.py` was described here as "now empty"; it has since been
> deleted outright. #8's ending is recorded inline below. #9's `_is_known()` became
> `_get_known_delivery()` in the `Ad`/`AdDelivery` split
> ([`AD_DELIVERY_SPLIT.md`](AD_DELIVERY_SPLIT.md) §5.1), and `bazos_runner.py` /
> `bazos_query_runner.py` in #5 are now `bazos/scraping/runner.py` /
> `bazos/scraping/query_runner.py` (commit `0a91b9a`).

Concrete improvements worth doing alongside the pipeline work. Ordered roughly by impact.

---

## ✅ 1. Delete dead commented-out code

Done. Removed ~60 lines of old SQLAlchemy leftovers and abandoned experiments across:
- `bazos_runner.py`
- `bazos_query_runner.py`
- `bazos_scraper.py`

---

## ✅ 2. Split `extract_product` — parsing shouldn't hit the DB

Done. `extract_product` now composes two focused methods:
- `_parse_product` — pure HTML parsing, returns a dict, no DB calls
- `_resolve_publishers` — `get_or_create` for `EmailPublisher`/`PhonePublisher`

The nested `get_url_query_dict_from_element_text` closure was also promoted to a static method `_parse_action_args`. Tests in `bazos/tests/test_parse_product.py` cover `_parse_product` against fixture HTML without a DB.

---

## ✅ 3. Fix the default mutable argument in `run_request`

Done. `extra_args: dict[Any, Any] = dict()` → `extra_args: dict | None = None`.

---

## ✅ 4. Move IP changer selection out of the class body

Done. Removed class-level `if settings.IP_CHANGER_TYPE == "DUMMY"` block; replaced with a ternary in `__init__`. Also removed the now-unnecessary `interval_multiplier_class` and `ip_changer_class` class attributes.

---

## ✅ 5. Centralise the ASCII-encode pattern

Done. New `bazos/utils.py` with `ascii_safe()`. Replaced 8 inline encode/decode calls across `bazos_runner.py` and `bazos_query_runner.py`.

---

## ✅ 6. Fix the page-break logic in `run_query`

Done. Replaced the `count = 0` sentinel pattern with:
```python
products = list(self.get_page_products(response))
yield from products
if not products:
    break
```

---

## ✅ 7. Replace `SendableMixin` with a Protocol

Done. `SendableMixin` inherited from Django's `Model` and raised `NotImplementedError` on abstract properties — double duty as a Django abstract model and a duck-type interface. Replaced with a `Protocol` in `bazos/protocols.py`; `bazos/mixins.py` is now empty. `Ad` implements it structurally, no inheritance needed.

Original proposal, for reference:

```python
# bazos/protocols.py
from typing import Protocol

class Sendable(Protocol):
    @property
    def message(self) -> str: ...
    @property
    def link(self) -> str: ...
```

`Ad` implements it implicitly — no inheritance needed. `Sender.send_sendable` accepts `Sendable` instead of `SendableMixin`. Decouples the sender layer from Django models entirely.

---

## ✅ 8. `DiscordSender._send` — remove silent infinite retry on connection errors

Done. Added `MAX_CONNECTION_RETRIES = 10` cap on `URLError`: increments a counter per call, sleeps with backoff, and re-raises after the limit. Rate-limit (`HTTPError`) still retries indefinitely — acceptable until the Plan A sender process redesign. Dead commented-out code also removed. Tests in `senders/tests/test_discord_sender.py`.

> **Both numbers have moved since, 2026-09-18.** `MAX_CONNECTION_RETRIES` is **5**, and
> `HTTPError` no longer retries at all: `DiscordSender._send` raises `RateLimitError` and
> `run_sender` owns the retry policy, which is exactly the "Plan A sender process redesign" this
> note was waiting on ([`PIPELINE_REFACTOR.md`](PIPELINE_REFACTOR.md) §3a, shipped).

---

## ✅ 9. `run_existing_query` — extract the dedup check

Done. Extracted `_is_known()` method using `.exists()` instead of `.count() == 0`.

---

## What not to refactor now

- **`Query.generate_random_queries`** — `randomly_generated` field and the `update(enabled=False)` at loop start is dead/experimental. Delete if confirmed unused.
- **`Ad.message` property** — works fine, not worth touching until notification format is redesigned for multi-marketplace.
- **`price_lower == 0` as "no price"** — implicit convention. Worth making `None`/nullable eventually, but requires a migration and touches URL generation — defer to a dedicated cleanup.
- **`bazos_id` naming on `Ad` vs publishers** — rename `Ad.bazos_id → external_id` as part of the marketplace abstraction (Plan B Step 7), not now.
