# SkippALGO Update - v6.2.X

## USI "Premium" Logic Implementation (User Request)

Implemented "Pattern A: Premium vs Standard" logic for USI (Universal Strength Index) to act as a quality filter without blocking entries.

### Core Changes

1.  **USI Definition Refined**:
    * Implemented strict "Red (Fastest) vs Envelope (All Others)" logic.
    * `usiMaxEnv` = Max of lines 1-4.
    * `usiMinEnv` = Min of lines 1-4.
    * **USI Buy Signal**: Red line crosses *above* `usiMaxEnv` (was below).
    * **USI Bull State**: Red line is strictly > `usiMaxEnv`.

2.  **Fail-Open / Non-Blocking**:
    * USI signals are now strictly *additive*. They do not gate the core Engine BUY/SHORT signals.
    * Removed previous generic `usiStackDir` logic in favor of this precise envelope method for quality assessment.

3.  **Visual Labeling ("Premium" Tier)**:
    * **BUY / SHORT**: Now displays `BUY (Prem)` or `SHORT (Prem)` if USI confirms the direction (State or Recent Signal within 3 bars).
    * **REV-BUY / REV-SHORT**: Confluence logic updated.
        * Old: `REV-BUY+` (cryptic).
        * New: `REV-BUY (Prem)` if USI confirms AND Liquidity Sweep occurred.

4.  **Files Updated**:
    * `SkippALGO.pine` (Indicator)
    * `SkippALGO_Strategy.pine` (Strategy)

5.  **Verified**:
    * Logic ensures main signals fire regardless of USI state.
    * Test suite passed (335 tests).
