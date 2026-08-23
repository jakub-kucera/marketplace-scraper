---
title: "P19 — Zero-results canary: implementation spec"
status: shipped
updated: 2026-08-21
verified: 2026-08-21
shipped_in: 739815c
---

# P19 — Zero-results canary: implementation spec

> **Archived — implemented 2026-08-21.** `BazosRunner._check_zero_results_canary` +
> `BazosQueryRunner.rows_seen_counter` ship exactly this design (see
> [`PROMPTS.md`](../../backlog/PROMPTS.md) P19). Kept for history/rationale, not as an open task.
>
> One post-implementation fix beyond what's written below: `zero_new_ads_passes` is now also
> reset to 0 on a zero-rows pass (previously only `zero_rows_passes` was touched in that
> branch), so a brief total outage can't let the zero-new-ads streak resume from its
> pre-outage count once parsing recovers. See `bazos/scraping/bazos_runner.py` and
> `bazos/tests/test_zero_results_canary.py::test_a_zero_row_pass_resets_the_zero_new_ads_counter`.

> Executable expansion of [`PROMPTS.md`](../../backlog/PROMPTS.md) P19. Every design decision is already
> made below — implement exactly what is written. Where this spec disagrees with P19's
> original wording, **this spec wins** (the deviations are called out and justified).

---

## 1. The problem, in one paragraph

`BazosScraper._parse_product` depends on hardcoded CSS class names (`inzeraty`,
`inzeratynadpis`, `nadpis`, `velikost10`, `popis`, `inzeratycena`, `inzeratylok`,
`inzeratyview`, `inzeratyakce`). If Bazos renames one, parsing silently yields nothing,
`run_scraper`'s outer handler swallows it, and the logs show a scraper that keeps running
and finding no new ads — **which is exactly what a genuinely quiet market looks like**.
There is no alert for this today. This task adds one.

---

## 2. What you are building

**Two independent counters on the runner, evaluated once per pass**, because "zero rows"
and "zero new ads" mean very different things:

| Signal | Meaning | Threshold | Log level |
|---|---|---|---|
| **Zero parsed rows** across all successful queries in a pass | Near-certain defect. A live listing page essentially always parses to >0 rows. | low (default **2** passes) | **ERROR** |
| **Zero new ads**, but rows *were* parsed | Weak signal. A quiet market looks identical. | high (default **6** passes) | **WARNING** |

Each counter increments on a qualifying pass, resets to 0 on a non-qualifying pass, and
resets to 0 immediately after it alerts (so it does not fire every pass forever).

> **Deviation from P19 step 2, deliberate.** P19 says "emit a WARNING". Use **ERROR** for the
> zero-rows signal. Reason: `self.log` fans out to the Discord `for_logging` channels at any
> level, but Sentry's logging integration only auto-captures **ERROR and above** — a WARNING
> here would stay invisible in Sentry. This is the same lesson already recorded in
> `PROMPTS.md` P20's 2026-08-09 note. The weak zero-new-ads signal stays WARNING on purpose:
> it fires on quiet markets too and should not create Sentry noise.

---

## 3. Step 1 — settings

**File:** `scraper/settings.py`

Add immediately after the `INTERVAL_LOWER` / `INTERVAL_UPPER` lines (around line 162):

```python
# ---------------------------------------------------------------------------
# Zero-results canary (P19)
# ---------------------------------------------------------------------------
# Consecutive passes parsing NO rows at all before alerting. A live listing page
# essentially always parses to >0 rows, so this is a near-certain defect signal
# (parser drift / blocked transport) — keep the threshold low.
ZERO_ROWS_ALERT_THRESHOLD = env("ZERO_ROWS_ALERT_THRESHOLD", default=2)

# Consecutive passes that parsed rows but found zero NEW ads. Weak signal — a
# genuinely quiet market is indistinguishable — so the threshold is high.
ZERO_NEW_ADS_ALERT_THRESHOLD = env("ZERO_NEW_ADS_ALERT_THRESHOLD", default=6)
```

`env` is the `environ.Env()` instance already defined at the top of the file; passing an
`int` default makes it cast to `int` automatically, same as `INTERVAL_LOWER` does.

Do **not** add these to `.env.sample` — that file is already incomplete by convention and
both settings have working defaults.

---

## 4. Step 2 — count parsed rows

**File:** `bazos/scraping/bazos_query_runner.py`

### 4a. New counter in `__init__`

Directly below the existing `self.new_product_counter = 0`:

```python
        self.rows_seen_counter = 0
```

### 4b. Increment it in **both** query loops

In `run_new_query`, make the loop body start with the increment:

```python
        for product in self.scraper.run_query(self.query):
            self.rows_seen_counter += 1
            if not product.topped:
```

In `run_existing_query`, same — first statement in the loop body:

```python
        for product in self.scraper.run_query(self.query):
            self.rows_seen_counter += 1
            existing = self._get_known(product)
```

The increment must be the **first** statement in each loop body, before any `break`,
`continue` or branching. The row that triggers the dedup `break` in `run_existing_query`
was parsed, so it counts.

### 4c. Do NOT change `run()`'s signature

`run()` must keep returning `int` (the new-ad count). Existing P18 tests patch it with
`patch.object(BazosQueryRunner, "run", return_value=3)`; changing the return type breaks
them. The runner reads `rows_seen_counter` off the instance instead.

---

## 5. Step 3 — accumulate per pass and evaluate

**File:** `bazos/scraping/bazos_runner.py`

### 5a. Two counters on the runner

In `BazosRunner.__init__`, after `self.ip_changer = ...`:

```python
        self.zero_rows_passes = 0
        self.zero_new_ads_passes = 0
```

These are **in-memory**, deliberately. Do not add a model or a migration — see §8.

### 5b. Per-pass accumulators

In `run()`, immediately after `start = datetime.now(timezone.utc)` and **before**
`for query in queries:`:

```python
            pass_rows_seen = 0
            pass_new_ads = 0
            successful_queries = 0
```

### 5c. Accumulate inside the existing `try`

In the `try` block, directly after the existing `query_run.new_ads_count = new_products_count`:

```python
                    pass_rows_seen += query_runner.rows_seen_counter
                    pass_new_ads += new_products_count
                    successful_queries += 1
```

These lines must be **inside** the `try`, after the assignment. A query that raises hits
`except` and `continue`s without contributing — that is intended (see §5e).

### 5d. Evaluate once per pass

In `run()`, after the `for query in queries:` loop ends and after the existing
`self.log(f"Finished running ...")` line, before `sleep_interval = self.get_next_interval()`:

```python
            self._check_zero_results_canary(pass_rows_seen, pass_new_ads, successful_queries)
```

### 5e. The new method

Add to `BazosRunner`, after `_interruptible_sleep`:

```python
    def _check_zero_results_canary(self, rows_seen: int, new_ads: int, successful_queries: int) -> None:
        """Alert when the pipeline stops producing — parser drift looks exactly like a quiet market.

        Never fatal: a genuinely dead category at 3am must not stop the scraper.
        """
        if successful_queries == 0:
            # No query completed, so this pass carries no evidence either way. Those failures
            # are already loud via QueryRun.success and logger.exception — don't double-alert,
            # and don't let a crash storm masquerade as parser drift.
            return

        if rows_seen == 0:
            self.zero_rows_passes += 1
            if self.zero_rows_passes >= settings.ZERO_ROWS_ALERT_THRESHOLD:
                self.log(
                    f"CANARY: {self.zero_rows_passes} consecutive passes parsed ZERO rows across "
                    f"{successful_queries} successful queries — the scraper is probably broken "
                    f"(parser drift / blocked transport), not the market being quiet.",
                    level=logging.ERROR,
                )
                self.zero_rows_passes = 0
            return

        self.zero_rows_passes = 0

        if new_ads == 0:
            self.zero_new_ads_passes += 1
            if self.zero_new_ads_passes >= settings.ZERO_NEW_ADS_ALERT_THRESHOLD:
                self.log(
                    f"CANARY: {self.zero_new_ads_passes} consecutive passes found zero NEW ads "
                    f"({rows_seen} rows parsed, so scraping itself works) — either a quiet market "
                    f"or dedup drift.",
                    level=logging.WARNING,
                )
                self.zero_new_ads_passes = 0
        else:
            self.zero_new_ads_passes = 0
```

The `return` after the zero-rows branch is load-bearing: zero rows implies zero new ads, and
without it a broken scraper would tick both counters and eventually emit both alerts.

`logging` and `settings` are already imported in this file — do not re-import them.

---

## 6. Step 4 — tests

**New file:** `bazos/tests/test_zero_results_canary.py`

Follow the structure of the existing `bazos/tests/test_query_run_tracking.py` — same
`StopLoop` sentinel, same `BazosRunner.__new__` construction trick.

### 6a. Helpers — copy these verbatim

```python
"""Tests for P19: the zero-results canary.

A Bazos HTML change silently zeroes the deal flow and looks identical to a quiet
market. These tests pin the counter/threshold/reset logic that tells them apart.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from bazos.models import QueryRun
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.bazos_query_runner import BazosQueryRunner
from bazos.scraping.bazos_runner import BazosRunner


class StopLoop(Exception):
    """Sentinel used to escape BazosRunner.run()'s `while True`."""


def make_runner():
    """Construct a BazosRunner bypassing __init__, with a no-op IP changer.

    __init__ is skipped, so the two canary counters must be initialised by hand here.
    """
    runner = BazosRunner.__new__(BazosRunner)
    runner.discord_loggers = []
    runner.interval_multiplier = MagicMock()
    runner.ip_changer = MagicMock()
    runner.ip_changer.check_ip_local.return_value = False
    runner.ip_changer.session = MagicMock()
    runner.zero_rows_passes = 0
    runner.zero_new_ads_passes = 0
    return runner


def run_n_passes(runner, n):
    """Run BazosRunner.run() for exactly n passes, then escape the infinite loop."""
    state = {"passes": 0}

    def fake_sleep(_seconds):
        state["passes"] += 1
        if state["passes"] >= n:
            raise StopLoop

    with patch.object(runner, "_interruptible_sleep", side_effect=fake_sleep):
        with pytest.raises(StopLoop):
            runner.run()


def patched_query_runner(rows_seen: int, new_ads: int):
    """Patch BazosQueryRunner.run so every query reports the given rows / new ads.

    Only `run` is patched — `__init__` still executes for real, so `rows_seen_counter`
    exists on the instance exactly as in production.
    """
    def fake_run(self):
        self.rows_seen_counter = rows_seen
        self.new_product_counter = new_ads
        return new_ads

    return patch.object(BazosQueryRunner, "run", fake_run)


def alerts_at(log_mock, level):
    """The canary messages logged at `level`."""
    return [
        call for call in log_mock.call_args_list
        if call.kwargs.get("level") == level and "CANARY" in call.args[0]
    ]
```

Wrap every `run_n_passes` call in
`patch.object(BazosScraper, "check_blacklisted", return_value=False)` so the pre-flight
guard never touches the mock session.

### 6b. Required tests

Write **all** of these. Names are prescriptive.

| Test | Setup | Assert |
|---|---|---|
| `test_rows_seen_counter_counts_every_parsed_row` | Unit test on `BazosQueryRunner`. Patch `scraper.run_query` to yield 3 unknown ads (use the `make_ad` fixture from `bazos/tests/conftest.py`). Call `run_existing_query()`. | `rows_seen_counter == 3` |
| `test_rows_seen_counter_counts_the_row_that_breaks_dedup` | Save one ad to the DB first, then yield that same ad (`topped=False`) followed by two more. Call `run_existing_query()`. | Loop breaks on the known ad **and** `rows_seen_counter == 1` — the break-row still counts |
| `test_alerts_after_threshold_consecutive_zero_row_passes` | `@override_settings(ZERO_ROWS_ALERT_THRESHOLD=2)`, `patched_query_runner(rows_seen=0, new_ads=0)`, `run_n_passes(runner, 2)`, `patch.object(runner, "log")` | exactly **1** ERROR-level CANARY alert |
| `test_zero_row_counter_resets_after_alerting` | Same, but `run_n_passes(runner, 4)` | exactly **2** ERROR alerts (pass 2 and pass 4), not 3 — proves the reset |
| `test_a_pass_with_rows_resets_the_zero_row_counter` | Threshold 2. Pass 1 rows=0, pass 2 rows=5, pass 3 rows=0. (Swap the patch between passes, or run three separate 1-pass runs against the same runner.) | **0** ERROR alerts |
| `test_zero_new_ads_alerts_at_its_own_threshold_and_level` | `@override_settings(ZERO_NEW_ADS_ALERT_THRESHOLD=3)`, `patched_query_runner(rows_seen=10, new_ads=0)`, 3 passes | exactly **1** WARNING CANARY alert and **0** ERROR alerts |
| `test_new_ads_found_resets_the_zero_new_ads_counter` | Threshold 3, rows=10. Passes: new_ads 0, 0, 4, 0, 0 | **0** WARNING CANARY alerts |
| `test_pass_where_every_query_failed_does_not_count_as_zero_rows` | Threshold 2. `patch.object(BazosQueryRunner, "run", side_effect=RuntimeError("boom"))`, 3 passes | **0** CANARY alerts at any level (the failures are reported by P18's `QueryRun.success` instead) |
| `test_canary_never_aborts_the_pass` | Threshold 1, rows=0, 2 passes, one `query` fixture | 2 `QueryRun` rows exist — the pass completed normally after alerting; no exception escapes |

All tests that touch the DB need `@pytest.mark.django_db`.

---

## 7. Verification — all four must pass

```bash
pytest bazos/tests/test_zero_results_canary.py -v   # new tests
pytest                                              # nothing else regressed, esp. test_query_run_tracking.py
ruff check .
mypy .
```

If `test_query_run_tracking.py` breaks, you changed `BazosQueryRunner.run`'s signature —
revert that part (see §4c).

---

## 8. Explicit non-goals — do NOT do these

- **Do not add a model, a migration, or a DB column.** The counters live in memory on the
  `BazosRunner` instance. Known limitation, accepted: if `run_scraper`'s outer handler
  rebuilds the runner after a crash, the counters reset. That is fine — a crash is already
  loud via `logger.exception` and Sentry. Do not "fix" it with persistence.
- **Do not make the alert fatal.** No `raise`, no `break`, no `sys.exit`. P19 step 4 is
  explicit: a genuinely dead category at 3am must not stop the scraper.
- **Do not alert per query.** The canary is evaluated once per pass, after the query loop.
- **Do not touch the IP guards** at `bazos_runner.py:40-51`. That is separate work (P20 /
  the guard-collapse change currently in the working tree) and will conflict.
- **Do not use `print()`.** Use `self.log(...)` — it fans out to the Discord `for_logging`
  channels, which is the entire point of the alert.
- **Do not change `BazosQueryRunner.run()`'s return type.**
- **Do not add retry, backoff, or self-healing logic.** This task is an alert, nothing else.
