# Test Plan v6.2 - Evaluation Section

**Objective**: Verify the new Evaluation Section (Brier, LogLoss, ECE, Drift) functions correctly and provides useful probabilistic feedback.

**Versions covered**: v6.2.0 (Evaluation), v6.2.23 (Cooldown fix, Strict Alerts), v6.2.24 (USI Quantum Pulse, Debug removal)

## Setup

1. Add `SkippALGO` to a chart (e.g., BTCUSDP 1m or 5m).
2. Enable "Show Table" in settings.
3. Scroll down to "Evaluation (Live Scoring)" section in settings.
4. Ensure "Show Evaluation rows" is CHECKED.

## Test Cases

### TC1: Initial Load & Table Structure

**Action**: Load the indicator on a fresh chart.
**Expected Result**:

* Table appears.
* Bottom rows (24-31) show "Evaluation" header.
* Columns: `Evaluation`, `LogLoss`, `ECE/Max`, `Drift(S-L)`, `#Obs`.
* Rows F1-F7 are present.
* Values should be initialized (likely `—` or `0` if no history calculated yet, or valid numbers if "History+Live" mode picked up confirmed bars).

### TC2: Data Accumulation

**Action**:

1. Allow the chart to run (or use Replay mode) for N bars to generate forecast opportunities.
2. Observe the `#Obs` column in the Evaluation section.
**Expected Result**:

* Counts (`#Obs`) should increment as forecasts resolve (age out or hit targets).
* `LogLoss` should start fluctuating (lower is better, < 0.69).
* `ECE` should populate (e.g., `5.2/12.0` meaning 5.2% avg error, 12% max error).

### TC3: Reset Functionality

**Action**:

1. Go to Settings -> "Forecast Calibration Enhancements".
2. Set `Reset calibration scope` to "All".
3. Check `Reset selected calibration NOW`.
4. Wait for one bar update.
5. Uncheck `Reset selected calibration NOW`.
**Expected Result**:

* All `#Obs` counts in the Evaluation table reset to 0.
* LogLoss and ECE reset to `—` or empty state.
* Accumulation restarts from 0.

### TC4: Head Switching (N vs 1)

**Action**:

1. Accumulate some data (e.g., `#Obs` > 10).
2. Note the F1 `LogLoss` value.
3. Go to Settings -> "Evaluation".
4. Change `Evaluate head` from "N" (Multi-factor) to "1" (Single-factor).
**Expected Result**:

* The table values update immediately.
* The `LogLoss` and `ECE` values should likely be slightly different (usually "N" is better/lower than "1", but not always).
* `#Obs` count remains consistent (since both heads are updated on the same events), but the *scores* change.

### TC5: Drift Logic

**Action**:

1. Observe `Drift(S-L)` column.
**Expected Result**:

* Value format: e.g., `+2.3pp` or `-1.5pp`.
* Positive values indicate Short predictions are performing better (yielding higher) than Longs.
* Negative values indicate Longs are performing better.

---

## v6.2.23 — Cooldown & Strict Alerts

### TC6: Cooldown Not Reset by EXIT/COVER

**Action**:

1. Enable cooldown (e.g., `cooldownBars = 5`).
2. Enter a trade and let it exit via TP or SL.
3. Observe the next valid entry signal timing.

**Expected Result**:

* After EXIT/COVER, the cooldown timer does NOT restart.
* `lastSignalBar` retains the value from the most recent BUY/SHORT — not from the exit event.
* Next valid entry is permitted based on distance from the *previous entry*, not from the exit.

### TC7: Strict Alert Confirmation Toggle

**Action**:

1. Locate `useStrictAlertConfirm` in the ⚡ Alerts settings group.
2. Test with toggle ON (default) — alerts should require `barstate.isconfirmed` outside revenue-open window.
3. Test with toggle OFF — alerts fire without strict confirmation.

**Expected Result (ON)**: `strictAlertsEnabled = useStrictAlertConfirm and not inRevOpenWindow` evaluates to `true` outside the revenue-open window.
**Expected Result (OFF)**: `strictAlertsEnabled` is always `false`, allowing all alerts.

---

## v6.2.24 — USI Quantum Pulse

### TC8: USI Enable/Disable

**Action**:

1. Enable USI (`useUsi = true`) and observe signal behavior.
2. Disable USI (`useUsi = false`) and compare.

**Expected Result**:

* When disabled: no USI impact on decision, confidence, or MTF vote. Script behaves identically to pre-USI version.
* When enabled: USI stacking can override decision gate, boost confidence, and contribute to MTF vote.

### TC9: USI Stacking Detection

**Action**:

1. Enable USI with `usiMinStack = 4`.
2. Find a trending period where RSI lines (13/11/7/5/3) are aligned above 50.
3. Verify that `usiBullStack` becomes true when ≥ 4 of 5 lines are above 50.

**Expected Result**:

* Bull stack detected when 4+ lines above 50; bear stack when 4+ below 50.
* `usiStackDir` is +1 (bull), −1 (bear), or 0 (no stack).

### TC10: USI Decision Override

**Action**:

1. Find a scenario where `decisionOkSafe = false` (decision gate blocks entry).
2. Enable USI with strong stacking alignment matching `trustDir`.

**Expected Result**:

* `usiStackOverride` becomes true.
* `decisionFinal` evaluates to `true` despite `decisionOkSafe = false`.
* Entry proceeds where it would otherwise be blocked.

### TC11: USI Confidence Boost

**Action**:

1. Enable USI with `usiConfBoost = 0.15`.
2. Observe confidence values during a USI-aligned stack period.

**Expected Result**:

* When stacking direction matches `trustDir`, confidence increases by 0.15.
* When stacking direction does NOT match, no boost applied.

### TC12: USI MTF Vote

**Action**:

1. Enable USI with `usiMtfWeight = 1.5`.
2. Observe `getVoteScore()` output with and without USI.

**Expected Result**:

* USI contributes `1.5 * usiScore` to the multi-timeframe vote total.
* Net effect visible as shifted vote scores during strong trend alignment.

---

## v6.2.24 — Debug Removal Verification

### TC13: No Debug Labels on Chart

**Action**:

1. Load both SkippALGO (Indicator) and SkippALGO_Strategy on a chart.
2. Inspect for any debug label blocks or plotchar pulse lines.

**Expected Result**:

* No pre-engine debug labels (gate states) visible.
* No post-engine debug labels (engine outputs) visible.
* No F1–F7 pulse plotchar lines.
* Plot budget remains well under 64 (~31 plots in Indicator).
