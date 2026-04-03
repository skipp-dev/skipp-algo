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
    core_body = _extract_function_body(_read(CORE_PATH), "resolve_long_ready_reason_code")
    dashboard_body = _extract_function_body(_read(DASHBOARD_PATH), "decode_ready_gate_text")

    for snippet in [
        "resolve_long_ready_lifecycle_reason_code",
        "resolve_long_ready_gate_reason_code",
        "reason_code := 9",
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
    core_body = _extract_function_body(_read(CORE_PATH), "resolve_long_strict_reason_code")
    dashboard_body = _extract_function_body(_read(DASHBOARD_PATH), "decode_strict_gate_text")

    for reason_code in range(2, 11):
        assert f"reason_code := {reason_code}" in core_body

    for label in [
        "Need Ready",
        "Signal Quality blocked",
        "LTF blocked",
        "HTF blocked",
        "Accel blocked",
        "SD blocked",
        "Vol blocked",
        "Stretch blocked",
        "DDVI blocked",
    ]:
        assert f'label_text := "{label}"' in dashboard_body


def test_arm_lifecycle_contract_stays_explicit() -> None:
    source_body = _extract_function_body(_read(CORE_PATH), "resolve_long_arm_source_state")
    trigger_body = _extract_function_body(_read(CORE_PATH), "compute_long_arm_should_trigger")
    payload_body = _extract_function_body(_read(CORE_PATH), "resolve_long_arm_transition_payload")

    for snippet in [
        "if bull_reclaim_ob_strict",
        "else if bull_reclaim_fvg_strict",
        "else if bull_reclaim_swing_low_strict",
        "else if bull_reclaim_internal_low_strict",
        "if helper_arm_source_kind == LONG_SOURCE_SWING_LOW or helper_arm_source_kind == LONG_SOURCE_INTERNAL_LOW",
        "if in_bull_ob_zone and in_bull_fvg_zone",
        "if ob_more_recent",
    ]:
        assert snippet in source_body

    for snippet in [
        "bool helper_zone_recent_ok = zone_recent",
        "if use_strict_sequence_eff",
        "helper_zone_recent_ok := zone_touch_event_recent",
        "if bull_reclaim_any_for_arm and helper_zone_recent_ok and not long_setup_armed and not long_invalidated_this_bar and micro_session_gate_ok and sd_armed_gate_ok and armed_prequality_ok",
    ]:
        assert snippet in trigger_body

    for snippet in [
        "select_long_arm_backing_zone_touch_count",
        "resolve_long_zone_id",
        "resolve_long_zone_top",
        "resolve_long_zone_bottom",
    ]:
        assert snippet in payload_body


def test_confirm_lifecycle_contract_stays_explicit() -> None:
    break_body = _extract_function_body(_read(CORE_PATH), "resolve_long_confirm_break_state")
    structure_body = _extract_function_body(_read(CORE_PATH), "resolve_long_confirm_structure_state")
    transition_body = _extract_function_body(_read(CORE_PATH), "compute_long_confirm_transition_state")

    for snippet in [
        "if live_exec and effective_use_live_confirm_break",
        "helper_long_confirm_break_src := high_price",
        "if long_setup_armed and not long_setup_confirmed and not na(long_arm_bar_index) and current_bar_index > long_arm_bar_index",
    ]:
        assert snippet in break_body

    for snippet in [
        "if long_setup_armed and not na(long_arm_bar_index) and not na(internal_choch_since_bars)",
        "if long_setup_armed and not na(long_arm_bar_index) and not na(internal_bos_since_bars)",
        "if long_internal_structure_mode == 'Internal CHoCH only'",
        "if not helper_long_confirm_structure_ok",
        "helper_long_confirm_structure_ok := helper_long_internal_structure_ok",
    ]:
        assert snippet in structure_body

    for snippet in [
        "if micro_session_gate_ok and micro_freshness_gate_ok",
        "if accel_confirm_gate_ok and sd_confirmed_gate_ok",
        "if close_safe_mode and long_confirm_break and long_confirm_structure_ok and confirm_is_fresh and long_confirm_bearish_guard_ok",
        "bool helper_long_should_confirm = helper_confirm_lifecycle_ok and helper_confirm_filters_ok",
    ]:
        assert snippet in transition_body


def test_plan_lifecycle_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "compute_long_plan_state")

    assert "if (long_setup_armed or long_setup_confirmed) and not na(long_trigger) and not na(long_invalidation_level)" in body


def test_overhead_context_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "compute_long_overhead_context")

    for snippet in [
        "if long_plan_active",
        "helper_planned_stop_level := long_invalidation_level - ob_threshold_atr * stop_buffer_atr_mult",
        "float helper_scan_ref = close_price",
        "if long_plan_active and not na(long_trigger)",
        "helper_scan_ref := long_trigger",
        "if array.size(ob_blocks_bear_param) > 0",
        "resolve_ob_alert_level",
        "if array.size(fvgs_bear_param) > 0",
        "resolve_fvg_alert_level",
        "if use_overhead_zone_filter and not na(helper_headroom_to_overhead) and not na(helper_planned_risk)",
        "helper_overhead_zone_ok := helper_headroom_to_overhead >= helper_planned_risk * min_headroom_r",
    ]:
        assert snippet in body


def test_risk_plan_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "compute_long_risk_plan_state")

    for snippet in [
        "if long_plan_active and not na(long_planned_stop_level) and not na(planned_risk)",
        "helper_long_stop_level := long_planned_stop_level",
        "helper_long_risk_r := planned_risk",
        "helper_long_target_1 := long_trigger + helper_long_risk_r * target1_r",
        "helper_long_target_2 := long_trigger + helper_long_risk_r * target2_r",
    ]:
        assert snippet in body


def test_ready_projection_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "resolve_long_ready_projection_state")

    for snippet in [
        "if long_setup_armed and long_internal_structure_ok and not long_setup_confirmed",
        "if not na(long_confirm_bar_index)",
        "helper_ready_bar_gap_ok := current_bar_index > long_confirm_bar_index",
        "if use_scoring_over_blocking",
        "helper_scoring_accel_ready := true",
        "helper_scoring_sd_ready := true",
        "helper_scoring_vol_ready := true",
        "helper_scoring_stretch_ready := true",
        "helper_scoring_ddvi_ready := true",
        "compute_long_ready_state",
    ]:
        assert snippet in body


def test_entry_projection_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "resolve_long_entry_projection_state")

    for snippet in [
        "compute_long_entry_best_state",
        "compute_long_entry_strict_state",
    ]:
        assert snippet in body


def test_execution_blocker_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "resolve_long_execution_blocker_state")

    for snippet in [
        "resolve_long_ready_blocker_text",
        "resolve_long_strict_blocker_text",
    ]:
        assert snippet in body


def test_bus_plan_levels_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "resolve_long_bus_plan_levels")

    for snippet in [
        "float helper_bus_trigger_level = na",
        "float helper_bus_invalidation_level = na",
        "float helper_bus_stop_level = na",
        "if long_plan_active",
        "helper_bus_trigger_level := long_trigger",
        "helper_bus_invalidation_level := long_invalidation_level",
        "helper_bus_stop_level := long_stop_level",
        "helper_bus_target_1 := long_target_1",
        "helper_bus_target_2 := long_target_2",
    ]:
        assert snippet in body


def test_bus_trigger_and_risk_rows_stay_execution_owned() -> None:
    trigger_body = _extract_function_body(_read(CORE_PATH), "resolve_bus_long_triggers_row")
    risk_body = _extract_function_body(_read(CORE_PATH), "resolve_bus_risk_plan_row")

    for snippet in [
        "else if na(bus_trigger_level) or na(bus_invalidation_level)",
        "else if long_entry_strict_state",
        "else if long_entry_best_state",
        "else if long_ready_state",
        "else if long_setup_confirmed",
    ]:
        assert snippet in trigger_body

    for snippet in [
        "else if na(bus_trigger_level) or na(bus_invalidation_level)",
        "else if not na(bus_stop_level) and not na(bus_target_1) and not na(bus_target_2)",
    ]:
        assert snippet in risk_body


def test_bus_surface_stays_runtime_owned() -> None:
    source = _read(CORE_PATH)

    assert "plot(long_visual_state, 'BUS StateCode', display = display.none)" in source
    assert "plot(long_validation_source, 'BUS SourceKind', display = display.none)" in source
    assert "plot(lib_sq_score, 'BUS QualityScore', display = display.none)" in source
    assert "resolve_bus_long_triggers_row(long_plan_active, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, bus_trigger_level, bus_invalidation_level)" in source
    assert "resolve_bus_risk_plan_row(long_plan_active, bus_trigger_level, bus_invalidation_level, bus_stop_level, bus_target_1, bus_target_2)" in source
    assert "resolve_bus_ready_gate_row(long_ready_state" in source
    assert "resolve_bus_strict_gate_row(long_entry_strict_state, long_ready_state, strict_signal_quality_gate_ok" in source
    assert "plot(bus_trigger_level, 'BUS Trigger', display = display.none)" in source
    assert "plot(bus_stop_level, 'BUS StopLevel', display = display.none)" in source


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


def test_ready_signal_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "resolve_long_ready_signal_state")

    for snippet in [
        "if current_bar_is_new",
        "helper_ready_state_rt_prev := 0",
        "if prior_bar_ready_state",
        "helper_ready_fired_this_bar := false",
        "if long_ready_state and helper_ready_state_rt_prev == 0 and not helper_ready_fired_this_bar",
        "if helper_long_ready_signal",
        "helper_ready_state_rt_prev := 1",
    ]:
        assert snippet in body


def test_debug_log_owner_contract_stays_explicit() -> None:
    body = _extract_function_body(_read(CORE_PATH), "emit_long_engine_debug_logs")

    for snippet in [
        "resolve_long_debug_event_values",
        "compose_long_debug_summary_text",
        "if show_long_engine_debug_eff and long_source_upgrade_now",
        "if show_long_engine_debug_eff and long_arm_signal",
        "if show_long_engine_debug_eff and long_confirm_signal",
        "if show_long_engine_debug_eff and long_ready_signal",
        "if show_long_engine_debug_eff and long_invalidate_signal",
        "compose_long_engine_event_log",
    ]:
        assert snippet in body