#!/usr/bin/env bash
# C13 reconcile-fills — daily local cron driver for the paper-fill
# reconciliation stage. Invoked by
# ~/Library/LaunchAgents/com.skippalgo.c13.reconcile.plist on Mon-Fri @
# 23:05 local time (after the US cash close in both EU/US DST regimes,
# including the few mismatch weeks; TWS still holds the day's executions).
#
# Pipeline:
#   1. reconcile_incubation_fills.py — queries the day's executions from
#      the PAPER TWS (read-only, refuses non-paper ports) and stamps
#      fill_price / close_price / close_action / size_usd onto
#      cache/live/incubation_<DATE>.jsonl, then backfills PnL/R via
#      backfill_live_outcomes.
#   2. push_to_data_branch — publishes the reconciled audit file to
#      data/phase-a-audit for the GH-hosted C13 cron.
#
# These reconciled records are the measurable paper fills the ADR-0023 §5
# E[PnL]-after-cost gate is blocked on (>= 20 fills).
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${REPO}/.venv}"

DATE="$(date -u +%Y-%m-%d)"
AUDIT="${REPO}/cache/live/incubation_${DATE}.jsonl"
STATUS_MARKER="${REPO}/cache/live/.reconcile_status_${DATE}"
PUSH_MARKER="${REPO}/cache/live/.reconcile_push_status_${DATE}"
TS="$(date -u +%FT%TZ)"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "$(dirname "${STATUS_MARKER}")" 2>/dev/null || true
    printf '%s:%s:%s\n' "${kind}" "${msg}" "${TS}" > "${STATUS_MARKER}" 2>/dev/null || true
}

cd "${REPO}"

# Lane 7: venv-realism guard (clear message instead of a cryptic set -u error).
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "reconcile cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "preflight-error"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "reconcile cron: python interpreter not executable at ${PY} (check C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "preflight-error"
    exit 1
fi

# No audit file at all (holiday, phase-a never fired) is a quiet no-op —
# there is nothing to reconcile and nothing to publish.
if [[ ! -f "${AUDIT}" ]]; then
    echo "reconcile cron: no audit file at ${AUDIT}; nothing to reconcile today"
    _write_marker "SUCCESS" "no-audit-file"
    exit 0
fi

export PYTHONPATH="${REPO}"
if ! "${PY}" -m scripts.reconcile_incubation_fills --audit "${AUDIT}"; then
    echo "reconcile cron: reconcile_incubation_fills FAILED — see above for details" >&2
    _write_marker "DEGRADED" "reconcile-failed:audit=${AUDIT}"
    exit 1
fi
_write_marker "SUCCESS" "reconcile-complete:audit=${AUDIT}"

# Publish the reconciled audit file so the GH-hosted C13 cron overlays the
# version WITH fills, not the morning's submit-only snapshot.
# shellcheck disable=SC1091
source "$(dirname "$0")/lib_c13_data_push.sh"
push_to_data_branch "chore(c13): reconciled fills ${DATE}" "${PUSH_MARKER}" \
    "cache/live/incubation_${DATE}.jsonl"
