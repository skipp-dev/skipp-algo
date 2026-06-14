#!/usr/bin/env bash
# Pin/ledger drift guard — local mirror of the authoritative fast-gates step.
#
# Extracts the test-file list from the "Run pin / ledger drift guard" step
# in .github/workflows/smc-fast-pr-gates.yml (single source of truth — the
# list grows over time, never hardcode it here) and runs it with the same
# pytest flags. Green here means the fast-gates drift guard AND the
# validate shards will be green for line-pin reasons.
#
# Why: adding/removing ANY line in a covered source file (open_prep/,
# smc_tv_bridge/, scripts/, newsstack_fmp/, streamlit_*) shifts every
# frozen-line ledger pinning a call site in that file. 2026-06-12: four
# ledger pins drifted in PR #2729 and were only caught in CI.
#
# Usage:   scripts/run_ledger_drift_guard.sh        (from anywhere in repo)
# Wired as a pre-push hook in .pre-commit-config.yaml; install with:
#   pre-commit install --hook-type pre-push
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/smc-fast-pr-gates.yml"

if [ ! -f "$WORKFLOW" ]; then
  echo "ERROR: workflow file not found: $WORKFLOW" >&2
  echo "       (moved/renamed? update WORKFLOW in $0)" >&2
  exit 1
fi

# Pull the test-file list out of the drift-guard step only (not the whole
# workflow), so unrelated pytest invocations don't leak in. Stateful awk:
# start capturing AFTER the matched step name, stop at the NEXT '- name:'
# line (whatever its initial/indentation) — no dependence on step-name
# initials. Path pattern tolerates subdirectories, uppercase, dots and
# dashes (tests/foo/test_Bar-x.py).
# grep exits 1 when nothing matches; '|| true' keeps set -e from aborting
# so the [ -z "$TESTS" ] check below can produce a useful error message.
TESTS="$(awk '
  /- name: Run pin \/ ledger drift guard/ {capture=1; next}
  capture && /- name:/ {capture=0}
  capture {print}
' "$WORKFLOW" | grep -oE 'tests/[A-Za-z0-9_./-]+\.py' | sort -u || true)"

if [ -z "$TESTS" ]; then
  echo "ERROR: could not extract drift-guard test list from $WORKFLOW" >&2
  echo "       (step renamed? update the awk range in $0)" >&2
  exit 1
fi

# Interpreter-Auswahl (worktree-tauglich): $PYBIN > Worktree-venv >
# Haupt-Checkout-venv (via git common dir) > python3. Kandidat muss
# pytest importieren können; xdist ist optional (sonst seriell).
MAIN_ROOT="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
PYBIN_RESOLVED=""
for cand in "${PYBIN:-}" "$REPO_ROOT/.venv/bin/python" "$MAIN_ROOT/.venv/bin/python" python3; do
  [ -n "$cand" ] || continue
  if "$cand" -c "import pytest" 2>/dev/null; then
    PYBIN_RESOLVED="$cand"
    break
  fi
done
if [ -z "$PYBIN_RESOLVED" ]; then
  echo "ERROR: no python with pytest found (tried PYBIN, worktree/.venv, $MAIN_ROOT/.venv, python3)" >&2
  exit 1
fi

XDIST_ARGS=""
if "$PYBIN_RESOLVED" -c "import xdist" 2>/dev/null; then
  XDIST_ARGS="-n auto --dist=worksteal"
fi

echo "ledger drift guard: $(echo "$TESTS" | wc -l | tr -d ' ') test files (source: $WORKFLOW; python: $PYBIN_RESOLVED)"
# shellcheck disable=SC2086  # word-splitting of $TESTS/$XDIST_ARGS is intentional
exec env PYTHONPATH="$REPO_ROOT" "$PYBIN_RESOLVED" -m pytest -q --maxfail=1 \
  $XDIST_ARGS -p no:cacheprovider $TESTS
