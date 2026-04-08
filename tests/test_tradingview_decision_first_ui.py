from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_core_has_decision_first_hero_contract() -> None:
    source = _read("SMC_Core_Engine.pine")

    assert 'indicator("SMC Core", "SMC Core", overlay = true' in source
    assert "var g_mode = '1. Core Setup'" in source
    assert "var g_output = '2. Output'" in source
    assert "var g_trade_plan = '3. Trade Plan'" in source
    assert "var g_session_gate = '4. Session Gate'" in source
    assert "var g_runtime = '5. Runtime Budget'" in source
    assert "var g_ltf = '6. Advanced - Lower Timeframe'" in source
    assert "resolve_core_product_state(" in source
    assert "resolve_trust_tier(" in source
    assert "compose_core_hero_text(" in source
    assert "var label core_hero_card = na" in source
    assert "compact_mode = input.bool(true, 'Focus View'" in source
    assert "show_dashboard = input.bool(true, 'Show Decision Brief', group = g_output" in source
    assert "enable_dynamic_alerts = input.bool(true, 'Enable dynamic alerts', group = g_output)" in source
    assert "target1_r = input.float(1.0, 'Target 1 (R)', minval = 0.25, step = 0.25, group = g_trade_plan)" in source
    assert "use_trade_session_gate = input.bool(true, 'Use Trade Session Gate', group = g_session_gate, inline = 'trade1')" in source
    assert "performance_mode = input.string('Balanced', 'Performance Mode', options = ['Light', 'Balanced', 'Pro', 'Debug'], group = g_runtime" in source
    assert 'Focus View' in source
    assert 'Confidence: ' in source
    assert "plot(core_plan_visible ? long_state.trigger : na, 'Core Trigger'" in source
    assert "plot(core_plan_visible ? long_state.invalidation_level : na, 'Core Invalidation'" in source


def test_dashboard_has_companion_summary_and_pro_diagnostics() -> None:
    source = _read("SMC_Dashboard.pine")

    assert 'var string g_surface = "1. Product Surface"' in source
    assert 'var string g_bus_lifecycle = "2. Operator Only - Lifecycle BUS"' in source
    assert 'var string g_local_debug = "8. Operator Only - Local Debug Mirrors"' in source
    assert 'surface_mode = input.string("Decision Brief"' in source
    assert source.index('surface_mode = input.string("Decision Brief"') < source.index('src_zone_active = input.source(close, "BUS ZoneActive"')
    assert "dashboard_product_state_text(" in source
    assert 'dashboard_row(smc_dashboard, 0, "SMC Decision Board", "Decision Brief | Linked setup active"' in source
    assert 'dashboard_row(smc_dashboard, 0, "SMC Decision Board", "Audit View | Expert review only", header_bg, txt)' in source
    assert 'dashboard_row(smc_dashboard, 1, "Structure"' in source
    assert 'dashboard_row(smc_dashboard, 2, "Session / Market"' in source
    assert 'dashboard_row(smc_dashboard, 3, "Event Risk"' in source
    assert 'dashboard_row(smc_dashboard, 4, "Data Quality"' in source
    assert 'dashboard_row(smc_dashboard, 5, "Short-term Pressure"' in source
    assert 'dashboard_row(smc_dashboard, 6, "Risk Plan"' in source
    assert 'dashboard_row(smc_dashboard, 1, "Action"' not in source
    assert 'dashboard_row(smc_dashboard, 2, "Why now"' not in source
    assert 'Audit View | Expert review only' in source
    assert 'dashboard_row(smc_dashboard, 2, "Action"' in source
    assert 'dashboard_row(smc_dashboard, 3, "Why now"' in source
    assert 'section_row(smc_dashboard, 1, "[ Decision Detail ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 10, "[ Lean Surface ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 18, "[ Gates ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 26, "[ Quality Rows ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 37, "[ Support / Metrics ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 48, "[ Risk / Plan ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 53, "[ Debug ]", header_bg, txt)' in source


def test_long_strategy_has_wrapper_controls_and_core_plan_outputs() -> None:
    source = _read("SMC_Long_Strategy.pine")

    assert 'strategy("SMC Execution", overlay = true' in source
    assert 'var string g_setup = "1. Execution Setup"' in source
    assert 'var string g_bus_entry = "3. Expert Mapping - Entry States"' in source
    assert source.index('entry_mode = input.string("Strict", "Entry Stage"') < source.index('src_armed = input.source(close, "BUS Armed"')
    assert source.index('use_take_profit = input.bool(true, "Enable Profit Target"') < source.index('src_trigger = input.source(close, "BUS Trigger"')
    assert 'src_armed = input.source(close, "BUS Armed"' in source
    assert 'src_entry_strict = input.source(close, "BUS EntryStrict"' in source
    assert 'src_trigger = input.source(close, "BUS Trigger"' in source
    assert 'src_invalidation = input.source(close, "BUS Invalidation"' in source
    assert 'entry_mode = input.string("Strict", "Entry Stage", options = ["Armed", "Confirmed", "Ready", "Best", "Strict"], group = g_setup' in source
    assert 'min_quality_score = input.float(0.0, "Minimum Setup Quality", step = 0.25, group = g_setup' in source
    assert 'use_take_profit = input.bool(true, "Enable Profit Target", group = g_trade_plan' in source
    assert 'take_profit_r = input.float(2.0, "Profit Target (R)", minval = 0.0, step = 0.25, group = g_trade_plan' in source
    assert 'plot(src_trigger, "Entry Price"' in source
    assert 'plot(src_invalidation, "Stop Loss"' in source
    assert 'plot(use_take_profit ? (strategy.position_size > 0 ? active_take_profit : take_profit_price) : na, "Profit Target"' in source


def test_r11_migration_and_operator_guide_is_linked_and_explicit() -> None:
    readme = _read("README.md")
    guide = _read("docs/smc-tradingview-r1-1-migration-and-operator-guide.md")

    assert "docs/smc-tradingview-r1-1-migration-and-operator-guide.md" in readme
    assert "compact_mode" in guide
    assert "surface_mode" in guide
    assert "entry_mode" in guide
    assert "SMC_Long_Strategy.pine" in guide
    assert "operator-only" in guide
    assert "BUS binding order" in guide
    assert "visual-only" in guide
    assert "Decision Brief" in guide
    assert "Entry Stage" in guide
