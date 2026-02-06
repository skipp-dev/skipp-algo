# Troubleshooting Report: "Ghost Signals" (Live Alert vs. Historical Data Discrepancy)

**Date:** February 6, 2026  
**Component:** `SkippALGO.pine` (Trend+Pullback Engine)  
**Issue:** User reported "Real BUY" alerts firing in real-time (e.g., PFE at 16:36), but the signal labels disappeared upon reloading the chart (Historical Data).

---

## 1. The Root Cause: "Repainting" via Granularity Mismatch

The core issue was a subtle form of **Repainting** caused by the difference between **Real-Time Data** and **Historical Data**.

* **Real-Time Execution:** The script recalculates on every price update (tick). A signal can fire if *any* tick within a minute meets the criteria (e.g., a momentary volume spike or a price dip matching a specific depth). Once an alert fires, it cannot be "un-fired".
* **Historical Execution:** When the chart is refreshed, the script runs only once per bar using the final `Open`, `High`, `Low`, `Close`, and `Volume` of that bar.
* **The Mismatch:**
  * **Volume:** A live 1-minute volume spike might trigger an alert, but the final 1-minute average volume might settle slightly lower, causing `Volume > SMA` to be `false` on history.
  * **Math Precision:** A Pullback Depth might calculate to `0.501 ATR` live, but `0.499 ATR` on history due to slight data aggregation differences, causing `Depth >= 0.5` to fail.
  * **Logic Definition:** The `Trend+Pullback` engine was strictly looking for a `Crossover` (Close crossing EMA). In live trading, a bar might dip, touch the EMA, and bounce (Reversal). The live alert fired on the "Touch", but historically, the bar just looks like a "Close above EMA" (no cross occurred), so the logic returned `false`.

---

## 2. Debugging Methodology

To solve this, we moved away from guessing and implemented a **Hybrid Diagnostic Logic**.

### Step 1: Signals vs. Triggers

We differentiated between the **Trigger** (The physical event, e.g., "Price touched EMA") and the **Signal** (The complex filter, e.g., "Price touched EMA AND Volume is High AND Forecast is Bullish").

### Step 2: "Logic Fail" Detectors

We injected temporary debug code that asked a specific question:
> *"Did the physical Trigger happen (EMA Touch), but the Final Signal failed?"*

If `True`, we plotted a **Grey "LOGIC FAIL" Label** containing the internal state of every filter:

```text
LOGIC FAIL
Engine=Trend+Pullback
Pullback=True
Vol=False   <-- CULPRIT FOUND
Set=True
ReclaimUp=False <-- CULPRIT FOUND
```

### Step 3: Iterative Isolation

1. **Iteration 1:** Debug label showed `Vol=False`.
    * *Diagnosis:* Historical volume was slightly lower than live volume.
    * *Fix:* Injected `volTol` (Volume Tolerance) factor to accept volume within 50% of the target on history.
2. **Iteration 2:** Debug label showed `ReclaimUp=False`.
    * *Diagnosis:* The `Trend+Pullback` engine required a strict `Crossover`. The live event was a "Bounce" (Price touched EMA but closed above). The `Hybrid` engine recognizes Bounces, but `Trend+Pullback` did not.
    * *Fix:* Rewrote `ReclaimUp` logic to include "Tolerant Bounces" (Price within 0.05 ATR of EMA) as valid trend reclaims.

---

## 3. The Solution Implementation

We implemented **Tolerance Factors** to bridge the gap between Live and Historical data.

### A. Volume Tolerance (`volTol`)

Allows the volume check to pass if the bar's volume is at least 50% of the relative requirement, accounting for data feed discrepancies.

```pine
volTol = 0.50
volOk = (not useVolConfirm) or (volume > (volSma * volMult * volTol))
```

### B. Pullback Depth Tolerance (`pbTol`)

Allocates a 0.25 ATR buffer to depth calculations, ensuring valid pullbacks aren't rejected because they are a fraction of a cent too shallow on history.

```pine
pbTol = 0.25
pullbackLongOk = ... (pbDepthLong >= (pbMinATR - pbTol)) ...
```

### C. Reclaim Tolerance & Logic Sync

The most critical fix. We updated the `Reclaim` logic to mathematically recognize "Near-Miss Bounces" that look like simple "Trends" on history but were actually "Reversals" in real-time.

```pine
// Allow deviation of 0.05 ATR to capture "Bounces" as valid Reclaims on history
reclaimTol = 0.05 * atr
reclaimUp  = bullBias and ( (crossClose_EmaF_up) or (close >= (emaF - reclaimTol) and close[1] < (emaF[1] + reclaimTol)) )
```

---

## 4. Summary

By relaxing strict equality checks and introducing "Fuzzy Logic" (Tolerances) for historical calculations, we ensured that the **Chart Visualization** now accurately reflects the **Alert Behavior**, restoring confidence in the system.
