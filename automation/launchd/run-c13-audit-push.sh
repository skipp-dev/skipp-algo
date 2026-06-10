#!/usr/bin/env bash
# C13 Phase-A — daily local cron driver to push audit artefacts to the
# dedicated `data/phase-a-audit` branch (keeps cron-bot churn off main).
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.audit-push.plist
# on Mon-Fri @ 17:30 local time (one hour after US-equity close).
#
# Repo policy: never --force, never --no-verify. Branch is protected on
# the remote; pushes use the same PAT-authenticated origin as the local
# `git push` (gh CLI keyring credentials are reused by git).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DATE="$(date -u +%Y-%m-%d)"

cd "${REPO}"

AUDIT="cache/live/incubation_${DATE}.jsonl"
SETUPS="cache/live/setups_${DATE}.jsonl"
GATES="cache/live/gate_status.json"

# Status marker so a degraded run is DETECTABLE rather than silently green.
# Written on every exit path (degraded:* or ok:*). cache/live is gitignored
# on main, so the marker never enters a commit.
STATUS_MARKER="cache/live/.audit_push_status_${DATE}"
mkdir -p cache/live 2>/dev/null || true

if [[ ! -f "${AUDIT}" ]]; then
    echo "audit-push: DEGRADED — no audit artefact at ${AUDIT}. Phase-A produced no" \
         "incubation file today; check com.skippalgo.c13.phase-a (Full-Disk-Access/TCC," \
         "venv path, or upstream trade-cards). Nothing pushed." >&2
    echo "degraded:no-audit-file:$(date -u +%FT%TZ)" > "${STATUS_MARKER}" || true
    exit 0
fi

# Publish the audit artefacts onto data/phase-a-audit via the shared
# isolated-worktree helper (audit pass-3 finding A1). The helper owns the
# hardened push pipeline — stale-worktree prune (R1), detached checkout so
# the branch ref is never contended, fail-loud markers on every exit path
# (R4), push-stderr capture (R5), and a one-shot non-fast-forward retry —
# so this driver no longer duplicates (and silently drifts from) that
# logic. fetch/worktree failures return non-zero and ``set -e`` surfaces
# them; push failures are soft (marker degraded:push-failed, retried on
# the next run). The primary working tree's checked-out branch is never
# touched.
# shellcheck source=automation/launchd/lib_c13_data_push.sh
source "$(dirname "$0")/lib_c13_data_push.sh"
push_to_data_branch \
    "chore(c13): phase-a audit ${DATE}" \
    "${STATUS_MARKER}" \
    "${AUDIT}" \
    "${SETUPS}" \
    "${GATES}"
