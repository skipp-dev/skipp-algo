#!/usr/bin/env bash
# C13 / T8.2 — daily local cron driver for opening-imbalance collection.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.collect-imbalance.plist
# on Mon-Fri @ 09:28 local time. Idempotent on the artefact path.

set -euo pipefail

# Derive REPO from this script's location so the driver is portable across
# workstations without editing the tracked file. VENV / WATCHLIST can be
# overridden via environment variables (set in the LaunchAgent plist's
# ``EnvironmentVariables`` block) for non-default paths.
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${C13_VENV:-${REPO}/.venv}"
WATCHLIST="${C13_WATCHLIST:-${REPO}/reports/databento_watchlist_top5_pre1530.csv}"

DATE="$(date -u +%Y-%m-%d)"
# Canonical "this invocation degraded" marker path for today's UTC date.
# Preflight failures always write here. Runtime collector failures also write
# here (in addition to the per-run-date marker) so machine checks that watch
# today's marker still see a degradation when catch-up replays historical dates.
TODAY_MARKER="${REPO}/cache/imbalance/.push_status_${DATE}"

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
    echo "imbalance cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "${TODAY_MARKER}" "degraded:preflight-error:$(date -u +%FT%TZ)"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# Pin the interpreter to the venv binary. Under a minimal LaunchAgent PATH a
# bare ``python`` can resolve to a missing/wrong binary even after activate
# (observed 2026-06-10); the explicit path is deterministic.
PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "imbalance cron: python interpreter not executable at ${PY}" >&2
    _write_marker "${TODAY_MARKER}" "degraded:preflight-error:$(date -u +%FT%TZ)"
    exit 1
fi

# Publish to the dedicated data branch via an isolated worktree so the push
# never lands on (or diverges) the primary tree's checked-out branch.
# shellcheck source=automation/launchd/lib_c13_data_push.sh
source "$(dirname "$0")/lib_c13_data_push.sh"
# Catch-up helper: replay business days missed while the machine was asleep.
# shellcheck source=automation/launchd/lib_c13_catchup.sh
source "$(dirname "$0")/lib_c13_catchup.sh"

# Collect + publish a single run-date. Invoked once per missed business day by
# c13_run_with_catchup (today only if no dates are missing). Returns non-zero on a
# collector failure so the catch-up driver can tally it without aborting the
# remaining dates.
process_one_date() {
    local DATE="$1"
    local OUTPUT="${REPO}/cache/imbalance/${DATE}.jsonl"
    local SUMMARY="${REPO}/cache/imbalance/${DATE}.summary.json"
    local MARKER="${REPO}/cache/imbalance/.push_status_${DATE}"
    local TS; TS="$(date -u +%FT%TZ)"

    # SA-03 (audit 2026-06-14): wrap collector so a non-zero exit writes a
    # degraded marker before returning — required for machine-detectable
    # monitoring of silent collector failures.
    if "${PY}" -m scripts.collect_opening_imbalances \
        --watchlist "${WATCHLIST}" \
        --output    "${OUTPUT}" \
        --summary-output "${SUMMARY}" \
        --trade-date "${DATE}"; then
        :
    else
        local rc=$?
        echo "imbalance cron: collect_opening_imbalances FAILED for ${DATE} (exit ${rc}) — see above for details" >&2
        _write_marker "${TODAY_MARKER}" "degraded:collector-error:${TS}"
        _write_marker "${MARKER}" "degraded:collector-error:${TS}"
        return 1
    fi

    push_to_data_branch \
        "chore(c13): imbalance snapshot ${DATE}" \
        "${MARKER}" \
        "cache/imbalance/${DATE}.jsonl" \
        "cache/imbalance/${DATE}.summary.json"
}

# Replay any business days missed while the workstation was asleep (launchd
# StartCalendarInterval coalesces multiple missed firings into a single wake);
# today is run as a safety net only when no dates are missing. Bounded by
# C13_CATCHUP_LOOKBACK_DAYS (default 7 calendar days).
c13_run_with_catchup "${REPO}/cache/imbalance" ".push_status_" process_one_date
