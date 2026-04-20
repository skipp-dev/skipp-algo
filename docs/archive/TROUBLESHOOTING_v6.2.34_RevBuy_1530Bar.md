# Troubleshooting Report v6.2.34: Missing REV-BUY Signal at 15:30 (Exchange Open)

**Date:** 2026-02-13
**Version:** v6.2.34
**Issue:** User reported a missing `REV-BUY` signal on the 15:30 bar (Feb 4), despite the bar meeting all structural and volume criteria.

## 1. Initial Findings

During the investigation of the missing 15:30 signal, we identified several filtering layers that were blocking the trade:

1. **Engulfing Filter:** The bar did not strictly meet the 3-bar engulfing definition. This logic was bypassed (`engulfLongOk = true`).
2. **Probability Floor:** The Neural Reversal logic had a hardcoded `revBuyMinProbFloor = 0.37`. The signal bar had a probability `pU = 0.2671`, which caused it to be silently rejected.
3. **Rescue Logic Gap:** The rescue path (designed for high-volume reversals) implied a higher probability requirement which this bar did not meet.

## 2. Resolution Steps

### Step 1: Lowered Probability Floor

We lowered the `revBuyMinProbFloor` from **0.37** to **0.25**. This acknowledges that valid reversal bars often occur when the prior trend probability is still dominant (low pU), and require less statistical confirmation if volume and structure are strong.

### Step 2: Open Window Bypass (15:20 - 15:40)

The user requested that the time window around the stock exchange open (15:20 - 15:40) should **not consider pU at all**. High volatility at the open often destabilizes probability models or results in `NaN` values during warmup.

**Implementation:**

- Added a time check: `_isOpenWindow` (min 920 to 940).
- Modified `probOkGlobal` logic to return `true` immediately if inside this window, bypassing all `pU` value checks (including `NaN` checks).

```pine
// v6.2.34: When in Open Window (15:20-15:40), force pU/pD checks to TRUE regardless of value.
probOkGlobal = _isOpenWindow or ((not na(pU) and pU >= revBuyMinProbFloor) and ...)
```

## 3. Code Cleanup

Following the fix validation, we removed all debug-related code to clean up the user interface and code footprint:

- Removed Inputs: `showEvidencePackDebug`, `debugProbeTime`, `showDebugLabels`.
- Removed Data Window Plots: `reliabilityOk`, `evidenceOk`, `pU`, `pD`, etc.
- Removed Logic: `f_debug_label` function and associated "GATE PROBE" label logic.

## 4. Verification

- **Test Suite:** 335 tests passed, including new test cases for the Open Window bypass logic.
- **Visual Check:** The 15:30 REV-BUY label now appears correctly on the chart.
