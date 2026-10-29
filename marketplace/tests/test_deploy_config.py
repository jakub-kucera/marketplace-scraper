"""Guards on how the stack comes back after a reboot.

On 2026-10-16 the Pi rebooted and stayed down for 22 hours. dockerd restarted every
`restart: always` container, but `postgres` had no policy, so the app containers came up
unable to resolve it. A leftover systemd unit then ran the apt `docker-compose` 1.29.2,
which names images differently from the v2 plugin `deploy.yml` builds with, and started
scraper, filter and sender on July's Python 3.11 images - a crashloop on
`No module named 'unfold'`. Neither half fails anywhere but on the Pi, so they are tested here.

No database and no network: this reads the repo's own config files.
"""
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO / "docker-compose.yml"


@pytest.fixture(scope="module")
def services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


def test_every_long_running_service_restarts_on_boot(services):
    """dockerd's restart policy is the only thing that brings the stack back after a reboot.
    Profiled services are one-shot tasks (`backup`) and must not restart."""
    missing = [
        name for name, spec in services.items()
        if not spec.get("profiles") and spec.get("restart") not in ("always", "unless-stopped")
    ]

    assert missing == []


def test_no_repo_script_reaches_compose_v1():
    """Directly, or through the unit that wraps it - `deploy.sh` did the latter."""
    offenders = [
        path.relative_to(REPO).as_posix()
        for path in [*REPO.glob("*.sh"), *(REPO / ".github" / "workflows").glob("*.yml")]
        if "docker-compose " in (text := path.read_text(encoding="utf-8"))
        or "start marketplace-docker" in text
    ]

    assert offenders == []
