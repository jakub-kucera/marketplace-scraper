"""The Pi runner's job-started hook - the one check on that runner a pull request cannot rewrite.

The repo is public and the Pi that runs production is its self-hosted runner. A pull_request run
uses the PR's own copy of the workflow, so a PR can point any job at `runs-on: self-hosted`. The
hook runs on the runner before any step, and a non-zero exit fails the job, so it is the boundary.
Every case that should be refused is a separate test, because the failure being guarded against
is a refusal that silently stopped happening.

No database and no network: this runs the shipped script under bash.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "runner" / "job-started.sh"

OWNER = "jakub-kucera"
OWNER_DISPATCH_ON_MAIN = {
    "GITHUB_REPOSITORY": f"{OWNER}/marketplace-scraper",
    "GITHUB_EVENT_NAME": "workflow_dispatch",
    "GITHUB_REF": "refs/heads/main",
    "GITHUB_ACTOR": OWNER,
    "GITHUB_TRIGGERING_ACTOR": OWNER,
}


def run_guard(**overrides: str | None) -> subprocess.CompletedProcess:
    """Run the hook the way the runner does (`bash -e`), with only the variables given."""
    variables = {**OWNER_DISPATCH_ON_MAIN, **overrides}
    env = {"PATH": os.environ["PATH"], **{k: v for k, v in variables.items() if v is not None}}
    return subprocess.run(
        ["bash", "-e", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10
    )


@pytest.mark.parametrize(
    "event, ref",
    [
        ("workflow_dispatch", "refs/heads/main"),  # contract check, run by hand
        ("schedule", "refs/heads/main"),  # contract check, weekly
        ("push", "refs/tags/v1.14.0"),  # deploy
    ],
)
def test_allows_the_owners_own_jobs(event, ref):
    result = run_guard(GITHUB_EVENT_NAME=event, GITHUB_REF=ref)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "overrides, reason",
    [
        # The attack this exists for: a PR that edits a workflow to run here.
        ({"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/pull/7/merge"}, "event"),
        # Refused on the event alone, even with a ref that would otherwise pass.
        ({"GITHUB_EVENT_NAME": "pull_request", "GITHUB_REF": "refs/heads/main"}, "event"),
        ({"GITHUB_EVENT_NAME": "pull_request_target"}, "event"),
        ({"GITHUB_EVENT_NAME": "issue_comment"}, "event"),
        ({"GITHUB_EVENT_NAME": "workflow_run"}, "event"),
        ({"GITHUB_EVENT_NAME": "repository_dispatch"}, "event"),
        ({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/heads/feature"}, "ref"),
        ({"GITHUB_REF": "refs/heads/feature"}, "ref"),
        ({"GITHUB_REF": "refs/heads/main-evil"}, "ref"),
        ({"GITHUB_EVENT_NAME": "push", "GITHUB_REF": "refs/tags/release-1"}, "ref"),
        # A collaborator with write access is not the owner.
        ({"GITHUB_ACTOR": "jirkovsky", "GITHUB_TRIGGERING_ACTOR": "jirkovsky"}, "actor"),
        ({"GITHUB_ACTOR": f"{OWNER}-evil", "GITHUB_TRIGGERING_ACTOR": f"{OWNER}-evil"}, "actor"),
        # A re-run keeps the original actor; the triggering actor is who clicked re-run.
        ({"GITHUB_TRIGGERING_ACTOR": "jirkovsky"}, "actor"),
        ({"GITHUB_REPOSITORY": "someone/marketplace-scraper"}, "repository"),
        ({"GITHUB_REPOSITORY": f"{OWNER}/marketplace-scraper-fork"}, "repository"),
    ],
)
def test_refuses(overrides, reason):
    result = run_guard(**overrides)

    assert result.returncode != 0
    # The first line only: the lines after it print every variable, so any reason would match there.
    assert result.stderr.splitlines()[0] == f"runner-guard: refusing this job: wrong {reason}"


@pytest.mark.parametrize("missing", sorted(OWNER_DISPATCH_ON_MAIN))
def test_fails_closed_when_a_variable_is_missing(missing):
    """If a runner upgrade stopped passing a variable to hooks, the answer must be "no"."""
    result = run_guard(**{missing: None})

    assert result.returncode != 0
    assert result.stderr.startswith("runner-guard: refusing this job: wrong ")
