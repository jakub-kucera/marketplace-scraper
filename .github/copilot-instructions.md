# Copilot Instructions for `marketplace-scrapper`

## Big picture architecture
- This is a Django project (`scraper/settings.py`) with app boundaries: `bazos` (scraping + domain), `ip_changer` (network identity rotation), `senders` (delivery), and `facebook` (publisher linking).
- Primary runtime path is `python manage.py run_scraper` -> `bazos/management/commands/run_scraper.py` -> `bazos/scraping/bazos_runner.py` -> `BazosQueryRunner` -> `BazosScraper`.
- Scraping is query-driven from DB models (`bazos/models.py`): `Query` defines what to search, `Ad` stores discoveries, `QueryRun` stores run metrics.
- `Query.new_query` controls first-run behavior; first pass uses capped backfill (`NEW_PRODUCT_LOAD_MAX`) and may suppress sends via `ignore_first_run`.
- Existing-query flow stops on first non-TOP already-known ad (`bazos/scraping/bazos_query_runner.py`), assuming results are ordered newest-first.

## Runtime and workflow commands
- Local dev is Django-first, not `main.py` (README has stale sections). Use:
  - `python manage.py migrate`
  - `python manage.py runserver`
  - `python manage.py run_scraper` (infinite loop)
- Safer debugging for crashes: `python manage.py run_scraper --unsafe` to let exceptions fail fast instead of being swallowed by the outer loop.
- Seed taxonomy before meaningful scraping:
  - `python manage.py create_sections`
  - `python manage.py create_categories`
- Tests are minimal and pytest-based (`pytest.ini` sets `DJANGO_SETTINGS_MODULE=scraper.settings`): run `pytest`.

## Project-specific coding patterns
- Preserve DB invariants in `Query` (`price_lower <= price_upper` and mutually exclusive `section`/`category` check in model constraints).
- Keep URL behavior aligned with model helpers (`Section.full_url`, `Category.full_url`, `Query.url`) instead of rebuilding URLs ad hoc.
- New ads are identified per query by `(query, bazos_id)` lookup in code (no DB unique constraint yet); avoid introducing logic that assumes global uniqueness.
- Message delivery expects `SendableMixin`-style objects (`message`, `link`), used by `DiscordSender.send_sendable`.
- Output/log lines are frequently ASCII-sanitized (`encode('ascii', 'ignore')`) to avoid terminal/webhook encoding issues.

## Integration points and dependencies
- PostgreSQL is the active default DB backend (`scraper/settings.py`); SQLite config exists but is commented out.
- Environment is loaded from `.env`; start from `.env.sample`. Critical vars: `SECRET_KEY`, `POSTGRES_*`, `TOR_PROXY_IP`, `TOR_PROXY_PASSWORD`, `LOCAL_IP_SUBNET`.
- IP rotation strategy is selected by `IP_CHANGER_TYPE` (`TOR` default, `DUMMY` for no-op) in `BazosRunner`.
- Tor path: HTTP requests use SOCKS proxy (`ip_changer/tor.py`), and identity changes via Stem control port 9051.
- Optional infra in `docker-compose.yml`: `postgres`, `adminer`, `tor_proxy`; scraper container entries are currently commented out.

## Change guidance for AI agents
- For scraping changes, update both URL generation and pagination semantics in `BazosScraper` (`create_url_*`, `run_query`) and validate against `test_gen_url.py`.
- For notification changes, preserve sender model-to-service mapping (`DiscordSender.from_model`) and webhook rate-limit retry behavior.
- For loop/control-flow edits, explicitly reason about blacklist checks (`check_bazos_blacklisted`) and local-IP guard (`check_ip_local`) to avoid accidental hot loops.
- Prefer targeted, small changes: this repo contains legacy/experimental files (`old_tests/`, notebooks, stale Dockerfile path to `main.py`).