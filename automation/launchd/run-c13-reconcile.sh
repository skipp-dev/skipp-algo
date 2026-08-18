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
# These reconciled records are Phase-B execution-promotion fills — they do
# NOT feed the ADR-0023 §5 E[PnL]-after-cost gate (that gate consumes the
# measurement benchmark's scored_family_events.json; correction 2026-07-06,
# see README.md).
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${REPO}/.venv}"

DATE="$(date -u +%Y-%m-%d)"
AUDIT="${REPO}/cache/live/incubation_${DATE}.jsonl"
PORTFOLIO_BEFORE="${REPO}/cache/live/portfolio_before_${DATE}.json"
PORTFOLIO_AFTER="${REPO}/cache/live/portfolio_after_${DATE}.json"
PORTFOLIO_FILLS="${REPO}/cache/live/portfolio_fills_${DATE}.json"
PORTFOLIO_REPORT="${REPO}/cache/live/portfolio_reconciliation_${DATE}.json"
PORTFOLIO_MONITORING="${REPO}/artifacts/portfolio/reconciliation_${DATE}.monitoring.json"
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
if ! "${PY}" -m scripts.reconcile_incubation_fills \
    --audit "${AUDIT}" \
    --portfolio-fills-output "${PORTFOLIO_FILLS}"; then
    echo "reconcile cron: reconcile_incubation_fills FAILED — see above for details" >&2
    _write_marker "DEGRADED" "reconcile-failed:audit=${AUDIT}"
    exit 1
fi

# Commercial-family paper audit (weekly review 2026-08-16, P0): once the
# commercial paper stage is live its submissions land in a SEPARATE dated
# file so the two writers never interleave. Reconcile it with the same
# machinery when present; absent means the paper stage is still dormant.
COMMERCIAL_AUDIT="${REPO}/cache/live/incubation_commercial_${DATE}.jsonl"
COMMERCIAL_FILLS="${REPO}/cache/live/portfolio_fills_commercial_${DATE}.json"
if [[ -f "${COMMERCIAL_AUDIT}" ]]; then
    if ! "${PY}" -m scripts.reconcile_incubation_fills \
        --audit "${COMMERCIAL_AUDIT}" \
        --portfolio-fills-output "${COMMERCIAL_FILLS}"; then
        echo "reconcile cron: commercial reconcile FAILED — see above for details" >&2
        _write_marker "DEGRADED" "commercial-reconcile-failed:audit=${COMMERCIAL_AUDIT}"
        exit 1
    fi
fi
if [[ ! -s "${PORTFOLIO_BEFORE}" ]]; then
    echo "reconcile cron: pre-submit portfolio snapshot missing at ${PORTFOLIO_BEFORE}" >&2
    _write_marker "DEGRADED" "portfolio-before-missing:path=${PORTFOLIO_BEFORE}"
    exit 1
fi
_capture_portfolio_after() {
    if [[ -n "${C13_IBKR_ACCOUNT:-}" ]]; then
        "${PY}" -m scripts.ibkr_portfolio_snapshot \
            --account "${C13_IBKR_ACCOUNT}" \
            --output "${PORTFOLIO_AFTER}"
    else
        "${PY}" -m scripts.ibkr_portfolio_snapshot \
            --output "${PORTFOLIO_AFTER}"
    fi
}
if ! _capture_portfolio_after; then
    echo "reconcile cron: post-session portfolio snapshot FAILED" >&2
    _write_marker "DEGRADED" "portfolio-after-failed:path=${PORTFOLIO_AFTER}"
    exit 1
fi
mkdir -p "$(dirname "${PORTFOLIO_MONITORING}")"
_portfolio_reconcile_exit=0
"${PY}" -m scripts.reconcile_portfolio_shadow \
    --before "${PORTFOLIO_BEFORE}" \
    --after "${PORTFOLIO_AFTER}" \
    --fills "${PORTFOLIO_FILLS}" \
    --output "${PORTFOLIO_REPORT}" \
    --monitoring-output "${PORTFOLIO_MONITORING}" || _portfolio_reconcile_exit=$?
if [[ ! -s "${PORTFOLIO_MONITORING}" ]]; then
    echo "reconcile cron: portfolio monitoring report missing" >&2
    _write_marker "DEGRADED" "portfolio-monitoring-missing:path=${PORTFOLIO_MONITORING}"
    exit 1
fi

# Publish only the sanitized monitoring report alongside the reconciled audit.
# Raw portfolio snapshots, account identifiers, positions and execution IDs
# remain local on C13 and are never copied to the data branch.
# shellcheck disable=SC1091
source "$(dirname "$0")/lib_c13_data_push.sh"
push_to_data_branch "chore(c13): reconciled fills ${DATE}" "${PUSH_MARKER}" \
    "cache/live/incubation_${DATE}.jsonl" \
    "cache/live/incubation_commercial_${DATE}.jsonl" \
    "artifacts/portfolio/reconciliation_${DATE}.monitoring.json"

if [[ "${_portfolio_reconcile_exit}" -ne 0 ]]; then
    echo "reconcile cron: portfolio position reconciliation FAILED" >&2
    _write_marker "DEGRADED" "portfolio-reconciliation-failed:report=${PORTFOLIO_REPORT}"
    exit "${_portfolio_reconcile_exit}"
fi
_write_marker "SUCCESS" "reconcile-complete:audit=${AUDIT}"
