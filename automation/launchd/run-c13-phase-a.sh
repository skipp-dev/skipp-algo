#!/usr/bin/env bash
# C13 Phase-A — daily local cron driver for the live-incubation runner
# in PAPER mode. Invoked by
# ~/Library/LaunchAgents/com.skippalgo.c13.phase-a.plist Mon-Fri
# targeting 09:28 ET (see the ET-gate comment below).
#
# Pipeline:
#   1. build_phase_a_inputs.py   → cache/live/setups_<DATE>.jsonl + gate_status.json
#   2. run_smc_live_incubation.py --phase paper --place-paper-orders
#        → cache/live/incubation_<DATE>.jsonl (bracket sets on the PAPER TWS)
#
# Phase-A is STRICTLY --phase paper. Since 2026-07-06 (C13b T1.2, operator
# decision) the runner SUBMITS the surviving intents to the IBKR *paper*
# account via --place-paper-orders — the flag carries a built-in paper-port
# guard and run_smc_live_incubation refuses it on any live phase. This
# produces Phase-B execution-promotion fills — NOT the ADR-0023 §5
# E[PnL]-after-cost gate input (that gate consumes the measurement
# benchmark's scored_family_events.json; correction 2026-07-06, see
# README.md). Promotion to --phase live_small or
# live_full remains a Phase-B decision and requires a real
# --account-state-json snapshot (see scripts/run_smc_live_incubation.py).
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# ET timezone gate: the plist fires at three candidate LOCAL times bracketing
# the 09:28 ET target across US/EU DST; proceed only in the true ET window. On a
# non-ET Mac (e.g. Europe/Berlin) the old single "09:28" plist fired at 03:28 ET
# — ~6h before the US open — so the ORB paper orders never filled (root-caused
# 2026-07-07). See lib_c13_et_gate.sh. Order placement has no catch-up (you
# cannot place opening orders late), so gating at the top is correct.
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" 09 28 10 phase-a || exit 0

VENV="${C13_VENV:-${REPO}/.venv}"

DATE="$(date -u +%Y-%m-%d)"
SETUPS="${REPO}/cache/live/setups_${DATE}.jsonl"
GATES="${REPO}/cache/live/gate_status.json"
AUDIT="${REPO}/cache/live/incubation_${DATE}.jsonl"
WSH="${REPO}/cache/wsh/${DATE}.jsonl"
PORTFOLIO_BEFORE="${REPO}/cache/live/portfolio_before_${DATE}.json"
PORTFOLIO_LIMITS="${REPO}/configs/portfolio_risk_limits.json"

# B2 (audit pass-4, 2026-06-10): every exit path must write a status
# marker so degraded runs are detectable without reading launchd stderr.
# Marker lives in cache/live/ alongside the other dated artefacts so the
# audit-push driver can report its presence/absence.
STATUS_MARKER="${REPO}/cache/live/.phase_a_status_${DATE}"

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

# 1. Build today's setups + gate_status from the latest open_prep
#    trade-cards CSV. Producer is fail-loud on unmapped setup_type but
#    handles empty CSVs (writes [] / {}) so an FMP-circuit-open day is
#    a soft no-op rather than a failure.
#    B1 (audit pass-4, 2026-06-10): producer now rejects CSVs older than
#    4 calendar days (relative to trade_date) so stale entry/stop prices
#    are never silently stamped with today's date. A stale-CSV failure
#    exits non-zero — write a DEGRADED marker so the audit-push driver
#    can surface the cause without requiring a launchd log read.
if ! "${PY}" -m scripts.build_phase_a_inputs \
    --trade-date "${DATE}"; then
    echo "phase-a cron: build_phase_a_inputs FAILED (stale CSV or unmapped setup_type) — see above for details" >&2
    _write_marker "DEGRADED" "build-phase-a-inputs-failed:trade_date=${DATE}"
    exit 1
fi

# 2. Optional WSH earnings filter. The wsh-earnings agent runs the
#    *afternoon before* (16:30 day N-1) writing cache/wsh/<N-1>.jsonl, so
#    today's exact-date file normally does NOT exist yet at 09:28. Using a
#    strict ${DATE} match therefore left the filter permanently inert
#    (F2, 2026-06-10). Fall back to the most recent WSH snapshot within the
#    last few days — the snapshot already encodes a forward event window —
#    so the earnings filter is actually applied, and log which file is used.
WSH_FLAG=""
WSH_FILE=""
if [[ -f "${WSH}" ]]; then
    WSH_FILE="${WSH}"
else
    # ISO-dated filenames sort chronologically; newest wins.
    WSH_FILE="$(ls -1 "${REPO}"/cache/wsh/*.jsonl 2>/dev/null | sort | tail -n1 || true)"
fi
if [[ -n "${WSH_FILE}" && -f "${WSH_FILE}" ]]; then
    WSH_BASENAME="$(basename "${WSH_FILE}" .jsonl)"
    # Only trust a snapshot at most 4 days old (tolerates a long weekend /
    # holiday) so we never silently gate on week-stale earnings data.
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

# --- smoke-sentinel guard ---
# 2026-08-02: until today this submit ignored cache/live/smoke_HALT, and it
# had to. The 08:00-ET smoke raised the sentinel on EVERY non-zero exit —
# including a merely unreachable TWS — and never auto-clears it. Across the
# 19 recorded smoke days 10 were DEGRADED, all of them EXIT=1
# (ConnectionRefused on 7497), so an honoured sentinel would have stood
# permanently: the 2 fills of 2026-07-14 landed on a DEGRADED day with the
# sentinel already standing since 07-10, and blocking them would have cost
# most of the 23-fill track record.
#
# The smoke now raises it ONLY for danger that carries state a human must
# inspect — EXIT=2 (risk violation) and EXIT=3 (leftover non-terminal
# orders). An unreachable TWS writes the day marker alone: this submit then
# fails on its own if TWS is still down, and runs if it came back. Because
# the sentinel finally means danger, honouring it is now correct.
SMOKE_HALT_PATH="${REPO}/cache/live/smoke_HALT"
if [[ -f "${SMOKE_HALT_PATH}" ]]; then
    echo "phase-a cron: smoke_HALT sentinel present" \
         "($(head -c 200 "${SMOKE_HALT_PATH}" | tr -d '\n')) — refusing to submit" \
         "paper orders until the operator clears ${SMOKE_HALT_PATH}" >&2
    _write_marker "DEGRADED" "smoke-halt-sentinel"
    exit 1
fi
# --- end smoke-sentinel guard ---

# Capture broker state immediately before the real paper submit. The runner
# refuses --place-paper-orders without this file; a stale/incomplete snapshot
# is recorded as a portfolio rejection in shadow mode rather than silently
# bypassing the evaluation. C13_IBKR_ACCOUNT is optional because the collector
# already fails closed when TWS exposes multiple managed accounts.
_capture_portfolio_before() {
    if [[ -n "${C13_IBKR_ACCOUNT:-}" ]]; then
        "${PY}" -m scripts.ibkr_portfolio_snapshot \
            --account "${C13_IBKR_ACCOUNT}" \
            --output "${PORTFOLIO_BEFORE}"
    else
        "${PY}" -m scripts.ibkr_portfolio_snapshot \
            --output "${PORTFOLIO_BEFORE}"
    fi
}
if ! _capture_portfolio_before; then
    echo "phase-a cron: portfolio snapshot FAILED — refusing paper submit" >&2
    _write_marker "DEGRADED" "portfolio-snapshot-failed:path=${PORTFOLIO_BEFORE}"
    exit 1
fi
if [[ ! -s "${PORTFOLIO_BEFORE}" ]]; then
    echo "phase-a cron: portfolio snapshot missing/empty — refusing paper submit" >&2
    _write_marker "DEGRADED" "portfolio-snapshot-empty:path=${PORTFOLIO_BEFORE}"
    exit 1
fi

# 3. Run the orchestrator. --place-paper-orders (C13b T1.2, 2026-07-06)
#    swaps the no-op audit stub for the paper submitter: surviving intents
#    are transmitted as bracket sets to the IBKR *paper* TWS on 127.0.0.1.
#    The submitter hard-refuses non-paper ports and the CLI refuses the
#    flag on any live phase, so a mis-configured TWS can never receive
#    real orders from this cron. Requires TWS (paper) to be running at
#    09:28 local — a down TWS makes the submit batch fail loudly
#    (action=submit_failed in the audit JSONL), never silently.
#    SA-02 (audit 2026-06-14): wrap the runner call so a non-zero exit
#    writes a DEGRADED marker before aborting — required for machine-
#    detectable monitoring of silent incubation failures.
# NOTE: the exit code MUST be captured with the ``|| var=$?`` idiom (as in
# run-c13-ibkr-smoke.sh). A bare ``cmd; _run_exit=$?`` is dead code under
# ``set -e``: a non-zero exit aborts the script on the cmd line itself and
# the DEGRADED branch below never runs (found 2026-07-07 — the marker was
# silently skipped on every runner crash).
# shellcheck disable=SC2086
_run_exit=0
"${PY}" -m scripts.run_smc_live_incubation \
    --phase paper \
    --place-paper-orders \
    --setups "${SETUPS}" \
    --gate-statuses "${GATES}" \
    --audit-output "${AUDIT}" \
    --portfolio-snapshot-json "${PORTFOLIO_BEFORE}" \
    --portfolio-risk-limits-json "${PORTFOLIO_LIMITS}" \
    ${WSH_FLAG} || _run_exit=$?
if [ "${_run_exit}" -ne 0 ]; then
    echo "phase-a cron: run_smc_live_incubation FAILED (exit ${_run_exit}) — see above for details" >&2
    _write_marker "DEGRADED" "incubation-failed:audit=${AUDIT}"
    exit "${_run_exit}"
fi

# Deploy-hygiene guard (2026-07-09): this cron submits against THIS checkout with
# NO auto-pull, so a fix merged to origin/main (e.g. #3297's min-tick snap) never
# reaches the submitting Mac until someone pulls — the silent gap that kept the C8
# ladder at 0 fills for weeks with every PR "merged" but undeployed. Publish how
# many commits the paper-submit ORDER PATH is behind origin/main so the daemon can
# emit it and the `C13 submitter on stale checkout` alert can page. audit-push
# ships cache/live/checkout_freshness.json to the data branch; the CI snapshot
# producer reads it. Best-effort + fully non-fatal (a fetch hiccup must never fail
# the cron — orders already placed above) and runs AFTER the submit so the network
# round-trip never delays the 09:28 order window.
_publish_checkout_freshness() {
    local out="${REPO}/cache/live/checkout_freshness.json"
    # Only the order-path files matter — unrelated main churn must not page.
    # DERIVED, not hand-listed (2026-08-18, Doppelgaenger-Sweep E1): the old
    # five-file list was blind to the import closure — a fix landing in e.g.
    # scripts/live_risk_limits.py or the sourced ET gate kept behind=0 and the
    # stale-checkout alert silent. scripts/c13_order_path_inventory.py walks
    # the closure of the submit entry points (80+ files) and refuses to emit a
    # collapsed list; tests/test_c13_order_path_inventory.py pins it.
    local -a paths=()
    while IFS= read -r _inv_line; do
        [[ -n "${_inv_line}" ]] && paths+=("${_inv_line}")
    done < <("${PY}" -m scripts.c13_order_path_inventory 2>/dev/null)
    if [[ ${#paths[@]} -eq 0 ]]; then
        echo "phase-a cron: WARNING — order-path inventory derivation failed;" \
             "skipping the freshness measurement rather than publishing a blind one." >&2
        return 0
    fi
    # Bounded fetch so a dead network cannot hang the launchd slot indefinitely.
    git -C "${REPO}" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20 \
        fetch --quiet origin main 2>/dev/null || return 0
    local head origin_main behind now
    head="$(git -C "${REPO}" rev-parse HEAD 2>/dev/null)" || return 0
    origin_main="$(git -C "${REPO}" rev-parse origin/main 2>/dev/null)" || return 0
    behind="$(git -C "${REPO}" rev-list --count HEAD..origin/main -- "${paths[@]}" 2>/dev/null)" || return 0
    [[ "${behind}" =~ ^[0-9]+$ ]] || return 0
    now="$(date -u +%s)"
    mkdir -p "${REPO}/cache/live" 2>/dev/null || true
    printf '{"submit_code_behind_commits": %s, "head": "%s", "origin_main": "%s", "checked_at_unix": %s}\n' \
        "${behind}" "${head}" "${origin_main}" "${now}" > "${out}" 2>/dev/null || return 0
    if [[ "${behind}" -gt 0 ]]; then
        echo "phase-a cron: WARNING — submit order-path code is ${behind} commit(s) behind origin/main;" \
             "a merged fix may be undeployed on this Mac. Run 'git pull --ff-only' in ${REPO}." >&2
    fi
}
_publish_checkout_freshness || true

_write_marker "SUCCESS" "incubation-complete:audit=${AUDIT}"
