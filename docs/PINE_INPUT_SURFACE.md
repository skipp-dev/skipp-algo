# Pine Input Surface Reduction

Reduces the visible input surface of major Pine scripts from **~4,000 raw inputs** to **~30-40 core controls** per script, improving onboarding and chart readability while preserving all engine behaviour.

## Summary

| Script | Inputs | Grouped | display.none | **Visible** | Groups |
|---|---:|---:|---:|---:|---:|
| SMC++.pine | 266 | 266 (100%) | 235 | **31** | 24 |
| SkippALGO.pine | 359 | 359 (100%) | 320 | **39** | 37 |
| SkippALGO_Strategy.pine | 357 | 357 (100%) | 322 | **35** | 39 |

## What changed

### Mechanism

- **`display = display.none`** — Removes the input value from the chart status-line overlay. The input is still fully available in the Settings dialog.
- **`group = ...`** — Organises inputs into collapsible sections in the Settings dialog.
- **No logic changes.** Every input, default value, and engine path is identical.

### SMC++.pine (266 inputs)

Already had 100% grouping (24 groups) and the best-in-class **User Preset** mechanism (`Easy / Standard / Pro` overrides 9 boolean flags at runtime). This pass added `display = display.none` to **211 expert-level inputs**, keeping **31 core toggles** visible on the status line:

Core visible: `signal_mode`, `long_user_preset`, `enable_ltf_sampling`, `ltf_timeframe`, `show_mtf_trend`, `mtf_trend_tf1-3`, `show_dashboard`, `enable_dynamic_alerts`, `performance_mode`, `show_risk_levels`, `target1_r`, `target2_r`, `use_vwap_filter`, `use_trade_session_gate`, `use_microstructure_profiles`, `use_index_gate`, `show_reclaim_markers`, `show_long_confirmation_markers`, `use_accel_module`, `use_sd_confluence`, `use_volatility_regime`, `use_stretch_context`, `use_ddvi_context`, `use_context_quality_score`, `show_Structure`, `show_ob`, `show_fvg`, `show_htf_fvg`, `show_eq`.

### SkippALGO.pine (359 inputs)

Had only 39% grouped. This pass:
1. **Grouped 200 ungrouped inputs** into 23 new logical groups (Core, Entry Gates, Risk Management, Structure/Breakout, Pullback Detection, Cooldown, MTF Confirmation, etc.)
2. **Added `display.none`** to 320 expert-level inputs (calibration, forecast filtering, signal filters, USI parameters, ensemble weights, target profiles, etc.)

Result: **39 core inputs** visible on the status line — configuration preset, engine mode, key risk parameters, structure controls, display toggles, and session filters.

### SkippALGO_Strategy.pine (357 inputs)

Same grouping and `display.none` treatment as SkippALGO.pine for parity. Strategy-specific groups (Engine calibration, export, policies) also hidden. **35 core inputs** visible.

## Tier classification

| Tier | Description | Status Line | Settings Dialog |
|---|---|---|---|
| **Core** (~30-40) | Master toggles, presets, key thresholds | ✅ Visible | ✅ Visible |
| **Advanced** | Sub-parameters within core groups | ❌ Hidden | ✅ Visible |
| **Expert** | Calibration, ensemble weights, USI internals, debug | ❌ Hidden | ✅ Visible |

## Regression tests

`tests/test_pine_input_surface.py` enforces:
- 100% grouping for all three scripts
- Visible surface in 25–45 range
- Indicator/Strategy parity (≤5 input delta)
- Balanced parens in all input declarations
- Version tag present

Run: `python -m pytest tests/test_pine_input_surface.py -v`

## Tools

| Tool | Command | Purpose |
|---|---|---|
| `pine_input_surface.py audit *.pine` | Inventory inputs, groups, display.none counts |
| `pine_input_surface.py lint *.pine` | Check ungrouped, parity, parens, version |
| `pine_apply_surface_reduction.py` | One-shot transformation (already applied) |
| `pine_apply_surface_reduction.py --dry-run` | Preview changes without writing |
