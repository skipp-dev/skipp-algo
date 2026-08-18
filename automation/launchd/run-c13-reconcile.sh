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

# Commercial-family paper audit (weekly review 2026-08-16, P0): once the
# commercial paper stage is live its submissions land in a SEPARATE dated
# file so the two writers never interleave. Its presence must be part of the
# entry gate: until 2026-08-18 (Doppelgaenger-Sweep E5) a missing ORB audit
# alone exited SUCCESS/no-audit-file BEFORE this file was even looked at, so
# a commercial-only trading day was never reconciled and its fills stayed
# out of the telemetry glob forever.
COMMERCIAL_AUDIT="${REPO}/cache/live/incubation_commercial_${DATE}.jsonl"
COMMERCIAL_FILLS="${REPO}/cache/live/portfolio_fills_commercial_${DATE}.json"
# Written by run-c13-eod-flatten.sh (15:45 ET): the market-close fills of the
# end-of-day flatten. Without them every flattened position shows up as an
# unexplained delta and the reconciliation reddens on its own cleanup.
EOD_FLATTEN_FILLS="${REPO}/cache/live/portfolio_fills_eod_${DATE}.json"

# No audit file at all (holiday, phase-a never fired, paper stage dormant)
# is a quiet no-op — there is nothing to reconcile and nothing to publish.
if [[ ! -f "${AUDIT}" && ! -f "${COMMERCIAL_AUDIT}" ]]; then
    echo "reconcile cron: no audit file at ${AUDIT} or ${COMMERCIAL_AUDIT}; nothing to reconcile today"
    _write_marker "SUCCESS" "no-audit-file"
    exit 0
fi

export PYTHONPATH="${REPO}"
if [[ -f "${AUDIT}" ]]; then
    if ! "${PY}" -m scripts.reconcile_incubation_fills \
        --audit "${AUDIT}" \
        --portfolio-fills-output "${PORTFOLIO_FILLS}"; then
        echo "reconcile cron: reconcile_incubation_fills FAILED — see above for details" >&2
        _write_marker "DEGRADED" "reconcile-failed:audit=${AUDIT}"
        exit 1
    fi
else
    echo "reconcile cron: no ORB audit at ${AUDIT}; reconciling the commercial audit only"
fi

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
# The position delta between the two snapshots is caused by ALL fills of the
# session — ORB and commercial together: der Broker-Account ist einer
# (Verdrahtungs-Sweep K8). Until 2026-08-18 (Doppelgaenger-Sweep E5)
# COMMERCIAL_FILLS was computed above and then never handed over, so a
# commercial fill showed up as an unexplained position delta. Each file is
# optional on its own (pre-flip has no commercial file, a commercial-only
# day has no ORB file), but ZERO fills despite an audit file is DEGRADED.
FILLS_ARGS=()
[[ -f "${PORTFOLIO_FILLS}" ]] && FILLS_ARGS+=(--fills "${PORTFOLIO_FILLS}")
[[ -f "${COMMERCIAL_FILLS}" ]] && FILLS_ARGS+=(--fills "${COMMERCIAL_FILLS}")
[[ -f "${EOD_FLATTEN_FILLS}" ]] && FILLS_ARGS+=(--fills "${EOD_FLATTEN_FILLS}")
if [[ ${#FILLS_ARGS[@]} -eq 0 ]]; then
    echo "reconcile cron: no fills output produced despite an audit file" >&2
    _write_marker "DEGRADED" "no-fills-output"
    exit 1
fi
_portfolio_reconcile_exit=0
"${PY}" -m scripts.reconcile_portfolio_shadow \
    --before "${PORTFOLIO_BEFORE}" \
    --after "${PORTFOLIO_AFTER}" \
    "${FILLS_ARGS[@]}" \
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
_push_exit=0
push_to_data_branch "chore(c13): reconciled fills ${DATE}" "${PUSH_MARKER}" \
    "cache/live/incubation_${DATE}.jsonl" \
    "cache/live/incubation_commercial_${DATE}.jsonl" \
    "artifacts/portfolio/reconciliation_${DATE}.monitoring.json" || _push_exit=$?
if [[ "${_push_exit}" -ne 0 ]]; then
    # A hard push failure previously killed the script here (set -e) BEFORE
    # any terminal marker, so the day read "never ran" instead of "degraded"
    # — the exact R6 shape the push lib's header describes for its own
    # marker. Record the truth, then keep the non-zero exit.
    echo "reconcile cron: data-branch push FAILED (exit ${_push_exit})" >&2
    _write_marker "DEGRADED" "data-push-failed:exit=${_push_exit}"
    exit "${_push_exit}"
fi

if [[ "${_portfolio_reconcile_exit}" -ne 0 ]]; then
    echo "reconcile cron: portfolio position reconciliation FAILED" >&2
    _write_marker "DEGRADED" "portfolio-reconciliation-failed:report=${PORTFOLIO_REPORT}"
    exit "${_portfolio_reconcile_exit}"
fi
_write_marker "SUCCESS" "reconcile-complete:audit=${AUDIT}"
