# Sprint C13b — Live-Inkubation Unblock

**Status:** PLANNED
**Prerequisite:** C13 Phase-A NO-GO signed
([`docs/c8_phase_a_signoff_2026-05-14.md`](../../docs/c8_phase_a_signoff_2026-05-14.md))
**Blocks:** C13 Phase-A Replay → C14 Phase-B Promotion
**ADR:** [`docs/DECISIONS.md § c13-phase-a-no-go-and-c13b-unblock-plan`](../../docs/DECISIONS.md#2026-06-09---c13-phase-a-no-go-and-c13b-unblock-plan)

## Problem Statement

Sprint C13 (Live-Inkubation Phase A) was signed off NO-GO at sprint
day 16 of 28. All four SMC families (BOS, OB, FVG, SWEEP) reported
zero trades, zero live days, and unknown drift across nine consecutive
daily cron runs (2026-05-04 → 2026-05-13). The calibration pipeline
functions end-to-end but has no data to process.

**Root cause:** T1 — IBKR Paper-Onboarding was never completed. The
IBKR paper-trading gateway was not connected, so no order submissions,
fills, or outcomes reached the pipeline.

## Scope

C13b is a **single-task unblock** — not a full sprint. It resolves
the T1 dependency so that C13 Phase-A can be replayed with real data.

### In Scope

1. **Complete IBKR Paper-Onboarding (T1)**
   - Finalize IBKR paper-trading account configuration
   - Establish gateway connectivity from the execution workstation
   - Verify IB Gateway / TWS paper session stays connected for ≥ 24 h

2. **End-to-end smoke test**
   - Submit at least one paper order per family (BOS, OB, FVG, SWEEP)
   - Confirm fills appear in `audit_orders_*.jsonl`
   - Run one cycle of `c13-daily-cron.yml` and verify non-empty
     `families_telemetry_*.json` output (at least one family with
     `n_trades > 0`)

3. **Unblock verification gate**
   - The cron produces a `calibration_report_public.json` where at
     least one family has `n_events > 0` and `metrics ≠ {}`
   - This file is committed or attached as artifact evidence

### Out of Scope

- Full 28-day incubation run (that is C13 Phase-A replay)
- Sign-off criteria evaluation (≥ 20 trades per family, drift score,
  slippage K-S test, hit-rate CI — all deferred to the replay)
- Code changes to the calibration pipeline (already operational)
- T7 (WSH Earnings-Hook) and T8 (Order-Imbalance-Hook) — deferred

## Acceptance Criteria

| # | Criterion | Verification |
|---|-----------|-------------|
| AC-1 | IBKR paper gateway connected and stable (≥ 24 h session) | Screenshot or log of connected session |
| AC-2 | ≥ 1 paper fill per family in `audit_orders_*.jsonl` | `jq` count on the audit file |
| AC-3 | `c13-daily-cron.yml` run produces non-empty telemetry | Link to passing GitHub Actions run |
| AC-4 | `calibration_report_public.json` has `n_events > 0` for ≥ 1 family | Artifact or commit reference |

## Exit → Next Step

When all four acceptance criteria pass:

1. Mark this spec as `DONE`
2. Open C13 Phase-A Replay sprint (re-use existing cron infrastructure,
   reset the 28-day clock)
3. C14 Phase-B Promotion remains BLOCKED until C13 replay produces a
   GO verdict

## Dependencies

| Dependency | Owner | Status |
|-----------|-------|--------|
| IBKR paper-trading account | Steffen (workstation-side) | ❌ blocked |
| IB Gateway / TWS software | Steffen (workstation-side) | ❌ not configured |
| `c13-daily-cron.yml` workflow | CI (automated) | ✅ operational |
| Calibration pipeline scripts | CI (automated) | ✅ operational |
| `families_telemetry` producer | CI (automated) | ✅ operational |

## Risk

| Risk | Mitigation |
|------|-----------|
| IBKR account approval delay | Escalate with IBKR support; consider alternative paper broker as fallback |
| Gateway disconnects during off-hours | Configure IB Gateway in headless mode with auto-restart |
| Paper fills have unrealistic latency | Document observed latency; flag if > 5 s median (potential drift-score bias) |
