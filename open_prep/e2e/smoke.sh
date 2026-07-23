#!/usr/bin/env bash
# Smoke driver for the open_prep pre-open scoring CLI (open_prep.run_open_prep) —
# the batch pipeline head that produces the ranked-candidate snapshot the
# realtime signals producer (and, downstream, the live-overlay daemon) consume.
#
# Runs one real end-to-end scoring pass over two explicit symbols and asserts
# the CLI exits 0 and writes a well-formed latest_open_prep_run.json.
#
# TWO safety measures (both verified by the driver):
#   1. main() auto-loads the repo .env, so a naive run makes REAL,
#      quota-costing FMP/Benzinga calls. This shadows every secret-like .env
#      key with a fake value (load_dotenv override=False → shell env wins), so
#      the run degrades to empty provider data instead of spending quota.
#   2. The CLI writes artifacts/open_prep/latest/*.json RELATIVE TO CWD, which
#      would clobber your real pipeline output. This runs in a throwaway temp
#      CWD (with PYTHONPATH=repo so `-m open_prep...` still resolves) and then
#      asserts the repo's real artifact was not touched.
#
# Usage (from anywhere in the repo):
#   bash open_prep/e2e/smoke.sh
#
# Env overrides: PY (default: this checkout's .venv, then the main checkout's
#   .venv, then python3 — first candidate that can import
#   open_prep.run_open_prep wins),
#   SMOKE_SYMBOLS (default AAPL,MSFT).
set -uo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"

# Interpreter resolution (worktree-aware): $PY > this checkout's .venv >
# the MAIN checkout's .venv (via git-common-dir) > python3. `git worktree`
# checkouts have no .venv of their own, so the old two-line fallback landed on
# the system python3 (3.9) while pyproject.toml declares requires-python
# ">=3.12" — the smoke then died on `cannot import name 'UTC' from 'datetime'`
# and similar, which reads like a product bug rather than a wrong interpreter.
# Mirrors scripts/run_ledger_drift_guard.sh, including its "candidate must be
# able to import what we need" check: probing the exact module this smoke runs
# covers both the version floor and the third-party deps in one go. The probe
# is side-effect free — open_prep.run_open_prep loads .env inside main(), not at
# import time.
MAIN_ROOT="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
PY_RESOLVED=""
for cand in "${PY:-}" "$ROOT/.venv/bin/python" "$MAIN_ROOT/.venv/bin/python" \
            "$ROOT/.venv/Scripts/python.exe" "$MAIN_ROOT/.venv/Scripts/python.exe" \
            python3 python; do
  [ -n "$cand" ] || continue
  if "$cand" -c "import open_prep.run_open_prep" 2>/dev/null; then
    PY_RESOLVED="$cand"
    break
  fi
done
if [ -z "$PY_RESOLVED" ]; then
  echo "ERROR: no python that can import open_prep.run_open_prep (tried \$PY, $ROOT/.venv, $MAIN_ROOT/.venv, python3, python)." >&2
  echo "       This repo requires Python >=3.12 (pyproject.toml). Create the project venv" >&2
  echo "       and install requirements.txt, or set PY=/path/to/python." >&2
  exit 1
fi
PY="$PY_RESOLVED"
# PY is now already an absolute, verified interpreter path; the previous
# `"$ROOT/$PY"` dance existed only because the old default was repo-relative.
PY_ABS="$PY"
SYMBOLS="${SMOKE_SYMBOLS:-AAPL,MSFT}"
FAILED=0

pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILED=1; }

# --help must work with no env at all.
if "$PY_ABS" -m open_prep.run_open_prep --help >/dev/null 2>&1; then
  pass "--help exits 0"
else
  fail "--help exits 0"
fi

# Shadow every secret-like key in .env so the auto-loaded .env cannot inject
# real credentials (KEY=val tokens have no spaces → safe unquoted word-split).
SHADOW=""
if [ -f .env ]; then
  SHADOW="$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' .env | sed 's/=$//' \
            | grep -iE 'KEY|TOKEN|SECRET|API' | sed 's/$/=fake-smoke/' | tr '\n' ' ')"
fi
echo "Shadowing $(printf '%s' "$SHADOW" | wc -w | tr -d ' ') .env secret(s)."

# Record the real artifact's state so we can prove the smoke did not touch it.
REAL_ART="artifacts/open_prep/latest/latest_open_prep_run.json"
before="$( [ -f "$REAL_ART" ] && stat -f '%m %z' "$REAL_ART" 2>/dev/null || echo absent )"

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "Running one scoring pass over $SYMBOLS in $TMP (this takes ~25s) …"
( cd "$TMP" && env $SHADOW FMP_API_KEY=fake-smoke OPEN_PREP_LOG_LEVEL=ERROR PYTHONPATH="$ROOT" \
    "$PY_ABS" -m open_prep.run_open_prep \
      --symbols "$SYMBOLS" --universe-source static --top 3 --trade-cards 2 \
      --pre-open-only --gap-mode off >run.log 2>&1 )
rc=$?
[ "$rc" = 0 ] && pass "CLI exits 0 (degraded providers)" || { fail "CLI exit ($rc)"; tail -15 "$TMP/run.log"; }

ART="$TMP/artifacts/open_prep/latest/latest_open_prep_run.json"
if [ -f "$ART" ]; then
  pass "wrote latest_open_prep_run.json ($(wc -c <"$ART" | tr -d ' ') bytes)"
  "$PY_ABS" - "$ART" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
need = ["code_version", "ranked_candidates", "trade_cards"]
missing = [k for k in need if k not in d]
sys.exit(1 if missing else 0)
PY
  [ $? = 0 ] && pass "artifact is valid JSON with code_version/ranked_candidates/trade_cards" \
             || fail "artifact missing expected top-level keys"
else
  fail "no artifact written"
fi

after="$( [ -f "$REAL_ART" ] && stat -f '%m %z' "$REAL_ART" 2>/dev/null || echo absent )"
[ "$before" = "$after" ] && pass "SAFETY: repo's real artifact untouched" \
                         || fail "SAFETY: repo artifact changed ($before -> $after)"

echo
if [ "$FAILED" = 0 ]; then echo "SMOKE OK"; else echo "SMOKE FAILED"; fi
exit "$FAILED"
