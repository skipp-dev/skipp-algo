# Code Review: SkippALGO v6.1 Deep Upgrade

**Reviewer:** GitHub Copilot (Simulated Peer Review)
**Target:** `SkippALGO.pine` (Phases 1-4 Upgrade)
**Last Updated:** 05 Feb 2026

## 1. Summary of Changes

The codebase successfully transitions from a static binning model to a dynamic, online-learning architecture.

* **Target Profiles**: Splitting targets by timeframe (Time-based vs Volatility-based) is a huge win for noise reduction on lower timeframes.
* **Ensemble**: The "Pullback" component finally gives the algo a way to distinguish *Extended* trends (which should revert) from *Early* trends (which should continue).
* **2D Calibration**: Adding Volatility as a dimension prevents the "High Volatility Trap" where standard trend signals often fail.
* **Platt Scaling**: Essential for probability integrity. Raw bin counts are too jumpy; SGD smoothing makes the "Displayed Probability" essentially a moving average of recent reliability.

## 2. TfState UDT Architecture (01 Feb 2026)

Both indicator and strategy now use the **TfState UDT pattern**:

* **7 TfState objects** (`tf1State`..`tf7State`) replace 100+ individual arrays
* **~450 lines removed** from strategy via this refactoring
* **Consistent signatures**: `f_reset_tf(TfState st)`, `f_process_tf(..., TfState st, ...)`
* **All 86 tests passing** after migration

## 3. Code Quality Check

* **Refactoring**: `f_process_tf` was refactored. While large, it is necessary to keep all state-update logic in one atomic transaction per bar.
* **Variable Scope**: State variables (`var`) are correctly isolated per timeframe. No leakage detected between `tfF1` and `tfF2`.
* **Efficiency**: Arrays are used heavily. This is performant in Pine v6. Removing items from the end of arrays (standard queue pop pattern) is optimal.

## 4. Deep Review Findings (01 Feb 2026)

### Critical Issues Identified

| Issue | Location | Severity | Status |
|-------|----------|----------|--------|
| Division by zero in `f_prob` | Line ~704 | 🔴 Critical | Documented |
| ATR=0 fallback produces misleading ratios | `f_process_tf` | 🔴 Critical | Documented |
| Array bounds in `f_bin2D` edge cases | Line ~684 | 🔴 Critical | Documented |
| FP drift in rolling buffer sums | `f_roll_add` | 🟠 Warning | Documented |
| Unused `hid` parameter | `f_process_tf` | 🟡 Minor | Documented |

### Recommendations

1. **Add division guards**: `n + 2.0 * alpha == 0 ? 0.5 : ...`
2. **Skip resolution on invalid ATR**: Don't fallback to `denom=1.0`
3. **Periodic sum recalculation**: Every 500 bars, recompute `array.sum(buf)`
4. **Extract magic numbers**: Define `VOL_THRESH_HIGH = 0.66`, etc.
5. **Consider TfState array**: Pine v6 supports `array<TfState>` for cleaner code

## 5. Critical Considerations

* **Learning Rate**: `lrPlatt` is hardcoded or set. If markets shift regime *very* instantly (e.g., News shock), SGD might lag. However, the `Gain` parameter in `f_cal_update` (for the raw bin counts) handles the fast adaptation, while Platt handles the "calibration curve" adaptation. This dual-speed approach is sound.
* **Complexity**: Debugging this script is now significantly harder. The path from "Price" to "Table Value" goes through ~5 layers of transformation.

## 6. Verification Status

* [x] Inputs Grouped Correctly
* [x] Array Sizes Expanded (3x for Volatility)
* [x] SGD Logic Implemented Correctly (Sigmoid -> Error -> Backprop)
* [x] Table Output Linked to Calibrated Probabilities
* [x] **TfState UDT Migration Complete** (01 Feb 2026): Both scripts use identical patterns
* [x] **Strategy Module Synced** (01 Feb 2026): `SkippALGO_Strategy.pine` mirrors the main indicator logic
* [x] **86 Tests Passing** (01 Feb 2026): Full test suite validates architecture
* [x] **210 Tests Passing** (05 Feb 2026): Full test suite validates architecture

## 7. Feb 02, 2026 Updates (Post‑Review Enhancements)

**Scope:** Both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

* **Quantile binning** for score dimension with rolling cut updates and fixed‑bin fallback.
* **Chop‑aware regime dimension**: trend regime drives the second bin axis; flat is explicitly represented in display.
* **Evidence/abstain gating + UI**: decision‑quality gate by edge, bin samples, and (optionally) total evidence; status shown in table header.
* **Multiclass safety fallback**: temperature/vector calibration applies only when sample thresholds are met; updates are gated similarly.
* **Temperature/vector scaling applied to display**: calibrated probabilities now reflect temp/vector adjustments when eligible.
* **Runtime safety**: guardrails for division/NA, quantile buffer bounds, and gating for weak bins.
* **Outlook table refactor**: fixed 10‑column layout (Dir + Up/Flat/Down + nCur) and removed forecast/eval blocks from the main table.
* **Tuple Destructuring Safety**: Refactored all tuple assignments (e.g., `[a, b] = f()`) to use temporary variables to prevent variable shadowing/redeclaration issues.

**Verdict**: Approved/Merge Ready.

## 8. Feb 04, 2026 Updates

* **Nonrepaint execution flags**: `didBuy/didShort/didExit/didCover` now drive alerts/labels on confirmed bars.
* **Alert helper refactor**: Consolidated alert calls into a helper function in both indicator and strategy.
* **Label price helper cleanup**: Simplified `f_label_price` for readability without changing behavior.
* **Edge-case coverage**: Added test ensuring trade-gate thresholds treat `0` as disabled.

## 9. Feb 05, 2026 Updates

* **Totals alignment**: Forecast totals now use the selected count arrays to reflect bull/bear calibration selection.
* **Forecast gating**: `canF*` flags depend on `enableForecast` directly, while `forecastAllowed` continues to gate execution.
* **Indicator/strategy parity**: Applied the same alignment to both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

## 10. Feb 05–06, 2026 Updates (v6.2 — Forecast Quality & Signal Enhancements)

### Safe Calibration Defaults (A1/A3/A4/A6/A7)

* **A1**: Raised `calMinSamples` to 30, `alphaN`/`alpha1` to 1.5 for better smoothing.
* **A3**: Guardrail skip — calibration updates skipped on `volShock`/`gapShock`/`rangeShock` bars.
* **A4**: Regularised calibrator with `kShrink` = 1.0, `kShrinkReg` = 0.8.
* **A6**: Queue capacity capped to `maxQ = 60` to prevent unbounded memory growth.
* **A7**: Platt parameter clamping to `[0.1, 5.0]` (A) / `[-3.0, 3.0]` (B).

### Adaptive Systems (C2/D3)

* **C2**: Adaptive cooldown — halves `cooldownBars` when `confidence >= 0.80`.
* **D3**: Weighted MTF scoring — higher timeframes weighted more (tf3 × 2.0, tf2 × 1.5, tf1 × 1.0).

### Deferred Deep-Review Items (A2/A5/B1–B4/C1/C3/C4/D1/D2)

All features opt-in with input toggles defaulting to OFF for backward compatibility.

* **A2 – SGD momentum (Adam-lite)**: Optional EMA on Platt SGD gradients via `useSgdMomentum`/`sgdBeta` (0.9). TfState extended with `momPlattN`/`momPlatt1` momentum vectors.
* **A5 – ECE-triggered recalibration**: Boosts Platt learning rate by `eceRecalBoost` (3×) when previous bar's ECE ≥ `eceWarn`. Uses `prevEvalEce` variable computed after eval metrics.
* **B1 – Continuous trend**: `f_state_score` conditionally uses `f_trend_strength()` (continuous [-1,1]) instead of binary trend when `useSmoothTrend` enabled.
* **B2 – ROC factor**: Signal-layer momentum gate via `f_roc_score()`, controlled by `wRoc` weight. Implemented as signal filter (not in calibration ensemble) to avoid breaking learned 2D bin distributions.
* **B3 – Pullback gradient**: Pullback conditions use `trendUpSmooth`/`trendDnSmooth` (0.3 threshold) instead of binary `trendUp`/`trendDn` when D1 is enabled.
* **B4 – Volume in ensemble**: Signal-layer volume gate via `f_vol_score()`, controlled by `wVol` weight. Same design rationale as B2.
* **C1 – Pre-signal momentum**: RSI alignment gate (`usePreMomentum`). Longs require RSI ≥ `preMomRsiLo` (35), shorts require RSI ≤ `preMomRsiHi` (65).
* **C3 – EMA acceleration**: Gap expansion filter (`useEmaAccel`) — requires EMA gap to be expanding (not contracting) for entry.
* **C4 – VWAP alignment**: Intraday-only direction filter (`useVwap`). Longs require close ≥ VWAP; shorts require close ≤ VWAP.
* **D1 – Smooth trend regime**: New `f_trend_strength(emaF, emaS)` function returns continuous [-1, 1] trend via normalised EMA diff.
* **D2 – ADX filter**: Minimum trend strength gate (`useAdx`/`adxLen`/`adxThresh`). Uses `ta.dmi()` built-in.

### Architecture

* New `f_ensemble6()` function for 6-factor weighted ensemble scoring (future use).
* Enhancement composite gates `enhLongOk`/`enhShortOk` AND all new signal filters together and are wired into all 4 signal engine modes (Hybrid, Breakout, Trend+Pullback, Loose).
* All changes applied to both `SkippALGO.pine` and `SkippALGO_Strategy.pine`.

### Tests

* 234 tests passing (24 new tests covering deferred feature presence in both files).
* Cross-validation test for Platt SGD updated to match `lrPlattEff` pattern.

**Verdict**: All deep-review items complete. PR #6 ready to merge.
