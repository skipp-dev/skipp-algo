# Changelog — SkippALGO v6.2.18 Entry Label Upgrade

**Date:** 12 Feb 2026
**Commits:** `4cf9923` (label switch), `0f9c46c` (indent fix), current commit
**Status:** All 297 tests passing, Pine Extension lint: 1 false-positive (see note)

---

## Overview

Entry labels (BUY, SHORT, REV-BUY, REV-SHORT) were switched from
`plotshape()` to `label.new()` to match the visual size of EXIT labels.
This resolves the long-running "orphan EXIT" illusion caused by BUY labels
being too small to notice on the chart.

**Root cause:** `plotshape()` renders as a small icon even at `size.large`,
while `label.new()` renders as a prominent text box. The visual size
mismatch caused users to overlook BUY labels between consecutive EXITs.

---

## Changes

### 1. Entry labels → `label.new()` with managed array

**Files:** `SkippALGO.pine`, `SkippALGO_Strategy.pine`

**Before:**
```pine
plotshape(showLongLabels and labelBuy, title="BUY", style=shape.labelup,
         location=location.belowbar, size=size.large, text="BUY",
         textcolor=color.white, color=color.new(color.green, 0))
```

**After:**
```pine
if showLongLabels and labelBuy
    f_entry_label(bar_index, low, "BUY\npU: " + _probTxt + "\nConf: " + _confTxt,
                  label.style_label_up, color.white, color.new(color.green, 0))
```

All 4 entry types (BUY, SHORT, REV-BUY, REV-SHORT) converted identically.

### 2. Probability & confidence in entry labels

Each entry label now shows:
- **pU** (bullish probability) for BUY / REV-BUY labels
- **pD** (bearish probability) for SHORT / REV-SHORT labels
- **Confidence** score (percentage)

Format example:
```
BUY
pU: 62.3%
Conf: 71.5%
```

### 3. Label budget rebalanced

Since `label.new()` is subject to TradingView's `max_labels_count=500`
FIFO limit, the budget was redistributed:

| Array            | Old Cap | New Cap | Notes                        |
|------------------|---------|---------|------------------------------|
| `_entryLabels`   | —       | 150     | New (was plotshape, no limit) |
| `_exitLabels`    | 400     | 250–300 | Reduced to share budget      |
| `_dbgLabels`     | 80      | 50      | Indicator only               |
| **Total**        | 480     | 450–500 | Within 500 max               |

### 4. Strategy file base indent fix

**File:** `SkippALGO_Strategy.pine`

The entire Strategy file had a spurious 4-space base indentation,
causing TradingView's Pine Script v6 compiler to fail with:
> Mismatched input "strategy" expecting "end of line without line continuation"

Stripped the 4-space base indent from all 4280 lines. `strategy()` is
now correctly at column 0.

---

## Lint Note

The Pine Script VS Code extension (`kaigouthro.pinescript-vscode`) reports
a false-positive syntax error at `f_target_profile_desc()` line 1007 in
Strategy (multi-line ternary continuation). The identical code in the
Indicator file produces no error, and the pattern is valid Pine Script v6
syntax. TradingView's own compiler accepts this code.

---

## Test Results

```
297 passed, 8 subtests passed in 0.52s
```

- **Python tests:** 297/297 pass
- **Pine lint (Indicator):** 0 errors
- **Pine lint (Strategy):** 1 false-positive (ternary continuation, see note above)
- **Pine lint (SmokeTest):** 0 errors
