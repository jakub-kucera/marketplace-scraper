# How to run:

## a) Setup using venv:

(Python 3.9 is preferable, but 3.8 should work, probably also 3.7)

1.     python -m venv venv
2.     source venv/bin/activate
3.     pip install -r requirements.txt

## b) Setup using conda:

1.     conda env update
2.     conda activate rtree

## Run CLI interface:

    python main.py

## Run tests:

    pytest

### Run code checkers

    pylint .
    mypy -p .# chip-facebook-post-maker


    python manage.py runserver
    python manage.py run_scraper

## Deployment (Raspberry Pi via GitHub Actions)

Services run in Docker Compose on the Pi: `marketplace_scraper`, `marketplace_server`, `postgres`, `tor_proxy`, `adminer`.

Deploying is done by pushing a `v*` tag — the GitHub Actions workflow (`.github/workflows/deploy.yml`) runs on a self-hosted runner installed on the Pi, builds images, runs migrations, and restarts all services.

```bash
git tag v1.0.0 && git push origin v1.0.0
```

**One-time runner setup on the Pi:**

1. Go to repo → Settings → Actions → Runners → New self-hosted runner (Linux / ARM64) and follow the install steps. Accept all defaults (work folder can be left as `_work` — the workflow operates directly on `/home/user/marketplace-scrapper` and doesn't use it).
2. Install as a service:
   ```bash
   sudo ./svc.sh install && sudo ./svc.sh start
   ```
3. Add the runner user to the docker group:
   ```bash
   sudo usermod -aG docker $USER
   ```
