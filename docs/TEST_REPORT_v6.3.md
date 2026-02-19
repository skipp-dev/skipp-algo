# Test Report v6.3

**Date:** Feb 07, 2026

**Subject:** QuickALGO Parity Upgrade & Full Regression Test

## Summary

* **Total Tests:** 335
* **Passed:** 335
* **Failed:** 0
* **Status:** PROMOTED

## Key Changes Validated

1. **QuickALGO.pine**:
   * Ported `USI Quantum Pulse` logic from Strategy/Indicator v6.3.
   * Implemented `qRegime`, `qVerify`, `30m Gate`, `Lean Debug`.
   * Verified distinct logic paths for "Verification" vs "Signal".

2. **Test Infrastructure**:
   * Fixed `ModuleNotFoundError` by adding `tests/__init__.py`.
   * Metrics updated in `tests/test_skippalgo_strategy_pine.py`: `revBuyMinProbFloor` lowered to `0.25` (Rescue Floor default).

## Execution Log

```txt
$ pytest tests/
============================= test session starts ==============================
platform darwin -- Python 3.11.7, pytest-8.3.4, pluggy-1.5.0
rootdir: /Users/steffenpreuss/Downloads/skipp-algo
configfile: pytest.ini
collected 335 items

tests/test_cross_validation.py ........................................  [ 11%]
tests/test_edge_cases.py ................................................ [ 26%]
tests/test_numerical_regression.py ...................................... [ 37%]
tests/test_skippalgo_pine.py ............................................ [ 50%]
tests/test_skippalgo_strategy.py ........................................ [ 62%]
tests/test_skippalgo_strategy_pine.py ................................... [100%]

============================= 335 passed in 0.43s ==============================
```

## Sign-off

System is stable and ready for deployment.

---

## Addendum — Feb 15, 2026 (USI Safety + Parity)

### Validation scope

Validated the latest USI-related updates in indicator and strategy parity:

1. **USI Red De-lag Option (Option 2)**
   * Inputs present in both scripts: `useUsiZeroLagRed`, `usiZlAggressiveness`.
   * Red-line source path uses `f_zl_src_pct(...)` in both scripts.

2. **Hard USI Directional Blocking**
   * BUY blocked when USI is bearish (`usiBearState`).
   * SHORT blocked when USI is bullish (`usiBullState`).
   * Verified identical logic in score decision blocks for Indicator + Strategy.

3. **Risk-gate parity resilience**
   * `baseEligible` regex check remains valid for `:=` assignment style in both scripts.

4. **Score + Chop merge parity**
   * Score merge updated to hybrid mode in both scripts:
     * `buySignal := (buySignal or scoreBuy) and not chopVeto`
     * `shortSignal := (shortSignal or scoreShort) and not chopVeto`
   * `scoreChopVeto` defined consistently from `chopRisk` and penalty/veto settings.
   * Added directional-context hardening input `scoreRequireDirectionalContext` (default ON), applied in both scripts before score injection.
   * Debug output now shows `veto:0/1`, `ctxL:0/1`, `ctxS:0/1`, and explicit `BLOCK:...` reason in both scripts for direct blocker visibility.

5. **Unified Exit Trigger + Cooldown Restoration (LONG + SHORT)**
    * Verified unified close logic in both scripts for both sides:
       * `riskExitHit (TP/SL/Trailing) OR usiExitHit OR engExitHit`
       * first trigger closes the active position.
    * Verified restored cooldown semantics on real exits/covers:
       * when `cooldownTriggers` is `ExitsOnly` or `AllSignals`, cooldown timestamps are updated on both EXIT and COVER events.
    * Verified parity at the corresponding `exitSignal` and `coverSignal` assignment blocks in Indicator + Strategy.

### Result

`tests/test_score_engine_parity.py` passed after extension with new parity assertions.

---

## Addendum — Feb 16, 2026 (v6.3.13 Parity Hardening)

### Scope

Validated repo state after the v6.3.13 maintenance pass:

1. **Strategy gate parity restored**
   * `allowEntry` now enforces reliability/evidence/eval/abstain decision gates (plus session filter).
2. **Dynamic risk parity completed**
   * Strategy now includes indicator-equivalent runtime blocks for:
     * Dynamic TP expansion,
     * Dynamic SL profile (widen/tighten),
     * preset-aware effective dynamic TP mapping.
3. **Structure + ChoCH wiring fixes**
   * `chochReqVol` is now active in ChoCH entry filtering,
   * BOS/ChoCH structure tags are rendered in Strategy,
   * BOS tags are rendered in Indicator.

### Execution

```txt
$ pytest -q
386 passed in 0.68s
```

### Addendum result

#### Status

PASS (386/386)
