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

## 5. Post-Merge Hotfixes (11. Feb 2026)

Three issues were discovered and fixed after the initial merge:

### 5.1 Type Mismatch in `f_stable_pulse` (Commit `c35f6a6`)

**Error:** `Cannot call "operator ?:" with argument "expr1"="barstate.isconfirmed". An argument of "series bool" type was used but a "series int" is expected.`

**Cause:** `ta.change(timeRaw)` returns `int` (time difference in ms), but the ternary also returns `barstate.isconfirmed` (bool). Pine requires both branches to have the same type.

**Fix:** Explicit boolean cast with `nz()`:
```pine
f_stable_pulse(isSame, timeRaw) => isSame ? barstate.isconfirmed : (nz(ta.change(timeRaw)) != 0)
```

### 5.2 Signal Blockage — No BUY/EXIT Labels (Commit `99917e6`)

**Error:** No trade signals appeared on the chart despite CHoCH/BOS markers being visible.

**Root Cause:** `confForecastArr` was changed from `barstate.isconfirmed` to `pulse1..pulse7`. Since pulse values are only `true` when an HTF bar completes (e.g., once every ~288 bars for Daily on 5min chart), the calibration system (`f_process_tf`) accumulated samples ~100-300x slower than intended. This kept forecast probabilities at uniform priors (~33%), which permanently blocked:
- `reliabilityOk` (too few samples / Brier undefined)
- `evidenceOk` (samples below minimum)
- `fcGateLong` (pU < minDirProb)
- Result: `allowEntry = false` on every bar

**Fix:** `confForecastArr` reverted to `barstate.isconfirmed` for all 7 horizons. The anti-repainting protection remains correctly applied through `f_stable_val()` on the **data values** (`c1`, `ef1`, `es1`, ...) that feed into the learner. These are two separate concerns:
- **Data stability** (anti-repaint) → `f_stable_val` latches HTF data to confirmed bars
- **Calibration cadence** (learning rate) → `barstate.isconfirmed` on every chart bar

```pine
// CORRECT architecture:
confForecastArr = array.from(barstate.isconfirmed, ...)   // calibrate every confirmed bar
c1 = f_stable_val(same1, c1_r, c1_r[1])                  // but with repaint-safe data
```

### 5.3 Architecture Summary (Final State)

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| HTF Data Retrieval | `f_tf_pack` → `_r` suffixed vars | Raw OHLCV + indicators from `request.security` |
| Data Stability | `f_stable_val(same, raw, raw[1])` | Latch to last completed HTF bar (anti-repaint) |
| Pulse Detection | `f_stable_pulse` → `pulse1..7` | Debug visualization only (`plotchar`) |
| Calibration Gate | `confForecastArr = barstate.isconfirmed` | Learn on every confirmed chart bar with stable data |

---

## 6. Verification (Final)

- **Pytest:** 247 passed, 0 failed
- **Pine Extension (VS Code):** 0 errors in both files
- **Signal Generation:** BUY/EXIT labels confirmed visible after fix 5.2

---

## Deployment Instructions

1. Copy content of `SkippALGO.pine` to TradingView Indicator script.
2. Copy content of `SkippALGO_Strategy.pine` to TradingView Strategy script.
3. Save and add to chart.
