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
#   4. Exits non-zero only if `gh pr merge` itself fails.

set -euo pipefail

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
      METHOD="${2:-squash}"
      shift 2
      ;;
    *)
      echo "unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

case "${METHOD}" in
  squash|merge|rebase) ;;
  *) echo "invalid --method: ${METHOD}" >&2 ; exit 2 ;;
esac

WAIT_SECONDS=480       # 8 minutes — p95+20% from docs/COPILOT_REVIEW_TRIAGE_PROTOCOL.md §5.9
POLL_INTERVAL=30
elapsed=0

echo "[pr_arm_after_copilot] Waiting up to ${WAIT_SECONDS}s for Copilot review on PR #${PR_NUMBER}..."

while (( elapsed < WAIT_SECONDS )); do
  copilot_review=$(gh pr view "${PR_NUMBER}" --json reviews \
    --jq '[.reviews[] | select(.author.login | test("opilot";"i"))] | length' 2>/dev/null || echo "0")

  if [[ "${copilot_review}" -gt 0 ]]; then
    echo "[pr_arm_after_copilot] Copilot review detected after ${elapsed}s. Arming auto-merge (${METHOD})."
    exec gh pr merge "${PR_NUMBER}" "--${METHOD}" --delete-branch --auto
  fi

  sleep "${POLL_INTERVAL}"
  elapsed=$(( elapsed + POLL_INTERVAL ))
done

echo "[pr_arm_after_copilot] Timeout (${WAIT_SECONDS}s) reached without Copilot review. Arming auto-merge anyway (${METHOD})."
exec gh pr merge "${PR_NUMBER}" "--${METHOD}" --delete-branch --auto
