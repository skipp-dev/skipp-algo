#!/usr/bin/env bash
# C13 Phase-A — daily local cron driver for the live-incubation runner
# in PAPER mode. Invoked by
# ~/Library/LaunchAgents/com.skippalgo.c13.phase-a.plist on Mon-Fri @
# 09:28 local time.
#
# Pipeline:
#   1. build_phase_a_inputs.py   → cache/live/setups_<DATE>.jsonl + gate_status.json
#   2. run_smc_live_incubation.py --phase paper   → cache/live/incubation_<DATE>.jsonl
#
# Phase-A is STRICTLY --phase paper (audit_only). Promotion to
# --phase live_small or live_full is a Phase-B decision and requires a
# real --account-state-json snapshot (see scripts/run_smc_live_incubation.py).
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${HOME}/.venv}"

DATE="$(date -u +%Y-%m-%d)"
SETUPS="${REPO}/cache/live/setups_${DATE}.jsonl"
GATES="${REPO}/cache/live/gate_status.json"
AUDIT="${REPO}/cache/live/incubation_${DATE}.jsonl"
WSH="${REPO}/cache/wsh/${DATE}.jsonl"

cd "${REPO}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

mkdir -p "${REPO}/cache/live"

export PYTHONPATH="${REPO}"

# 1. Build today's setups + gate_status from the latest open_prep
#    trade-cards CSV. Producer is fail-loud on unmapped setup_type but
#    handles empty CSVs (writes [] / {}) so an FMP-circuit-open day is
#    a soft no-op rather than a failure.
python -m scripts.build_phase_a_inputs \
    --trade-date "${DATE}"

# 2. Optional WSH earnings filter — only applied if today's WSH JSONL
#    exists (com.skippalgo.c13.wsh-earnings runs the night before).
WSH_FLAG=""
if [[ -f "${WSH}" ]]; then
    WSH_FLAG="--wsh-events-jsonl ${WSH}"
fi

# 3. Run the orchestrator. --phase paper means submit_fn defaults to
#    the no-op stub inside run_smc_live_incubation.py, so no IBKR
#    orders are placed even if TWS is running on a live account.
# shellcheck disable=SC2086
python -m scripts.run_smc_live_incubation \
    --phase paper \
    --setups "${SETUPS}" \
    --gate-statuses "${GATES}" \
    --audit-output "${AUDIT}" \
    ${WSH_FLAG}
