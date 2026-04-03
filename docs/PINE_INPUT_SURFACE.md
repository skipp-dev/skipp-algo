# Pine Input Surface Reduction

Reduces the visible input surface of major Pine scripts from **~4,000 raw inputs** to **~35-45 core controls** per script, improving onboarding and chart readability while preserving all engine behaviour.

## Summary

| Script | Inputs | Grouped | display.none | **Visible** | Groups |
|---|---:|---:|---:|---:|---:|
| SMC_Core_Engine.pine | 249 | 249 (100%) | 206 | **43** | 23 |
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

### SMC_Core_Engine.pine (249 inputs)

The active split-core producer now follows the same surface-governance policy as the other large Pine scripts: **100% grouped**, **43 visible operator controls**, and all lifecycle, module-tuning, debug, color, and visual-calibration parameters moved behind `display.none`.

The operator-facing anchors of that surface are `long_user_preset` plus `compact_mode`. Future surface work should collapse behavior into those two controls before adding new visible toggles.

Core visible: `signal_mode`, `long_user_preset`, `compact_mode`, `enable_ltf_sampling`, `use_ltf_for_strict_entry`, `ltf_timeframe`, `mtf_trend_tf1-3`, `show_dashboard`, `enable_dynamic_alerts`, `dynamic_long_alert_mode`, `performance_mode`, `stop_buffer_atr_mult`, `target1_r`, `target2_r`, `use_vwap_filter`, `use_trade_session_gate`, `use_opening_range_gate`, `opening_range_minutes`, `use_microstructure_profiles`, `use_index_gate`, `long_signal_window`, `long_setup_expiry_bars`, `long_confirm_expiry_bars`, `max_bars_arm_to_confirm`, `max_bars_confirm_to_ready`, `max_zone_touches_for_entry`, `use_overhead_zone_filter`, `use_strict_sequence`, `use_strict_sweep_for_zone_reclaim`, `use_strict_confirm_guard`, `use_lean_signal_quality_gate`, `use_accel_module`, `use_sd_confluence`, `use_volatility_regime`, `use_stretch_context`, `use_ddvi_context`, `show_Structure`, `show_ob`, `show_fvg`, `show_htf_fvg`, `fvg_htf`.

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
- 100% grouping for the active core plus the three existing Pine scripts
- Visible surface in the configured per-script ranges, including 35–45 for `SMC_Core_Engine.pine`
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
