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

# Django dev server — `/admin/` is the only route in scraper/urls.py; there are no views
python manage.py runserver

# One-off tools
python manage.py compare_bazos_scrapers   # HTML vs hidden-API scraper overlap; read-only, never writes Ads
python getyourguide/gyg_scraper.py        # standalone script: Caminito del Rey availability → Discord webhook

# Tests / checks
pytest         # runs against real Postgres — needs `docker compose up -d postgres` first.
               # Django builds an isolated `test_<POSTGRES_DB>`; the dev DB is untouched.
               # `TEST_DB=sqlite pytest` forces SQLite :memory: — for the live contract job only.
ruff check .   # lint: pyflakes-only rules (unused imports/vars, undefined names); no formatting/import-sort rules
mypy .         # lenient: ignore_missing_imports, no --strict; union-attr disabled (Django/mock Optional noise)
```

Docker Compose runs the full stack: `marketplace_scraper`, `marketplace_filter`, `marketplace_sender`, `marketplace_server` (Django, port 8000), plus `postgres`, `adminer` (port 8081), and `tor_proxy` (SOCKS 9050 / control 9051). The `backup` service is **not** part of that — see below.

**Backups** (`backup/`, [`docs/BACKUPS.md`](docs/BACKUPS.md)): a **one-shot** container built `FROM postgres:15.2` so the `pg_dump` client matches the server by construction. It dumps to `./backups/` (gitignored — dumps hold seller PII), pushes to `restic` if `RESTIC_REPOSITORY` is set, then exits; with it unset the local dump still runs, so it is safe to deploy before off-host storage exists. Dumps use **`-Z0` on purpose** — pg_dump's own compression defeats restic's dedup (measured, `docs/BACKUPS.md` §6.1).

Two things to know before touching it:
- It sits behind a compose **`profiles: ["backup"]`** key, so `docker compose up -d` never starts it and nothing idles between runs. **`docker compose build` silently skips profiled services** — `deploy.yml` builds with `--profile backup`, and dropping that flag leaves the backup image stale forever.
- Scheduling is a **systemd timer** on the Pi (`backup/systemd/`, installed manually), not a loop in the container: `Persistent=true` catches up a backup missed while the Pi was down, which a sleep loop cannot. Force one with `sudo systemctl start marketplace-backup.service`, or `docker compose run --rm backup` directly.

Deliberately *not* a `Job` in the app's queue: backups must survive the app being broken, which is also why failure alerts go through `BACKUP_DISCORD_WEBHOOK_URL` rather than the `Discord` table. Restore procedure is `docs/BACKUPS.md` §9.

**CI/CD** — two workflows. `test.yml` runs `pytest`, `ruff check .`, `mypy .` on push/PR to `main`. `deploy.yml` fires on a **`v*` tag** and deploys to a self-hosted runner on a Raspberry Pi (`docker compose build` → `down` → **pre-migration `pg_dump`** → `migrate` → `up -d`); `git tag v1.2.3 && git push origin v1.2.3` is the only deploy path. A failed pre-migration dump **aborts the deploy** — that's intentional, a bad migration is the likeliest data-loss event here.

**Self-hosted runner prerequisites** (Raspberry Pi, discovered the hard way 2026-08-22 — not needed again until the runner is reprovisioned): the Pi's `docker.io` package (Debian's build, currently 20.10.24) ships neither the Compose v2 nor the `buildx` CLI plugin, so `docker compose --profile backup build` fails outright. Both must be installed manually as CLI plugins (`/usr/local/lib/docker/cli-plugins/docker-compose` and `docker-buildx`, from the `docker/compose` and `docker/buildx` GitHub releases, `*-linux-aarch64`/`*-linux-arm64` respectively) — `apt`'s version is too old to carry them. Separately, the runner's `actions.runner*.service` must be **restarted** after the `user` account is added to the `docker` group — systemd services don't pick up new group membership from an already-running process, so `docker compose` fails with `permission denied ... docker.sock` until the service is bounced (`sudo systemctl restart actions.runner.*.service`), even though `groups` already shows `docker` for interactive SSH sessions.

## Architecture

Django scraper for online marketplaces — primarily the Czech **Bazos.cz**, with a marketplace-abstraction layer extended to others (**Vinted** live as of Stage 8). It monitors search `Query` rows, detects new ads, filters them, and sends Discord notifications.

**The pipeline is decoupled into three independent processes that communicate through the `Ad.status` column** (a queue in Postgres). Each stage polls with `select_for_update(skip_locked=True)` so multiple workers are safe:

```
run_scraper  →  BazosRunner (bazos/scraping/bazos_runner.py)   # orchestrates queries, IP rotation, sleep
                  → BazosQueryRunner (bazos_query_runner.py)    # per-query dedup, price-change detection
                    → MarketplaceScraper (BazosScraper)         # HTTP + BeautifulSoup; writes Ad(status=PENDING)
run_filter   →  build_rule_engine(ad.query) (bazos/filters.py)  # PENDING/PRICE_CHANGED → APPROVED / REJECTED
run_sender   →  DiscordSender (senders/services/)               # APPROVED → SENT / FAILED (retry w/ backoff)
```

**Ad status state machine** (`AdStatus` in `bazos/models.py`): `PENDING → APPROVED | REJECTED | SUPPRESSED`, then `APPROVED → SENT | FAILED`. `PRICE_CHANGED` re-enters at the filter stage. Each stage owns its transitions — the scraper must not send directly; it only sets `PENDING` (or `SUPPRESSED` for an `ignore_first_run` backfill). Batch sizes / poll intervals / `MAX_SEND_ATTEMPTS` live in `bazos/const.py`.

**Marketplace abstraction** (Stages 6–7):
- `bazos/scraping/marketplace.py` — `MarketplaceScraper` **Protocol** (`marketplace` attr, `run_query`, `load_full_description`, `check_blacklisted`). `BazosScraper` satisfies it structurally.
- `Marketplace` (`TextChoices` in `bazos/models.py`) is the single source of valid values — it types `Query.marketplace` *and* `Ad.marketplace` and keys the scraper registry. `BAZOS`, `BAZOS_API`, and `VINTED` are all registered and live.
- `_build_scrapers(session)` / `get_scraper(marketplace, session)` — **module-level** in `bazos/scraping/bazos_query_runner.py` (not a method). Both `BazosQueryRunner.__init__` and `BazosRunner._blacklist_checker` dispatch through `get_scraper`.
- `bazos/scraping/bazos/bazos_api_scraper.py` — `BazosApiScraper`, a second `MarketplaceScraper` using Bazos's hidden mobile JSON API instead of HTML (see `docs/bazos-api/BAZOS_HIDDEN_API_RESEARCH.md`). Registered under `Marketplace.BAZOS_API` for validation only (`python manage.py compare_bazos_scrapers`) — no `Query` uses that value, so `run_scraper` stays HTML-only (`BazosScraper`) in production.
- `bazos/scraping/vinted/vinted_scraper.py` — `VintedScraper` (Stage 8), backed by the `vinted-scraper` PyPI package. Ignores the `session` it's passed — the library builds its own `httpx` client, since Vinted bans proxy/VPN traffic and Tor is a non-starter there. `Query.extra_params` (JSONField) carries Vinted-specific search params (`base_url`, `catalog_ids`, ...); ignored by Bazos. See `docs/refactor/STAGE8_VINTED_SPEC.md`.
- `bazos/protocols.py` — `Sendable` Protocol (`.message`, `.link`), replaces the old `SendableMixin` ABC. `Ad` implements it.

**Key models** (`bazos/models.py`):
- `Query` — what to scrape (text, price range, location, section/category, `marketplace`, `sender` FK) **plus its filter config** (`filter_blocklist`, `filter_required`, `filter_rule_names`). `new_query=True` triggers a backfill-only first run (up to `NEW_PRODUCT_LOAD_MAX=50`; suppressed if `ignore_first_run`).
- `Ad` — discovered listings, identified per-query by `(query, marketplace, external_id)` (`external_id` was renamed from `bazos_id`; no DB unique constraint). Carries pipeline fields (`status`, `filter_reason`, `sent_at`, `send_attempts`) and optional FKs to `EmailPublisher` / `PhonePublisher`.
- `PriceChange` — append-only price history (`ad.price_history`). Written by `BazosQueryRunner.run_existing_query` when a re-seen ad's `price_raw` differs; it also flips the ad to `PRICE_CHANGED`, which is the *only* producer of that status. `PriceDropRule` reads the newest row back.
- `QueryRun` — per-execution metrics; always saved, including on failure (`success`, `error`). `Section` / `Category` — Bazos taxonomy + URL helpers.
- `EmailPublisher` / `PhonePublisher` — opaque Bazos seller ids with a `blocked` flag; share `PublisherMixin.partner_rows()` ("who else appears alongside me").
- `Discord` (`senders/models.py`) — webhook configs (`notify` ping flag, `for_logging` flag).

**Filtering** (`bazos/filters.py`): `run_filter` builds a per-ad engine via `build_rule_engine(ad.query)`. Rules run in order, **first non-`PASS` wins**, all-`PASS` ⇒ approve. Shipped rules (`RULE_REGISTRY`):

| rule name | rejects when | stays neutral (`PASS`) when |
|---|---|---|
| `price_range` | parsed `price_raw` outside `query.price_lower..price_upper` | range is `0-0` ("no filter"), or price unparseable (`Dohodou`, `V textu`) |
| `blocklist_keyword` | `name`+`short_description` contains a `query.filter_blocklist` phrase | list empty |
| `required_keyword` | `name`+`short_description` contains none of `query.filter_required` | list empty |
| `publisher_blocklist` | the ad's email/phone publisher has `blocked=True` | neither is blocked |
| `price_drop` | a `PRICE_CHANGED` ad whose newest `PriceChange` did **not** go down | ad isn't `PRICE_CHANGED`, or no parseable history |

`Query.filter_rule_names` selects which rules apply — **empty means all of them** (the same permissive-when-empty convention as the two keyword lists); an unknown name raises `ValueError` when the engine is built. `PassthroughRule` is a test-only no-op and is *not* wired into `run_filter`.

**Seller identity** (`SellerAdCounts` in `bazos/models.py`): a Bazos seller is a *pair* of opaque ids (email_id, phone_id) and the same person routinely posts under many pairings, so counts are reported three ways — `by_email`, `by_phone`, `combined` — and their disagreement is the signal. `combined` walks the email↔phone graph transitively to a fixpoint, bounded by `MAX_IDENTITY_ROUNDS=5`. Two consequences worth knowing before touching it: counts are of ads **in this DB**, not the seller's true Bazos total; and `Ad.message` embeds `seller_ad_counts().summary`, so rendering an ad for Discord fires several `COUNT` queries — never call `.message` in a loop over a large queryset. Migration 0025 removed a `bazos_id=0` sentinel that used to merge unrelated sellers into one identity.

**Senders** (`senders/services/`): `Sender` ABC + `DiscordSender` (the only production sender; posts via `discord_notify`, raises `RateLimitError` on HTTP error for the sender's retry loop, retries `URLError` in-process up to `MAX_CONNECTION_RETRIES`). `SlackSender`, `EmailSender`, `CalendarConditionSender` are experimental stubs — some import broken `src.*` paths and won't run.

**Django admin** (`bazos/admin.py`, ~380 lines — a real operational surface, not scaffolding): force-run button (custom `force-run/` URL, see below), per-query ad count + last-run annotations, `filter_rule_names` rendered as checkboxes (`QueryAdminForm`), publisher partner tables with block/unblock actions and links into a filtered `Ad` changelist, `PriceChange` inline on `Ad`.

**IP rotation** (`ip_changer/`): `IPChanger` ABC (`ip_changer.py`) with `TorIPChanger` (`tor.py`, renews Tor identity via Stem control port 9051 and validates the new IP) and `DummyIPChanger` (`dummy.py`, no-op for dev), selected by `IP_CHANGER_TYPE`. `OpenVPNIPChanger` (`openvpn.py`) is an unfinished stub.

**Other apps:**
- `facebook/` — `FBUser` model + `python manage.py import_data --path <file>` to bulk-load a leaked FB dataset; joined to ads via `PhonePublisher.fb_user` for publisher enrichment.
- `getyourguide/` — a **standalone script** (`gyg_scraper.py`), not in `INSTALLED_APPS`; polls a GetYourGuide tour API and fires a Discord webhook when a spot opens.

**Observability:** app loggers (`bazos`, `senders`, `ip_changer`) log at INFO to console **and** the DB via `django-db-logger`. Sentry is enabled only when `SENTRY_DSN` is set *and* not under pytest (error tracking, no perf tracing).

**Existing-query dedup**: stops on the first non-TOP ad already known in DB, assuming newest-first ordering from Bazos.

**Force-run**: `BazosRunner._interruptible_sleep` wakes early (within ~5s) when `force_run.flag` (`settings.FORCE_RUN_FLAG_PATH`) appears, so the admin button can interrupt the sleep between passes.

**Testing:** the suite runs on **real Postgres**, the same engine as production, so Postgres-only behaviour is genuinely exercised — `select_for_update(skip_locked=True, of=("self",))` reaches the SQL, migration 0027's deferred-FK-trigger flush executes, and `max_length`/`int4` limits are enforced (all three are silently no-ops or unenforced on SQLite). Locally that means **`docker compose up -d postgres` must be running**; connection settings come from `.env` (`POSTGRES_HOST=localhost`, port 5435) and Django builds an isolated `test_<POSTGRES_DB>`, never touching the dev database. CI (`test.yml`) provides a `postgres:15.2` service container.

The root `conftest.py` hooks `django_db_modify_db_settings` (not `django_db_setup`) so that `TEST_DB=sqlite` can swap in SQLite `:memory:` — used by **one** caller, `contract-check.yml`'s live job, which runs in a container with no DB and only asserts on live-site parsing — while leaving pytest-django's own `--reuse-db`/`--create-db` intact. A test that passes on SQLite and fails on Postgres is reporting a real defect; don't reach for the env var to silence it. Postgres costs ~2× SQLite (~40s vs 14s for 532 tests), almost all of it building the test DB through the 40-migration chain: `pytest --reuse-db` skips that and halves the run (54s → 28s). Caveat — the migration tests roll the schema backwards and forward again in a fixture teardown, so a run killed mid-test can strand a reused DB at an older schema; `--create-db` rebuilds it, and the default (no flag) is immune. `conftest.py` also no-ops `DatabaseLogHandler.emit` session-wide so DB-free unit tests can log.

Note `POSTGRES_HOST` in `.env` is the **host-side** value (`localhost`). The compose services don't read it — `docker-compose.yml` pins `POSTGRES_HOST: postgres` in each service's `environment:` block, which overrides `env_file`. Before that pin, `.env` had to say `postgres` and nothing on the host could connect at all.

## Coding patterns

- **Pipeline stages own their `Ad.status` transitions.** New long-running stages should poll with `select_for_update(skip_locked=True, of=("self",))` and a status filter, like `run_filter`/`run_sender`. The `of=("self",)` matters — both commands `select_related`, and without it the joined `Query`/publisher rows get locked too.
- **Adding a marketplace**: add a `Marketplace` choice, implement the `MarketplaceScraper` protocol, register it in `_build_scrapers()`; don't special-case it in the runner.
- **Blacklist / IP guards**: `BazosRunner.run` probes `check_blacklisted()` per query, rotates IP on a hit, and `continue`s to the next query when `BazosBlacklistedError` survives rotation; `check_ip_local()` also `continue`s. When editing that loop, make sure every path either advances the loop or sleeps, or you get a hot request loop. Note `IPChanger.check_bazos_blacklisted` is a *different* thing — the default `is_blacklisted` callback inside `renew_ip_bazos_ok`.
- URL generation must use model helpers (`Section.full_url`, `Category.full_url`, `Query.url`) — never rebuild URLs ad hoc.
- `Query` has DB constraints: `price_lower <= price_upper`, and `section`/`category` are mutually exclusive.
- Use the `logging` module (`logging.getLogger(__name__)`) — not `print()`. App loggers are configured in `settings.py` (INFO → console + DB).
- For scraping changes, update both `create_url_*` and `run_query` in `BazosScraper` and validate against `bazos/tests/test_gen_url.py`.
- **Dead code is excluded on purpose** — the authoritative list is the `exclude` blocks in `pyproject.toml` (ruff and mypy each name them): `bazos_scraper_click.py`, `notifier.py`, `selenium_driver.py`, the Slack/Email/Calendar senders, `openvpn.py`. Don't "fix" lint or types in those. Same for `old_tests/`, `experiments/` notebooks, `bazos_app_decomplied/`.
- Refactor-planning notes and Bazos API research (not runtime docs) live under `docs/` — see [`docs/README.md`](docs/README.md) for the index and the current stage-status table.

## Environment

Copy `.env.sample` to `.env`. **Only `SECRET_KEY` has no default** — everything else falls back in `settings.py`: `POSTGRES_DB/USER/PASSWORD` (`postgres`), `POSTGRES_HOST` (`localhost`), `POSTGRES_PORT` (`5432`), `TOR_PROXY_IP`/`TOR_PROXY_PASSWORD` (empty), `LOCAL_IP_SUBNET` (`0.0.0.0/24`), `IP_CHANGER_TYPE` (`TOR`), `ALLOWED_HOSTS`, `SENTRY_DSN` (empty disables Sentry), `INTERVAL_LOWER`/`INTERVAL_UPPER` (15/45 min). `POSTGRES_PORT` *is* required for `docker compose` — it's interpolated into the port mapping.

`.env.sample` is incomplete: it omits `IP_CHANGER_TYPE`, `POSTGRES_HOST`, `INTERVAL_*`, `ALLOWED_HOSTS`, and the getyourguide vars (`GYG_DISCORD_WEBHOOK_URL`, falling back to `DISCORD_LOGGER_WEBHOOK_URL`; `GYG_POLL_INTERVAL`, default 300s). For local dev without Tor, set `IP_CHANGER_TYPE=DUMMY`.

Sleep between scraper passes is `uniform(INTERVAL_LOWER, INTERVAL_UPPER)`, doubled 22:00–06:00 Prague time via `NightMultiplier`.
