# Changelog — SkippALGO v6.2

## Overview

This release contains three parity bug-fixes between Indicator and Strategy,
a Pine token-limit reduction (forecast table removal from Indicator), and
updated cross-validation tests.

---

## Commits

### 1. Parity fixes — `8cf2758`

Three signal-affecting bugs were found during a deep code review and fixed in
both `SkippALGO.pine` (Indicator) and `SkippALGO_Strategy.pine` (Strategy):

| Bug | File(s) | Description |
|-----|---------|-------------|
| **BUG 1 — Loose `enhOk` gap** | Both | Loose engine was missing the `enhOk` signal-enhancement gate that Hybrid/Breakout/Trend+Pullback all apply. Loose entries could bypass pre-momentum, EMA-accel, VWAP, ADX, smooth-trend, and RegSlope filters. Fixed by inserting `and enhOk` into the Loose branch. |
| **BUG 2 — RegSlope missing from Strategy** | Strategy | The entire Regression Slope Oscillator subsystem (`f_log_regression_single`, `f_calc_reg_slope_osc`, `useRegSlope` input, `regSlopeOk` gate) was absent from Strategy. Ported ~30 lines. |
| **BUG 3 — `barsSinceEntry` decay phase-shift** | Both | `barsSinceEntry` was incremented *before* the risk-decay interpolation, causing the sustained-risk level to kick in one bar early. Moved the increment to *after* the decay computation. |

Five new regression tests were added in `tests/test_cross_validation.py`:

- `test_loose_engine_uses_enhOk`
- `test_barsSinceEntry_zero_on_entry`
- `test_canStructExit_uses_gte`
- `test_regslope_subsystem_exists_both`
- (plus existing parity tests that now pass)

### 2. Documentation & diagnostic fix — `d9b8ada`

- Added `docs/REVIEW_v6.1.md`, `docs/TEST_REPORT_v6.1.md`, `docs/TRADINGVIEW_TEST_CHECKLIST.md`
- Fixed Pine diagnostic warnings in both files

### 3. Forecast table removal (Indicator) — *this commit*

**Problem:** Pine compiler reported 102,715 tokens (limit: 100,000) in
`SkippALGO.pine`.

**Solution:** Removed the forecast display columns and evaluation section from
the Indicator's table rendering. All forecast *computation*, calibration, and
entry-gating logic is **preserved** — only display was removed.

#### Indicator changes (`SkippALGO.pine`, ~447 lines removed)

| Area | Detail |
|------|--------|
| Table dimensions | 10 cols × 22 rows → 5 cols × 17 rows |
| `f_rowTF` | Removed forecast columns 5-9 (Dir, Up%, Flat%, Down%, n(N)\|n(1)); simplified parameter list |
| `f_rowTF_idx` | No longer passes `dispPUN/dispPFN/dispPDN/dispNN/totNArr/dispN1` arrays |
| Dead functions removed | `f_bin_quality`, `f_fmtBrier`, `f_fmtCnt`, `f_rowRel`, `f_eval_get`, `f_rowEval` |
| Eval section removed | Baseline comparator rows 16-20 (Uniform, Prior, Elig, Elig Δ, Coverage/Cov) |
| Ops row removed | Lightweight HUD when eval section was hidden |
| `hdrForecast` variable | Removed |
| T/M/L legend | Condensed from 3 rows to 2 (merged ATR info) |
| Footer | Fixed at row 16 (was dynamic: 16/17/21) |

> **Strategy (`SkippALGO_Strategy.pine`) retains the full forecast table** and
> all evaluation/ops-row display logic unchanged.

#### Test changes (`tests/test_cross_validation.py`, 12 tests updated)

Display-only assertions were scoped to Strategy only (Indicator no longer has
those display elements):

- `test_evaluation_functions_exist` — `f_eval_get` check → Strategy only
- `test_ep_negative_triggers_invariant_and_clamp` → Strategy only
- `test_ops_row_independent_of_showEvalSection` → Strategy only
- `test_inv_latch_exists` — `INV(L)` display check → Strategy only
- `test_inv_latch_snapshot_includes_tf` → Strategy only
- `test_ep_decomposition_exists` → Strategy only
- `test_ops_row_shows_tf_label` → Strategy only
- `test_footer_row_is_dynamic` → Strategy only
- `test_ep_decomp_guarded_by_qsync` → Strategy only
- `test_resolve_thresh_helper_exists` → Strategy only
- `test_ep_naming_consistency` → Strategy only
- `test_eligpending_raw_clamped_split` → Strategy only

**All 271 tests pass.** Pine diagnostics: 0 errors, 0 warnings.

---

## Test Suite Summary

| Metric | Value |
|--------|-------|
| Total tests | 271 |
| Passed | 271 |
| Failed | 0 |
| Pine diagnostics | Clean (0 errors) |
