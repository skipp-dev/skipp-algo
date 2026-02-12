# PR Draft — v6.2.21 Strict Mode UX, Adaptive Strictness, Open-Window Controls

## Title

`feat(strict): signal-level strict markers, adaptive strictness, open-window fine controls, and enriched alert payload`

## What changed

This PR introduces a strict-mode enhancement bundle across indicator and strategy:

- strict confirmation visualization at signal-level (icon/label/both)
- open-window exception controls split by side, mode, and engine scope
- adaptive strict margin tied to ATR percentile rank
- enriched alert payload metadata (`mode`, `confirm_delay`)
- behavioral simulator + tests for strict event ordering

## Why

The goal is to improve strict-mode observability and operational precision:

- Traders can now see when strict confirmation actually happened.
- Open-window exceptions can be tuned safely without globally weakening filters.
- Strictness adapts to volatility regimes instead of static thresholds.
- Alert consumers (automation/webhook handlers) receive explicit strict metadata.
- Behavioral tests lock in delayed strict entry semantics and same-bar exits.

## Files touched

- `SkippALGO.pine`
- `SkippALGO_Strategy.pine`
- `tests/pine_sim.py`
- `tests/test_behavioral.py`
- `tests/test_skippalgo_pine.py`
- `tests/test_skippalgo_strategy_pine.py`

## Backward compatibility

- Default behavior remains conservative and compatible with prior setup.
- New controls are opt-in or additive.
- Existing alert consumers continue to work; payload now includes extra fields.

## Validation

- Targeted strict-related test suites: passed
- Full test suite (`pytest`): passed

## Suggested reviewer focus

1. strict event ordering (entry delay vs same-bar exits)
2. open-window side/mode/engine scoping logic
3. indicator/strategy parity for strict and payload logic
4. adaptive strict margin safety bounds
