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

from scraper.sentry import before_send, should_report

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


# ---------------------------------------------------------------------------
# scraper/sentry.py — what is reported, and how it groups
# ---------------------------------------------------------------------------

def _django_q_event(message: str) -> dict:
    return {"logger": "django-q", "logentry": {"message": message, "params": []}}


@pytest.mark.parametrize("first, second", [
    ("Q Cluster south-avocado-maine-dakota failed to start. Sentinel exited with exit code 1.",
     "Q Cluster idaho-bravo-ten-arizona failed to start. Sentinel exited with exit code 1."),
    ("Failed 'bazos.jobs.compare_bazos_scrapers' (eight-happy-whiskey-yankee) - Task exceeded "
     "maximum timeout value (1800 seconds) : Traceback (most recent call last):\n  File x",
     "Failed 'bazos.jobs.compare_bazos_scrapers' (hamper-solar-kilo-carbon) - Task exceeded "
     "maximum timeout value (1800 seconds) : Traceback (most recent call last):\n  File y"),
    ("reincarnated worker Process-a286513a4fb34580b2639398c7a3dbd2 after timeout",
     "reincarnated worker Process-846a82802e9b4181bd88b164f226814e after timeout"),
], ids=["cluster-name", "task-name", "process-id"])
def test_django_q_names_do_not_split_one_failure_into_many_issues(first, second):
    """django-q formats a random name into each message, so Sentry opened 12 issues for
    one failed cluster start and 5 for one weekly timeout."""
    a = before_send(_django_q_event(first), {})["fingerprint"]
    b = before_send(_django_q_event(second), {})["fingerprint"]

    assert a == b


def test_different_jobs_still_group_apart():
    template = "Failed '{}' (eight-happy-whiskey-yankee) - boom"
    a = before_send(_django_q_event(template.format("bazos.jobs.heartbeat")), {})["fingerprint"]
    b = before_send(_django_q_event(template.format("bazos.jobs.score_ad")), {})["fingerprint"]

    assert a != b


def test_other_events_keep_sentrys_own_grouping():
    event = {"logger": "bazos.scraping.runner", "logentry": {"message": "Query %s failed"}}

    assert "fingerprint" not in before_send(event, {})


@pytest.mark.parametrize("argv, expected", [
    (["manage.py", "run_scraper"], True),
    (["manage.py", "qcluster"], True),
    (["manage.py", "shell"], False),
    (["manage.py", "dbshell"], False),
    (["manage.py"], True),
], ids=["daemon", "cluster", "shell", "dbshell", "bare"])
def test_interactive_shells_do_not_report(argv, expected):
    """A typo in `manage.py shell` inside a Pi container was reported as a production error."""
    assert should_report("https://key@sentry.test/1", argv, running_tests=False) is expected


def test_nothing_reports_without_a_dsn_or_under_pytest():
    assert should_report("", ["manage.py", "run_scraper"], running_tests=False) is False
    assert should_report("https://key@sentry.test/1", ["manage.py", "run_scraper"], running_tests=True) is False
