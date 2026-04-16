#!/usr/bin/env bash
# tv_verify_publish_chain.sh — Verify the entire publish chain is green.
#
# Usage:
#   ./scripts/tv_verify_publish_chain.sh [--report-only]
#
# This script:
#   1. Runs automation unit tests (selectors, validation model)
#   2. Runs readonly smoke preflight (auth + existing scripts check)
#   3. Runs full mainline preflight (compile + binding + runtime)
#   4. Generates an evidence summary
#   5. Prints a pass/fail verdict
#
# Options:
#   --report-only   Skip browser automation, only generate evidence summary
#                   from existing reports
#
# Exit codes:
#   0  All checks passed
#   1  One or more checks failed (see output for details)

set -euo pipefail
cd "$(dirname "$0")/.."

REPORT_ONLY=false
if [[ "${1:-}" == "--report-only" ]]; then
    REPORT_ONLY=true
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
VERDICT_FILE="automation/tradingview/reports/verify-chain-${TIMESTAMP}.json"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  TradingView Publish Chain Verification                     ║"
echo "║  $(date -u +"%Y-%m-%d %H:%M UTC")                                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

FAILURES=0

# ── Step 1: Automation unit tests ─────────────────────────────
echo "▶ Step 1/4: Automation unit tests"
if npm run tv:test 2>&1 | tail -5; then
    echo "  ✓ Unit tests passed"
else
    echo "  ✗ Unit tests FAILED"
    FAILURES=$((FAILURES + 1))
fi
echo ""

if [[ "$REPORT_ONLY" == "true" ]]; then
    echo "▶ Steps 2-3 skipped (--report-only mode)"
    echo ""
else
    # ── Step 2: Readonly smoke ────────────────────────────────────
    echo "▶ Step 2/4: Readonly smoke preflight"
    SMOKE_REPORT="automation/tradingview/reports/smoke-readonly-${TIMESTAMP}.json"
    if npm run tv:smoke-readonly -- --out "$SMOKE_REPORT" 2>&1 | tail -10; then
        echo "  ✓ Readonly smoke passed"
    else
        echo "  ✗ Readonly smoke FAILED"
        FAILURES=$((FAILURES + 1))
    fi
    echo ""

    # ── Step 3: Full mainline preflight ───────────────────────────
    echo "▶ Step 3/4: Full mainline preflight"
    if npm run tv:preflight:smc-mainline 2>&1 | tail -15; then
        echo "  ✓ Mainline preflight passed"
    else
        echo "  ✗ Mainline preflight FAILED"
        FAILURES=$((FAILURES + 1))
    fi
    echo ""
fi

# ── Step 4: Evidence summary ─────────────────────────────────
echo "▶ Step 4/4: Evidence summary"
if python3 scripts/tv_publish_evidence_summary.py --out "$VERDICT_FILE" 2>&1; then
    echo "  ✓ Evidence summary generated: $VERDICT_FILE"
else
    echo "  ⚠ Evidence summary generation failed (non-blocking)"
fi
echo ""

# ── Verdict ───────────────────────────────────────────────────
echo "════════════════════════════════════════════════════════════════"
if [[ $FAILURES -eq 0 ]]; then
    echo "  VERDICT: ALL CHECKS PASSED ✓"
    echo "════════════════════════════════════════════════════════════════"
    exit 0
else
    echo "  VERDICT: ${FAILURES} CHECK(S) FAILED ✗"
    echo "════════════════════════════════════════════════════════════════"
    exit 1
fi
