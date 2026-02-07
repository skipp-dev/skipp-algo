# SkippALGO Market Structure Integration (v6.2)

## 1. Concept: BOS vs ChoCH

**BOS (Break of Structure)**

* **Definition**: Price breaks a swing level in the *same* direction as the established trend.
* **Meaning**: Trend Continuation.
* **Risk**: Standard.
* **Signal**: "BOS" (Green).

**ChoCH (Change of Character)**

* **Definition**: Price breaks a swing level in the *opposite* direction of the established trend.
* **Meaning**: Trend Reversal.
* **Risk**: High (Counter-trend). Requires stricter confirmation.
* **Signal**: "ChoCH" (Purple).

## 2. Implementation Logic

### State Tracking

The script uses a persistent variable `structState` to remember the last confirmed trend direction:

* `1`: Bullish Structure
* `-1`: Bearish Structure

### Signal Classification

* **Long Breakout (`breakoutLong`)**:
  * If `structState == 1` (Already Bullish) -> **BOS**
  * If `structState == -1` (Was Bearish) -> **ChoCH**
* **Short Breakout (`breakoutShort`)**:
  * If `structState == -1` (Already Bearish) -> **BOS**
  * If `structState == 1` (Was Bullish) -> **ChoCH**

### Strict ChoCH Filtering

ChoCH signals are more dangerous than BOS signals. To filter out "fakeouts", ChoCH entries require:

1. **Higher Probability** (`chochMinProb`, default 0.50): The Neural Engine must be *very* sure.
2. **Volume** (`chochReqVol`): Reversals without volume are ignored.

### Fast Exit via ChoCH

The logic also updates the **Exit Conditions**:

* If you are **LONG**, and a **Short Breakout** occurs:
  * Old Logic: Wait for EMA flip (`bearBias`). Slow.
  * New Logic: Exit immediately on the break (`breakShort`). Fast.
  * **Reason**: "ChoCH" (Structural Reversal).

### No "Flip" (Stop-and-Reverse) Policy

The script is designed for safety and capital preservation.

* **Behavior**: A ChoCH event will trigger an **Exit** from your current position, but it will **NOT** immediately open a new position in the opposite direction on the same bar.
* **Why?**: "Flipping" (e.g., selling long to buy short instantly) is high risk. The script exits first (going to Flat), allowing you to re-assess. You must wait for a subsequent valid entry signal (e.g., a pullback or a second breakout) to re-enter.

## 3. Configuration

* **Show BOS / ChoCH structure tags**: Toggle the distinct labels.
* **ChoCH Min Confidence**: Threshold for Reversal entries (Rec: 0.50).
* **ChoCH Require Volume?**: Mandatory volume check for reversals.
