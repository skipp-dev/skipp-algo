from __future__ import annotations

import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / "SMC_Core_Engine.pine"
DASHBOARD_PATH = ROOT / "SMC_Dashboard.pine"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_function_body(source: str, function_name: str) -> str:
    start = source.find(f"{function_name}(")
    assert start != -1, f"{function_name} not found"
    body_start = source.index("\n", start) + 1
    lines: list[str] = []
    for line in source[body_start:].splitlines():
        if line.strip() == "" or line.startswith("    "):
            lines.append(line)
        else:
            break
    return "\n".join(lines)


def test_long_state_code_contract_preserves_lifecycle_precedence() -> None:
    body = _extract_function_body(_read(CORE_PATH), "resolve_long_state_code")
    expected_order = [
        "if invalid_state\n        -1",
        "else if long_entry_strict_state\n        7",
        "else if long_entry_best_state\n        6",
        "else if long_ready_state\n        5",
        "else if long_setup_confirmed\n        4",
        "else if long_building_state\n        3",
        "else if long_setup_armed\n        2",
        "else if long_zone_active\n        1",
        "else\n        0",
    ]
    positions = [body.index(snippet) for snippet in expected_order]
    assert positions == sorted(positions)


def test_state_label_and_dashboard_decoders_stay_aligned() -> None:
    core_source = _read(CORE_PATH)
    dashboard_source = _read(DASHBOARD_PATH)
    engine_setup = _extract_function_body(core_source, "resolve_long_setup_state_label")
    engine_visual = _extract_function_body(core_source, "resolve_long_visual_state_label")
    dashboard_setup = _extract_function_body(dashboard_source, "setup_text")
    dashboard_visual = _extract_function_body(dashboard_source, "long_visual_text")

    for label in ["Invalidated", "In Zone", "Armed", "Building", "Confirmed", "Ready", "Entry Best", "Entry Strict"]:
        assert label in engine_setup
        assert label in dashboard_setup

    for label in ["Fail", "Neutral", "In Zone", "Armed", "Building", "Confirmed", "Ready"]:
        assert label in engine_visual
        assert label in dashboard_visual


def test_ready_gate_reason_contract_matches_dashboard_decoder() -> None:
    core_body = _extract_function_body(_read(CORE_PATH), "resolve_bus_ready_gate_row")
    dashboard_body = _extract_function_body(_read(DASHBOARD_PATH), "decode_ready_gate_text")

    for snippet in [
        "reason_code := 2",
        "reason_code := 3",
        "reason_code := 4",
        "reason_code := long_confirm_expired ? 5 : 6",
        "reason_code := 7",
        "reason_code := 8",
        "reason_code := 9",
        "reason_code := 10",
        "reason_code := 11",
        "reason_code := 12",
        "reason_code := 13",
        "reason_code := 14",
        "reason_code := 15",
        "reason_code := 16",
        "reason_code := 17",
        "reason_code := 18",
        "reason_code := 19",
        "reason_code := 20",
        "reason_code := 21",
        "reason_code := 22",
        "reason_code := 23",
        "reason_code := 24",
    ]:
        assert snippet in core_body

    for label in [
        "Need confirmed setup",
        "Use close-safe mode",
        "Wait one bar",
        "Confirm expired",
        "Setup stale",
        "Bearish guard",
        "Need main BOS",
        "Lifecycle not ready",
        "Setup hard gate",
        "Session blocked",
        "Micro session blocked",
        "Micro fresh blocked",
        "Overhead blocked",
        "Trade hard gate",
        "Market gate",
        "Vola gate",
        "Environment gate",
        "Quality gate",
        "Accel gate",
        "SD gate",
        "Vol gate",
        "Stretch gate",
        "DDVI gate",
    ]:
        assert f'label_text := "{label}"' in dashboard_body


def test_strict_gate_reason_contract_matches_dashboard_decoder() -> None:
    core_body = _extract_function_body(_read(CORE_PATH), "resolve_bus_strict_gate_row")
    dashboard_body = _extract_function_body(_read(DASHBOARD_PATH), "decode_strict_gate_text")

    for reason_code in range(2, 10):
        assert f"reason_code := {reason_code}" in core_body

    for label in [
        "Need Ready",
        "LTF blocked",
        "HTF blocked",
        "Accel blocked",
        "SD blocked",
        "Vol blocked",
        "Stretch blocked",
        "DDVI blocked",
    ]:
        assert f'label_text := "{label}"' in dashboard_body


def test_bus_surface_stays_runtime_owned() -> None:
    source = _read(CORE_PATH)

    assert "plot(long_visual_state, 'BUS StateCode', display = display.none)" in source
    assert "plot(long_validation_source, 'BUS SourceKind', display = display.none)" in source
    assert "plot(lib_sq_score, 'BUS QualityScore', display = display.none)" in source
    assert "resolve_bus_long_triggers_row(long_plan_active)" in source
    assert "resolve_bus_risk_plan_row(long_plan_active)" in source
    assert "resolve_bus_ready_gate_row(long_ready_state" in source
    assert "resolve_bus_strict_gate_row(long_entry_strict_state, long_ready_state" in source


def test_dynamic_alert_gate_contract_stays_explicit_per_lifecycle_edge() -> None:
    body = _extract_function_body(_read(CORE_PATH), "compute_long_dynamic_alert_gates")

    for clause in [
        "if enable_dynamic_alerts and long_invalidate_signal",
        "if enable_dynamic_alerts and alert_long_entry_strict_event",
        "if enable_dynamic_alerts and alert_long_entry_best_event",
        "if enable_dynamic_alerts and long_ready_signal",
        "if enable_dynamic_alerts and long_confirm_signal",
        "if enable_dynamic_alerts and alert_long_clean_event",
        "if enable_dynamic_alerts and alert_long_early_event",
        "if enable_dynamic_alerts and alert_long_armed_event",
        "if enable_dynamic_alerts and long_arm_signal",
        "if enable_dynamic_alerts and alert_long_watchlist_event",
    ]:
        assert clause in body