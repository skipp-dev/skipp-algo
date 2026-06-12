#!/usr/bin/env bash
# C13 IBKR Smoke — pre-market adapter round-trip guard (Mon-Fri @ 08:00 ET).
#
# Invoked by
#   ~/Library/LaunchAgents/com.skippalgo.c13.ibkr-smoke.plist
# 90 minutes before US-equity open (09:30 ET).
#
# What this does:
#   1. Runs smoke_smc_to_ibkr_adapter.py --mode live against the Paper
#      Gateway on 127.0.0.1:7497 (place + immediate cancel, no fills).
#   2. Records the result to cache/live/smoke_<DATE>.jsonl (audit trail).
#   3. On EXIT=3 (live smoke left non-terminal / leftover orders) writes
#      cache/live/smoke_HALT — run_ibkr_open_execution.py reads this at
#      startup and refuses to submit real orders until the file is removed
#      by the operator.
#   4. On any other non-zero exit (e.g. TWS down, risk violation EXIT=2)
#      also writes cache/live/smoke_HALT so the execution runner is
#      blocked until the operator investigates.
#
# Sentinel lifecycle:
#   smoke_HALT is a plain file; remove it manually once the root cause
#   is understood and the issue is resolved.  run_ibkr_open_execution
#   also blocks if NO smoke JSONL for today exists (smoke never fired),
#   but --skip-smoke-guard bypasses both checks for emergency use.
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${REPO}/.venv}"
DATE="$(date -u +%Y-%m-%d)"
AUDIT="${REPO}/cache/live/smoke_${DATE}.jsonl"
HALT="${REPO}/cache/live/smoke_HALT"
STATUS_MARKER="${REPO}/cache/live/.ibkr_smoke_status_${DATE}"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "${REPO}/cache/live"
    printf '%s|%s\n' "${kind}" "${msg}" > "${STATUS_MARKER}"
}

_write_halt() {
    local reason="$1"
    mkdir -p "${REPO}/cache/live"
    # Overwrite any stale sentinel so mtime reflects this run.
    printf 'HALT|%s|%s\n' "${reason}" "$(date -u +%FT%TZ)" > "${HALT}"
    echo "ibkr-smoke: smoke_HALT written (${reason}) — execution blocked until" \
         "operator removes ${HALT}" >&2
}

cd "${REPO}"

if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "ibkr-smoke: virtualenv activate not found at ${VENV}/bin/activate" \
         "(set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "venv-missing:${VENV}/bin/activate"
    _write_halt "venv-missing"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

PY="${VENV}/bin/python"

if [[ ! -x "${PY}" ]]; then
    echo "ibkr-smoke: python interpreter missing or not executable at ${PY}" >&2
    _write_marker "DEGRADED" "python-missing:${PY}"
    _write_halt "python-missing"
    exit 1
fi

mkdir -p "${REPO}/cache/live"

# Capture exit code without letting set -e abort the script.
SMOKE_EXIT=0
"${PY}" -m scripts.smoke_smc_to_ibkr_adapter \
    --mode live \
    --audit-path "${AUDIT}" \
    || SMOKE_EXIT=$?

case "${SMOKE_EXIT}" in
    0)
        _write_marker "SUCCESS" "smoke-ok:audit=${AUDIT}"
        if [[ -f "${HALT}" ]]; then
            # Deliberately NOT auto-removed: the sentinel lifecycle requires an
            # operator to investigate the original failure before clearing it.
            echo "ibkr-smoke: round-trip OK (EXIT=0), but a pre-existing" \
                 "smoke_HALT sentinel is still present — execution stays" \
                 "BLOCKED until the operator removes ${HALT}" >&2
        else
            echo "ibkr-smoke: round-trip OK (EXIT=0). Execution unblocked."
        fi
        ;;
    2)
        # Risk limits violated — hard block.
        _write_marker "DEGRADED" "risk-violation:EXIT=2:audit=${AUDIT}"
        _write_halt "risk-violation:EXIT=2"
        echo "ibkr-smoke: EXIT=2 risk violation — smoke_HALT written." >&2
        exit 2
        ;;
    3)
        # Live smoke left non-terminal / leftover orders — hard block.
        _write_marker "DEGRADED" "leftover-orders:EXIT=3:audit=${AUDIT}"
        _write_halt "leftover-orders:EXIT=3"
        echo "ibkr-smoke: EXIT=3 leftover orders — smoke_HALT written." >&2
        exit 3
        ;;
    *)
        # Connection error, unexpected exception, etc.
        _write_marker "DEGRADED" "unexpected:EXIT=${SMOKE_EXIT}:audit=${AUDIT}"
        _write_halt "unexpected:EXIT=${SMOKE_EXIT}"
        echo "ibkr-smoke: unexpected EXIT=${SMOKE_EXIT} — smoke_HALT written." >&2
        exit "${SMOKE_EXIT}"
        ;;
esac
