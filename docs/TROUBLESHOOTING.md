# Troubleshooting Log - SkippALGO v6.1 (Feb 2024)

## Issue: Missed High-Volume Reversal Signals

**Date**: Feb 7, 2026
**Reported By**: User
**Description**:
The algorithm failed to trigger a valid "REV-BUY" signal during a high-volatility event at 15:30 (Volume 17.7x) and a preceding setup at 15:27 (Volume 1.6x). Despite high Neural Probabilities (>50%), the entries were blocked by internal safety gates.

### Root Cause Analysis

1. **Over-Conservative Safety Gates**: The `allowEntry` logic enforces strict statistical checks (Reliability, Evidence, Abstain). During extreme volatility ("shock" moves), the calibration stats can momentarily appear "weak" or "insufficiently sampled," causing the `Abstain` gate to block the trade despite massive volume confirmation.
2. **Engine Scope Bug**: The user was running the **"Trend+Pullback"** engine. The specific logic for Neural Reversals (`revBuy` / `revShort`) was historically nested inside the `if engine == "Hybrid"` block. As a result, other engines physically could not trigger these reversals.
3. **Strict Choppiness Filter**: The `flatAbstainThr` (default 0.45) blocked the 15:27 signal because the "Flat" probability was marginally elevated, flagging the market as "too choppy" despite the breakout volume.

### Resolution Implemented

1. **"Rescue Mode" (Volume Override)**:
    - Introduced a new logic path: `allowRescue = hugeVolG and barstate.isconfirmed and cooldownOk`.
    - **Rule**: If Volume > 1.5x the 20-period SMA, the algorithm *bypasses* the standard statistical safety gates (Reliability, Evidence, Abstain) and proceeds directly to signal generation.
    - *Rationale*: Huge volume acts as its own confirmation, superseding the need for long-term statistical stability during shock events.

2. **Global Reversal Logic**:
    - Lifted the `revBuy` and `revShort` logic out of the "Hybrid" engine block.
    - Created global flags `revBuyGlobal` and `revShortGlobal` that are now injected into **all** engines (Hybrid, Breakout, Trend+Pullback).
    - *Result*: A "Trend+Pullback" engine can now take a sudden Neural Reversal trade if the volume and probability align, without waiting for trend confirmation.

3. **Parameter Tuning**:
    - **Rescue Threshold**: Lowered `hugeVolG` definition from `2.0x` to `1.5x` to capture the 15:27 signal (which had ~1.6x volume).
    - **Choppiness/Abstain**: Relaxed `flatAbstainThr` input default from `0.45` to `0.55`. This allows trades to proceed even if the "Flat" probability is slightly dominant (up to 55%), preventing valid signals from being filtered out in noisy but directional markets.

### Verification

- **Code Changes**: Applied to both `SkippALGO.pine` (Study) and `SkippALGO_Strategy.pine` (Strategy).
- **Outcome**: The 15:27 signal (1.6x Vol) and 15:30 signal (17x Vol) should now both trigger as valid "REV-BUY" entries regardless of the selected Engine.
