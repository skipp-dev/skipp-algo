from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_core_has_decision_first_hero_contract() -> None:
    source = _read("SMC_Core_Engine.pine")

    assert "resolve_core_product_state(" in source
    assert "resolve_trust_tier(" in source
    assert "compose_core_hero_text(" in source
    assert "var label core_hero_card = na" in source
    assert 'Visual Mode (Lite Hero)' in source


def test_dashboard_has_compact_detail_and_pro_diagnostics() -> None:
    source = _read("SMC_Dashboard.pine")

    assert 'surface_mode = input.string("Compact Detail"' in source
    assert "dashboard_product_state_text(" in source
    assert 'dashboard_row(smc_dashboard, 0, "SMC Decision Detail", "Compact | Operator bindings hidden"' in source
    assert 'dashboard_row(smc_dashboard, 0, "SMC Dashboard", "v5.5d Pro Diagnostics | operator companion", header_bg, txt)' in source
    assert 'v5.5d Pro Diagnostics' in source
    assert 'section_row(smc_dashboard, 1, "[ Decision Lifecycle ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 10, "[ Lite Surface Mirrors ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 18, "[ Context Gates ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 26, "[ Quality Detail ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 37, "[ Modules, Pressure & Plan ]", header_bg, txt)' in source
    assert 'section_row(smc_dashboard, 53, "[ Engine Detail ]", header_bg, txt)' in source


def test_skippalgo_has_decision_hud_and_product_alert_action() -> None:
    source = _read("SkippALGO.pine")

    assert 'surfaceMode = input.string("Lite"' in source
    assert 'showDecisionHud = input.bool(true, "Show decision HUD"' in source
    assert 'forecastMode = input.string("Trade Gate", "Forecast mode"' in source
    assert 'riskProfile = input.string("Balanced", "Risk profile"' in source
    assert "resolve_skipp_product_state(" in source
    assert "resolve_skipp_alert_action(" in source
    assert 'var table decisionHud = table.new(position.top_right, 2, 11, border_width = 1)' in source
    assert 'table.cell(decisionHud, 0, 0, "SkippALGO Decision HUD"' in source
    assert 'f_hud_row(decisionHud, 2, "Trade Threshold", hudThreshold' in source
    assert 'f_hud_row(decisionHud, 6, "Main Risk", hudMainRisk' in source
    assert 'alertcondition(alertReadyLongCond, title="SMC READY LONG"' in source
    assert 'alertcondition(alertEnterLongCond, title="SMC ENTER LONG"' in source
    assert 'msg := "SkippALGO | action=" + actionText + " | why=" + hudWhyNow + " | risk=" + hudMainRisk + " | legacy=" + labels' in source


def test_r11_migration_and_operator_guide_is_linked_and_explicit() -> None:
    readme = _read("README.md")
    guide = _read("docs/smc-tradingview-r1-1-migration-and-operator-guide.md")

    assert "docs/smc-tradingview-r1-1-migration-and-operator-guide.md" in readme
    assert "compact_mode" in guide
    assert "surface_mode" in guide
    assert "surfaceMode" in guide
    assert "operator-only" in guide
    assert "BUS binding order" in guide
    assert "visual-only" in guide
