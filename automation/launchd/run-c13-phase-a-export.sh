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

cd "${REPO}"
# Lane 7: venv-realism guard. Sourcing a missing activate yields a
# cryptic ``no such file or directory`` from inside `set -u`; surface a
# clear error so the operator can fix C13_VENV in the plist.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "phase-a-export cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# Pin the interpreter to the venv binary; a bare ``python`` can resolve to a
# missing/wrong binary under a minimal LaunchAgent PATH (observed 2026-06-10).
PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "phase-a-export cron: python interpreter not executable at ${PY}" >&2
    exit 1
fi

# Phase-A is paper-only; an export failure (e.g. transient FMP circuit
# open) must NOT block the downstream runner — it will fall back to the
# most recent successful CSV via build_phase_a_inputs.py auto-discovery.
export PYTHONPATH="${REPO}"
"${PY}" -m scripts.export_open_prep_lists || \
    echo "open_prep export failed (non-fatal); phase-a runner will use prior CSV"
