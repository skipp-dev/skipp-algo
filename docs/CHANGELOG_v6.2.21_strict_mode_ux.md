# CHANGELOG v6.2.21 — Strict Mode UX & Open-Window Refinements

Date: 2026-02-12

## Summary

This update improves strict-mode transparency, adds finer open-window control, introduces adaptive strictness by volatility regime, and extends alert payload metadata for downstream automation.

## Indicator + Strategy Changes

### 1) Strict Mode as Signal-Level Visualization

- Added strict confirmation marker controls:

  - `showStrictSignalMarkers`
  - `strictMarkerStyle` (`Icon | Label | Both`)

- Added strict-confirmed overlays:

  - `STRICT-CONF BUY`
  - `STRICT-CONF SHORT`

  - Optional labels:

    - `STRICT-CONFIRMED BUY`
    - `STRICT-CONFIRMED SHORT`

### 2) Fine-Grained Open-Window Exception Control

- Added side-specific window controls:

  - `revOpenWindowLongMins`
  - `revOpenWindowShortMins`

- Added applicability controls:

  - `revOpenWindowMode` (`All Entries | Reversals Only`)
  - `revOpenWindowEngine` (`All | Hybrid | Breakout | Trend+Pullback | Loose`)

- Forecast-gate bypass and reversal-probability bypass now apply by side, mode, and selected engine scope.

### 3) Adaptive Strictness (Volatility-Aware)

- Added adaptive strictness inputs:

  - `useAdaptiveStrictMargin`
  - `strictAdaptiveRange`
  - `strictAdaptiveLen`

- Effective strict margin now adapts via ATR percentile rank:

  - stricter in high-volatility regimes
  - looser in calm regimes

### 4) Alert Payload Expansion

- JSON payload now includes:

  - `"mode": "strict" | "normal"`
  - `"confirm_delay": 1 | 0`

- Human-readable runtime alerts now include:

  - `mode=...`
  - `confirm_delay=...`

## Test Coverage Added

### Behavioral Simulation

- Added strict event-layer simulation fields and memory in `tests/pine_sim.py`:

  - delayed strict BUY/SHORT event conditions
  - same-bar EXIT/COVER behavior
  - strict auto-disable in open-window context

### New Behavioral Tests

- Added `TestStrictEventBehavior` in `tests/test_behavioral.py`:

  1. strict BUY alert fires on follow-up bar (delay = 1)
  2. EXIT remains same-bar in strict mode
  3. strict mode disabled in open-window, falls back to normal same-bar BUY alert

### Contract/Regex Tests

- Expanded strict/open-window/payload assertions in:

  - `tests/test_skippalgo_pine.py`
  - `tests/test_skippalgo_strategy_pine.py`

## Validation

- Targeted strict-related suites: passed
- Full pytest suite: passed

## Notes

- Strategy compile shadowing issue was fixed by renaming a local alert message variable to avoid parent-scope name conflict.
