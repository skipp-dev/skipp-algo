#!/usr/bin/env bash
# One-command driver for the Streamlit terminal GUI (streamlit_terminal.py):
# launch headless → wait for health → screenshot the RENDERED app with
# Playwright → tear down. Prints the screenshot path (Read it to verify).
#
# SAFETY: streamlit_terminal.py auto-loads the repo .env and fetches live
# provider data on load, so a naive run spends real FMP/Benzinga quota. This
# shadows every secret-like .env key with a fake value first, so the app
# renders its full chrome (sidebar/config/metrics) with a degraded/empty feed
# instead of billing.
#
# Usage (from anywhere in the repo):
#   bash e2e/screenshot_terminal.sh            # -> writes a temp PNG, prints path
#   OUT=/tmp/term.png bash e2e/screenshot_terminal.sh
#
# Env overrides: PORT (8501), OUT (mktemp .png), PY (.venv/bin/python).
set -uo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

PORT="${PORT:-8501}"
OUT="${OUT:-$(mktemp -t terminal-shot).png}"
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY="python3"
B="http://127.0.0.1:${PORT}"
LOG="$(mktemp -t streamlit-terminal.XXXXXX.log)"

SHADOW=""
if [ -f .env ]; then
  SHADOW="$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | sed 's/=$//' \
            | grep -iE 'KEY|TOKEN|SECRET|API' | sed 's/$/=fake-smoke/' | tr '\n' ' ')"
fi
echo "Shadowing $(printf '%s' "$SHADOW" | wc -w | tr -d ' ') .env secret(s); launching on :${PORT} (log: $LOG)"

# shellcheck disable=SC2086  # intentional word-split of KEY=val tokens
env $SHADOW FMP_API_KEY=fake-smoke \
  "$PY" -m streamlit run streamlit_terminal.py \
    --server.headless true --server.port "$PORT" --server.address 127.0.0.1 \
    --browser.gatherUsageStats false >"$LOG" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null; wait "$PID" 2>/dev/null; rm -f "$LOG"; }
trap cleanup EXIT

# Wait for Streamlit liveness.
for _ in $(seq 1 40); do
  [ "$(curl -sS -m2 -o /dev/null -w '%{http_code}' "$B/_stcore/health" 2>/dev/null || echo 000)" = "200" ] && break
  kill -0 "$PID" 2>/dev/null || { echo "streamlit exited early:"; tail -20 "$LOG"; exit 1; }
  sleep 0.5
done

# Screenshot the rendered app (Playwright waits for the websocket render).
node e2e/streamlit_screenshot.mjs "$B" "$OUT" || { echo "screenshot failed"; tail -20 "$LOG"; exit 1; }

# A rendered terminal is ~50-70 KB; the loading skeleton is ~15-20 KB.
bytes=$(wc -c <"$OUT" | tr -d ' ')
if [ "$bytes" -ge 30000 ]; then
  echo "SCREENSHOT OK: $OUT (${bytes} bytes) — Read it to verify the rendered terminal."
else
  echo "SCREENSHOT SUSPECT: $OUT is only ${bytes} bytes (likely the loading skeleton, not the app)."
  exit 1
fi
