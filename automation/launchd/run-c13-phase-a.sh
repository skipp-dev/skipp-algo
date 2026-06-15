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
VENV="${C13_VENV:-${REPO}/.venv}"

DATE_TODAY="$(date -u +%Y-%m-%d)"

# B2 (audit pass-4, 2026-06-10): every exit path must write a status
# marker so degraded runs are detectable without reading launchd stderr.
# Marker lives in cache/live/ alongside the other dated artefacts so the
# audit-push driver can report its presence/absence. ``STATUS_MARKER`` is a
# module-global set to the current run-date (today for preflight, then per
# missed business day inside process_one_date) so the catch-up loop stamps
# the correct dated marker on every exit path.
STATUS_MARKER="${REPO}/cache/live/.phase_a_status_${DATE_TODAY}"
_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "${REPO}/cache/live"
    printf '%s|%s\n' "${kind}" "${msg}" > "${STATUS_MARKER}"
}

cd "${REPO}"
# Preflight (once, not per run-date): a venv/interpreter problem is not
# specific to any one date, so stamp today's marker and bail.
# Lane 7: venv-realism guard. Sourcing a missing activate yields a
# cryptic ``no such file or directory`` from inside `set -u`; surface a
# clear error so the operator can fix C13_VENV in the plist.
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "phase-a cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "venv-missing:${VENV}/bin/activate"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

# Invoke the interpreter by absolute path rather than relying on
# ``source activate`` to prepend ${VENV}/bin to PATH. Under launchd the
# inherited PATH is minimal and a bare ``python`` can resolve to a
# missing/wrong binary (observed 2026-06-10: ``python: command not found``
# even after a successful activate). The explicit path is the single
# source of truth for which interpreter runs.
PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "phase-a cron: python interpreter not found/executable at ${PY} (check C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "python-not-executable:${PY}"
    exit 1
fi

export PYTHONPATH="${REPO}"

# Catch-up helper: replay business days the workstation slept through
# instead of letting launchd coalesce them into a single wake.
# shellcheck source=automation/launchd/lib_c13_catchup.sh
source "$(dirname "$0")/lib_c13_catchup.sh"

# Build + incubate a single run-date in PAPER mode. Invoked once per missed
# business day by c13_run_with_catchup (and always at least for today).
# Returns non-zero on a build/incubation failure so the catch-up driver can
# tally it without aborting the remaining dates.
process_one_date() {
    local DATE="$1"
    local SETUPS="${REPO}/cache/live/setups_${DATE}.jsonl"
    local GATES="${REPO}/cache/live/gate_status.json"
    local AUDIT="${REPO}/cache/live/incubation_${DATE}.jsonl"
    local WSH="${REPO}/cache/wsh/${DATE}.jsonl"
    # Point the module-global marker at this run-date (intentionally not
    # ``local``) so _write_marker stamps the correct dated file.
    STATUS_MARKER="${REPO}/cache/live/.phase_a_status_${DATE}"

    # 1. Build the run-date's setups + gate_status from the latest open_prep
    #    trade-cards CSV. Producer is fail-loud on unmapped setup_type but
    #    handles empty CSVs (writes [] / {}) so an FMP-circuit-open day is
    #    a soft no-op rather than a failure.
    #    B1 (audit pass-4, 2026-06-10): producer now rejects CSVs older than
    #    4 calendar days (relative to trade_date) so stale entry/stop prices
    #    are never silently stamped. A stale-CSV failure exits non-zero —
    #    write a DEGRADED marker so the audit-push driver can surface the
    #    cause without requiring a launchd log read.
    if ! "${PY}" -m scripts.build_phase_a_inputs \
        --trade-date "${DATE}"; then
        echo "phase-a cron: build_phase_a_inputs FAILED for ${DATE} (stale CSV or unmapped setup_type) — see above for details" >&2
        _write_marker "DEGRADED" "build-phase-a-inputs-failed:trade_date=${DATE}"
        return 1
    fi

    # 2. Optional WSH earnings filter. The wsh-earnings agent runs the
    #    *afternoon before* (16:30 day N-1) writing cache/wsh/<N-1>.jsonl, so
    #    today's exact-date file normally does NOT exist yet at 09:28. Using a
    #    strict ${DATE} match therefore left the filter permanently inert
    #    (F2, 2026-06-10). Fall back to the most recent WSH snapshot within the
    #    last few days — the snapshot already encodes a forward event window —
    #    so the earnings filter is actually applied, and log which file is used.
    local WSH_FLAG=""
    local WSH_FILE=""
    if [[ -f "${WSH}" ]]; then
        WSH_FILE="${WSH}"
    else
        # ISO-dated filenames sort chronologically; newest wins.
        WSH_FILE="$(ls -1 "${REPO}"/cache/wsh/*.jsonl 2>/dev/null | sort | tail -n1 || true)"
    fi
    if [[ -n "${WSH_FILE}" && -f "${WSH_FILE}" ]]; then
        local WSH_BASENAME
        WSH_BASENAME="$(basename "${WSH_FILE}" .jsonl)"
        # Only trust a snapshot at most 4 days old (tolerates a long weekend /
        # holiday) so we never silently gate on week-stale earnings data.
        local _today_epoch _file_epoch WSH_AGE_DAYS
        _today_epoch="$(date -u -j -f "%Y-%m-%d" "${DATE}" "+%s" 2>/dev/null || echo "")"
        _file_epoch="$(date -u -j -f "%Y-%m-%d" "${WSH_BASENAME}" "+%s" 2>/dev/null || echo "")"
        if [[ -n "${_today_epoch}" && -n "${_file_epoch}" ]]; then
            WSH_AGE_DAYS=$(( (_today_epoch - _file_epoch) / 86400 ))
        else
            WSH_AGE_DAYS=-1
        fi
        if [[ "${WSH_AGE_DAYS}" -ge 0 && "${WSH_AGE_DAYS}" -le 4 ]]; then
            echo "phase-a cron: applying WSH earnings filter from ${WSH_FILE} (age ${WSH_AGE_DAYS}d)"
            WSH_FLAG="--wsh-events-jsonl ${WSH_FILE}"
        else
            echo "phase-a cron: newest WSH snapshot ${WSH_FILE} is ${WSH_AGE_DAYS}d old (>4d or unparseable); earnings filter SKIPPED (stale)" >&2
        fi
    else
        echo "phase-a cron: no WSH snapshot found under cache/wsh/; earnings filter SKIPPED (no data)" >&2
    fi

    # 3. Run the orchestrator. --phase paper means submit_fn defaults to
    #    the no-op stub inside run_smc_live_incubation.py, so no IBKR
    #    orders are placed even if TWS is running on a live account.
    #    SA-02 (audit 2026-06-14): wrap the runner call so a non-zero exit
    #    writes a DEGRADED marker before returning — required for machine-
    #    detectable monitoring of silent incubation failures.
    # shellcheck disable=SC2086
    if "${PY}" -m scripts.run_smc_live_incubation \
        --phase paper \
        --setups "${SETUPS}" \
        --gate-statuses "${GATES}" \
        --audit-output "${AUDIT}" \
        ${WSH_FLAG}; then
        :
    else
        local rc=$?
        echo "phase-a cron: run_smc_live_incubation FAILED for ${DATE} (exit ${rc}) — see above for details" >&2
        _write_marker "DEGRADED" "incubation-failed:audit=${AUDIT}"
        return 1
    fi

    _write_marker "SUCCESS" "incubation-complete:audit=${AUDIT}"
}

# Replay any business days missed while the workstation was asleep (launchd
# StartCalendarInterval coalesces multiple missed firings into a single wake),
# then today. The phase-a marker uses a ``SUCCESS|``/``DEGRADED|`` format, so a
# date counts as done only when its marker begins with ``SUCCESS``. Bounded by
# C13_CATCHUP_LOOKBACK_DAYS (default 7 calendar days).
c13_run_with_catchup "${REPO}/cache/live" ".phase_a_status_" process_one_date "" "SUCCESS"
