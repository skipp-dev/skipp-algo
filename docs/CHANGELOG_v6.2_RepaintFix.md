# v6.2 Stable Sync Patch & Optimization Report

**Date:** 11. Februar 2026
**Status:** RELEASE CANDIDATE (Ready to Merge)
**Files Affects:** `SkippALGO.pine`, `SkippALGO_Strategy.pine`
**Verification:** 247 Tests Passed (Pytest), Linting Clean

## Executive Summary

This update eliminates High Time Frame (HTF) repainting by implementing a "Stable Sync" mechanism ("Patch A"). It also includes critical performance optimizations ("Lazy Brier") to prevent execution timeouts and code hardening fixes (removing invalid parameters).

---

## 1. Core Fix: Stable Sync (HTF Repainting)

### Problem

Previously, the logic used `barstate.isconfirmed` in a way that could allow intra-bar HTF data updates to leak into the learning state (calibration). This caused historical results to differ from live trading functionality ("Repainting").

### Solution (Patch A)

We implemented a strict "Pulse & Latch" mechanism for all HTF data retrieval.

1. **Raw Retrieval:** `f_tf_pack` now returns raw values suffixed with `_r` (e.g., `c1_r`).
2. **Stable Pulse:** A pulse is generated *only* when the HTF time changes, indicating a completed bar.

    ```pine
    pulse = ta.change(time_htf)
    ```

3. **Value Latching:** We use `f_stable_val` to hold the previous bar's value stable until the pulse triggers.

    ```pine
    // If same bar, keep raw (live) or held value. 
    // Logic ensures we update calibration ONLY on the 'pulse'.
    val = f_stable_val(same, valRaw, valPrev)
    ```

4. **Sync:** The forecast arrays (`confForecastArr`) now carry the `pulse` boolean instead of `barstate.isconfirmed`, ensuring the `f_process_tf` function only executes learning steps at rigid intervals.

---

## 2. Performance Optimization (Lazy Logic)

### Problem

The "Script is taking too long to execute" error was risking runtime stability due to heavy Brier Score calculations running on every tick.

### Solution

Implemented "Lazy Brier" evaluation in `SkippALGO.pine`:

- Brier Score calculations are now wrapped in a conditional block.
- Logic runs **only** if one of the following is true:
  - `calibrateInBackground` is enabled.
  - `showTable` is enabled.
  - `showEvalSection` is enabled.

```pine
doBrier = enableForecast and (calibrateInBackground or showTable or showEvalSection)
// ... calculation logic ...
```

---

## 3. Code Hardening & Cleanup

### Fixes

* **Invalid Parameter:** Removed `force_overlay=true` from `label.new()` calls. This parameter does not exist in Pine Script v6 `label.new` signature and was causing warnings/errors.
- **Debug Isolation:**
  - **Indicator:** Uses `showEvidencePackDebug` input.
  - **Strategy:** Uses a distinct `showDebugPulse` input.
  - *Result:* Prevents variable name collisions and ensures clean namespaces.
- **Syntax Compliance:** Verified all `plotchar` calls adhere to strict positional/named argument requirements.

---

## 4. Verification

- **Logic Tests:** `pytest` suite passed (247 items). Updated `test_skippalgo_strategy.py` to recognize the new `_r` variable structure.
- **Linting:** VS Code Pine Extension reports **0 Errors** for both files.
- **TradingView Check:** Manually verified generic syntax compliance for deployment.

---

## Deployment Instructions

1. Copy content of `SkippALGO.pine` to TradingView Indicator script.
2. Copy content of `SkippALGO_Strategy.pine` to TradingView Strategy script.
3. Save and add to chart.
