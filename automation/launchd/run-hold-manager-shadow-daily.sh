#!/usr/bin/env bash
# Hold Manager R2 shadow — daily post-close capture driver.
#
# Invoked by ~/Library/LaunchAgents/com.skippalgo.hold-manager-shadow-daily.plist
# Mon-Fri targeting 16:15 ET (shortly after the XNYS close; the plist fires at
# three ET-bracketing local times, the shared ET gate lets exactly one proceed).
#
# What it does — the mechanical half of the daily R2 observation duty:
#   1. Fetches the authenticated receiver state (per-session delivery
#      breakdown) and stores a dated snapshot under
#      ~/Library/Application Support/skipp-algo/hold-manager-shadow/.
#   2. Runs the fail-closed reconciliation in --check mode against the
#      checked-in observations: a receiver session without a recorded row
#      surfaces as a blocker — that IS the operator reminder.
#   3. Posts a macOS notification with the day's event count and verdict.
#
# What it deliberately does NOT do: write the governance observations file or
# move pinned tests. Recording a session row is an operator act (scaffold with
# scripts/scaffold_smc_hold_manager_shadow_session.py, complete the
# TradingView-side fields, run the reconcile WITHOUT --check, re-run the
# evaluator, and move the pinned checked-in-state expectations in the same PR).
#
# Secret: the receiver token is read from the login Keychain item
# `skipp.hold-manager-shadow` (never from the repo, never echoed). Missing
# token / failed fetch notify loudly and exit 0 (launchd must not flap).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"

source "$(dirname "$0")/lib_c13_et_gate.sh"
c13_require_et_window "$REPO" 16 15 10 hold-manager-shadow || exit 0

ET_DATE="$(TZ=America/New_York date +%Y-%m-%d)"
OUT_DIR="${HOLD_MANAGER_SHADOW_SNAPSHOT_DIR:-$HOME/Library/Application Support/skipp-algo/hold-manager-shadow}"
mkdir -p "$OUT_DIR"

notify() {
    # $1 = title suffix, $2 = message. Notification failures must not kill
    # the capture (headless/SSH sessions have no notification center).
    /usr/bin/osascript -e "display notification \"$2\" with title \"HM Shadow: $1\"" 2>/dev/null || true
}

TOKEN="$(security find-generic-password -s skipp.hold-manager-shadow -w 2>/dev/null || true)"
if [ -z "$TOKEN" ]; then
    echo "hold-manager-shadow[$ET_DATE]: Keychain item 'skipp.hold-manager-shadow' missing — cannot fetch state." >&2
    notify "Erfassung FEHLGESCHLAGEN" "Keychain-Token skipp.hold-manager-shadow fehlt"
    exit 0
fi

STATE_URL="${HOLD_MANAGER_SHADOW_STATE_URL:-https://liveoverlaydaemon-production.up.railway.app/tradingview/hold-manager-shadow/state}"
SNAP="$OUT_DIR/state-${ET_DATE}.json"
if ! curl -fsS -m 30 -H "X-Hold-Manager-Shadow-Token: ${TOKEN}" "$STATE_URL" > "${SNAP}.tmp"; then
    echo "hold-manager-shadow[$ET_DATE]: state fetch failed." >&2
    rm -f "${SNAP}.tmp"
    notify "Erfassung FEHLGESCHLAGEN" "Receiver-State-Fetch fehlgeschlagen (${ET_DATE})"
    exit 0
fi
mv "${SNAP}.tmp" "$SNAP"

VENV="${HM_VENV:-$REPO/.venv}"
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
    echo "hold-manager-shadow[$ET_DATE]: venv python not found at $PY (set HM_VENV in plist)." >&2
    notify "Erfassung UNVOLLSTÄNDIG" "Snapshot ok, aber venv fehlt — reconcile --check übersprungen"
    exit 0
fi

EVENTS="$("$PY" -c "import json,sys; print(json.load(open(sys.argv[1])).get('uniqueEvents', 0))" "$SNAP" 2>/dev/null || echo "?")"

# rc=2 (blocked) is an expected daily outcome, not a failure: it is exactly
# the "session row still missing / conflict" reminder for the operator.
SUMMARY="$(cd "$REPO" && "$PY" -m scripts.reconcile_smc_hold_manager_shadow_deliveries --state "$SNAP" --check 2>&1 || true)"
VERDICT="$(printf '%s\n' "$SUMMARY" | "$PY" -c "import json,sys
try:
    print(json.loads(sys.stdin.read()).get('verdict', 'parse-error'))
except Exception:
    print('parse-error')" 2>/dev/null || echo parse-error)"

echo "hold-manager-shadow[$ET_DATE]: uniqueEvents=$EVENTS reconcile-check verdict=$VERDICT snapshot=$SNAP"
printf '%s\n' "$SUMMARY"

if [ "$VERDICT" = "reconciled" ]; then
    notify "Capture $ET_DATE" "$EVENTS Events, reconcile-check OK. Session-Row (expected-Seite) erfassen + Evaluator laufen lassen."
else
    notify "Capture $ET_DATE — AKTION nötig" "$EVENTS Events, reconcile-check: $VERDICT. Session-Row erfassen/abgleichen (Details im Log)."
fi
