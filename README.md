# Marketplace Scraper

[![tests](https://github.com/jakub-kucera/marketplace-scraper/actions/workflows/test.yml/badge.svg)](https://github.com/jakub-kucera/marketplace-scraper/actions/workflows/test.yml)

A Django application that watches online marketplaces for new listings, filters them against
saved searches, and sends matches to Discord. Built around the Czech classifieds site
[Bazos.cz](https://bazos.cz), with a marketplace-abstraction layer extended to Vinted and Sbazar.

Built for personal, non-commercial market monitoring - not a commercial scraping service.

## What it does

- Polls saved searches (`Query` rows) against one or more marketplaces, routed through Tor for
  IP rotation.
- Detects new and price-changed listings and runs them through a configurable rule engine -
  price range, keywords, seller blocklist, location radius, price drops, and an optional price
  model.
- Delivers approved matches to Discord via webhook, with per-query routing and a periodic
  summary digest.
- Tracks delisting over time (`manage.py check_delisted`) - the only outcome signal the project
  has, used to judge how a listing's life ends.
- Optional, off by default per query: a linear price model scored against listing text, LLM-based
  spec extraction (Gemini/Anthropic, `NULL` provider with no key configured), and reference
  pricing pulled from Zboží.cz.

## Architecture

```
run_scraper  ->  scrape queries, dedup, write Ad + AdDelivery(PENDING)
run_filter   ->  PENDING / PRICE_CHANGED -> APPROVED | REJECTED
run_sender   ->  APPROVED -> SENT | FAILED  (Discord)
```

Three independent long-running processes communicate entirely through `AdDelivery.status`, a
queue kept in Postgres - no message broker. A background worker (`django-q2`, also backed by
Postgres) runs scheduled jobs: the delisting sweep, a pipeline watchdog, catalog syncs, log
pruning, and on-demand enrichment triggered from the admin.

The full architecture, data model, and every deliberate design decision (with the trap it avoids)
is written up in [`CLAUDE.md`](CLAUDE.md) - it is the primary reference for working in this
codebase, not just agent instructions.

## Stack

Django 5.2, Python 3.12, Postgres, Docker Compose, Tor (SOCKS proxy for IP rotation), django-q2
for background jobs, django-unfold for the admin theme, Poetry for dependencies.

## Getting started

```bash
poetry install
cp .env.sample .env        # SECRET_KEY has no default - everything else does

docker compose up -d postgres tor_proxy

python manage.py migrate
python manage.py create_sections
python manage.py create_categories

python manage.py runserver        # admin UI at /admin/
python manage.py run_scraper      # each in its own terminal
python manage.py run_filter
python manage.py run_sender
```

Or run the full stack - scraper, filter, sender, qcluster, the admin server, Postgres, Tor, and
Adminer - in Docker:

```bash
docker compose up -d
```

See [`CLAUDE.md`](CLAUDE.md) for the complete command reference, one-off management commands, and
every environment variable and its default.

## Testing

```bash
docker compose up -d postgres
pytest            # real Postgres, not SQLite - Postgres-only behavior is part of what's tested
ruff check .
mypy .
```

## Deployment

`.github/workflows/deploy.yml` deploys to a self-hosted runner on every pushed `v*` tag: build,
verify the built image, back up the database, migrate, restart.

```bash
git tag v1.2.3 && git push origin v1.2.3
```

## Documentation

- [`CLAUDE.md`](CLAUDE.md) - architecture, commands, the data model, and every deliberate design
  decision this codebase encodes.
- [`docs/`](docs/README.md) - research findings, shipped specs, and the open backlog, organized by
  lifecycle (`active` / `proposal` / `reference` / `shipped` / `superseded`) rather than by date.

## License

No license is granted. All rights reserved.
