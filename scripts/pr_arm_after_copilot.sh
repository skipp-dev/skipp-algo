#!/usr/bin/env bash
# pr_arm_after_copilot.sh — wait for Copilot's first review, then arm SQUASH auto-merge.
#
# Background: Copilot does not auto-re-review after `git push`. When you arm
# `gh pr merge --auto` immediately after PR creation, the PR can squash before
# Copilot has emitted its first review — actionable inline comments are then
# silently lost.
#
# Wait constant: 8 minutes (p95 + 20% margin from 30-PR latency dataset).
# See docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md §5.9 for derivation.
#
# Usage:
#   scripts/pr_arm_after_copilot.sh <pr-number> [--method squash|merge|rebase]
#
# Behaviour:
#   1. Polls every 30s for up to 8 minutes for the first Copilot review.
#   2. As soon as a Copilot review appears, arms auto-merge with the chosen method.
#   3. If no Copilot review after 8 minutes, arms auto-merge anyway (timeout-safe).
#   4. Exits non-zero on `gh` errors (auth, rate-limit, missing PR) instead of
#      silently waiting the full 8 minutes.

set -euo pipefail

# Require `gh` to be available before we promise the user we will arm auto-merge.
if ! command -v gh >/dev/null 2>&1; then
  echo "[pr_arm_after_copilot] error: 'gh' CLI not found in PATH" >&2
  exit 3
fi

# Require `git` too, otherwise the rev-parse below would fail with a misleading
# "not a git work tree" message (the failing `git` lookup is indistinguishable
# from a non-repo directory).
if ! command -v git >/dev/null 2>&1; then
  echo "[pr_arm_after_copilot] error: 'git' not found in PATH" >&2
  exit 3
fi

# Anchor to the repo root containing this script so it works no matter the
# caller's CWD (the script may be invoked via absolute path from anywhere).
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
if ! git -C "${REPO_ROOT}" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "[pr_arm_after_copilot] error: ${REPO_ROOT} is not a git work tree" >&2
  exit 3
fi
cd "${REPO_ROOT}"

PR_NUMBER="${1:-}"
METHOD="squash"

if [[ -z "${PR_NUMBER}" ]]; then
  echo "usage: $0 <pr-number> [--method squash|merge|rebase]" >&2
  exit 2
fi

shift
while [[ $# -gt 0 ]]; do
  case "$1" in
    --method)
      # Guard against `--method` being the trailing arg (set -e + `shift 2`
      # without an arg would exit silently; explicit error is friendlier).
      if [[ $# -lt 2 ]]; then
        echo "[pr_arm_after_copilot] error: --method requires an argument" >&2
        exit 2
      fi
      METHOD="$2"
      shift 2
      ;;
    *)
      echo "[pr_arm_after_copilot] error: unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

case "${METHOD}" in
  squash|merge|rebase) ;;
  *) echo "[pr_arm_after_copilot] error: invalid --method: ${METHOD}" >&2 ; exit 2 ;;
esac

WAIT_SECONDS=480       # 8 minutes — p95+20% from docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md §5.9
POLL_INTERVAL=30
elapsed=0

echo "[pr_arm_after_copilot] Waiting up to ${WAIT_SECONDS}s for Copilot review on PR #${PR_NUMBER}..."

while (( elapsed < WAIT_SECONDS )); do
  # Surface real `gh` errors (auth, rate-limit, missing PR) instead of
  # treating them as "no review yet" — those would waste the full 8-minute
  # wait and then call `gh pr merge` against an unreachable PR.
  poll_err=$(mktemp)
  copilot_review=$(gh pr view "${PR_NUMBER}" --json reviews \
    --jq '[.reviews[] | select(.author.login | test("opilot";"i"))] | length' \
    2>"${poll_err}" || true)
  if [[ -s "${poll_err}" ]]; then
    echo "[pr_arm_after_copilot] gh error during poll (PR #${PR_NUMBER}):" >&2
    cat "${poll_err}" >&2
    rm -f "${poll_err}"
    exit 4
  fi
  rm -f "${poll_err}"

  copilot_review="${copilot_review:-0}"
  if [[ "${copilot_review}" =~ ^[0-9]+$ ]] && (( copilot_review > 0 )); then
    echo "[pr_arm_after_copilot] Copilot review detected after ${elapsed}s. Arming auto-merge (${METHOD})."
    exec gh pr merge "${PR_NUMBER}" "--${METHOD}" --delete-branch --auto
  fi

  sleep "${POLL_INTERVAL}"
  elapsed=$(( elapsed + POLL_INTERVAL ))
done

echo "[pr_arm_after_copilot] Timeout (${WAIT_SECONDS}s) reached without Copilot review. Arming auto-merge anyway (${METHOD})."
exec gh pr merge "${PR_NUMBER}" "--${METHOD}" --delete-branch --auto
