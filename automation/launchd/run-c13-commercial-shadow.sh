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
#      observation gate PENDING→PASS after >=20 unique snapshots)
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
DATASET="${C13_COMMERCIAL_DATASET:-XNAS.ITCH}"
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
    printf '%s|%s\n' "${kind}" "${msg}" > "${STATUS_MARKER}"
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
#    pull is a failed ATTEMPT statistic, not a broken chain — but it is a
#    DEGRADED day marker so the audit-push driver surfaces it.
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
push_to_data_branch "chore(c13): commercial shadow ${DATE}" \
    "${REPO}/cache/live/.commercial_shadow_push_status_${DATE}" \
    "cache/live/commercial_campaign/campaign_report.json"

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

_run_exit=0
"${PY}" -m scripts.run_smc_live_incubation \
    --phase paper \
    --place-paper-orders \
    --prospective-paper-pilot \
    --setups "${SETUPS_OUT}" \
    --gate-statuses "${GATES_OUT}" \
    --audit-output "${PAPER_AUDIT}" \
    --portfolio-snapshot-json "${PORTFOLIO_BEFORE}" \
    --portfolio-risk-limits-json "${PORTFOLIO_LIMITS}" || _run_exit=$?
if [ "${_run_exit}" -ne 0 ]; then
    echo "commercial-shadow cron: commercial paper submit FAILED (exit ${_run_exit})" >&2
    _write_marker "DEGRADED" "commercial-submit-failed:audit=${PAPER_AUDIT}"
    exit "${_run_exit}"
fi

_write_marker "SUCCESS" "commercial-paper-submitted:audit=${PAPER_AUDIT}"
