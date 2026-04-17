# Pine Surface Audit — 2026-04-17

## Overview

Audit of the user-facing input surfaces across the three SMC mainline targets.

## Surface Metrics

| Script | Total Inputs | Visible | Hidden | BUS Bindings |
|---|---|---|---|---|
| SMC Core Engine | 250 | 10 | 240 | 0 (source) |
| SMC Dashboard | 67 | 8 | 59 | 59 |
| SMC Long Strategy | 14 | 6 | 8 | 8 |

## Core Engine Visible Surface (10 inputs)

| Group | Input | Type | Tooltip | Display |
|---|---|---|---|---|
| 1. Mode | Signal Mode | enum | ✅ | status_line |
| 1. Mode | Trading Style | string | ✅ | status_line |
| 1. Mode | Focus View | bool | ✅ | default |
| 1. Mode | Color Theme | string | ✅ | default |
| 2. Output | Show Decision Brief | bool | ✅ | default |
| 2. Output | Enable dynamic alerts | bool | ✅ (added WP-14) | default |
| 3. Trade Plan | Target 1 (R) | float | ✅ (added WP-14) | default |
| 3. Trade Plan | Target 2 (R) | float | ✅ (added WP-14) | default |
| 4. Session Gate | Use Trade Session Gate | bool | ✅ (added WP-14) | default |
| 5. Runtime Budget | Performance Mode | string | ✅ | status_line |

## Dashboard Visible Surface (8 inputs)

| Group | Input | Type | Tooltip |
|---|---|---|---|
| Surface | View | string | ✅ |
| Surface | Show Brief Panel | bool | — |
| Surface | Show Trade Plan | bool | — |
| Surface | Highlight Live Setup | bool | — |
| Surface | Compact Dashboard | bool | ✅ |
| Local Debug | OB Debug Enabled | bool | ✅ |
| Local Debug | FVG Debug Enabled | bool | — |
| Local Debug | Long Engine Debug Enabled | bool | — |

## Strategy Visible Surface (6 inputs)

| Group | Input | Type | Tooltip |
|---|---|---|---|
| Setup | Entry Mode | string | — |
| Setup | Min Quality Score | int | — |
| Setup | Use Regime Gate | bool | — |
| Setup | Backtest Mode | bool | ✅ |
| Trade Plan | Use Take Profit | bool | ✅ |
| Trade Plan | Take Profit (R) | float | ✅ |

## WP-14 Changes

4 tooltips added to visible Core Engine inputs that previously lacked them:

1. **Enable dynamic alerts** — explains alert lifecycle message behavior
2. **Target 1 (R)** — explains R-multiple meaning
3. **Target 2 (R)** — explains second target and overlay
4. **Use Trade Session Gate** — explains session window restriction

## Surface Design Principles

- **Visible by default**: Only inputs the operator actively adjusts (mode, trade plan, performance)
- **Hidden by default**: All technical parameters, BUS bindings, and advanced modules use `display = display.none`
- **Group numbering**: Sequential 1-23 in Core Engine; groups 6-23 are "Advanced" and entirely hidden
- **Tooltip coverage**: All visible inputs now have tooltips (100% after WP-14)
- **BUS inputs**: Always hidden, always prefixed with `BUS ` for automation contract matching
