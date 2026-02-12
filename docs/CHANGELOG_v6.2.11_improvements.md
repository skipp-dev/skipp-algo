# Changelog — SkippALGO v6.2.11 Parity & Quality Improvements

**Date:** 14 Feb 2026
**Commits:** `745c690` (8 fixes), test alignment fix (current)
**Status:** All 297 tests passing, 0 Pine Script lint errors

---

## Overview

This release implements eight targeted improvements across both Indicator
and Strategy files, addressing parity gaps, hardcoded values, missing
features, and operator safety issues identified during a post-v6.2.11
code review.

---

## Fixes (by priority)

### 1. [HIGH] cooldownOk → cooldownOkSafe in Strategy rescue path

**File:** `SkippALGO_Strategy.pine`
**Problem:** The `allowRescueLong` / `allowRescueShort` lines in Strategy
used the raw `cooldownOk` variable instead of `cooldownOkSafe` (the
fail-closed coercion). If `cooldownOk` returned `na`, Strategy rescue
entries could incorrectly fire.
**Fix:** Replaced `cooldownOk` with `cooldownOkSafe` in both rescue
definitions, matching the Indicator.

### 2. [HIGH] Conditional probability floor

**Files:** `SkippALGO.pine`, `SkippALGO_Strategy.pine`
**Problem:** The standard entry probability floor (`pU >= 0.50` /
`pD >= 0.50`) was applying unconditionally, which risked double-gating
when `forecastAllowed` was true (the forecast gate already enforces
`minDirProb`).
**Fix:** Wrapped the floor in `if not forecastAllowed`, so it only
activates as a safety net when the full forecast gate is not checking
probabilities.

### 3. [MEDIUM] decayBars / exitGraceBars tooltip

**Files:** `SkippALGO.pine`, `SkippALGO_Strategy.pine`
**Problem:** The `decayBars` and `exitGraceBars` inputs lacked tooltip
explanations, making their interaction unclear.
**Fix:** Added descriptive tooltips explaining the decay schedule and
grace period behavior.

### 4. [MEDIUM] rescueMinProb configurable input

**Files:** `SkippALGO.pine`, `SkippALGO_Strategy.pine`
**Problem:** The rescue minimum probability threshold was hardcoded to
`0.20` inside signal logic, preventing tuning without code edits.
**Fix:** Extracted to `rescueMinProb` input (default `0.30`) with tooltip.
Both `impulseLong` and `impulseShort` rescue paths use this input.

### 5. [MEDIUM] Fix stale Strategy comment

**File:** `SkippALGO_Strategy.pine`
**Problem:** A code comment still referenced `0.40` as the rescue
probability floor, but the actual value had been lowered to `0.20`.
**Fix:** Updated comment to accurately reflect current logic.

### 6. [LOW] Port Breakeven / Stalemate to Indicator

**File:** `SkippALGO.pine`
**Problem:** Breakeven and Stalemate exit features existed only in
Strategy. The Indicator lacked them, causing parity drift.
**Fix:** Ported both features with matching inputs (`useBreakeven`,
`beTrigger`, `beOffset`, `useStalemate`, `staleBars`, `staleMinATR`),
state variables (`isBeHit`, `enBar`), and exit logic. Added `staleExit`
to both `exitSignal` and `coverSignal` paths.

### 7. [LOW] Align operand ordering + parity gaps

**File:** `SkippALGO_Strategy.pine`
**Problem:** Several minor parity gaps vs the Indicator:
- `emaAccelTol` calculation missing in Strategy
- `pbTol = 0.25` pullback tolerance missing in Strategy
- `enhLongOk and hybridLongTrigger` operand ordering differed

**Fix:** Added `emaAccelTol` (5% tolerance) and `pbTol` (0.25 ATR) to
Strategy. Aligned operand ordering in Hybrid engine to match Indicator.

### 8. [LOW] Extract hardcoded values to inputs

**Files:** `SkippALGO.pine`, `SkippALGO_Strategy.pine`
**Problem:** Two magic numbers were embedded in signal logic:
- Reversal recency window: hardcoded `5` bars
- ChoCH grace period: hardcoded `2` bars

**Fix:** Extracted to configurable inputs:
- `revRecencyBars` (default 5): Maximum bars after ChoCH for reversal validity
- `chochGraceBars` (default 2): Minimum bars held before ChoCH can trigger exit

---

## Test Alignment

Two test patterns in `test_features_v6_1.py` were updated to match the
refactored code:

| Test | Old pattern | New pattern |
|------|-------------|-------------|
| `test_stale_reversal_filter` | `barsSinceChoCH_L <= \d+` | `barsSinceChoCH_L <= revRecencyBars` |
| `test_reversal_entry_gate` | `allowRevBypass = allowNeuralReversals and cooldownOkSafe and (...)` | `allowRevBypass = allowNeuralReversals and barstate.isconfirmed and cooldownOkSafe and (...)` |
| `test_reversal_entry_gate` | `if pos == 0 and (allowEntry or allowRescue or allowRevBypass)` | `if (pos == 0 and (allowEntry or allowRescue)) or allowRevBypass` |

---

## New Inputs Summary

| Input | Default | File(s) | Description |
|-------|---------|---------|-------------|
| `useBreakeven` | false | Indicator | Enable breakeven stop movement |
| `beTrigger` | 1.5 | Indicator | ATR multiple to trigger breakeven |
| `beOffset` | 0.1 | Indicator | ATR offset above entry for BE stop |
| `useStalemate` | false | Indicator | Enable stalemate exit |
| `staleBars` | 20 | Indicator | Bars before stalemate check |
| `staleMinATR` | 0.3 | Indicator | Min profit (ATR) to avoid stalemate exit |
| `rescueMinProb` | 0.30 | Both | Min probability for volume-rescue entries |
| `revRecencyBars` | 5 | Both | Max bars after ChoCH for reversal validity |
| `chochGraceBars` | 2 | Both | Min bars held before ChoCH exit |

---

## Validation

- **Python tests:** 297/297 passed (0.57s)
- **Pine Script lint:** 0 errors on all 3 `.pine` files
- **No regressions** in behavioral, cross-validation, numerical, or edge-case suites
