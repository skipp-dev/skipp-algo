from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / 'SMC_Core_Engine.pine'
EXPECTED_BUS_LABELS = [
    'BUS ZoneActive',
    'BUS Armed',
    'BUS Confirmed',
    'BUS Ready',
    'BUS EntryBest',
    'BUS EntryStrict',
    'BUS Trigger',
    'BUS Invalidation',
    'BUS QualityScore',
    'BUS SourceKind',
    'BUS StateCode',
    'BUS TrendPack',
    'BUS MetaPack',
    'BUS HardGatesPackA',
    'BUS HardGatesPackB',
    'BUS EventRiskRow',
    'BUS QualityPackA',
    'BUS QualityPackB',
    'BUS QualityBoundsPack',
    'BUS ModulePackA',
    'BUS ModulePackB',
    'BUS ModulePackC',
    'BUS ModulePackD',
    'BUS EnginePack',
    'BUS StopLevel',
    'BUS Target1',
    'BUS Target2',
    'BUS LeanPackA',
    'BUS LeanPackB',
]


def _read_core_source() -> str:
    return CORE_PATH.read_text(encoding = 'utf-8')


def _nonempty_lines_before(lines: list[str], index: int, count: int = 3) -> list[str]:
    previous: list[str] = []
    cursor = index - 1
    while cursor >= 0 and len(previous) < count:
        if lines[cursor].strip():
            previous.append(lines[cursor])
        cursor -= 1
    return previous


def test_core_engine_file_exists_and_uses_core_header() -> None:
    assert CORE_PATH.exists(), 'SMC_Core_Engine.pine must exist'
    source = _read_core_source()

    assert 'indicator("SMC Core Engine", "SMC Core", overlay = true' in source
    assert 'indicator("Smart Money Concepts (Highly Advanced)", "SMC++", overlay = true' not in source


def test_core_engine_header_restores_import_prelude_and_blocks_stray_method_body() -> None:
    source = _read_core_source()
    lines = source.splitlines()
    indicator_index = next(i for i, line in enumerate(lines) if line.startswith('indicator("SMC Core Engine", "SMC Core"'))
    following_nonempty = [line for line in lines[indicator_index + 1:] if line.strip()][:6]

    assert following_nonempty[:3] == [
        'import preuss_steffen/smc_core_types/1 as ct',
        'import preuss_steffen/smc_utils/1 as u',
        'import preuss_steffen/smc_draw/1 as d',
    ]
    assert not following_nonempty[0].startswith((' ', '\t'))
    assert 'method hide(Profile this) =>' in source
    assert 'indicator("SMC Core Engine", "SMC Core", overlay = true, max_bars_back = 500, max_lines_count = 300, max_boxes_count = 300, max_labels_count = 300)\n            for bucket in this.buckets' not in source


def test_core_engine_breadth_gate_uses_optional_text_input_and_guarded_request() -> None:
    source = _read_core_source()

    assert "var string breadth_gate_symbol = input.string('', 'Breadth'" in source
    assert "input.symbol('INDEX:ADD', 'Breadth'" not in source
    assert 'string breadth_gate_symbol_effective = str.trim(breadth_gate_symbol)' in source
    assert 'if use_breadth_symbol_gate' in source
    assert '[breadth_missing_calc_value, breadth_gate_ok_calc_value] = u.external_breadth_gate(breadth_gate_symbol_effective, breadth_gate_mode, breadth_gate_len)' in source
    assert 'breadth_missing_calc := breadth_missing_calc_value' in source
    assert 'breadth_gate_ok_calc := breadth_gate_ok_calc_value' in source
    assert 'else\n        breadth_missing_calc := true\n        breadth_gate_ok_calc := false' in source


def test_core_engine_uses_effective_microstructure_aliases_for_generated_library_handoff() -> None:
    source = _read_core_source()

    assert 'import preuss_steffen/smc_micro_profiles_generated/1 as mp' in source
    assert 'input.string(\'\', \'Clean reclaim tickers\'' not in source
    assert 'string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS' in source
    assert 'string stop_hunt_tickers_effective = mp.STOP_HUNT_PRONE_TICKERS' in source
    assert 'string weak_afterhours_tickers_effective = mp.WEAK_AFTERHOURS_TICKERS' in source
    assert 'u.csv_has_symbol_token(clean_reclaim_tickers_effective, current_symbol_key, current_symbol_key_qualified)' in source
    assert 'u.csv_has_symbol_token(stop_hunt_tickers_effective, current_symbol_key, current_symbol_key_qualified)' in source
    assert 'u.csv_has_symbol_token(fast_decay_tickers_effective, current_symbol_key, current_symbol_key_qualified)' in source
    assert 'u.csv_has_symbol_token(clean_reclaim_tickers, current_symbol_key, current_symbol_key_qualified)' not in source



def test_core_engine_any_overlaps_guards_empty_arrays_before_reverse_iteration() -> None:
    source = _read_core_source()

    assert 'method any_overlaps(OrderBlock[] this, float range_top, float range_btm) =>' in source
    assert 'if not na(this) and this.size() > 0' in source
    assert 'for i = this.size() - 1 to 0' in source
    assert 'if not na(this)\n        for i = this.size() - 1 to 0' not in source


def test_core_engine_reverse_loops_are_guarded_before_size_minus_one_iteration() -> None:
    lines = _read_core_source().splitlines()
    reverse_loop_pattern = re.compile(r'for i = ([A-Za-z_][A-Za-z0-9_]*)\.size\(\) - 1 to ')

    for index, line in enumerate(lines):
        match = reverse_loop_pattern.search(line)
        if not match:
            continue

        array_name = match.group(1)
        context = '\n'.join(_nonempty_lines_before(lines, index, count = 3))
        assert (
            f'{array_name}.size() > 0' in context
            or f'not na({array_name}) and {array_name}.size() > 0' in context
            or f'na({array_name}) ? false :' in context and f'{array_name}.size() > 0' in context
        ), f'Reverse loop for {array_name} must be preceded by a non-empty array guard'


def test_core_engine_last_element_array_gets_are_guarded() -> None:
    lines = _read_core_source().splitlines()
    last_get_pattern = re.compile(r'array\.get\(([A-Za-z_][A-Za-z0-9_]*), array\.size\(\1\) - 1\)')

    for index, line in enumerate(lines):
        match = last_get_pattern.search(line)
        if not match:
            continue

        array_name = match.group(1)
        context = '\n'.join(_nonempty_lines_before(lines, index, count = 5))
        assert (
            f'if array.size({array_name}) > 0' in context
            or f'array.size({array_name}) > 0' in context
            or f'= array.size({array_name}) > 0' in context
        ), f'Last-element array.get for {array_name} must be guarded by an array.size() check'


def test_core_engine_exports_exact_hidden_bus() -> None:
    source = _read_core_source()

    hidden_bus_calls = re.findall(r"plot\([^\n]+display\s*=\s*display\.none\)", source)
    assert len(hidden_bus_calls) == len(EXPECTED_BUS_LABELS)

    for label in EXPECTED_BUS_LABELS:
        assert f"'{label}'" in source

    assert 'pack_bus_row(' in source
    assert 'pack_bus_four(' in source
    assert 'pack_bus_trend_set(' in source


def test_core_engine_uses_signal_quality_as_primary_gate() -> None:
    source = _read_core_source()

    assert "var bool use_lean_signal_quality_gate = input.bool(true, 'Use Signal Quality Gate'" in source
    assert "var bool use_lean_signal_quality_gate = input.bool(false, 'Use Signal Quality Gate'" not in source
    assert '[context_quality_score, context_quality_gate_ok, htf_alignment_ok, strict_entry_ltf_ok, effective_min_context_quality_score, effective_context_quality_max_score] = compute_context_quality()' in source
    assert '// [v5.5b] Signal Quality is the primary quality surface; local context quality stays diagnostic only.' in source
    assert 'bool primary_quality_gate_ok = not use_lean_signal_quality_gate or signal_quality_ok' in source
    assert 'bool best_signal_quality_gate_ok = not use_lean_signal_quality_gate or signal_quality_good' in source
    assert 'bool strict_signal_quality_gate_ok = not use_lean_signal_quality_gate or signal_quality_high' in source
    assert 'compute_long_environment_context(bool market_regime_gate_ok, bool vola_regime_gate_safe, bool primary_quality_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool event_risk_gate_ok_param) =>' in source
    assert '[environment_hard_gate_ok, quality_gate_ok, microstructure_entry_gate_ok, trade_hard_gate_ok, long_environment_focus_display] = compute_long_environment_context(market_regime_gate_ok, vola_regime_gate_safe, primary_quality_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, event_risk_gate_ok)' in source
    assert 'compute_long_environment_context(bool market_regime_gate_ok, bool vola_regime_gate_safe, bool context_quality_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok) =>' not in source
    assert '[environment_hard_gate_ok, quality_gate_ok, microstructure_entry_gate_ok, trade_hard_gate_ok, long_environment_focus_display] = compute_long_environment_context(market_regime_gate_ok, vola_regime_gate_safe, context_quality_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok)' not in source
    assert 'compute_long_entry_best_state(bool long_ready_state, bool best_signal_quality_gate_ok, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe) =>' in source
    assert 'bool long_entry_best_state = compute_long_entry_best_state(long_ready_state, best_signal_quality_gate_ok, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe)' in source
    assert 'compute_long_entry_best_state(bool long_ready_state, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe) =>' not in source
    assert 'bool long_entry_best_state = compute_long_entry_best_state(long_ready_state, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe)' not in source
    assert 'compute_long_entry_strict_state(bool long_ready_state, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'bool long_entry_strict_state = compute_long_entry_strict_state(long_ready_state, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert 'compute_long_entry_strict_state(bool long_ready_state, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' not in source
    assert 'bool long_entry_strict_state = compute_long_entry_strict_state(long_ready_state, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' not in source
    assert 'bool combined_quality_gate_ok' not in source
    assert 'signal_bias_bullish' not in source


def test_core_engine_has_no_dashboard_or_alert_transport_layer() -> None:
    source = _read_core_source()

    assert 'alertcondition(' not in source
    assert 'dynamic_alert_seen_keys' not in source
    assert 'emit_long_dynamic_alerts(' not in source
    assert 'emit_bullish_dynamic_alerts(' not in source
    assert 'dashboard_header(' not in source
    assert 'dashboard_section_header(' not in source
    assert 'dashboard_row(' not in source
    assert 'dashboard_section_row(' not in source
    assert 'compute_dashboard_' not in source
    assert 'render_dashboard_' not in source
    assert 'var table _smc_dashboard = table.new(' not in source


def test_core_engine_ends_at_hidden_bus_boundary() -> None:
    source = _read_core_source().rstrip()

    assert "plot(pack_bus_four(resolve_bus_ob_light_row(lib_obl_side, lib_obl_fresh, lib_obl_mitigation_state), resolve_bus_fvg_light_row(lib_fvgl_side, lib_fvgl_fresh, lib_fvgl_invalidated), pack_bus_row(lib_scl_context_score, lib_scl_in_killzone ? 1 : 2), pack_bus_row(lib_sq_score, 0)), 'BUS LeanPackB', display = display.none)" in source
    assert source.endswith('/////////////////////////////////////////////////////////////////////////////////')
    assert "'BUS LeanPackB', display = display.none)\n\n// ── Mini Health Badge (v5.5a) ──" in source


def test_core_engine_extracts_remaining_display_helpers() -> None:
    source = _read_core_source()

    assert 'compose_long_alert_text_suffixes(bool use_overhead_zone_filter, float headroom_to_overhead, float planned_risk, int signal_quality_score, string signal_quality_tier, bool use_strict_sequence, bool use_strict_sweep_for_zone_reclaim, bool use_strict_confirm_guard, bool use_microstructure_profiles, string micro_profile_text, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display) =>' in source
    assert 'resolve_long_debug_event_values(bool long_invalidate_signal, string long_setup_source_display, string long_debug_event_source_display, int long_setup_backing_zone_touch_count, int long_debug_event_touch_count, float long_setup_trigger, float long_debug_event_trigger, float long_invalidation_level, float long_debug_event_invalidation) =>' in source
    assert 'resolve_event_risk_state(bool market_event_blocked, bool symbol_event_blocked, string event_window_state, string event_risk_level) =>' in source
    assert 'compute_long_freshness_state(bool long_setup_armed, bool long_setup_confirmed, int current_bar_index, int long_arm_bar_index, int long_confirm_bar_index, int max_bars_arm_to_confirm, int max_bars_confirm_to_ready, bool use_microstructure_profiles, bool micro_is_fast_decay, int effective_fast_decay_setup_age_max, int effective_fast_decay_confirm_age_max) =>' in source
    assert 'resolve_long_zone_source_label(int long_source_kind) =>' in source
    assert 'resolve_long_anchor_source_label(int long_source_kind) =>' in source
    assert 'resolve_long_primary_source_text(int long_source_kind) =>' in source
    assert 'resolve_long_source_label_text(int long_source_kind) =>' in source
    assert 'resolve_long_source_fallback_text(string source_text) =>' in source
    assert 'compose_long_source_invalidated_text(string source_text) =>' in source
    assert 'compose_long_backing_zone_lost_text(string source_text) =>' in source
    assert 'compose_long_setup_expired_text(string source_text) =>' in source
    assert 'compose_long_confirm_expired_text(string source_text) =>' in source
    assert 'compose_long_source_transition_text(string long_entry_origin_source_text, string long_validation_source_text) =>' in source
    assert 'resolve_long_source_display_text(int long_entry_origin_source, int long_validation_source, string long_entry_origin_source_text, string long_validation_source_text) =>' in source
    assert 'compose_zone_range_text(string zone_label, float zone_top, float zone_bottom) =>' in source
    assert 'compose_ob_zone_summary_text(float ob_top, float ob_bottom) =>' in source
    assert 'compose_fvg_zone_summary_text(float fvg_top, float fvg_bottom) =>' in source
    assert 'compose_combined_zone_summary_text(float ob_top, float ob_bottom, float fvg_top, float fvg_bottom) =>' in source
    assert 'resolve_long_zone_summary_display_text(bool show_ob_zone, float ob_top, float ob_bottom, bool show_fvg_zone, float fvg_top, float fvg_bottom, string empty_text) =>' in source
    assert 'resolve_long_debug_mode_suffix(string long_engine_debug_mode) =>' in source
    assert 'append_debug_module_text(string debug_text, string module_text) =>' in source
    assert 'append_enabled_debug_module_text(string debug_text, bool show_module, string module_text) =>' in source
    assert 'compose_long_debug_module_label(string long_engine_debug_mode) =>' in source
    assert 'resolve_enabled_debug_modules_display_text(bool show_ob_debug, bool show_fvg_debug, bool show_long_engine_debug, string long_engine_debug_mode) =>' in source
    assert 'compose_passed_status_text() =>' in source
    assert 'compose_eligible_status_text() =>' in source
    assert 'compose_awaiting_status_text(status_label) =>' in source
    assert 'compose_blocked_status_text(status_label) =>' in source
    assert 'compose_need_ready_status_text(string long_ready_blocker_text) =>' in source
    assert 'resolve_long_environment_focus_text(bool market_regime_gate_ok, bool vola_regime_gate_safe, bool event_risk_gate_ok_param) =>' in source
    assert 'resolve_long_ready_blocker_display_text(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'resolve_long_setup_state_label(int state_code) =>' in source
    assert 'long_setup_state_has_source_display(int state_code) =>' in source
    assert 'compose_long_setup_state_text(int state_code, string long_setup_source_display) =>' in source
    assert 'resolve_long_setup_state_code(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar) =>' in source
    assert 'resolve_long_setup_display_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>' in source
    assert '[long_setup_age, long_confirm_age, confirm_is_fresh, ready_is_fresh, micro_setup_fresh_enough, micro_confirm_fresh_enough, micro_freshness_gate_ok] = compute_long_freshness_state(' in source
    assert 'resolve_long_visual_state_code(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidate_signal, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar) =>' in source
    assert 'resolve_long_visual_state_label(int long_visual_state) =>' in source
    assert 'resolve_long_strict_blocker_display_text(bool long_entry_strict_state, bool long_ready_state, string long_ready_blocker_text, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'resolve_long_engine_debug_label_display_text(string long_engine_debug_mode, string long_setup_text, string long_visual_text, string long_setup_source_display, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string overhead_text, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'resolve_long_engine_event_log_display_text(string long_engine_debug_mode, string event_name, string long_setup_source_display, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_debug_primary_line(bool debug_mode_full, string long_setup_source_display, int long_setup_backing_zone_touch_count, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_debug_full_summary_text(string long_setup_source_display, int long_setup_backing_zone_touch_count, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_debug_label_header_text(string long_engine_debug_mode, string long_setup_text, string long_visual_text) =>' in source
    assert 'compose_long_debug_event_header_text(string event_name, string long_setup_source_display, float long_setup_trigger, float long_invalidation_level) =>' in source
    assert 'compose_long_debug_last_invalid_text(string long_last_invalid_source) =>' in source
    assert 'compose_long_debug_reason_text(string long_last_invalid_source) =>' in source
    assert 'resolve_long_upgrade_edge_text(bool ob_source_upgrade_ok, bool fvg_source_upgrade_ok) =>' in source
    assert 'compose_long_upgrade_reason_text(string target_source_text, string edge_text, float quality_gain) =>' in source
    assert 'resolve_long_confirm_freshness_text(bool ready_is_fresh) =>' in source
    assert 'resolve_long_armed_freshness_text(bool confirm_is_fresh) =>' in source
    assert 'resolve_long_source_state_text(bool long_source_alive, bool long_source_broken) =>' in source
    assert 'resolve_long_zone_quality_text(int effective_long_active_touch_count) =>' in source
    assert 'resolve_long_overhead_alert_text(bool use_overhead_zone_filter, float headroom_to_overhead, float planned_risk) =>' in source
    assert 'compose_long_score_detail_suffix(int signal_quality_score, string signal_quality_tier) =>' in source
    assert 'resolve_long_strict_alert_suffix(bool use_strict_sequence, bool use_strict_sweep_for_zone_reclaim, bool use_strict_confirm_guard) =>' in source
    assert 'compose_long_environment_alert_suffix(string long_environment_focus_display, string overhead_text) =>' in source
    assert 'compose_long_micro_alert_suffix(string micro_profile_text, string freshness_text, string source_state_text, string zone_quality_text) =>' in source
    assert 'compose_long_debug_pipe_upgrade_text(string long_source_upgrade_reason) =>' in source
    assert 'compose_long_debug_pipe_reason_text(string long_last_invalid_source) =>' in source
    assert 'compose_long_debug_newline_upgrade_text(string long_source_upgrade_reason) =>' in source
    assert 'compose_long_debug_newline_last_invalid_text(string long_last_invalid_source) =>' in source
    assert 'compose_long_debug_label_full_mode_text(string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string long_ready_blocker_text, string long_strict_blocker_text, float long_setup_trigger, float long_invalidation_level, string overhead_text) =>' in source
    assert 'compose_long_debug_event_state_text(bool debug_mode_full, int long_setup_backing_zone_touch_count, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_health_badge_text(string signal_bias_alignment, string signal_quality_tier, int signal_quality_score, string event_risk_state, string signal_freshness, string signal_warnings, string provider_status) =>' in source
    assert 'resolve_health_badge_color(string signal_quality_tier) =>' in source
    assert '[overhead_text, long_score_detail_suffix, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix] = compose_long_alert_text_suffixes(use_overhead_zone_filter_eff, headroom_to_overhead, planned_risk, lib_sq_score, lib_sq_tier, use_strict_sequence_eff, use_strict_sweep_for_zone_reclaim_eff, use_strict_confirm_guard, use_microstructure_profiles, micro_profile_text, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display)' in source
    assert '[debug_log_source_display, debug_log_touch_count, debug_log_trigger, debug_log_invalidation] = resolve_long_debug_event_values(long_invalidate_signal, long_setup_source_display, long_debug_event_source_display, long_state.backing_zone_touch_count, long_debug_event_touch_count, long_state.trigger, long_debug_event_trigger, long_state.invalidation_level, long_debug_event_invalidation)' in source
    assert 'string event_risk_state         = resolve_event_risk_state(lib_erl_market_blocked, lib_erl_symbol_blocked, lib_erl_window_state, lib_erl_level)' in source
    assert 'string source_text = resolve_long_zone_source_label(long_source_kind)' in source
    assert 'source_text := resolve_long_anchor_source_label(long_source_kind)' in source
    assert 'string source_text = resolve_long_primary_source_text(long_source_kind)' in source
    assert 'resolve_long_source_label_text(long_source_kind)' in source
    assert 'source_text := resolve_long_source_fallback_text(source_text)' in source
    assert 'invalidation_reason := compose_long_source_invalidated_text(long_validation_source_text)' in source
    assert 'invalidation_reason := compose_long_backing_zone_lost_text(long_validation_source_text)' in source
    assert 'invalidation_reason := compose_long_setup_expired_text(long_entry_origin_source_text)' in source
    assert 'invalidation_reason := compose_long_confirm_expired_text(long_entry_origin_source_text)' in source
    assert 'resolve_long_zone_summary_display_text(show_ob_zone, ob_top, ob_bottom, show_fvg_zone, fvg_top, fvg_bottom, empty_text)' in source
    assert 'source_display := compose_long_source_transition_text(long_entry_origin_source_text, long_validation_source_text)' in source
    assert 'resolve_long_source_display_text(long_entry_origin_source, long_validation_source, long_entry_origin_source_text, long_validation_source_text)' in source
    assert 'zone_text := compose_combined_zone_summary_text(ob_top, ob_bottom, fvg_top, fvg_bottom)' in source
    assert 'zone_text := compose_ob_zone_summary_text(ob_top, ob_bottom)' in source
    assert 'zone_text := compose_fvg_zone_summary_text(fvg_top, fvg_bottom)' in source
    assert 'resolve_enabled_debug_modules_display_text(show_ob_debug, show_fvg_debug, show_long_engine_debug, long_engine_debug_mode)' in source
    assert "debug_text := append_enabled_debug_module_text(debug_text, show_ob_debug, 'OB')" in source
    assert "debug_text := append_enabled_debug_module_text(debug_text, show_fvg_debug, 'FVG')" in source
    assert 'debug_text := append_enabled_debug_module_text(debug_text, show_long_engine_debug, compose_long_debug_module_label(long_engine_debug_mode))' in source
    assert "trade_gate_reason := compose_blocked_status_text('Session Gate')" in source
    assert "environment_gate_reason := compose_blocked_status_text('Market Gate')" in source
    assert "lifecycle_reason := compose_awaiting_status_text('Confirm')" in source
    assert "ready_gate_reason := compose_blocked_status_text('Touch Count')" in source
    assert "strict_gate_reason := compose_blocked_status_text('Signal Quality')" in source
    assert 'strict_blocker_text := compose_need_ready_status_text(long_ready_blocker_text)' in source
    assert 'string helper_long_environment_focus_display = resolve_long_environment_focus_text(market_regime_gate_ok, vola_regime_gate_safe, event_risk_gate_ok_param)' in source
    assert 'resolve_long_ready_blocker_display_text(long_ready_state, long_setup_confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)' in source
    assert 'int state_code = resolve_long_setup_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)' in source
    assert 'resolve_long_setup_display_text(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidated_now, invalidated_prior_setup, long_invalidated_this_bar, long_setup_source_display)' in source
    assert 'compose_long_setup_state_text(state_code, long_setup_source_display)' in source
    assert 'resolve_long_visual_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidate_signal, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)' in source
    assert 'long_visual_text := resolve_long_visual_state_label(long_visual_state)' in source
    assert 'resolve_long_visual_state_label(long_visual_state)' in source
    assert 'resolve_long_strict_blocker_display_text(long_entry_strict_state, long_ready_state, long_ready_blocker_text, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert 'debug_text := compose_long_debug_full_summary_text(long_setup_source_display, long_setup_backing_zone_touch_count, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, long_ready_blocker_text, long_strict_blocker_text)' in source
    assert 'resolve_long_engine_debug_label_display_text(long_engine_debug_mode, long_setup_text, long_visual_text, long_setup_source_display, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, overhead_text, long_setup_trigger, long_invalidation_level, long_setup_backing_zone_touch_count, long_source_upgrade_now, long_source_upgrade_reason, long_last_invalid_source, long_ready_blocker_text, long_strict_blocker_text)' in source
    assert 'resolve_long_engine_event_log_display_text(long_engine_debug_mode, event_name, long_setup_source_display, long_setup_trigger, long_invalidation_level, long_setup_backing_zone_touch_count, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, long_source_upgrade_now, long_source_upgrade_reason, long_last_invalid_source, long_ready_blocker_text, long_strict_blocker_text)' in source
    assert "string debug_text = compose_long_debug_label_header_text(long_engine_debug_mode, long_setup_text, long_visual_text)" in source
    assert "debug_text += '\\n' + compose_long_debug_primary_line(debug_mode_full, long_setup_source_display, long_setup_backing_zone_touch_count, long_ready_blocker_text, long_strict_blocker_text)" in source
    assert 'string event_text = compose_long_debug_event_header_text(event_name, long_setup_source_display, long_setup_trigger, long_invalidation_level)' in source
    assert 'debug_text := compose_long_debug_last_invalid_text(long_last_invalid_source)' in source
    assert 'debug_text += compose_long_debug_newline_last_invalid_text(long_last_invalid_source)' in source
    assert 'event_text += compose_long_debug_pipe_reason_text(long_last_invalid_source)' in source
    assert 'string edge_text = resolve_long_upgrade_edge_text(ob_source_upgrade_ok, fvg_source_upgrade_ok)' in source
    assert 'upgrade_reason := compose_long_upgrade_reason_text(target_source_text, edge_text, quality_gain)' in source
    assert 'freshness_text := resolve_long_confirm_freshness_text(ready_is_fresh)' in source
    assert 'freshness_text := resolve_long_armed_freshness_text(confirm_is_fresh)' in source
    assert 'source_state_text := resolve_long_source_state_text(long_source_alive, long_source_broken)' in source
    assert 'zone_quality_text := resolve_long_zone_quality_text(effective_long_active_touch_count)' in source
    assert 'string overhead_text = resolve_long_overhead_alert_text(use_overhead_zone_filter, headroom_to_overhead, planned_risk)' in source
    assert 'string score_suffix = compose_long_score_detail_suffix(signal_quality_score, signal_quality_tier)' in source
    assert 'string strict_suffix = resolve_long_strict_alert_suffix(use_strict_sequence, use_strict_sweep_for_zone_reclaim, use_strict_confirm_guard)' in source
    assert 'string environment_suffix = compose_long_environment_alert_suffix(long_environment_focus_display, overhead_text)' in source
    assert 'micro_suffix := compose_long_micro_alert_suffix(micro_profile_text, freshness_text, source_state_text, zone_quality_text)' in source
    assert 'debug_text += compose_long_debug_pipe_upgrade_text(long_source_upgrade_reason)' in source
    assert 'debug_text += compose_long_debug_newline_upgrade_text(long_source_upgrade_reason)' in source
    assert 'debug_text += compose_long_debug_newline_last_invalid_text(long_last_invalid_source)' in source
    assert 'event_text += compose_long_debug_pipe_upgrade_text(long_source_upgrade_reason)' in source
    assert 'event_text += compose_long_debug_pipe_reason_text(long_last_invalid_source)' in source
    assert 'debug_text += compose_long_debug_label_full_mode_text(freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, long_ready_blocker_text, long_strict_blocker_text, long_setup_trigger, long_invalidation_level, overhead_text)' in source
    assert 'event_text += compose_long_debug_event_state_text(debug_mode_full, long_setup_backing_zone_touch_count, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, long_ready_blocker_text, long_strict_blocker_text)' in source
    assert "resolve_long_source_text(int long_source_kind) =>\n    string source_text = resolve_long_zone_source_label(long_source_kind)\n    if source_text == ''\n        source_text := resolve_long_anchor_source_label(long_source_kind)\n    source_text := resolve_long_source_fallback_text(source_text)\n    source_text" not in source
    assert "resolve_long_source_text(int long_source_kind) =>\n    string source_text = resolve_long_primary_source_text(long_source_kind)\n    source_text := resolve_long_source_fallback_text(source_text)\n    source_text" not in source
    assert "compose_long_setup_source_display(int long_entry_origin_source, int long_validation_source) =>\n    string long_entry_origin_source_text = resolve_long_source_text(long_entry_origin_source)\n    string long_validation_source_text = resolve_long_source_text(long_validation_source)\n    string source_display = long_validation_source_text\n    if long_entry_origin_source == LONG_SOURCE_NONE\n        source_display := long_validation_source_text\n    else if long_validation_source == LONG_SOURCE_NONE or long_entry_origin_source == long_validation_source\n        source_display := long_entry_origin_source_text\n    else\n        source_display := long_entry_origin_source_text + ' -> ' + long_validation_source_text\n    source_display" not in source
    assert "compose_long_setup_source_display(int long_entry_origin_source, int long_validation_source) =>\n    string long_entry_origin_source_text = resolve_long_source_text(long_entry_origin_source)\n    string long_validation_source_text = resolve_long_source_text(long_validation_source)\n    string source_display = long_validation_source_text" not in source
    assert "zone_text := 'OB ' + u.format_level(ob_top) + ' / ' + u.format_level(ob_bottom)" not in source
    assert "zone_text := 'FVG ' + u.format_level(fvg_top) + ' / ' + u.format_level(fvg_bottom)" not in source
    assert "zone_text := compose_zone_range_text('OB', ob_top, ob_bottom)" not in source
    assert "zone_text := compose_zone_range_text('FVG', fvg_top, fvg_bottom)" not in source
    assert "debug_text := debug_text + ' | FVG'" not in source
    assert "debug_text := 'Long' + long_debug_mode_suffix" not in source
    assert "compose_enabled_debug_modules_text(bool show_ob_debug, bool show_fvg_debug, bool show_long_engine_debug, string long_engine_debug_mode) =>\n    string debug_text = 'off'" not in source
    assert "compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>\n    int state_code = resolve_long_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)" not in source
    assert "compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>\n    int state_code = resolve_long_setup_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)" not in source
    assert "resolve_long_visual_state(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidate_signal, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar) =>\n    resolve_long_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar, long_invalidate_signal)" not in source
    assert "compose_zone_summary_text(bool show_ob_zone, float ob_top, float ob_bottom, bool show_fvg_zone, float fvg_top, float fvg_bottom, string empty_text) =>\n    string zone_text = empty_text" not in source
    assert "resolve_long_ready_blocker_text(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>\n    string lifecycle_reason = resolve_long_ready_lifecycle_reason(long_ready_state, long_setup_confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready, bull_bos_sig, main_bos_recent)" not in source
    assert "resolve_long_strict_blocker_text(bool long_entry_strict_state, bool long_ready_state, string long_ready_blocker_text, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>\n    string strict_blocker_text = compose_passed_status_text()" not in source
    assert "compose_long_engine_debug_label_text(string long_engine_debug_mode, string long_setup_text, string long_visual_text, string long_setup_source_display, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string overhead_text, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>\n    bool debug_mode_full = debug_mode_is_full(long_engine_debug_mode)" not in source
    assert "compose_long_engine_event_log(string long_engine_debug_mode, string event_name, string long_setup_source_display, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>\n    bool debug_mode_full = debug_mode_is_full(long_engine_debug_mode)" not in source
    assert "resolve_long_visual_text(int long_visual_state) =>\n    resolve_long_visual_state_label(long_visual_state)" not in source
    assert "trade_gate_reason := 'Blocked: Session Gate'" not in source
    assert "lifecycle_reason := 'Awaiting Confirm'" not in source
    assert "ready_gate_reason := 'Blocked: Touch Count'" not in source
    assert "strict_blocker_text := 'Need Ready: ' + long_ready_blocker_text" not in source
    assert "invalidation_reason := long_validation_source_text + ' source invalidated'" not in source
    assert "invalidation_reason := long_entry_origin_source_text + ' confirm expired'" not in source
    assert "debug_text := 'last=' + long_last_invalid_source" not in source
    assert "debug_text += '\\nlast=' + long_last_invalid_source" not in source
    assert "event_text += ' | reason=' + long_last_invalid_source" not in source
    assert "float quality_gain = math.max(target_quality - long_locked_source_quality, 0.0)\n        string edge_text = 'beat locked source confluence'" not in source
    assert "string edge_text = 'beat locked source confluence'\n        if ob_source_upgrade_ok and fvg_source_upgrade_ok\n            edge_text := 'won tie on stronger confluence'\n        upgrade_reason := target_source_text + ' ' + edge_text + ' +' + str.tostring(quality_gain, '#.##') + 'Q'" not in source
    assert "upgrade_reason := target_source_text + ' ' + edge_text + ' +' + str.tostring(quality_gain, '#.##') + 'Q'" not in source
    assert "if ready_is_fresh\n            freshness_text := 'confirm fresh'\n        else\n            freshness_text := 'confirm stale'" not in source
    assert "if confirm_is_fresh\n            freshness_text := 'armed fresh'\n        else\n            freshness_text := 'armed stale'" not in source
    assert "if long_source_alive\n            source_state_text := 'source alive'\n        else if long_source_broken\n            source_state_text := 'source invalid'\n        else\n            source_state_text := 'source lost'" not in source
    assert "if effective_long_active_touch_count <= 1\n            zone_quality_text := 'fresh touch'\n        else if effective_long_active_touch_count == 2\n            zone_quality_text := '2nd touch'\n        else\n            zone_quality_text := 'crowded'" not in source
    assert "compose_long_alert_text_suffixes(bool use_overhead_zone_filter, float headroom_to_overhead, float planned_risk, int signal_quality_score, string signal_quality_tier, bool use_strict_sequence, bool use_strict_sweep_for_zone_reclaim, bool use_strict_confirm_guard, bool use_microstructure_profiles, string micro_profile_text, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display) =>\n    string overhead_text = 'off'" not in source
    assert "string score_suffix = ' | sq=' + str.tostring(signal_quality_score) + '/' + signal_quality_tier\n    string strict_suffix = ''\n    if use_strict_sequence or use_strict_sweep_for_zone_reclaim or use_strict_confirm_guard\n        strict_suffix := ' | strict=on'\n    string environment_suffix = ' | env=' + long_environment_focus_display + ' | overhead=' + overhead_text" not in source
    assert "string micro_suffix = ''\n    if use_microstructure_profiles\n        micro_suffix := ' | micro=' + micro_profile_text + ' | freshness=' + freshness_text + ' | source=' + source_state_text + ' | zone=' + zone_quality_text" not in source
    assert "debug_text += ' | ' + compose_long_debug_upgrade_text(long_source_upgrade_reason)" not in source
    assert "debug_text += '\\n' + compose_long_debug_upgrade_text(long_source_upgrade_reason)" not in source
    assert "debug_text += '\\n' + compose_long_debug_last_invalid_text(long_last_invalid_source)" not in source
    assert "event_text += ' | ' + compose_long_debug_upgrade_text(long_source_upgrade_reason)" not in source
    assert "event_text += ' | ' + compose_long_debug_reason_text(long_last_invalid_source)" not in source
    assert "if debug_mode_full\n        debug_text += '\\n' + compose_long_debug_fresh_source_text(freshness_text, source_state_text)\n        debug_text += '\\n' + compose_long_debug_zone_env_text(zone_quality_text, long_environment_focus_display)\n        debug_text += '\\n' + compose_long_debug_ready_strict_text(long_ready_blocker_text, long_strict_blocker_text)\n        debug_text += '\\n' + compose_long_debug_levels_text(long_setup_trigger, long_invalidation_level, overhead_text)" not in source
    assert "if debug_mode_full\n        event_text += ' | ' + compose_long_debug_event_context_text(long_setup_backing_zone_touch_count, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display)\n    event_text += ' | ' + compose_long_debug_ready_strict_text(long_ready_blocker_text, long_strict_blocker_text)" not in source
    assert "setup_text := 'Entry Best | ' + long_setup_source_display" not in source
    assert "setup_text := 'Entry Strict | ' + long_setup_source_display" not in source
    assert 'string dir_icon   = lib_sq_bias_alignment == "bull" ? "▲" : lib_sq_bias_alignment == "bear" ? "▼" : "◆"' not in source
    assert 'string tier_icon  = lib_sq_tier == "high" ? "🟢" : lib_sq_tier == "good" ? "🟡" : lib_sq_tier == "ok" ? "🟠" : "🔴"' not in source
    assert 'string event_icon = event_risk_state == "blocked" ? "⛔" : event_risk_state == "caution" ? "⚡" : "✓"' not in source
    assert 'string fresh_icon = lib_sq_freshness == "fresh" ? "●" : lib_sq_freshness == "aging" ? "◐" : "○"' not in source
    assert 'string event_risk_state         = lib_erl_market_blocked or lib_erl_symbol_blocked ? "blocked" : (lib_erl_window_state == "COOLDOWN" or (lib_erl_window_state == "PRE_EVENT" and (lib_erl_level == "HIGH" or lib_erl_level == "ELEVATED"))) ? "caution" : "clear"' not in source
