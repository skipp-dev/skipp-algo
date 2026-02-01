# Test Plan v6.2 - Evaluation Section

**Objective**: Verify the new Evaluation Section (Brier, LogLoss, ECE, Drift) functions correctly and provides useful probabilistic feedback.

## Setup
1.  Add `SkippALGO` to a chart (e.g., BTCUSDP 1m or 5m).
2.  Enable "Show Table" in settings.
3.  Scroll down to "Evaluation (Live Scoring)" section in settings.
4.  Ensure "Show Evaluation rows" is CHECKED.

## Test Cases

### TC1: Initial Load & Table Structure
**Action**: Load the indicator on a fresh chart.
**Expected Result**:
*   Table appears.
*   Bottom rows (24-31) show "Evaluation" header.
*   Columns: `Evaluation`, `LogLoss`, `ECE/Max`, `Drift(S-L)`, `#Obs`.
*   Rows F1-F7 are present.
*   Values should be initialized (likely `—` or `0` if no history calculated yet, or valid numbers if "History+Live" mode picked up confirmed bars).

### TC2: Data Accumulation
**Action**: 
1.  Allow the chart to run (or use Replay mode) for N bars to generate forecast opportunities.
2.  Observe the `#Obs` column in the Evaluation section.
**Expected Result**:
*   Counts (`#Obs`) should increment as forecasts resolve (age out or hit targets).
*   `LogLoss` should start fluctuating (lower is better, < 0.69).
*   `ECE` should populate (e.g., `5.2/12.0` meaning 5.2% avg error, 12% max error).

### TC3: Reset Functionality
**Action**:
1.  Go to Settings -> "Forecast Calibration Enhancements".
2.  Set `Reset calibration scope` to "All".
3.  Check `Reset selected calibration NOW`.
4.  Wait for one bar update.
5.  Uncheck `Reset selected calibration NOW`.
**Expected Result**:
*   All `#Obs` counts in the Evaluation table reset to 0.
*   LogLoss and ECE reset to `—` or empty state.
*   Accumulation restarts from 0.

### TC4: Head Switching (N vs 1)
**Action**:
1.  Accumulate some data (e.g., `#Obs` > 10).
2.  Note the F1 `LogLoss` value.
3.  Go to Settings -> "Evaluation".
4.  Change `Evaluate head` from "N" (Multi-factor) to "1" (Single-factor).
**Expected Result**:
*   The table values update immediately.
*   The `LogLoss` and `ECE` values should likely be slightly different (usually "N" is better/lower than "1", but not always).
*   `#Obs` count remains consistent (since both heads are updated on the same events), but the *scores* change.

### TC5: Drift Logic
**Action**:
1.  Observe `Drift(S-L)` column.
**Expected Result**:
*   Value format: e.g., `+2.3pp` or `-1.5pp`.
*   Positive values indicate Short predictions are performing better (yielding higher) than Longs.
*   Negative values indicate Longs are performing better.
