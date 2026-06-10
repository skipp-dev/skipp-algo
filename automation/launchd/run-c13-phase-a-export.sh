#!/usr/bin/env bash
# C13 Phase-A — daily local cron driver for fresh open_prep trade-cards.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.phase-a-export.plist
# on Mon-Fri @ 09:18 local time (10 minutes BEFORE the phase-a runner
# at 09:28). Idempotent: writes timestamped CSV under reports/.
#
# Output: reports/open_prep_trade_cards_<TS>.csv (consumed by the
# subsequent build_phase_a_inputs.py invocation in run-c13-phase-a.sh).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${REPO}/.venv}"

DATE="$(date -u +%Y-%m-%d)"

# B2 (audit pass-4, 2026-06-10): write a status marker on every exit
# path so degraded runs are detectable without reading launchd stderr.
STATUS_MARKER="${REPO}/cache/live/.phase_a_export_status_${DATE}"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "${REPO}/cache/live"
    printf '%s|%s\n' "${kind}" "${msg}" > "${STATUS_MARKER}"
}

cd "${REPO}"
# Lane 7: venv-realism guard. Sourcing a missing activate yields a
# cryptic ``no such file or directory`` from inside `set -u`; surface a
# clear error so the operator can fix C13_VENV in the plist.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "phase-a-export cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "venv-missing:${VENV}/bin/activate"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# Pin the interpreter to the venv binary; a bare ``python`` can resolve to a
# missing/wrong binary under a minimal LaunchAgent PATH (observed 2026-06-10).
PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "phase-a-export cron: python interpreter not executable at ${PY}" >&2
    _write_marker "DEGRADED" "python-not-executable:${PY}"
    exit 1
fi

# Phase-A is paper-only; an export failure (e.g. transient FMP circuit
# open) must NOT block the downstream runner — it will fall back to the
# most recent successful CSV via build_phase_a_inputs.py auto-discovery.
export PYTHONPATH="${REPO}"
if "${PY}" -m scripts.export_open_prep_lists; then
    _write_marker "SUCCESS" "export-complete:date=${DATE}"
else
    echo "open_prep export failed (non-fatal); phase-a runner will use prior CSV"
    _write_marker "DEGRADED" "export-failed-non-fatal:date=${DATE}"
fi
