#!/usr/bin/env bash
# C13 / Phase-A — live-incubation session driver.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.phase-a-session.plist
# on Mon-Fri @ 09:25 local time (ET). Reads cache/phase_a/setups_<DATE>.jsonl
# + gate_status_<DATE>.json (written 10 minutes earlier by the prep agent)
# and starts run_smc_live_incubation in --phase paper (size_scale=0.1,
# _no_op_submit default, audit-log only).
#
# CRITICAL TWS BLOCKER: the operator MUST verify TWS is running with a
# **PAPER** account on port 7497 BEFORE this agent fires. The runner
# defaults to audit-only, but any future flag flip to live submission
# while a real-cash account is logged in would be unrecoverable. This
# driver therefore refuses to start unless the killswitch sentinel
# ``cache/phase_a/.go-live`` is present (see install instructions in
# automation/launchd/README.md).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${HOME}/.venv}"
PHASE="${C13_PHASE:-paper}"

DATE="$(date -u +%Y-%m-%d)"
PHASE_A_DIR="${REPO}/cache/phase_a"
SETUPS="${PHASE_A_DIR}/setups_${DATE}.jsonl"
GATE_STATUS="${PHASE_A_DIR}/gate_status_${DATE}.json"
AUDIT_DIR="${REPO}/cache/incubation"
AUDIT_OUTPUT="${AUDIT_DIR}/incubation_${DATE}.jsonl"
KILLSWITCH="${PHASE_A_DIR}/.go-live"

cd "${REPO}"
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# 1. Operator-go-live sentinel. The file MUST exist AND contain the
#    literal string "PAPER-CONFIRMED" — this is the human ack that TWS
#    is on a paper account, NOT live cash. Absent or wrong-content =
#    soft-skip, no order activity, no audit record.
if [[ ! -f "${KILLSWITCH}" ]]; then
    echo "Killswitch ${KILLSWITCH} absent; soft-skipping Phase-A session for ${DATE}." >&2
    exit 0
fi
if ! grep -qx "PAPER-CONFIRMED" "${KILLSWITCH}"; then
    echo "Killswitch ${KILLSWITCH} present but not marked PAPER-CONFIRMED; soft-skipping." >&2
    exit 0
fi

# 2. Inputs must exist (the prep agent runs at 09:15; if it failed,
#    we refuse to invent missing files).
if [[ ! -f "${SETUPS}" ]] || [[ ! -f "${GATE_STATUS}" ]]; then
    echo "Phase-A inputs missing for ${DATE} (setups=${SETUPS}, gate=${GATE_STATUS}); did the prep agent run?" >&2
    exit 1
fi

mkdir -p "${AUDIT_DIR}"

# 3. The runner expects a JSON array; convert JSONL → JSON-array on the
#    fly. Empty file → empty array (Phase-A seed contract). Done in
#    Python rather than jq to avoid an extra dependency.
SETUPS_JSON="$(mktemp -t skippalgo-c13-setups.XXXXXX.json)"
trap 'rm -f "${SETUPS_JSON}"' EXIT
python - "${SETUPS}" "${SETUPS_JSON}" <<'PY'
import json
import sys
from pathlib import Path

src, dst = Path(sys.argv[1]), Path(sys.argv[2])
records = []
with src.open(encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
dst.write_text(json.dumps(records), encoding="utf-8")
PY

python -m scripts.run_smc_live_incubation \
    --phase "${PHASE}" \
    --setups "${SETUPS_JSON}" \
    --gate-statuses "${GATE_STATUS}" \
    --audit-output "${AUDIT_OUTPUT}"

echo "Phase-A session complete for ${DATE}; audit log appended to ${AUDIT_OUTPUT}."
