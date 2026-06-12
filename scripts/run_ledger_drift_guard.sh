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

# Pull the test-file list out of the drift-guard step only (not the whole
# workflow), so unrelated pytest invocations don't leak in. Stateful awk:
# start capturing AFTER the matched step name, stop at the NEXT '- name:'
# line (whatever its initial/indentation) — no dependence on step-name
# initials. Path pattern tolerates subdirectories, uppercase, dots and
# dashes (tests/foo/test_Bar-x.py).
TESTS="$(awk '
  /- name: Run pin \/ ledger drift guard/ {capture=1; next}
  capture && /- name:/ {capture=0}
  capture {print}
' "$WORKFLOW" | grep -oE 'tests/[A-Za-z0-9_./-]+\.py' | sort -u)"

if [ -z "$TESTS" ]; then
  echo "ERROR: could not extract drift-guard test list from $WORKFLOW" >&2
  echo "       (step renamed? update the awk range in $0)" >&2
  exit 1
fi

PYBIN="${PYBIN:-.venv/bin/python}"
if ! "$PYBIN" -c "" 2>/dev/null; then
  PYBIN="python3"
fi

echo "ledger drift guard: $(echo "$TESTS" | wc -l | tr -d ' ') test files (source: $WORKFLOW)"
# shellcheck disable=SC2086  # word-splitting of $TESTS is intentional
exec env PYTHONPATH="$REPO_ROOT" "$PYBIN" -m pytest -q --maxfail=1 \
  -n auto --dist=worksteal -p no:cacheprovider $TESTS
