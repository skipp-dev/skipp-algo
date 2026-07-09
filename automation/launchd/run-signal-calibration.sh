#!/usr/bin/env bash
# Nightly signal follow-through calibration — local launchd driver.
# Invoked by ~/Library/LaunchAgents/com.skippalgo.signals.calibration.plist
# on Mon-Fri @ 23:15 local time: after the US cash close in both EU/US DST
# regimes AND after the 23:05 C13 reconcile, so the two FMP-consuming night
# jobs never overlap.
#
# Pipeline (measurement, NOT optimization — see the Holly analysis decision):
#   scripts/calibrate_signal_followthrough.py joins the day's signal events
#   (written by the realtime engine when RT_SIGNAL_EVENT_LOG_DIR is set) to
#   FMP 1-minute bars and writes the empirical follow-through table
#   P(favorable move >= target | level, volume bucket) as
#   calibration_<DATE>.json + calibration_latest.json in the events dir.
#
# Quiet no-op (exit 0) when no event files exist yet — engine not logging,
# holiday, or the env var simply not set on this machine.
#
# Repo policy: never --force, never --no-verify. This driver does not push.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
VENV="${SIGNAL_CAL_VENV:-${REPO}/.venv}"
EVENTS_DIR="${RT_SIGNAL_EVENT_LOG_DIR:-${REPO}/artifacts/open_prep/signal_events}"

DATE="$(date -u +%Y-%m-%d)"
STATUS_MARKER="${EVENTS_DIR}/.calibration_status_${DATE}"
TS="$(date -u +%FT%TZ)"

_write_marker() {
    local kind="$1"
    local msg="${2:-}"
    mkdir -p "$(dirname "${STATUS_MARKER}")" 2>/dev/null || true
    printf '%s:%s:%s\n' "${kind}" "${msg}" "${TS}" > "${STATUS_MARKER}" 2>/dev/null || true
}

cd "${REPO}"

# Lane 7: venv-realism guard (clear message instead of a cryptic set -u error).
if [[ ! -f "${VENV}/bin/activate" ]]; then
    echo "signal-calibration cron: virtualenv activate script not found at ${VENV}/bin/activate (set SIGNAL_CAL_VENV in plist)" >&2
    _write_marker "DEGRADED" "preflight-error"
    exit 1
fi
# shellcheck disable=SC1091
source "${VENV}/bin/activate"

PY="${VENV}/bin/python"
if [[ ! -x "${PY}" ]]; then
    echo "signal-calibration cron: python interpreter not executable at ${PY} (check SIGNAL_CAL_VENV in plist)" >&2
    _write_marker "DEGRADED" "preflight-error"
    exit 1
fi

# launchd inherits no shell profile: surface FMP_API_KEY from ${REPO}/.env
# when the plist does not provide one. Read the single KEY=VALUE line
# verbatim (no eval, no sourcing of arbitrary shell) and strip optional
# surrounding quotes; the value is never echoed.
if [[ -z "${FMP_API_KEY:-}" && -f "${REPO}/.env" ]]; then
    _fmp_line="$(grep -m1 '^FMP_API_KEY=' "${REPO}/.env" || true)"
    if [[ -n "${_fmp_line}" ]]; then
        FMP_API_KEY="${_fmp_line#FMP_API_KEY=}"
        FMP_API_KEY="${FMP_API_KEY%\"}"; FMP_API_KEY="${FMP_API_KEY#\"}"
        FMP_API_KEY="${FMP_API_KEY%\'}"; FMP_API_KEY="${FMP_API_KEY#\'}"
        export FMP_API_KEY
    fi
fi
if [[ -z "${FMP_API_KEY:-}" ]]; then
    echo "signal-calibration cron: FMP_API_KEY not set (env or ${REPO}/.env) — cannot fetch 1-min bars" >&2
    _write_marker "DEGRADED" "no-fmp-key"
    exit 1
fi

# No signal events yet is a quiet no-op, not an error: the realtime engine
# only writes them when RT_SIGNAL_EVENT_LOG_DIR is set, and holidays produce
# no signals at all.
if [[ ! -d "${EVENTS_DIR}" ]] || ! ls "${EVENTS_DIR}"/signal_events_*.jsonl >/dev/null 2>&1; then
    echo "signal-calibration cron: no signal_events_*.jsonl under ${EVENTS_DIR} — nothing to calibrate"
    _write_marker "SKIPPED" "no-events"
    exit 0
fi

OUT_DATED="${EVENTS_DIR}/calibration_${DATE}.json"
"${PY}" scripts/calibrate_signal_followthrough.py \
    --events-dir "${EVENTS_DIR}" \
    --horizon-min "${SIGNAL_CAL_HORIZON_MIN:-60}" \
    --target-pct "${SIGNAL_CAL_TARGET_PCT:-0.5}" \
    --out "${OUT_DATED}"

# latest = stable path for consumers (rt_notify threshold source, dashboards).
cp -f "${OUT_DATED}" "${EVENTS_DIR}/calibration_latest.json"
_write_marker "OK" "calibrated"
echo "signal-calibration cron: wrote ${OUT_DATED} (+ calibration_latest.json)"
