# Update Record v6.1.1

**Date**: October 2023  
**Status**: Applied to Indicator & Strategy

## Summary of Changes

This update addresses two critical edge cases identified in testing: "Fake Reversal Drift" (False Positives) and "Missed Structure Exits" (False Negatives).

### 1. Smart Stale Reversal Filter (Entry Logic)

**Problem**: The algorithm was taking Reversal entries based on ChoCH (Change of Character) signals that occurred up to 12 bars ago. In low volatility (low volume) environments, price would sometimes "drift" sideways after a ChoCH, triggering a late entry when volume was dead, leading to immediate stops.

**Solution**: implemented a dynamic recency filter based on Volume.

- **High Volume (`Vol > SMA`)**: We accept ChoCH signals from older bars (dynamic). The market is active, so the structure change is likely still valid.
- **Low Volume (`Vol < SMA`)**: We **strictly** enforce a 5-bar limit on ChoCH recency. If the reversal happened >5 bars ago and volume is low, the entry is ignored.

**Code Logic**:

```pine
// Entry Condition:
bool revRecencyOkL = (not na(barsSinceChoCH_L)) and (barsSinceChoCH_L <= 5 or volRatioG >= 1.0)
```

### 2. Explicit ChoCH Exit Trigger (Exit Logic)

**Problem**: In fast-moving reversal scenarios, the strategy relied on `breakShort` (generic breakout) to trigger exits. In some "V-Shape" reversal cases where the structure flipped from Bullish to Bearish immediately, the standard breakout signal (which requires specific candle closes vs wicks) might lag or potential race conditions in the `breakout` definition caused missed exits.

**Solution**: Added `isChoCH` (Character Change) as an explicit, unconditional exit trigger.

- **Logic**: If the internal Market Structure State flips (Bull -> Bear), we exit immediately, regardless of whether strict Breakout rules (like candle close filters) are fully met. This ensures we "fail safe" and exit the position on the first sign of structural failure.

**Code Logic**:

```pine
// Exit Condition:
structHit = ((breakShort or isChoCH_Short) and canStructExit)
```

## Impact Simulation

| Scenario | Old Behavior v6.1 | New Behavior v6.1.1 |
| :--- | :--- | :--- |
| **Drifting Reversal** | Entered late on Bar 10 with low volume. Often stopped out. | **No Entry**. Ignored because volatility is too low to sustain the old reversal signal. |
| **High Vol Reversal** | Entered on Bar 10. | **Entry Accepted**. High volume confirms the move is still live. |
| **Fast V-Shape Dump** | Sometimes held position until Stop Loss or Trail hit. | **Immediate Exit**. Detects structure flip (ChoCH) and closes position. |
