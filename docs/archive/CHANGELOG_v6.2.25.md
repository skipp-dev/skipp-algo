# SkippALGO v6.2.25 — Code Quality & Bug Fix Release

**Date:** 2026-02-13  
**Scope:** SkippALGO.pine (Indicator), SkippALGO_Strategy.pine (Strategy parity), QuickALGO.pine  
**Tests:** 334/334 passing (8 subtests)

---

## Summary

Comprehensive code-review sweep addressing 20 issues across 5 categories:
4 bug fixes, 4 dead-code removals, 6 named constants, 1 deduplication, and
5 documentation improvements.  No user-facing input changes; all toggles and
defaults remain identical.

---

## Bug Fixes (4)

### 1. EMA Acceleration Short — Inverted Condition

**Lines ~3693 | Severity: Medium**

`emaAccelShortOk` used `<=` (gap must *shrink*), opposite to the long-side `>=`
(gap must *expand*).  Both sides now require an expanding EMA gap before
allowing entry, which is the correct semantic for "accelerating trend."

```diff
- emaAccelShortOk = (not useEmaAccel) or (emaGap <= (emaGapPrev + emaAccelTol))
+ emaAccelShortOk = (not useEmaAccel) or (emaGap >= (emaGapPrev - emaAccelTol))
```

### 2. Missing Forecast/Volume/SET Gates on Trend+Pullback & Loose Engines

**Lines ~4068-4076 | Severity: High**

Hybrid and Breakout engines checked `fcGateLongSafe`, `volOkSafe`, and
`setOkLongSafe` (plus short equivalents), but Trend+Pullback and Loose did
**not**.  This left two engines without forecast-gate, volume-confirmation,
and SET-confluence enforcement.  All four engines now share identical gate
requirements.

### 3. Label Budget Overflow (630 → 460)

**Scattered | Severity: Low**

TradingView enforces `max_labels_count=500`.  Five label arrays summed to 630,
risking silent auto-deletion of older labels.  Reduced totals:

| Array | Old | New |
|-------|-----|-----|
| `_dbgLabels` | 50 | 30 |
| `_strictLabels` | 80 | 50 |
| `_preLabels` | 100 | 60 |
| `_entryLabels` | 150 | 120 |
| `_exitLabels` | 250 | 200 |
| **Total** | **630** | **460** |

### 4. volTol Comment Mismatch

**Line ~3622 | Severity: Low**

Comment said "5% tolerance" but code was `0.50` (50%).  Corrected comment to
accurately describe the 50% volume tolerance.  Value now references
`VOL_TOLERANCE` constant.

---

## Dead Code Removal (4)

### 5. Unused Debug Inputs: `covOkHi`, `covOkLo`, `showOpsRow`

**Lines ~560-562**

Three `input.*()` declarations with no downstream consumers.  Removed entirely.

### 6. Unused Percentile Helpers: `f_pctl_float`, `f_pctl_int`

**Lines ~4566-4583**

Two helper functions (~18 lines) with zero call sites.  Replaced with a
one-line removal comment.

### 7. UT Bot Empty Section Header

**Line ~4672**

An orphan `// UT Bot …` comment block with no code underneath.  Removed.

### 8. Legacy Mark: `f_eval_on_resolve`

**Line ~1757**

Function is effectively dead when `use3Way = true` (the default).  Added a
`// LEGACY` header comment explaining the condition rather than deleting it
(branches still compile and could be re-enabled).

---

## Named Constants (6)

Replaced hardcoded magic numbers with descriptive constants defined near the
top of the file (~line 213):

| Constant | Value | Usage |
|----------|-------|-------|
| `REV_BUY_PROB_FLOOR` | 0.37 | Hard floor for REV-BUY probability check |
| `STD_ENTRY_PROB_FLOOR` | 0.50 | Standard entry probability safety net |
| `CHOCH_RECENCY_BARS` | 12 | Maximum bars since ChoCH for recency check |
| `EMA_TOUCH_TOL_ATR` | 0.05 | EMA-touch tolerance as fraction of ATR |
| `PB_DEPTH_TOL_ATR` | 0.25 | Pullback depth tolerance in ATR units |
| `VOL_TOLERANCE` | 0.50 | Volume threshold tolerance multiplier |

All 8+ usage sites updated to reference these constants.

---

## Deduplication (1)

### 9. Strict Alert Computation

**Lines ~4380 + ~4685**

Strict-alert variables (`strictAtrRank`, `strictMtfMarginEff`,
`buyEventStrict`, etc.) were computed twice — once in the Visuals section and
again (with `*Vis` suffix) in the Alerts section.  Unified to a single
computation in Visuals; the Alerts section now reuses those variables directly.
All `*Vis`-suffixed duplicates eliminated.

---

## Documentation (5)

### 10. `exitConfChoCh` Asymmetry

**Line ~4268**

Expanded inline comment explaining the intentional asymmetry: bearish ChoCH
exits are filtered by `exitConfChoCh` to avoid premature exit, while bullish
ChoCH exits are intentionally unfiltered for aggressive short-side protection.

### 11. `confForecastArr` Calibration Comment

**Line ~3150**

Expanded PATCH A comment clarifying that `barstate.isconfirmed` is
intentionally used for all horizons (chart-TF rate), not the HTF rate, for
faster warm-up while anti-repaint data protection is handled by `f_stable_val`.

### 12. `dirFlag` Usage Clarification

**Line ~2479**

Added comment explaining `dirFlag` is the raw bias value pushed to `st.qBias`,
while `biasSel` is the mutable copy used for zero-fallback logic.

---

## Test Updates

4 tests updated to match code changes:

| Test | Change |
|------|--------|
| `test_loose_engine_uses_enhOk` | Snippet window 300→500 chars (added comment line) |
| `test_pre_labels_are_dynamic_label_new_not_plotshape` | `MAX_PRE_LABELS` 100→60 |
| `test_strict_signal_visualization_exists` | Removed `*Vis` suffix from variable names |
| `test_rev_buy_min_prob_floor_including_open_window` | Checks `REV_BUY_PROB_FLOOR` constant |

---

## Files Changed

- `SkippALGO.pine` — 28 edits (all review items)
- `SkippALGO_Strategy.pine` — 18 edits (parity port of all applicable items)
- `QuickALGO.pine` — 7 edits (independent code review)
- `tests/test_cross_validation.py` — 1 edit (snippet window)
- `tests/test_skippalgo_pine.py` — 3 edits (updated assertions)
- `tests/test_skippalgo_strategy_pine.py` — 2 edits (updated assertions)
- `docs/SkippALGO_Deep_Technical_Documentation.md` — USI/Cooldown/Strict/Debug sections
- `tests/TEST_PLAN_v6.2.md` — TC6–TC13 added

---

## Strategy Parity (18 edits)

All applicable v6.2.25 fixes ported to `SkippALGO_Strategy.pine`:

| Fix | Notes |
|-----|-------|
| Named constants block | `REV_BUY_PROB_FLOOR`, `STD_ENTRY_PROB_FLOOR`, `EMA_TOUCH_TOL_ATR`, `PB_DEPTH_TOL_ATR`, `VOL_TOLERANCE` |
| EMA Accel Short fix | `<=` → `>=` |
| T+P / Loose gate parity | `fcGate + volOk + setOk` added |
| `REV_BUY_PROB_FLOOR` constant | Replaced `0.37` literal |
| `STD_ENTRY_PROB_FLOOR` constant | Replaced `0.50` literal |
| Volume tolerance | **New** — Strategy was missing entirely; added `VOL_TOLERANCE` multiplier |
| Touch-EMA tolerance | **New** — Strategy had exact `emaF` comparison; added `touchTol = EMA_TOUCH_TOL_ATR * atr` |
| `pbTol` → `PB_DEPTH_TOL_ATR` | Constant reference |
| Label budgets | `MAX_STRICT_LABELS` 80→50, `MAX_PRE_LABELS` 100→60, `MAX_ENTRY_LABELS` 150→120, `MAX_EXIT_LABELS` 300→200 |
| `confForecastArr` comment | Expanded calibration rationale |
| `f_eval_on_resolve` LEGACY mark | Added header comment |
| `exitConfChoCh` asymmetry comments | Both long-exit and short-exit blocks |
| `dirFlag` clarification | Comment explaining `dirFlag` vs `biasSel` |

Items NOT applicable to Strategy (don't exist): `covOkHi`/`covOkLo`/`showOpsRow`, `f_pctl_float`/`f_pctl_int`, `UT Bot`, `*Vis` strict dedup, `CHOCH_RECENCY_BARS`.

---

## QuickALGO.pine — Independent Code Review (6 fixes)

### 1. `max_labels_count=500`
Added to `indicator()` call — prevents silent label loss on long charts.

### 2. Magic Numbers in Trendlines
`60000` → `10e10` and `0` → `-10e10` for highest/lowest init values.
Old values broke on BTC and other high-priced instruments.

### 3. Market Profile Buy/Sell Flow Bug (Critical)
`recent_buy_vol` and `recent_sell_vol` were both set to `ta.sma(volume, 20)`
on every bar (only one `if` path executes), making `vol_ratio` effectively
always ~0.5 and rendering strong_buy_flow / strong_sell_flow useless.

Replaced with body-weighted buy/sell pressure using candle direction and
body-to-range ratio:

```pine
bodyRange = math.max(high - low, syminfo.mintick)
buyPressure  = close >= open ? volume * ((close - open) / bodyRange) : 0.0
sellPressure = close <  open ? volume * ((open - close) / bodyRange) : 0.0
```

### 4. Removed Dead Input: `tp_box_height`
Declared but never referenced. Removed.

### 5. Removed Dead Variable: `cvd_level`
Computed as `"Low"/"Medium"/"High"` string but never displayed. Removed.
(`cvd_color` is still used by the table.)

### 6. Added `alertcondition()` for Buy/Sell Signals
QuickALGO had no alert conditions. Added:

```pine
alertcondition(did_buy,  title="QuickALGO Buy",  message="QuickALGO BUY signal — Conf: {{close}}")
alertcondition(did_sell, title="QuickALGO Sell", message="QuickALGO SELL signal — Conf: {{close}}")
```
