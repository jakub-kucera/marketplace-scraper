# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Dependencies (Python 3.11, Poetry)
poetry install

# Database setup (run once, in order)
python manage.py migrate
python manage.py create_sections
python manage.py create_categories

# --- Pipeline processes (each runs as its own long-lived loop) ---
python manage.py run_scraper          # scrape queries → Ad rows (status PENDING)
python manage.py run_scraper --unsafe # crash-fast mode: bypass outer exception swallowing
python manage.py run_filter           # PENDING/PRICE_CHANGED → APPROVED/REJECTED
python manage.py run_sender           # APPROVED → SENT/FAILED (Discord delivery)

# Django dev server
python manage.py runserver

# Standalone one-off scrapers (NOT Django apps)
python getyourguide/gyg_scraper.py    # Caminito del Rey availability → Discord webhook

# Tests / checks
pytest
mypy -p .
pylint .
```

Docker Compose runs the full stack: `marketplace_scraper`, `marketplace_filter`, `marketplace_sender`, `marketplace_server` (Django, port 8000), plus `postgres`, `adminer` (port 8081), and `tor_proxy` (SOCKS 9050 / control 9051). CI (`.github/workflows/test.yml`) runs `pytest` on push/PR to `main`.

## Architecture

Django scraper for online marketplaces — primarily the Czech **Bazos.cz**, with a marketplace-abstraction layer being extended to others (Vinted planned). It monitors search `Query` rows, detects new ads, filters them, and sends Discord notifications.

**The pipeline is decoupled into three independent processes that communicate through the `Ad.status` column** (a queue in Postgres). Each stage polls with `select_for_update(skip_locked=True)` so multiple workers are safe:

```
run_scraper  →  BazosRunner (bazos/scraping/bazos_runner.py)   # orchestrates queries, IP rotation, sleep
                  → BazosQueryRunner (bazos_query_runner.py)    # per-query dedup, dispatches by query.marketplace
                    → MarketplaceScraper (BazosScraper)         # HTTP + BeautifulSoup; writes Ad(status=PENDING)
run_filter   →  RuleEngine (bazos/filters.py)                   # PENDING/PRICE_CHANGED → APPROVED / REJECTED
run_sender   →  DiscordSender (senders/services/)              # APPROVED → SENT / FAILED (retry w/ backoff)
```

**Ad status state machine** (`AdStatus` in `bazos/models.py`): `PENDING → APPROVED | REJECTED | SUPPRESSED`, then `APPROVED → SENT | FAILED`. `PRICE_CHANGED` re-enters at the filter stage. Each stage owns its transitions — the scraper must not send directly; it only sets `PENDING` (or `SUPPRESSED` for an `ignore_first_run` backfill). Batch sizes / poll intervals / `MAX_SEND_ATTEMPTS` live in `bazos/const.py`.

**Marketplace abstraction** (Stages 6–7):
- `bazos/scraping/marketplace.py` — `MarketplaceScraper` **Protocol** (`marketplace` attr, `run_query`, `load_full_description`, `check_blacklisted`). `BazosScraper` satisfies it structurally.
- `BazosQueryRunner._build_scrapers()` is the registry keyed by `query.marketplace`; add new marketplaces there.
- `bazos/protocols.py` — `Sendable` Protocol (`.message`, `.link`), replaces the old `SendableMixin` ABC. `Ad` implements it.

**Key models** (`bazos/models.py`):
- `Query` — what to scrape (text, price range, location, section/category, `marketplace`, `sender` FK). `new_query=True` triggers a backfill-only first run (up to `NEW_PRODUCT_LOAD_MAX=50`; suppressed if `ignore_first_run`).
- `Ad` — discovered listings, identified per-query by `(query, marketplace, external_id)` (`external_id` was renamed from `bazos_id`; no DB unique constraint). Carries pipeline fields (`status`, `filter_reason`, `sent_at`, `send_attempts`) and optional FKs to `EmailPublisher` / `PhonePublisher`.
- `QueryRun` — per-execution metrics. `Section` / `Category` — Bazos taxonomy + URL helpers.
- `Discord` (`senders/models.py`) — webhook configs (`notify` ping flag, `for_logging` flag).

**Filtering** (`bazos/filters.py`): `RuleEngine` applies ordered `FilterRule`s (first non-`PASS` wins; default approve). Currently only `PassthroughRule` (approves everything) is wired in `run_filter` — real rules are still a placeholder.

**Senders** (`senders/services/`): `Sender` ABC + `DiscordSender` (the only production sender; posts via `discord_notify`, raises `RateLimitError` on HTTP error for the sender's retry loop). `SlackSender`, `EmailSender`, `CalendarConditionSender` are experimental stubs — some import broken `src.*` paths and won't run.

**IP rotation** (`ip_changer/`): `IPChanger` ABC (`ip_changer.py`) with `TorIPChanger` (`tor.py`, renews Tor identity via Stem control port 9051 and validates the new IP) and `DummyIPChanger` (`dummy.py`, no-op for dev), selected by `IP_CHANGER_TYPE`. `OpenVPNIPChanger` (`openvpn.py`) is an unfinished stub.

**Other apps:**
- `facebook/` — `FBUser` model + `python manage.py import_data --path <file>` to bulk-load a leaked FB dataset; joined to ads via `PhonePublisher.fb_user` for publisher enrichment.
- `getyourguide/` — a **standalone script** (`gyg_scraper.py`), not in `INSTALLED_APPS`; polls a GetYourGuide tour API and fires a Discord webhook when a spot opens.

**Observability:** app loggers (`bazos`, `senders`, `ip_changer`) log at INFO to console **and** the DB via `django-db-logger`. Sentry is enabled only when `SENTRY_DSN` is set (error tracking, no perf tracing).

**Existing-query dedup**: stops on the first non-TOP ad already known in DB, assuming newest-first ordering from Bazos.

**Force-run**: `BazosRunner._interruptible_sleep` wakes early when `force_run.flag` (`settings.FORCE_RUN_FLAG_PATH`) appears, so the admin/UI can interrupt the sleep between passes.

## Coding patterns

- **Pipeline stages own their `Ad.status` transitions.** New long-running stages should poll with `select_for_update(skip_locked=True)` and a status filter, like `run_filter`/`run_sender`.
- **Adding a marketplace**: implement the `MarketplaceScraper` protocol and register it in `BazosQueryRunner._build_scrapers()`; don't special-case it in the runner.
- URL generation must use model helpers (`Section.full_url`, `Category.full_url`, `Query.url`) — never rebuild URLs ad hoc.
- `Query` has DB constraints: `price_lower <= price_upper`, and `section`/`category` are mutually exclusive.
- Use the `logging` module (`logging.getLogger(__name__)`) — not `print()`. App loggers are configured in `settings.py` (INFO → console + DB).
- For scraping changes, update both `create_url_*` and `run_query` in `BazosScraper` and validate against `bazos/tests/test_gen_url.py`.
- For loop/control-flow edits, explicitly reason about `check_bazos_blacklisted` and `check_ip_local` guards to avoid hot loops.
- Legacy/experimental code lives in `old_tests/`, notebooks (`*.ipynb`), and the sender/openvpn stubs above; the many `*.md` files at repo root (`PIPELINE_REFACTOR*.md`, `REFACTOR_*.md`, `STAGE8_VINTED_DESIGN.md`, `PROMPTS.md`) are refactor-planning notes, not runtime docs.

## Environment

Copy `.env.sample` to `.env`. Required: `SECRET_KEY`, `POSTGRES_DB/USER/PASSWORD/HOST/PORT`, `TOR_PROXY_IP`, `TOR_PROXY_PASSWORD`, `LOCAL_IP_SUBNET`, `IP_CHANGER_TYPE` (`TOR` or `DUMMY`). Optional: `SENTRY_DSN` (empty disables Sentry), `ALLOWED_HOSTS`, `GYG_DISCORD_WEBHOOK_URL`/`GYG_POLL_INTERVAL` (getyourguide). Sleep intervals: `INTERVAL_LOWER`/`INTERVAL_UPPER` (default 15–45 min, doubled 22:00–06:00 Prague time via `NightMultiplier`).
