#!/usr/bin/env bash
# Smoke driver for the SMC Live Overlay Daemon (FastAPI).
#
# Boots the daemon locally with a fake Databento key + a throwaway path
# secret, waits for /health, then exercises every public endpoint and asserts
# the response codes / key payload fields. No real Databento account or market
# data is touched — the feed thread auth-fails harmlessly in the background
# while the HTTP surface serves the honest "stale / no data" state.
#
# Usage (from anywhere in the repo):
#   bash services/live_overlay_daemon/e2e/smoke.sh
#
# Env overrides: PORT (default 8799), TOKEN (default smoketoken123),
#   PY (default .venv/bin/python, falls back to python3).
set -uo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

PORT="${PORT:-8799}"
TOKEN="${TOKEN:-smoketoken123}"
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
B="http://127.0.0.1:${PORT}"
LOG="$(mktemp -t overlay-daemon.XXXXXX.log)"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=1; }
check() { # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then pass "$1 ($2)"; else fail "$1 (got $2, want $3)"; fi
}

echo "Launching daemon on :${PORT} (log: $LOG)"
OVERLAY_SECRET_TOKEN="$TOKEN" \
DATABENTO_API_KEY="db-fake0000000000000000000000000000" \
PORT="$PORT" LOG_LEVEL="warning" \
  "$PY" -m services.live_overlay_daemon.main >"$LOG" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; rm -f "$LOG"; }
trap cleanup EXIT

# Wait for liveness (feed auth-fails in the background; HTTP still serves).
for _ in $(seq 1 30); do
  code=$(curl -sS -m 2 -o /dev/null -w '%{http_code}' "$B/health" 2>/dev/null || echo 000)
  [ "$code" = "200" ] && break
  kill -0 "$PID" 2>/dev/null || { echo "daemon exited early:"; tail -20 "$LOG"; exit 1; }
  sleep 0.5
done

echo "Driving endpoints:"
check "/health"                 "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/health")" 200
check "/ready"                  "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/ready")" 200
check "/{token}/smc_live"       "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/$TOKEN/smc_live?symbol=AAPL&tf=15m")" 200
check "/metrics (basic auth)"   "$(curl -sS -m5 -u "x:$TOKEN" -o /dev/null -w '%{http_code}' "$B/metrics")" 200
check "/{token}/metrics"        "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/$TOKEN/metrics")" 200
check "bad token -> 404"        "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/WRONGTOKEN/smc_live?symbol=AAPL&tf=15m")" 404
check "unauth /metrics -> 401"  "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/metrics")" 401

# Payload shape assertions.
smc=$(curl -sS -m5 "$B/$TOKEN/smc_live?symbol=AAPL&tf=15m")
echo "$smc" | grep -q '"schema":"smc-live-overlay/1"' && pass "smc_live schema field" || fail "smc_live schema field"
echo "$smc" | grep -q '"symbol":"AAPL"' && pass "smc_live echoes symbol" || fail "smc_live echoes symbol"
metrics=$(curl -sS -m5 -u "x:$TOKEN" "$B/metrics")
n=$(printf '%s\n' "$metrics" | grep -c '^live_overlay_')
[ "$n" -ge 100 ] && pass "metrics exposes $n live_overlay_* series" || fail "metrics series count ($n)"
printf '%s\n' "$metrics" | grep -q '^live_overlay_trading_signals_active_total' \
  && pass "trading_signals gauges present" || fail "trading_signals gauges present"

echo
if [ "$FAILED" = 0 ]; then echo "SMOKE OK"; else echo "SMOKE FAILED"; fi
exit "$FAILED"
