#!/usr/bin/env bash
# C13 / T7.1 — daily local cron driver for WSH earnings calendar pull.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.wsh-earnings.plist
# on Mon-Fri @ 16:30 local time. Idempotent on the artefact path.

set -euo pipefail

# Derive REPO from this script's location so the driver is portable across
# workstations without editing the tracked file. VENV / WATCHLIST can be
# overridden via environment variables (set in the LaunchAgent plist's
# ``EnvironmentVariables`` block).
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${REPO}/.venv}"
WATCHLIST="${C13_WATCHLIST:-${REPO}/reports/databento_watchlist_top5_pre1530.csv}"
WINDOW_DAYS=14

DATE="$(date -u +%Y-%m-%d)"
OUTPUT="${REPO}/cache/wsh/${DATE}.jsonl"
SUMMARY="${REPO}/cache/wsh/${DATE}.summary.json"
FEED_MARKER="${REPO}/cache/wsh/.feed_status_${DATE}"
PUSH_MARKER="${REPO}/cache/wsh/.push_status_${DATE}"

cd "${REPO}"
# Lane 7: venv-realism guard. Sourcing a missing activate yields a
# cryptic ``no such file or directory`` from inside `set -u`; surface a
# clear error so the operator can fix C13_VENV in the plist.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "WSH cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
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
    exit 1
fi

# Run the calendar pull. Exit-code contract (see scripts/wsh_earnings_calendar):
#   0 — completed with >=1 earnings event resolved
#   2 — completed but the feed yielded ZERO events while reporting errors
#       (e.g. IBKR entitlement missing / watchlist rows lack conIds); the
#       summary is still written so the degradation is auditable
#   1 — hard failure (no usable summary written)
TS="$(date -u +%FT%TZ)"
set +e
"${PY}" -m scripts.wsh_earnings_calendar \
    --watchlist "${WATCHLIST}" \
    --window-days "${WINDOW_DAYS}" \
    --output    "${OUTPUT}" \
    --summary-output "${SUMMARY}"
RC=$?
set -e

if [[ ${RC} -eq 1 ]]; then
    echo "WSH cron: DEGRADED — calendar pull failed hard (rc=1); nothing to publish." >&2
    printf 'degraded:feed-error:%s\n' "${TS}" > "${FEED_MARKER}" 2>/dev/null || true
    exit 1
elif [[ ${RC} -eq 2 ]]; then
    # Feed returned zero events: the earnings FILTER will gate against an
    # empty set, i.e. earnings protection is effectively OFF. Record it loudly
    # but STILL publish the summary so the gap is visible downstream.
    echo "WSH cron: DEGRADED — feed returned ZERO earnings events (rc=2)." >&2
    echo "  Likely causes: (1) IBKR account lacks the WSH news entitlement (Error 10276)," >&2
    echo "                 (2) watchlist rows are missing IBKR conIds." >&2
    printf 'degraded:no-events:%s\n' "${TS}" > "${FEED_MARKER}" 2>/dev/null || true
else
    printf 'ok:events:%s\n' "${TS}" > "${FEED_MARKER}" 2>/dev/null || true
fi

# Publish to the dedicated data branch via an isolated worktree so the push
# never lands on (or diverges) the primary tree's checked-out branch.
# shellcheck source=automation/launchd/lib_c13_data_push.sh
source "$(dirname "$0")/lib_c13_data_push.sh"
push_to_data_branch \
    "chore(c13): WSH earnings snapshot ${DATE}" \
    "${PUSH_MARKER}" \
    "cache/wsh/${DATE}.jsonl" \
    "cache/wsh/${DATE}.summary.json"
