#!/usr/bin/env bash
# Job-started hook for the Pi's self-hosted runner. Refuses every job the owner did not start
# from main or a v* tag.
#
# The repo is public and the Pi runs production. A pull_request run uses the PR's own copy of
# the workflow, so any PR can point a job at `runs-on: self-hosted`, and a check written into
# a workflow file would be deleted by the very PR it is meant to stop. This hook lives on the
# runner, where no PR can reach it, and a non-zero exit fails the job before any step runs.
#
# Install outside actions-runner/ (GitHub's advice) and root-owned, so a job cannot edit it:
#   sudo install -D -o root -g root -m 755 runner/job-started.sh /opt/runner-guard/job-started.sh
#   echo 'ACTIONS_RUNNER_HOOK_JOB_STARTED=/opt/runner-guard/job-started.sh' >> ~/actions-runner/.env
#   sudo ~/actions-runner/svc.sh stop && sudo ~/actions-runner/svc.sh start   # .env is read at start
set -u

OWNER="jakub-kucera"
REPOSITORY="jakub-kucera/marketplace-scraper"

refuse() {
    {
        echo "runner-guard: refusing this job: wrong $1"
        echo "  repository=${GITHUB_REPOSITORY:-} event=${GITHUB_EVENT_NAME:-} ref=${GITHUB_REF:-}"
        echo "  actor=${GITHUB_ACTOR:-} triggering_actor=${GITHUB_TRIGGERING_ACTOR:-}"
    } >&2
    exit 1
}

[ "${GITHUB_REPOSITORY:-}" = "$REPOSITORY" ] || refuse "repository"

case "${GITHUB_EVENT_NAME:-}" in
    push | schedule | workflow_dispatch) ;;
    *) refuse "event" ;;
esac

case "${GITHUB_REF:-}" in
    refs/heads/main | refs/tags/v*) ;;
    *) refuse "ref" ;;
esac

# Both: a re-run keeps the original actor, and the triggering actor is whoever clicked re-run.
[ "${GITHUB_ACTOR:-}" = "$OWNER" ] || refuse "actor"
[ "${GITHUB_TRIGGERING_ACTOR:-}" = "$OWNER" ] || refuse "actor"

echo "runner-guard: allowed ${GITHUB_EVENT_NAME} on ${GITHUB_REF} by ${GITHUB_ACTOR}"
