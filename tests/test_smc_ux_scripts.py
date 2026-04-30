"""Structural tests for the Confluence Hub, Setup Check, and Mobile Dashboard Pine scripts.

These verify that the new UX scripts follow the BUS consumer contract
and don't accidentally become producers or duplicate Core Engine logic.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent

CONFLUENCE_PATH = ROOT / "SkippALGO_Confluence.pine"
SETUP_CHECK_PATH = ROOT / "SMC_Setup_Check.pine"
MOBILE_PATH = ROOT / "SMC_Mobile_Dashboard.pine"
DASHBOARD_PATH = ROOT / "SMC_Dashboard.pine"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Setup Check ──────────────────────────────────────────────

def test_setup_check_is_indicator() -> None:
    source = _read(SETUP_CHECK_PATH)
    assert 'indicator("SMC Setup Check v1"' in source
    assert "strategy(" not in source


def test_setup_check_consumes_bus_schema() -> None:
    source = _read(SETUP_CHECK_PATH)
    assert 'input.source(close, "BUS SchemaVersion"' in source
    assert "7001" in source


def test_setup_check_has_6_bus_bindings() -> None:
    source = _read(SETUP_CHECK_PATH)
    count = source.count("input.source(")
    assert count == 6


def test_setup_check_has_no_own_plots() -> None:
    """Setup Check should not produce any visible or hidden plots."""
    source = _read(SETUP_CHECK_PATH)
    # Only table output, no plot() calls
    plot_calls = re.findall(r"^plot\(", source, re.MULTILINE)
    assert len(plot_calls) == 0


def test_setup_check_is_a_pure_consumer() -> None:
    source = _read(SETUP_CHECK_PATH)
    assert "detect_structure" not in source
    assert "track_obs" not in source
    assert "OrderBlock" not in source
    assert "request.security" not in source


# ── Confluence Hub ───────────────────────────────────────────

def test_confluence_is_indicator() -> None:
    source = _read(CONFLUENCE_PATH)
    assert 'indicator("SkippALGO Confluence Hub v1"' in source
    assert "strategy(" not in source


def test_confluence_consumes_bus_schema() -> None:
    source = _read(CONFLUENCE_PATH)
    assert 'input.source(close, "BUS SchemaVersion"' in source
    assert "7001" in source


def test_confluence_has_6_bus_bindings() -> None:
    source = _read(CONFLUENCE_PATH)
    count = source.count("input.source(")
    assert count == 6


def test_confluence_exports_hidden_score() -> None:
    source = _read(CONFLUENCE_PATH)
    assert "plot(confluence, \"Confluence Score\", display = display.none)" in source


def test_confluence_has_alert_conditions() -> None:
    source = _read(CONFLUENCE_PATH)
    alerts = re.findall(r"alertcondition\(", source)
    assert len(alerts) == 2


def test_confluence_imports_library() -> None:
    source = _read(CONFLUENCE_PATH)
    assert "import preuss_steffen/smc_micro_profiles_generated/1 as mp" in source


def test_confluence_is_a_pure_consumer() -> None:
    """Confluence reads BUS + computes its own indicators — no SMC engine logic."""
    source = _read(CONFLUENCE_PATH)
    assert "detect_structure" not in source
    assert "track_obs" not in source
    assert "OrderBlock" not in source
    assert "request.security" not in source


def test_confluence_score_range() -> None:
    """Score is clamped to 0–100 via math.max/math.min."""
    source = _read(CONFLUENCE_PATH)
    assert "math.max(0.0, math.min(100.0, raw_score))" in source


# ── Mobile Dashboard ────────────────────────────────────────

def test_mobile_is_indicator() -> None:
    source = _read(MOBILE_PATH)
    assert 'indicator("SMC Mobile v7"' in source
    assert "strategy(" not in source


def test_mobile_consumes_bus_schema() -> None:
    source = _read(MOBILE_PATH)
    assert 'input.source(close, "BUS SchemaVersion"' in source
    assert "7001" in source


def test_mobile_has_8_bus_bindings() -> None:
    source = _read(MOBILE_PATH)
    count = source.count("input.source(")
    # 6 baseline bindings + 2 Trade-Mgmt rows (Trade / Stop) added in the
    # mobile-mirror of the desktop dashboard's Trade-Mgmt drill-down
    # (system review 2026-04-24, mirrors var_budget Hold +2 ledger bump).
    assert count == 8


def test_mobile_has_no_overlays() -> None:
    """Mobile Dashboard should have zero plot/line/box/label calls — table only."""
    source = _read(MOBILE_PATH)
    assert re.findall(r"^plot\(", source, re.MULTILINE) == []
    assert "line.new(" not in source
    assert "box.new(" not in source
    assert "label.new(" not in source


def test_mobile_is_a_pure_consumer() -> None:
    source = _read(MOBILE_PATH)
    assert "detect_structure" not in source
    assert "track_obs" not in source
    assert "OrderBlock" not in source
    assert "request.security" not in source


def test_mobile_imports_library() -> None:
    source = _read(MOBILE_PATH)
    assert "import preuss_steffen/smc_micro_profiles_generated/1 as mp" in source


# ── Dashboard Explain Mode ──────────────────────────────────

def test_dashboard_has_explain_mode() -> None:
    source = _read(DASHBOARD_PATH)
    assert '"Explain"' in source
    assert 'surface_mode == "Explain"' in source


def test_dashboard_explain_mode_has_checklist() -> None:
    """Explain mode should contain at least 9 ✅/❌ checklist rows."""
    source = _read(DASHBOARD_PATH)
    # Find the Explain section
    explain_start = source.index('surface_mode == "Explain"')
    explain_end = source.index("else if compact_dashboard")
    explain_section = source[explain_start:explain_end]
    check_marks = explain_section.count("✅") + explain_section.count("❌")
    assert check_marks >= 18  # 9 criteria × 2 (pass + fail labels)
