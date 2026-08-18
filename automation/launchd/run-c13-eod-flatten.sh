#!/usr/bin/env bash
# C13 end-of-day flatten — daily local cron driver that closes every
# remaining paper position ~15 minutes before the US cash close.
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.eod-flatten.plist at
# the SIX candidate local times bracketing 15:45 ET (regular days) and
# 12:45 ET (scheduled 13:00-ET early closes) across the US/EU DST mismatch
# weeks; the ET gate below targets the day's close from
# scripts/us_equity_early_closes.py and lets exactly one fire per ET weekday
# proceed (same pattern as run-c13-phase-a.sh).
#
# Why (measured 2026-08-18): the campaign submits bracket sets and
# disconnects — the executor's client-side time stop never runs, DAY exit
# legs die at the bell, and positions whose tp/sl did not trigger intraday
# accumulated as unprotected zombies (nine one-lot leftovers since June).
# scripts/c13_eod_flatten.py is the missing exit half: it drains ALL
# working orders (reqGlobalCancel, cross-client) and market-closes every
# open position, writing the fills as PortfolioFill rows so the nightly
# reconcile (run-c13-reconcile.sh) can explain the position deltas.
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

VENV="${C13_VENV:-${REPO}/.venv}"
DATE="$(date -u +%Y-%m-%d)"
FILLS="${REPO}/cache/live/portfolio_fills_eod_${DATE}.json"
REPORT="${REPO}/cache/live/eod_flatten_report_${DATE}.json"
STATUS_MARKER="${REPO}/cache/live/.eod_flatten_status_${DATE}"
TS="$(date -u +%FT%TZ)"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "$(dirname "${STATUS_MARKER}")" 2>/dev/null || true
    printf '%s:%s:%s\n' "${kind}" "${msg}" "${TS}" > "${STATUS_MARKER}" 2>/dev/null || true
}

cd "${REPO}"

# venv-Preflight VOR dem Gate: das Gate-Ziel haengt vom Fruehschluss-Kalender
# ab, und der lebt als Single Source in Python (scripts/us_equity_early_closes
# — Review 2026-08-18 Important #2). Die Shell repliziert keine Datumsliste.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "eod-flatten cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "preflight-error"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "eod-flatten cron: python interpreter not executable at ${PY} (check C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "python-not-executable:${PY}"
    exit 1
fi

# An Halbtagen (13:00-ET-Close) zielt das Gate auf 12:45 ET statt 15:45 ET —
# sonst invertiert der Flatten seinen Zweck: reqGlobalCancel NACH dem Close
# toetet nur noch den GTC-Schutz und schliessen kann er nichts mehr. Die
# Plist feuert dafuer zusaetzlich die 12:45-ET-Kandidaten; das Gate laesst
# genau den passenden durch. Test-Hook: C13_GATE_NOW_ET_DATE.
ET_DATE="${C13_GATE_NOW_ET_DATE:-$(TZ=America/New_York date +%Y-%m-%d)}"
read -r TARGET_HH TARGET_MM < <("${PY}" -m scripts.us_equity_early_closes --date "${ET_DATE}")

# shellcheck disable=SC1091
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" "${TARGET_HH}" "${TARGET_MM}" 10 eod-flatten || exit 0

rc=0
"${PY}" -m scripts.c13_eod_flatten \
    --date "${DATE}" \
    --fills-output "${FILLS}" \
    --report-output "${REPORT}" \
    ${C13_IBKR_ACCOUNT:+--account "${C13_IBKR_ACCOUNT}"} || rc=$?

if [[ "${rc}" -ne 0 ]]; then
    echo "eod-flatten cron: c13_eod_flatten exited ${rc} — see ${REPORT}" >&2
    _write_marker "DEGRADED" "flatten-rc:${rc}"
    exit 1
fi

_write_marker "SUCCESS" "fills:${FILLS}"
