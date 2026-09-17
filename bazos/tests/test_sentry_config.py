"""Guards on how Sentry is labelled — the settings defaults and the deploy-time stamp.

Neither half fails loudly when it breaks, which is why they are tested. Sentry defaults
`environment` to "production" when none is given, so *removing* configuration silently
relabels every event rather than erroring: in one measured 24h window, six of ten
"production" issues were really `manage.py shell` sessions against a dev database. The
deploy step is the same shape of hazard — delete it and the Pi reverts to reporting itself
as "development", with nothing anywhere going red.

No database and no network: this reads the repo's own config files.
"""
from pathlib import Path

import pytest
import yaml
from django.conf import settings

REPO = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"
ENV_SAMPLE = REPO / ".env.sample"


@pytest.fixture(scope="module")
def deploy_steps() -> list[dict]:
    workflow = yaml.safe_load(DEPLOY_WORKFLOW.read_text(encoding="utf-8"))
    jobs = workflow["jobs"]
    assert len(jobs) == 1, "deploy.yml grew a second job; this fixture picks the only one"
    return list(jobs.values())[0]["steps"]


def _step_named(steps: list[dict], fragment: str) -> tuple[int, dict]:
    for index, step in enumerate(steps):
        if fragment.lower() in str(step.get("name", "")).lower():
            return index, step
    raise AssertionError(f"no deploy step whose name contains {fragment!r}")


# ---------------------------------------------------------------------------
# settings.py
# ---------------------------------------------------------------------------

def test_settings_expose_both_sentry_labels():
    assert isinstance(settings.SENTRY_ENVIRONMENT, str)
    assert isinstance(settings.SENTRY_RELEASE, str)


def test_environment_does_not_default_to_production():
    """The whole point. An unconfigured machine must not claim to be the Pi, and the test
    suite is exactly such a machine — nothing here sets SENTRY_ENVIRONMENT.
    """
    assert settings.SENTRY_ENVIRONMENT != "production"


def test_env_sample_documents_both_variables():
    sample = ENV_SAMPLE.read_text(encoding="utf-8")

    assert "SENTRY_ENVIRONMENT=" in sample
    assert "SENTRY_RELEASE=" in sample


# ---------------------------------------------------------------------------
# deploy.yml — the only thing that marks a run "production"
# ---------------------------------------------------------------------------

def test_deploy_stamps_environment_and_release(deploy_steps):
    _, step = _step_named(deploy_steps, "Stamp the release")
    script = step["run"]

    assert "SENTRY_ENVIRONMENT=production" in script
    assert "SENTRY_RELEASE=%s" in script and "github.ref_name" in script


def test_deploy_stamp_is_idempotent(deploy_steps):
    """Re-deploying a tag must not append a second copy of each key."""
    _, step = _step_named(deploy_steps, "Stamp the release")

    assert "sed -i" in step["run"] and "/^SENTRY_ENVIRONMENT=/d" in step["run"]


def test_stamp_happens_before_the_services_start(deploy_steps):
    """Containers read `env_file: .env` at create time, so a stamp written afterwards
    would not reach the process until some later restart."""
    stamp_index, _ = _step_named(deploy_steps, "Stamp the release")
    start_index, _ = _step_named(deploy_steps, "Start all services")

    assert stamp_index < start_index
