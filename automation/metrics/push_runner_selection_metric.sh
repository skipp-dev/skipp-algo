#!/usr/bin/env bash
# Durably record one CI runner-selection event onto a dedicated metrics branch.
#
# Why a separate branch: the runner-selection decision happens on every routed
# workflow run, but GitHub Actions runs are ephemeral. To build an *aggregate*
# counter across runs we need durable storage. Committing to the default branch
# would spam its history, so we keep an append-only JSON-Lines ledger on an
# orphan ``metrics/runner-selection`` branch instead.
#
# This script is designed to run from inside a workflow checkout that already
# has push credentials configured by ``actions/checkout`` (it reuses ``origin``
# rather than re-cloning, so the ambient token is honoured). A metrics write
# must NEVER fail the surrounding workflow — callers should invoke it with
# ``continue-on-error: true``.
#
# Required environment:
#   REASON                resolver reason (e.g. matched_idle_self_hosted_runner)
#   RUNNER_ENVIRONMENT    self-hosted | github-hosted
# Optional environment:
#   MATCHED_RUNNER_NAME   name of the matched self-hosted runner (may be empty)
#   WORKFLOW              workflow name (e.g. github.workflow)
#   EVENT_NAME            triggering event (e.g. schedule / workflow_dispatch)
#   RUN_ID                GitHub run id
#   METRICS_BRANCH        default: metrics/runner-selection
#   PYTHON_BIN            default: python3
#   GIT_AUTHOR_NAME/EMAIL default: skippalgo-bot / bot@skippalgo.local

set -euo pipefail

METRICS_BRANCH="${METRICS_BRANCH:-metrics/runner-selection}"
METRICS_FILE_REL="metrics/runner_selection.jsonl"
SUMMARY_FILE_REL="metrics/runner_selection_summary.md"
PY="${PYTHON_BIN:-python3}"
GIT_NAME="${GIT_AUTHOR_NAME:-skippalgo-bot}"
GIT_EMAIL="${GIT_AUTHOR_EMAIL:-bot@skippalgo.local}"
MAX_ATTEMPTS=5

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
METRICS_SCRIPT="${REPO_DIR}/scripts/runner_selection_metrics.py"

if [[ -z "${REASON:-}" || -z "${RUNNER_ENVIRONMENT:-}" ]]; then
    echo "push_runner_selection_metric: REASON and RUNNER_ENVIRONMENT are required" >&2
    exit 2
fi

WORKDIR="$(mktemp -d)"
MB="${WORKDIR}/mb"
cleanup() {
    git -C "${REPO_DIR}" worktree remove --force "${MB}" >/dev/null 2>&1 || true
    rm -rf "${WORKDIR}"
}
trap cleanup EXIT

append_and_commit() {
    "${PY}" "${METRICS_SCRIPT}" append \
        --metrics-file "${MB}/${METRICS_FILE_REL}" \
        --summary-md "${MB}/${SUMMARY_FILE_REL}" \
        --reason "${REASON}" \
        --runner-environment "${RUNNER_ENVIRONMENT}" \
        --matched-runner-name "${MATCHED_RUNNER_NAME:-}" \
        --workflow "${WORKFLOW:-}" \
        --event-name "${EVENT_NAME:-}" \
        --run-id "${RUN_ID:-}" >/dev/null
    git -C "${MB}" add "${METRICS_FILE_REL}" "${SUMMARY_FILE_REL}"
    git -C "${MB}" -c "user.name=${GIT_NAME}" -c "user.email=${GIT_EMAIL}" \
        commit --quiet -m "metrics(runner): ${RUNNER_ENVIRONMENT} selection (${REASON}) [skip ci]"
}

attempt=0
while :; do
    attempt=$((attempt + 1))
    git -C "${REPO_DIR}" worktree remove --force "${MB}" >/dev/null 2>&1 || true
    rm -rf "${MB}"

    if git -C "${REPO_DIR}" fetch --quiet origin "${METRICS_BRANCH}" 2>/dev/null; then
        git -C "${REPO_DIR}" worktree add --quiet --detach "${MB}" FETCH_HEAD
    else
        # Branch does not exist yet → start an orphan with an empty tree.
        git -C "${REPO_DIR}" worktree add --quiet --detach "${MB}"
        git -C "${MB}" checkout --quiet --orphan "${METRICS_BRANCH}"
        git -C "${MB}" rm -rfq --cached . >/dev/null 2>&1 || true
        find "${MB}" -mindepth 1 -maxdepth 1 -not -name '.git' -exec rm -rf {} +
    fi

    append_and_commit

    if git -C "${MB}" push --quiet origin "HEAD:${METRICS_BRANCH}" 2>/dev/null; then
        echo "recorded runner-selection metric on ${METRICS_BRANCH} (attempt ${attempt})"
        break
    fi

    if [[ "${attempt}" -ge "${MAX_ATTEMPTS}" ]]; then
        echo "push_runner_selection_metric: push failed after ${MAX_ATTEMPTS} attempts" >&2
        exit 1
    fi
    sleep "$((attempt * 2 + RANDOM % (attempt + 1)))"
done
