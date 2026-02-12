# Changelog — SkippALGO v6.2.7

**Date:** 12 Feb 2026
**Commits:** `a391350` → `fad0af1` (6 commits)
**Status:** Merged to main, all tests green (297 passed, 8 subtests)

---

## Overview

This release resolves two user-reported bugs ("orphan EXIT labels" and
"missing REV-BUY signals"), refactors the reversal injection architecture
for cross-engine consistency, and introduces a Python-based behavioral test
simulator for the signal state machine.

---

## Bug Fixes

### 1. Orphan EXIT labels — `a391350`

**Problem:** Users reported EXIT labels appearing on the chart without a
preceding BUY. Two independent root causes were identified:

| Root cause | Detail |
|-----------|--------|
| **Debug label budget drain** | `showDebugLabels` defaulted to `true`, generating ~24 labels per ChoCH event. This exhausted TradingView's 500-label hard limit via FIFO eviction, causing BUY labels to be silently deleted while their corresponding EXIT labels survived. |
| **ChoCH exit bypassing grace period** | `isChoCH_Short` triggered an EXIT on bar+1 after entry. The structural exit grace period (`exitGraceBars`) was not applied to ChoCH-based exits. |

**Fix (Indicator + Strategy):**

- `showDebugLabels` now defaults to `false` with a tooltip warning about label budget
- Rolling debug label cap of 80 via `f_debug_label()` helper function
- New ChoCH-specific grace: `canChochExit = barsSinceEntry >= min(2, exitGraceBars)`
- EXIT/COVER labels now include "Held N bars" for diagnostic visibility

### 2. Missing REV-BUY signals — `3162d7f`

**Problem:** Neural Reversal entries (REV-BUY/REV-SHORT) were unreachable
when standard forecast gates failed. The reversal logic was nested inside
`if pos == 0 and (allowEntry or allowRescue)`, so when neither `allowEntry`
nor `allowRescue` was true, the code never reached the reversal evaluation
block — even though reversals are designed to bypass those gates.

**Fix (Indicator + Strategy):**

- Added a third entry path: `allowRevBypass = allowNeuralReversals and cooldownOkSafe and (isChoCH_Long or isChoCH_Short)`
- Main loop gate changed to: `if pos == 0 and (allowEntry or allowRescue or allowRevBypass)`
- Cooldown is still respected (no gate bypass beyond what was explicitly intended)

---

## Refactoring

### 3. Named bypass variable — `b719c23`

Extracted the inline bypass condition into a named boolean `allowRevBypass`
for readability and maintainability. No behavioral change.

### 4. Unified reversal injection — `19853ec`, `fad0af1`

**Discovery:** The Loose engine did not inject `revBuyGlobal`/`revShortGlobal`
into `buySignal`/`shortSignal`, unlike Hybrid, Breakout, and Trend+Pullback.
This meant Neural Reversals were silently dropped in Loose mode even after
the `allowRevBypass` fix got us into the entry evaluation block.

**Fix (Indicator + Strategy):**

- Removed per-engine reversal injection from Hybrid, Breakout, Trend+Pullback
- Added a single unified injection point **after** the engine if/else-if chain
  and **before** conflict resolution:

```pine
// Unified Neural Reversal injection (all engines, including Loose)
if allowNeuralReversals
    buySignal   := buySignal   or revBuyGlobal
    shortSignal := shortSignal or revShortGlobal
```

- This guarantees identical reversal semantics across all 4 engine modes
- Wrapped in `if allowNeuralReversals` guard for readability + micro-perf
- Conflict resolution (`if buySignal and shortSignal => cancel both`) remains unchanged

---

## Test Infrastructure

### 5. Behavioral test simulator — `e71287e`

**Motivation:** The existing 263 tests were 100% regex/structure-based (verifying
that specific code patterns exist in the Pine source). While valuable for
preventing regressions in code structure, they cannot verify the *behavioral
correctness* of the signal state machine.

**Solution:** A Python-based behavioral simulator that transpiles SkippALGO's
core control flow into executable Python:

| File | Purpose | Lines |
|------|---------|-------|
| `tests/pine_sim.py` | Simulator: entry guards, signal engines, state machine, exit grace | ~460 |
| `tests/test_behavioral.py` | 33 behavioral tests across 7 test classes | ~650 |

**Simulator scope:**

- Entry guard: `allowEntry` / `allowRescue` / `allowRevBypass` (3 paths)
- Signal engine: per-engine signal computation + unified reversal injection
- State machine: `pos` transitions (EXIT > COVER > BUY > SHORT precedence)
- Exit logic: structural exits, ChoCH exits, risk exits, grace periods
- Cooldown enforcement
- Conflict resolution

**Test coverage by class:**

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestEntryGuardReachability` | 7 | Standard entry, rescue, reversal bypass, blocking conditions |
| `TestStateMachineInvariants` | 5 | No orphan exits, pos validity, lifecycle |
| `TestConflictResolution` | 3 | Buy+short cancellation, shorts-disabled |
| `TestExitGracePeriods` | 3 | Structural grace, ChoCH min-2-bar grace, risk ignores grace |
| `TestAllEngines` | 7 | Per-engine signal firing, reversal injection in all engines |
| `TestMultiBarScenarios` | 8 | Full lifecycles, macro/volume/drawdown/probability gates |
| `TestCooldownBehavior` | 1 | Re-entry blocked during cooldown window |

### 6. Regression test for unified injection — `fad0af1`

Added `test_unified_reversal_injection` to `tests/test_features_v6_1.py`:

- Verifies the comment + guard + injection lines exist in both Pine files
- Verifies injection precedes conflict resolution (positional assertion)

---

## Verification

### Pine diagnostics

- `SkippALGO.pine`: 0 errors, 0 warnings
- `SkippALGO_Strategy.pine`: 0 errors, 0 warnings

### Test suite

```
297 passed, 8 subtests passed in 0.55s
```

---

## Critical Hotfix

### 6. Phantom Entry / NA Poisoning Fix — `4225ce0`

**Problem:** "Exit without Buy" persisted because trades were entering without labels.
Root cause: `revBuyGlobal` became `na` due to `pU` (probability) being `na` at history start.
Pine treats `buySignal = true or na` as `true` (Entry!), but `labelBuy = true and not na` as `na` (No Label!).

**Fix (Indicator + Strategy):**

- **Strict NA Check**: `probOkGlobal = (not na(pU) and pU >= 0.50)`
- **Fail-Closed Logic**: Wrapped `revBuyGlobal` in `f_fc_bool()` to force any lingering `na` to `false`.
- This ensures atomic signal behavior: either fully True or fully False.

---

## Files changed (cumulative)

| File | Changes |
|------|---------|
| `SkippALGO.pine` | Debug label budget, ChoCH grace, allowRevBypass, unified reversal injection |
| `SkippALGO_Strategy.pine` | Parity with all Indicator changes |
| `tests/pine_sim.py` | NEW — behavioral simulator |
| `tests/test_behavioral.py` | NEW — 33 behavioral tests + 8 engine subtests |
| `tests/test_features_v6_1.py` | +2 regression tests (reversal gate, unified injection) |
