#!/usr/bin/env bash
# Smoke driver for the SMC signals producer (the 24/7 realtime engine,
# open_prep.realtime_signals) — the process that produces the signal snapshot
# the live-overlay daemon serves.
#
# Boots the engine with a spare telemetry port on loopback and a Bearer token,
# waits for /healthz, then exercises the telemetry HTTP surface
# (/healthz, /readyz, /telemetry.json, /metrics, /signals) and asserts codes +
# key content before killing it.
#
# SAFETY: main() auto-loads the repo .env, so a naive run makes REAL,
# quota-consuming provider calls (FMP/Benzinga) with your live keys. This
# driver shadows every secret-like .env key with a fake value first
# (load_dotenv uses override=False, so the shell env wins) — no authenticated
# provider calls are made. Public unauthenticated Benzinga RSS may still be
# fetched during the single poll cycle before teardown.
#
# Usage (from anywhere in the repo):
#   bash services/signals_producer/e2e/smoke.sh
#
# Env overrides: PORT (default 8199), TOKEN (default smokebearer123),
#   PY (default .venv/bin/python, falls back to python3).
set -uo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

PORT="${PORT:-8199}"
TOKEN="${TOKEN:-smokebearer123}"
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
B="http://127.0.0.1:${PORT}"
LOG="$(mktemp -t signals-producer.XXXXXX.log)"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=1; }
check() { if [ "$2" = "$3" ]; then pass "$1 ($2)"; else fail "$1 (got $2, want $3)"; fi; }

# Shadow every secret-like key in .env with a fake so the auto-loaded .env
# (load_dotenv override=False) cannot inject real credentials into the poll.
SHADOW=()
if [ -f .env ]; then
  while IFS= read -r k; do SHADOW+=("$k=fake-smoke"); done < <(
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | sed 's/=$//' | grep -iE 'KEY|TOKEN|SECRET|API' | sort -u
  )
fi
echo "Shadowing ${#SHADOW[@]} .env secret(s); launching engine on :${PORT} (log: $LOG)"

# ${arr[@]+"${arr[@]}"} — portable empty-array expansion (macOS bash 3.2 errors
# on a bare "${arr[@]}" under `set -u` when the array is empty, e.g. a checkout
# with no .env such as a bare git worktree).
env ${SHADOW[@]+"${SHADOW[@]}"} \
  FMP_API_KEY=fake-smoke-key \
  SIGNALS_INTERNAL_TOKEN="$TOKEN" \
  TELEMETRY_BIND_HOST=127.0.0.1 \
  "$PY" -m open_prep.realtime_signals --telemetry-port "$PORT" --interval 5 --top-n 3 \
  >"$LOG" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; rm -f "$LOG"; }
trap cleanup EXIT

for _ in $(seq 1 40); do
  code=$(curl -sS -m 2 -o /dev/null -w '%{http_code}' "$B/healthz" 2>/dev/null || echo 000)
  [ "$code" = "200" ] && break
  kill -0 "$PID" 2>/dev/null || { echo "engine exited early:"; tail -25 "$LOG"; exit 1; }
  sleep 0.5
done

echo "Driving telemetry endpoints:"
check "/healthz"                    "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/healthz")" 200
# /readyz is 503 until a watchlist + fresh poll exist (honest cold-start state).
rz=$(curl -sS -m5 -w '\n%{http_code}' "$B/readyz"); rzcode=$(printf '%s' "$rz" | tail -1)
[ "$rzcode" = "200" ] || [ "$rzcode" = "503" ] && pass "/readyz reachable ($rzcode: $(printf '%s' "$rz" | head -1))" || fail "/readyz ($rzcode)"
check "/telemetry.json"             "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/telemetry.json")" 200
check "/metrics no token -> 401"    "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/metrics")" 401
check "/metrics + Bearer -> 200"    "$(curl -sS -m5 -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}' "$B/metrics")" 200
check "/signals no token -> 401"    "$(curl -sS -m5 -o /dev/null -w '%{http_code}' "$B/signals")" 401
check "/signals + Bearer -> 200"    "$(curl -sS -m5 -H "Authorization: Bearer $TOKEN" -o /dev/null -w '%{http_code}' "$B/signals")" 200

# Content assertions (stable engine surface — present on any checkout).
metrics=$(curl -sS -m5 -H "Authorization: Bearer $TOKEN" "$B/metrics")
n=$(printf '%s\n' "$metrics" | grep -c '^signals_producer_')
[ "$n" -ge 5 ] && pass "metrics exposes $n signals_producer_* series" || fail "metrics series count ($n)"
printf '%s\n' "$metrics" | grep -q '^signals_producer_watchlist_symbols' \
  && pass "engine gauges present (watchlist_symbols)" || fail "engine gauges present"
# Informational: the FMP usage counter (#3279) only appears on trees that
# include that PR and once the lazy FMP client has been created by a poll.
if printf '%s\n' "$metrics" | grep -q '^signals_producer_fmp_requests_total'; then
  pass "FMP usage counter present (#3279)"
else
  printf '  \033[33mINFO\033[0m FMP usage counter absent (pre-#3279 tree or no poll yet) — not asserted\n'
fi
sig=$(curl -sS -m5 -H "Authorization: Bearer $TOKEN" "$B/signals")
printf '%s' "$sig" | grep -q '"signal_count"' && pass "/signals payload has signal_count" || fail "/signals signal_count"

# Safety assertion: no AUTHENTICATED provider call with a real key leaked.
if grep -qE 'api\.benzinga\.com/[^ ]*token=(bz\.|[A-Za-z0-9]{20})' "$LOG"; then
  fail "SAFETY: an authenticated Benzinga call with a real-looking token appeared in the log"
else
  pass "no authenticated provider call with a real key (secrets shadowed)"
fi

echo
if [ "$FAILED" = 0 ]; then echo "SMOKE OK"; else echo "SMOKE FAILED"; fi
exit "$FAILED"
