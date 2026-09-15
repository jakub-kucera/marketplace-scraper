FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Pinned: poetry writes and reads the lock format, so an unpinned `pip install poetry`
# makes the image depend on whatever released most recently. poetry.lock is generated
# by this version.
RUN pip install poetry==2.4.1

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-root --no-interaction --no-ansi

CMD ["python", "manage.py", "run_scraper"]
