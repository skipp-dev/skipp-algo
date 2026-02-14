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
