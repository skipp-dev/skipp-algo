// SkippALGO Structure Test (Test Plan v6.2)
// Purpose: Verify BOS/ChoCH logic and strict filtering for Reversals.

// Scenario 1: Uptrend Continuation (BOS)
// Setup:
// - Structure State = Bullish (1)
// - Price breaks Swing High
// Expected:
// - isBOS = true, isChoCH = false
// - Signal generation uses Standard Forecast Prob (0.42)
// - Label: "BOS" (Green)

// Scenario 2: Downtrend to Uptrend Reversal (ChoCH)
// Setup:
// - Structure State = Bearish (-1)
// - Price breaks Swing High
// Expected:
// - isBOS = false, isChoCH = true
// - Signal generation uses Strict ChoCH Prob (0.50)
// - Label: "ChoCH" (Purple)

// Scenario 3: ChoCH Filtering (Rejection)
// Setup:
// - Structure State = Bearish (-1)
// - Price breaks Swing High (ChoCH Condition met)
// - Forecast Prob = 0.45 (Good for BOS, bad for ChoCH)
// Expected:
// - Signal Rejected (buySignal = false)
// - No Label

// Scenario 4: ChoCH Filtering (Acceptance)
// Setup:
// - Same as above, but Forecast Prob = 0.52
// Expected:
// - Signal Accepted
// - Label: "ChoCH"

// Code Verification Checklist:
// [x] Inputs added (chochMinProb, chochReqVol)
// [x] Structure State Variable (structState)
// [x] Logic to flip state on breakouts only
// [x] Integration into Hybrid Engine signals
// [x] Integration into Breakout Engine signals
// [x] Visuals (Plotshape for BOS/ChoCH)
