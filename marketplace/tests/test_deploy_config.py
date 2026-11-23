"""Guards on the Pi's deploy path: how the stack comes back after a reboot, and which tags deploy.

On 2026-10-16 the Pi rebooted and stayed down for 22 hours. dockerd restarted every
`restart: always` container, but `postgres` had no policy, so the app containers came up
unable to resolve it. A leftover systemd unit then ran the apt `docker-compose` 1.29.2,
which names images differently from the v2 plugin `deploy.yml` builds with, and started
scraper, filter and sender on July's Python 3.11 images - a crashloop on
`No module named 'unfold'`. Neither half fails anywhere but on the Pi, so they are tested here.

No database and no network: this reads the repo's own config files.
"""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO / "docker-compose.yml"
DEPLOY_WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"
TAG_GUARD_STEP = "Refuse a tag that is not on main"


@pytest.fixture(scope="module")
def services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


@pytest.fixture(scope="module")
def deploy_steps() -> list[dict]:
    jobs = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    assert len(jobs) == 1, "deploy.yml grew a second job; this fixture picks the only one"
    return list(jobs.values())[0]["steps"]


def _index_of_step(steps: list[dict], predicate) -> int:
    for index, step in enumerate(steps):
        if predicate(step):
            return index
    raise AssertionError("no deploy step matches")


def _git(cwd: Path, *args: str) -> None:
    # Isolated from the developer's git config, so commit signing or hooks cannot leak in.
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd, env=env, check=True, capture_output=True,
    )


@pytest.fixture(scope="module")
def deploy_clone(tmp_path_factory) -> Path:
    """A clone shaped like the Pi's after the fetch step: `origin/main` plus every tag.

    main has moved on since the tags on it were made, so passing them also covers redeploying an
    older release - the rollback path the guard must not break.
    """
    root = tmp_path_factory.mktemp("deploy")
    origin, work, clone = root / "origin.git", root / "work", root / "clone"
    _git(root, "init", "--bare", "-b", "main", str(origin))
    _git(root, "init", "-b", "main", str(work))
    _git(work, "commit", "--allow-empty", "-m", "release")
    _git(work, "tag", "v1.0.0")
    _git(work, "tag", "-a", "v1.0.1", "-m", "annotated, as a tag object rather than a commit")
    _git(work, "checkout", "-b", "side")
    _git(work, "commit", "--allow-empty", "-m", "never merged")
    _git(work, "tag", "v9.9.9")
    _git(work, "checkout", "main")
    _git(work, "commit", "--allow-empty", "-m", "main moves on")
    _git(work, "push", str(origin), "main", "side", "--tags")
    _git(root, "clone", str(origin), str(clone))
    return clone


@pytest.mark.parametrize(
    "tag, deploys",
    [("v1.0.0", True), ("v1.0.1", True), ("v9.9.9", False), ("v0.0.0-missing", False)],
)
def test_deploy_refuses_a_tag_that_is_not_on_main(deploy_steps, deploy_clone, tag, deploys):
    """Runs the shipped step, with GitHub's default shell for `run:` (`bash -e`)."""
    step = deploy_steps[_index_of_step(deploy_steps, lambda s: s.get("name") == TAG_GUARD_STEP)]
    env = {"PATH": os.environ["PATH"], "GITHUB_REF": f"refs/tags/{tag}"}

    result = subprocess.run(
        ["bash", "-e", "-c", step["run"]], cwd=deploy_clone, env=env, capture_output=True, timeout=30
    )

    assert (result.returncode == 0) is deploys, result.stdout + result.stderr


def test_tag_is_checked_after_the_fetch_and_before_the_checkout(deploy_steps):
    """Before the fetch, `origin/main` is stale and a new release would be refused. After the
    checkout, it is too late: every service bind-mounts this directory, so a checkout is already
    a deploy."""
    guard = _index_of_step(deploy_steps, lambda s: s.get("name") == TAG_GUARD_STEP)
    fetch = _index_of_step(deploy_steps, lambda s: "git fetch" in s.get("run", ""))
    checkout = _index_of_step(deploy_steps, lambda s: "git checkout" in s.get("run", ""))

    assert fetch < guard < checkout


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
