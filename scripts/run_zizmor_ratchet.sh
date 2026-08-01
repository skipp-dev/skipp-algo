#!/usr/bin/env bash
# zizmor workflow-security ratchet — local mirror of the authoritative
# fast-gates step.
#
# Extracts the severity budgets AND the pinned zizmor version from the
# "zizmor (workflow security ratchet)" step in
# .github/workflows/smc-fast-pr-gates.yml (single source of truth — the
# budgets shrink over time as findings get fixed, never hardcode them
# here) and applies the same pass/fail rule locally.
#
# Why: the ratchet pins the status quo (high/medium counts on main). A PR
# that adds a template-injection or artipacked finding to a workflow only
# fails in CI, ~2 min after the push. Running it at commit time catches it
# while the workflow edit is still in your head.
#
# Why the version pin matters: the budgets are counts, not rules. A
# different zizmor version applies a different audit set and reports a
# different number of findings against the SAME workflows, which would
# produce a false block (or a false green). This script therefore refuses
# to run under an unpinned version — it prefers a matching zizmor on PATH
# and otherwise falls back to `uvx --from zizmor==<pinned>`, which fetches
# the exact wheel CI uses.
#
# Usage:   scripts/run_zizmor_ratchet.sh        (from anywhere in repo)
# Wired as a pre-commit hook in .pre-commit-config.yaml; install with:
#   pre-commit install
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/smc-fast-pr-gates.yml"
WORKFLOW_DIR=".github/workflows/"

if [ ! -f "$WORKFLOW" ]; then
  echo "ERROR: workflow file not found: $WORKFLOW" >&2
  echo "       (moved/renamed? update WORKFLOW in $0)" >&2
  exit 1
fi

# Capture the zizmor step only (not the whole workflow), so an unrelated
# pip pin or env block elsewhere can never leak in. Stateful awk: start
# capturing AFTER the matched step name, stop at the NEXT step-level
# '- name:' line (anchored to 6 leading spaces so the step's own run-block
# content — which quotes "::error title=zizmor-ratchet::" strings — can
# never trigger premature end of capture). Mirrors the awk range in
# scripts/run_ledger_drift_guard.sh.
STEP="$(awk '
  /- name: zizmor \(workflow security ratchet\)/ {capture=1; next}
  capture && /^      - name:/ {capture=0}
  capture {print}
' "$WORKFLOW")"

if [ -z "$STEP" ]; then
  echo "ERROR: could not locate the zizmor step in $WORKFLOW" >&2
  echo "       (step renamed? update the awk range in $0)" >&2
  exit 1
fi

# Strip comment tails BEFORE extraction: the step carries a dated changelog
# comment block ("high 91->92 (2026-07-22): ...") whose numbers must never
# be mistaken for the live budgets.
STEP_CODE="$(printf '%s\n' "$STEP" | sed 's/[[:space:]]*#.*$//')"

extract_budget() {
  # $1 = env var name -> prints the integer, or nothing when absent/ambiguous
  printf '%s\n' "$STEP_CODE" \
    | grep -oE "$1:[[:space:]]*\"?[0-9]+\"?" \
    | grep -oE '[0-9]+' \
    | sort -u
}

HIGH_BUDGET="$(extract_budget ZIZMOR_HIGH_BUDGET || true)"
MEDIUM_BUDGET="$(extract_budget ZIZMOR_MEDIUM_BUDGET || true)"
PINNED_VERSION="$(printf '%s\n' "$STEP_CODE" \
  | grep -oE 'zizmor==[0-9][0-9A-Za-z.-]*' | sed 's/^zizmor==//' | sort -u || true)"

# Each must resolve to EXACTLY one value. An empty result means the step was
# restructured and this guard would otherwise pass vacuously; two values mean
# the extraction is ambiguous. Both are hard errors, never a silent green.
for pair in "ZIZMOR_HIGH_BUDGET:$HIGH_BUDGET" "ZIZMOR_MEDIUM_BUDGET:$MEDIUM_BUDGET" \
            "zizmor==<version>:$PINNED_VERSION"; do
  name="${pair%%:*}"
  value="${pair#*:}"
  count="$(printf '%s' "$value" | grep -c . || true)"
  if [ "$count" != "1" ]; then
    echo "ERROR: expected exactly one $name in the zizmor step of $WORKFLOW, found $count" >&2
    echo "       (step restructured? update the extraction in $0)" >&2
    exit 1
  fi
done

# Runner resolution: a matching zizmor on PATH is fastest; uvx fetches the
# exact pinned wheel (cached after the first run). A non-matching local
# zizmor is deliberately NOT used — see the version-pin note in the header.
LOCAL_VERSION=""
if command -v zizmor >/dev/null 2>&1; then
  LOCAL_VERSION="$(zizmor --version 2>/dev/null | grep -oE '[0-9][0-9A-Za-z.-]*' | head -1 || true)"
fi

if [ "$LOCAL_VERSION" = "$PINNED_VERSION" ]; then
  ZIZMOR_CMD=(zizmor)
  RUNNER="zizmor $PINNED_VERSION (PATH)"
elif command -v uvx >/dev/null 2>&1; then
  ZIZMOR_CMD=(uvx --quiet --from "zizmor==$PINNED_VERSION" zizmor)
  RUNNER="uvx zizmor==$PINNED_VERSION${LOCAL_VERSION:+ (PATH has $LOCAL_VERSION — not used)}"
else
  echo "ERROR: no zizmor==$PINNED_VERSION available." >&2
  if [ -n "$LOCAL_VERSION" ]; then
    echo "       zizmor $LOCAL_VERSION is on PATH but the fast-gates budgets are" >&2
    echo "       measured against $PINNED_VERSION — a different version reports a" >&2
    echo "       different finding count, so running it would be misleading." >&2
  fi
  echo "       Install the pinned version:  uv tool install zizmor==$PINNED_VERSION" >&2
  echo "       (or install uv so this script can use 'uvx --from zizmor==$PINNED_VERSION')" >&2
  exit 1
fi

PYBIN_RESOLVED=""
for cand in "${PYBIN:-}" "$REPO_ROOT/.venv/bin/python" python3 python; do
  [ -n "$cand" ] || continue
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import json" 2>/dev/null; then
    PYBIN_RESOLVED="$cand"
    break
  fi
done
if [ -z "$PYBIN_RESOLVED" ]; then
  echo "ERROR: no python interpreter found (tried PYBIN, .venv, python3, python)" >&2
  exit 1
fi

REPORT="$(mktemp -t zizmor_report.XXXXXX)"
ZIZMOR_LOG="$(mktemp -t zizmor_log.XXXXXX)"
trap 'rm -f "$REPORT" "$ZIZMOR_LOG"' EXIT

echo "zizmor ratchet: $WORKFLOW_DIR (budgets: $WORKFLOW; runner: $RUNNER)"

# zizmor exits non-zero (14) whenever findings exist; the ratchet — not the
# exit code — decides pass/fail, so swallow it exactly like the CI step does.
# --offline skips the network audits, matching how the budgets were measured.
# --quiet only lowers zizmor's own stderr log level (one INFO line per audited
# workflow, ~70 lines of noise in a commit hook); it does not change the JSON
# report, so the counts stay identical to CI. The log is captured rather than
# discarded so a genuine zizmor failure is still visible below.
"${ZIZMOR_CMD[@]}" --quiet --no-progress --offline --format json "$WORKFLOW_DIR" \
  > "$REPORT" 2> "$ZIZMOR_LOG" || true

if [ ! -s "$REPORT" ]; then
  echo "ERROR: zizmor produced no report — treat as FAIL, not as zero findings." >&2
  echo "--- zizmor output ---" >&2
  cat "$ZIZMOR_LOG" >&2
  exit 1
fi

exec env \
  ZIZMOR_HIGH_BUDGET="$HIGH_BUDGET" \
  ZIZMOR_MEDIUM_BUDGET="$MEDIUM_BUDGET" \
  ZIZMOR_REPORT="$REPORT" \
  "$PYBIN_RESOLVED" - <<'PY'
import json, os, sys

findings = json.load(open(os.environ["ZIZMOR_REPORT"]))
high = sum(1 for f in findings if f["determinations"]["severity"] == "High")
medium = sum(1 for f in findings if f["determinations"]["severity"] == "Medium")
hb = int(os.environ["ZIZMOR_HIGH_BUDGET"])
mb = int(os.environ["ZIZMOR_MEDIUM_BUDGET"])
print(f"zizmor: high={high} (budget {hb}), medium={medium} (budget {mb})")
ok = True
if high > hb:
    print(f"zizmor-ratchet: high-severity findings rose {hb} -> {high}. "
          "New workflow code introduced a security finding "
          "(run `zizmor --offline .github/workflows/` to see it).")
    ok = False
if medium > mb:
    print(f"zizmor-ratchet: medium-severity findings rose {mb} -> {medium}. "
          "New workflow code introduced a security finding "
          "(run `zizmor --offline .github/workflows/` to see it).")
    ok = False
if ok and (high < hb or medium < mb):
    print(f"zizmor-ratchet: findings below budget (high {high}/{hb}, medium {medium}/{mb}) "
          "— consider lowering ZIZMOR_*_BUDGET in smc-fast-pr-gates.yml to lock in the improvement.")
sys.exit(0 if ok else 1)
PY
