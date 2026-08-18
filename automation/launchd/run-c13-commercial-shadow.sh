#!/usr/bin/env bash
# C13 commercial-family shadow — intraday local cron driver for the
# Phase-1 commercial paper pilot (weekly review 2026-08-16, P0).
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.c13.commercial-shadow.plist
# at several RTH candidate times (see the plist); the ET gate below no-ops
# any fire that lands outside regular trading hours.
#
# Pipeline per fire:
#   1. pull_databento_edge_input.py  → point-in-time payload (bars + SMC
#      structure) for ${C13_COMMERCIAL_SYMBOL}
#   2. run_commercial_shadow_campaign.py → audit-only campaign attempt under
#      cache/live/commercial_campaign/ (immutable attempts, strict audit,
#      observation gate PENDING→PASS after >=20 unique snapshots; verdict
#      QUIET = only blocker is a family with zero setups — distinct from
#      FAIL since 2026-08-18 (C4), paper stays dormant on both; failure
#      budget is a rolling window of the last 20 substantive attempts (C2))
#   3. DORMANT paper stage — runs ONLY when BOTH interlocks hold:
#        a. configs/commercial_paper_submission.json says enabled=true
#           (a dated operator decision, flipped by PR after reviewing the
#           campaign observation gate — the pilot doc's launch-gate review)
#        b. campaign_report.json observation_gate.verdict == "PASS"
#      Then the documented split invocation runs with the REAL paper
#      submitter (--place-paper-orders --prospective-paper-pilot) into
#      cache/live/incubation_commercial_<DATE>.jsonl — the families
#      telemetry glob picks that file up and the Phase-1 gate can flip.
#
# Until both interlocks hold this driver cannot place any order: the
# campaign controller has no broker I/O path at all, and the paper stage
# is skipped with a logged reason. The submitter itself additionally
# refuses non-paper ports and non-DU* accounts.
#
# Repo policy: never --force, never --no-verify.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

# RTH gate: target 12:45 ET with ±195m tolerance = 09:30–16:00 ET. Unlike
# the 09:28 order window there is no single correct minute — any RTH
# snapshot is a valid observation — so the wide window is the point.
# Scope "hour": one attempt per ET HOUR, not per day — ~6 observations per
# session is the whole design, and a failed attempt must only burn its own
# hour slot (2026-08-17: the day-scoped marker let the failed 16:05 fire
# swallow all five later fires).
source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" 12 45 195 commercial-shadow hour || exit 0

VENV="${C13_VENV:-${REPO}/.venv}"
DATE="$(date -u +%Y-%m-%d)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SYMBOL="${C13_COMMERCIAL_SYMBOL:-AAPL}"
# EQUS.MINI, not XNAS.ITCH: current-day XNAS.ITCH history is gated on a live
# data license this account does not hold (measured 2026-08-17 23:42Z: the
# clamped retry answered "403 license_not_found_unauthorized ... A live data
# license is required to access XNAS.ITCH data after <T-1 04:00Z>"). The
# account DOES hold the EQUS.MINI live license — the same feed family the
# signals producers already consume — so its current-day history is pullable
# (proven end-to-end same night: 201 bars, clamp engaged, campaign attempt
# audited into a scratch dir).
DATASET="${C13_COMMERCIAL_DATASET:-EQUS.MINI}"
CAMPAIGN_DIR="${REPO}/cache/live/commercial_campaign"
PIT_INPUT="${CAMPAIGN_DIR}/inputs/pit_${SYMBOL}_${STAMP}.json"
SUBMISSION_CONFIG="${REPO}/configs/commercial_paper_submission.json"
CAMPAIGN_REPORT="${CAMPAIGN_DIR}/campaign_report.json"
PAPER_AUDIT="${REPO}/cache/live/incubation_commercial_${DATE}.jsonl"
PORTFOLIO_BEFORE="${REPO}/cache/live/portfolio_before_commercial_${DATE}.json"
PORTFOLIO_LIMITS="${REPO}/configs/portfolio_risk_limits.json"
STATUS_MARKER="${REPO}/cache/live/.commercial_shadow_status_${DATE}"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "${REPO}/cache/live"
    # Append, never truncate: up to six fires share this day file and a later
    # fire must not erase an earlier fire's outcome (the old `>` lost five of
    # six attempts). Operator-inspectable day log; NO automated consumer
    # reads it (verified 2026-08-18 — nothing greps this marker family).
    printf '%s %s|%s\n' "$(date -u +%H:%M:%SZ)" "${kind}" "${msg}" >> "${STATUS_MARKER}"
}

cd "${REPO}"
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "commercial-shadow cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "venv-missing:${VENV}/bin/activate"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"
PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "commercial-shadow cron: python interpreter not found/executable at ${PY} (check C13_VENV in plist)" >&2
    _write_marker "DEGRADED" "python-not-executable:${PY}"
    exit 1
fi
export PYTHONPATH="${REPO}"

# smoke_HALT means danger with state a human must inspect (risk violation /
# leftover non-terminal orders) — the paper stage must not submit past it,
# and pausing the observation too costs nothing compared to the confusion
# of half-running pipelines under a standing sentinel.
SMOKE_HALT_PATH="${REPO}/cache/live/smoke_HALT"
if [[ -f "${SMOKE_HALT_PATH}" ]]; then
    echo "commercial-shadow cron: smoke_HALT sentinel present" \
         "($(head -c 200 "${SMOKE_HALT_PATH}" | tr -d '\n')) — skipping this fire" >&2
    _write_marker "DEGRADED" "smoke-halt-sentinel"
    exit 1
fi

# 1. Point-in-time pull: 5 calendar days of 1m bars end at "now", the
#    producer's freshness guard (max_event_age) does the rest. A failed
#    pull is a failed ATTEMPT statistic, not a broken chain — recorded as a
#    DEGRADED line in the operator-inspectable day log.
mkdir -p "${CAMPAIGN_DIR}/inputs"
START="$(date -u -v-5d +%Y-%m-%d 2>/dev/null || date -u -d '5 days ago' +%Y-%m-%d)"
END="$(date -u +%Y-%m-%dT%H:%M:%S)"
_pull_exit=0
"${PY}" -m scripts.pull_databento_edge_input \
    --symbol "${SYMBOL}" \
    --dataset "${DATASET}" \
    --timeframe 15m \
    --start "${START}" \
    --end "${END}" \
    --output "${PIT_INPUT}" || _pull_exit=$?
if [ "${_pull_exit}" -ne 0 ]; then
    echo "commercial-shadow cron: databento pull FAILED (exit ${_pull_exit})" >&2
    _write_marker "DEGRADED" "databento-pull-failed:symbol=${SYMBOL}"
    exit "${_pull_exit}"
fi

# 2. Audit-only campaign attempt (no network/broker I/O by construction).
#    Freshness budgets 900s (not the 300s defaults): Databento historical
#    availability trails the wall clock intraday — measured 2026-08-17,
#    XNAS.ITCH served up to 14:00:00Z at a 14:05:00Z request — so a clamped
#    point-in-time pull is ~5-7 minutes old by construction and 300s would
#    fail-close every honest attempt. 900s still catches a genuinely stale
#    chain (yesterday's payload is hours old). The campaign contract freezes
#    these numbers immutably; the review before any broker flip sees them.
_campaign_exit=0
"${PY}" -m scripts.run_commercial_shadow_campaign \
    --input "${PIT_INPUT}" \
    --campaign-dir "${CAMPAIGN_DIR}" \
    --max-setup-age-seconds 900 \
    --max-source-age-p95-seconds 900 || _campaign_exit=$?
if [ "${_campaign_exit}" -ne 0 ]; then
    echo "commercial-shadow cron: campaign attempt FAILED (exit ${_campaign_exit})" >&2
    _write_marker "DEGRADED" "campaign-attempt-failed:input=${PIT_INPUT}"
    exit "${_campaign_exit}"
fi

# Publish the campaign report on EVERY successful attempt (sanitised
# aggregate, no account state) so observation progress is visible on the
# data branch during the audit-only weeks, not only after the flip.
# shellcheck disable=SC1091
source "$(dirname "$0")/lib_c13_data_push.sh"
_push_exit=0
push_to_data_branch "chore(c13): commercial shadow ${DATE}" \
    "${REPO}/cache/live/.commercial_shadow_push_status_${DATE}" \
    "cache/live/commercial_campaign/campaign_report.json" || _push_exit=$?
if [ "${_push_exit}" -ne 0 ]; then
    # Report publishing is best-effort visibility; the attempt itself is
    # already durably recorded under the campaign dir, and a git/network
    # hiccup must not abort the fire before the paper-stage decision and
    # marker run (the old hard exit left the day with no status at all —
    # and once the flip arms the paper stage, a GitHub outage must never
    # become a trading outage).
    echo "commercial-shadow cron: report push failed (exit ${_push_exit}) — continuing" >&2
    _write_marker "DEGRADED" "report-push-failed:exit=${_push_exit}"
fi

# 3. Paper stage — double interlock, both sides machine-readable.
_submission_enabled="$("${PY}" -c "
import json, sys
try:
    cfg = json.load(open('${SUBMISSION_CONFIG}'))
    print('true' if cfg.get('enabled') is True else 'false')
except Exception:
    print('false')
")"
_campaign_verdict="$("${PY}" -c "
import json
try:
    report = json.load(open('${CAMPAIGN_REPORT}'))
    print(report.get('observation_gate', {}).get('verdict', 'ABSENT'))
except Exception:
    print('ABSENT')
")"
if [[ "${_submission_enabled}" != "true" || "${_campaign_verdict}" != "PASS" ]]; then
    echo "commercial-shadow cron: paper stage dormant" \
         "(submission_enabled=${_submission_enabled}, campaign_verdict=${_campaign_verdict})" \
         "— audit-only observation recorded"
    _write_marker "SUCCESS" "campaign-observed:paper-dormant:verdict=${_campaign_verdict}"
    exit 0
fi

# Interlocks hold: run the documented split invocation with the REAL paper
# submitter. Same guards as phase-a: fresh portfolio snapshot required,
# paper port + DU* enforced inside the submitter.
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
if ! _capture_portfolio_before || [[ ! -s "${PORTFOLIO_BEFORE}" ]]; then
    echo "commercial-shadow cron: portfolio snapshot missing/failed — refusing paper submit" >&2
    _write_marker "DEGRADED" "portfolio-snapshot-failed:path=${PORTFOLIO_BEFORE}"
    exit 1
fi

SETUPS_OUT="${CAMPAIGN_DIR}/inputs/setups_${STAMP}.json"
GATES_OUT="${CAMPAIGN_DIR}/inputs/gates_${STAMP}.json"
DIAG_OUT="${CAMPAIGN_DIR}/inputs/diagnostics_${STAMP}.json"
_producer_exit=0
"${PY}" -m scripts.build_commercial_family_setups \
    --input "${PIT_INPUT}" \
    --setups-output "${SETUPS_OUT}" \
    --gate-status-output "${GATES_OUT}" \
    --diagnostics-output "${DIAG_OUT}" \
    --trade-date "${DATE}" || _producer_exit=$?
if [ "${_producer_exit}" -ne 0 ]; then
    echo "commercial-shadow cron: setup producer FAILED (exit ${_producer_exit})" >&2
    _write_marker "DEGRADED" "producer-failed:input=${PIT_INPUT}"
    exit "${_producer_exit}"
fi

# WSH earnings filter — mirrors run-c13-phase-a.sh: newest snapshot wins,
# at most 4 days old (tolerates a long weekend), otherwise the filter is
# skipped LOUDLY. Without this flag EarningsFilter is None and the pilot
# doc's promised earnings-blocked audit rows can never exist (2026-08-18
# Verdrahtungs-Sweep K7).
WSH_FLAG=""
WSH_FILE="${REPO}/cache/wsh/${DATE}.jsonl"
if [[ ! -f "${WSH_FILE}" ]]; then
    # ISO-dated filenames sort chronologically; newest wins.
    WSH_FILE="$(ls -1 "${REPO}"/cache/wsh/*.jsonl 2>/dev/null | sort | tail -n1 || true)"
fi
if [[ -n "${WSH_FILE}" && -f "${WSH_FILE}" ]]; then
    WSH_BASENAME="$(basename "${WSH_FILE}" .jsonl)"
    _today_epoch="$(date -u -j -f "%Y-%m-%d" "${DATE}" "+%s" 2>/dev/null || echo "")"
    _file_epoch="$(date -u -j -f "%Y-%m-%d" "${WSH_BASENAME}" "+%s" 2>/dev/null || echo "")"
    if [[ -n "${_today_epoch}" && -n "${_file_epoch}" ]]; then
        WSH_AGE_DAYS=$(( (_today_epoch - _file_epoch) / 86400 ))
    else
        WSH_AGE_DAYS=-1
    fi
    if [[ "${WSH_AGE_DAYS}" -ge 0 && "${WSH_AGE_DAYS}" -le 4 ]]; then
        echo "commercial-shadow cron: applying WSH earnings filter from ${WSH_FILE} (age ${WSH_AGE_DAYS}d)"
        WSH_FLAG="--wsh-events-jsonl ${WSH_FILE}"
    else
        echo "commercial-shadow cron: newest WSH snapshot ${WSH_FILE} is ${WSH_AGE_DAYS}d old (>4d or unparseable); earnings filter SKIPPED (stale)" >&2
    fi
else
    echo "commercial-shadow cron: no WSH snapshot found under cache/wsh/; earnings filter SKIPPED (no data)" >&2
fi

# Snapshot idempotency guard: the audit-only path skips replayed snapshots
# (REPLAY_SKIPPED), but this split invocation bypasses run_shadow_once and
# run_smc_live_incubation appends blindly — and a wake-catch-up fire can
# cross an ET hour boundary and pass the hour-scoped gate twice minutes
# apart. The same source snapshot must never be submitted twice.
_snapshot_id="$("${PY}" -c "
import json
try:
    doc = json.load(open('${SETUPS_OUT}'))
    setups = doc.get('setups', doc) if isinstance(doc, dict) else doc
    if not setups:
        print('EMPTY')
    else:
        ids = {s.get('source_snapshot_id') for s in setups if isinstance(s, dict)}
        ids.discard(None)
        print(next(iter(ids)) if len(ids) == 1 else '')
except Exception:
    print('')
")"
if [[ "${_snapshot_id}" == "EMPTY" ]]; then
    echo "commercial-shadow cron: producer emitted no setups — nothing to submit"
    _write_marker "SUCCESS" "paper-no-setups:setups=${SETUPS_OUT}"
    exit 0
fi
if [[ -z "${_snapshot_id}" ]]; then
    echo "commercial-shadow cron: no unambiguous source_snapshot_id in setups — refusing paper submit" >&2
    _write_marker "DEGRADED" "paper-snapshot-id-missing:setups=${SETUPS_OUT}"
    exit 1
fi
if [[ -f "${PAPER_AUDIT}" ]] && grep -qF "${_snapshot_id}" "${PAPER_AUDIT}"; then
    echo "commercial-shadow cron: snapshot ${_snapshot_id} already in ${PAPER_AUDIT} — skipping duplicate paper submit"
    _write_marker "SUCCESS" "paper-duplicate-snapshot-skipped:${_snapshot_id}"
    exit 0
fi

_run_exit=0
# Same vendor-honest 900s freshness budget as the campaign stage above: the
# setups come from the SAME clamped PIT pull (~5-7 minutes old by
# construction, measured 2026-08-17), so the submitter's 300s default would
# fail-close every honest submission (2026-08-18 Verdrahtungs-Sweep K3).
# shellcheck disable=SC2086  # WSH_FLAG is deliberately word-split
"${PY}" -m scripts.run_smc_live_incubation \
    --phase paper \
    --place-paper-orders \
    --prospective-paper-pilot \
    --setups "${SETUPS_OUT}" \
    --gate-statuses "${GATES_OUT}" \
    --max-setup-age-seconds 900 \
    ${WSH_FLAG} \
    --audit-output "${PAPER_AUDIT}" \
    --portfolio-snapshot-json "${PORTFOLIO_BEFORE}" \
    --portfolio-risk-limits-json "${PORTFOLIO_LIMITS}" || _run_exit=$?
if [ "${_run_exit}" -ne 0 ]; then
    echo "commercial-shadow cron: commercial paper submit FAILED (exit ${_run_exit})" >&2
    _write_marker "DEGRADED" "commercial-submit-failed:audit=${PAPER_AUDIT}"
    exit "${_run_exit}"
fi

# The families-telemetry glob on the CI side reads cache/live/incubation_*.jsonl
# from data/phase-a-audit — without this push the commercial paper audit never
# reaches the Phase-1 gate. This mechanises the header's promise ("the
# families telemetry glob picks that file up"), which had no transport edge
# (2026-08-18 Verdrahtungs-Sweep K1). Same sanitisation class as the phase-a
# audit push: per-intent audit rows only, no account state.
_paper_push_exit=0
push_to_data_branch "chore(c13): commercial paper audit ${DATE}" \
    "${REPO}/cache/live/.commercial_paper_push_status_${DATE}" \
    "cache/live/incubation_commercial_${DATE}.jsonl" || _paper_push_exit=$?
if [ "${_paper_push_exit}" -ne 0 ]; then
    # The submission already happened; a git hiccup here must not hide that
    # from the day log (the reconcile driver pushes the file again at 23:05).
    echo "commercial-shadow cron: paper-audit push failed (exit ${_paper_push_exit}) — continuing" >&2
    _write_marker "DEGRADED" "paper-audit-push-failed:exit=${_paper_push_exit}"
fi

_write_marker "SUCCESS" "commercial-paper-submitted:audit=${PAPER_AUDIT}"
