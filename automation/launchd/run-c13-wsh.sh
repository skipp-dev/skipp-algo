#!/usr/bin/env bash
# C13 / T7.1 — daily local cron driver for WSH earnings calendar pull.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.wsh-earnings.plist
# Mon-Fri targeting 16:30 ET (plist fires three ET-bracketing local
# times; the ET gate picks one). Idempotent on the artefact path.

set -euo pipefail

# Derive REPO from this script's location so the driver is portable across
# workstations without editing the tracked file. VENV / WATCHLIST can be
# overridden via environment variables (set in the LaunchAgent plist's
# ``EnvironmentVariables`` block).
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# ET timezone gate: the plist fires at three candidate LOCAL times bracketing
# the 16:30 ET target across US/EU DST; proceed only in the true ET window
# (lib_c13_et_gate.sh). Root-caused 2026-07-07: a non-ET Mac fired these ~6h off.
# 16:30 ET -> 21:30/22:30/23:30 Berlin (same day).
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" 16 30 10 wsh-earnings || exit 0
VENV="${C13_VENV:-${REPO}/.venv}"
WATCHLIST="${C13_WATCHLIST:-${REPO}/reports/databento_watchlist_top5_pre1530.csv}"
WINDOW_DAYS=14

DATE="$(date -u +%Y-%m-%d)"
OUTPUT="${REPO}/cache/wsh/${DATE}.jsonl"
SUMMARY="${REPO}/cache/wsh/${DATE}.summary.json"
FEED_MARKER="${REPO}/cache/wsh/.feed_status_${DATE}"
PUSH_MARKER="${REPO}/cache/wsh/.push_status_${DATE}"
TS="$(date -u +%FT%TZ)"

_write_marker() {
    local marker_path="$1"
    local marker_value="$2"
    mkdir -p "$(dirname "${marker_path}")" 2>/dev/null || true
    printf '%s\n' "${marker_value}" > "${marker_path}" 2>/dev/null || true
}

cd "${REPO}"
# Lane 7: venv-realism guard. Sourcing a missing activate yields a
# cryptic ``no such file or directory`` from inside `set -u`; surface a
# clear error so the operator can fix C13_VENV in the plist.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "WSH cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "${FEED_MARKER}" "degraded:preflight-error:${TS}"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# Pin the interpreter to the venv binary. Under a minimal LaunchAgent PATH a
# bare ``python`` can resolve to a missing/wrong binary even after activate
# (observed 2026-06-10); the explicit path is deterministic.
PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "WSH cron: python interpreter not executable at ${PY}" >&2
    _write_marker "${FEED_MARKER}" "degraded:preflight-error:${TS}"
    exit 1
fi

# Run the calendar pull. Exit-code contract (see scripts/wsh_earnings_calendar):
#   0 — completed with >=1 earnings event resolved
#   2 — completed but the feed yielded ZERO events while reporting errors
#       (e.g. IBKR entitlement missing / watchlist rows lack conIds); the
#       summary is still written so the degradation is auditable
#   1 — hard failure (no usable summary written)
SOURCE="ibkr"
set +e
"${PY}" -m scripts.wsh_earnings_calendar \
    --watchlist "${WATCHLIST}" \
    --window-days "${WINDOW_DAYS}" \
    --output    "${OUTPUT}" \
    --summary-output "${SUMMARY}"
RC=$?
set -e

# FMP fallback (2026-08-19). The IBKR path returned ZERO events on 41 of 41
# days since 2026-06-11, and the cause is structural rather than transient:
# ${WATCHLIST} has no con_id column, so every symbol hits the -1 sentinel and
# reqWshEventData skips it. A WSH entitlement would not change that. FMP needs
# no conIds, is already a paid production dependency, and writes the SAME
# record shape into the SAME ${OUTPUT}, so every consumer downstream is
# untouched. Only reached when IBKR yields nothing — IBKR stays preferred.
if [[ ${RC} -ne 0 ]]; then
    echo "WSH cron: IBKR path returned rc=${RC}; trying the FMP calendar." >&2
    set +e
    "${PY}" -m scripts.fmp_earnings_calendar \
        --watchlist "${WATCHLIST}" \
        --window-days "${WINDOW_DAYS}" \
        --output    "${OUTPUT}"
    FMP_RC=$?
    set -e
    if [[ ${FMP_RC} -eq 0 ]]; then
        echo "WSH cron: FMP supplied the earnings calendar (IBKR rc=${RC})." >&2
        RC=0
        SOURCE="fmp"
    else
        echo "WSH cron: FMP fallback also produced nothing (rc=${FMP_RC})." >&2
    fi
fi

if [[ ${RC} -eq 1 ]]; then
    echo "WSH cron: DEGRADED — calendar pull failed hard (rc=1); nothing to publish." >&2
    _write_marker "${FEED_MARKER}" "degraded:feed-error:${TS}"
    exit 1
elif [[ ${RC} -eq 2 ]]; then
    # Both sources yielded zero events. The filter now treats an empty file as
    # MISSING data and blocks under its fail-closed default, so this no longer
    # reads downstream as "checked, no earnings today" (2026-08-19).
    echo "WSH cron: DEGRADED — no earnings events from IBKR or FMP (rc=2)." >&2
    echo "  Likely causes: (1) watchlist rows are missing IBKR conIds," >&2
    echo "                 (2) IBKR account lacks the WSH entitlement (Error 10276)," >&2
    echo "                 (3) FMP_API_KEY unset/empty in this environment." >&2
    _write_marker "${FEED_MARKER}" "degraded:no-events:${TS}"
else
    _write_marker "${FEED_MARKER}" "ok:events-${SOURCE}:${TS}"
fi

# Publish to the dedicated data branch via the hook-free publishing clone so
# the push never lands on (or diverges) the primary tree's checked-out branch.
# shellcheck source=automation/launchd/lib_c13_data_push.sh
source "$(dirname "$0")/lib_c13_data_push.sh"
push_to_data_branch \
    "chore(c13): WSH earnings snapshot ${DATE}" \
    "${PUSH_MARKER}" \
    "cache/wsh/${DATE}.jsonl" \
    "cache/wsh/${DATE}.summary.json"
