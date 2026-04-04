from __future__ import annotations

import pathlib
import re

from tests.smc_manifest_test_utils import ROOT, load_manifest


CORE_PATH = ROOT / 'SMC_Core_Engine.pine'


MANIFEST = load_manifest()
EXPECTED_BUS_LABELS = list(MANIFEST.ENGINE_BUS_LABELS)


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
    assert 'pack_bus_counts(' in source
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
    assert 'resolve_long_ready_projection_state(bool long_setup_armed, bool long_internal_structure_ok, bool long_setup_confirmed, int long_confirm_bar_index, int current_bar_index, bool use_scoring_over_blocking, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe, bool close_safe_mode, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool quality_gate_ok) =>' in source
    assert '[long_building_state, ready_bar_gap_ok, scoring_accel_ready, scoring_sd_ready, scoring_vol_ready, scoring_stretch_ready, scoring_ddvi_ready, lifecycle_ready_ok, long_ready_state] = resolve_long_ready_projection_state(long_state.armed, long_internal_structure_ok, long_state.confirmed, long_state.confirm_bar_index, bar_index, use_scoring_over_blocking, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe, close_safe_mode, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, quality_gate_ok)' in source
    assert 'compute_long_entry_best_state(bool long_ready_state, bool best_signal_quality_gate_ok, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe) =>' in source
    assert 'resolve_long_entry_projection_state(bool long_ready_state, bool best_signal_quality_gate_ok, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert '[long_entry_best_state, long_entry_strict_state] = resolve_long_entry_projection_state(long_ready_state, best_signal_quality_gate_ok, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert 'compute_long_entry_best_state(bool long_ready_state, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe) =>' not in source
    assert 'bool long_entry_best_state = compute_long_entry_best_state(long_ready_state, best_signal_quality_gate_ok, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe)' not in source
    assert 'compute_long_entry_strict_state(bool long_ready_state, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'compute_long_entry_strict_state(bool long_ready_state, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' not in source
    assert 'bool long_entry_strict_state = compute_long_entry_strict_state(long_ready_state, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' not in source
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

    assert "plot(resolve_bus_ltf_delta_state(show_dashboard_ltf_eff, ltf_sampling_active, ltf_price_only, ltf_volume_delta), 'BUS LtfDeltaState', display = display.none)" in source
    assert "plot(resolve_bus_safe_trend_state(bullish_trend_safe, bearish_trend_safe), 'BUS SafeTrendState', display = display.none)" in source
    assert "plot(resolve_bus_micro_profile_code(use_microstructure_profiles, micro_profile_text, micro_modifier_text), 'BUS MicroProfileCode', display = display.none)" in source
    assert "plot(resolve_bus_sd_confluence_row(use_sd_confluence, sd_support_both_recent, sd_bullish_divergence_recent, sd_higher_lows_recent, sd_support_any_recent), 'BUS SdConfluenceRow', display = display.none)" in source
    assert "plot(resolve_bus_sd_osc_row(use_sd_confluence, sd_value, sd_above_zero, sd_rising, sd_below_zero, sd_falling), 'BUS SdOscRow', display = display.none)" in source
    assert "plot(resolve_bus_vol_regime_row(use_volatility_regime, vol_regime_trend_ok), 'BUS VolRegimeRow', display = display.none)" in source
    assert "plot(resolve_bus_vol_squeeze_row(use_volatility_regime, vol_squeeze_on, vol_squeeze_release_recent, vol_squeeze_recent), 'BUS VolSqueezeRow', display = display.none)" in source
    assert "plot(resolve_bus_ready_blocker_code(long_ready_state, long_state.confirmed, lifecycle_ready_ok, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe), 'BUS ReadyBlockerCode', display = display.none)" in source
    assert "plot(resolve_bus_strict_blocker_code(long_entry_strict_state, long_ready_state, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe), 'BUS StrictBlockerCode', display = display.none)" in source
    assert "plot(resolve_bus_vol_expansion_state(use_volatility_regime, vol_momentum_expanding_long, vol_stack_spread_rising), 'BUS VolExpansionState', display = display.none)" in source
    assert "plot(resolve_bus_ddvi_context_state(use_ddvi_context, ddvi_bias_ok, ddvi_bull_divergence_any, ddvi_lower_extreme_context), 'BUS DdviContextState', display = display.none)" in source
    assert "plot(resolve_bus_stretch_support_mask(use_stretch_context, in_lower_extreme, lower_extreme_recent, anti_chase_ok_ready, anti_chase_ok_entry_best), 'BUS StretchSupportMask', display = display.none)" in source
    assert "plot(ltf_bias_hint, 'BUS LtfBiasHint', display = display.none)" in source
    assert "plot(pack_bus_counts(array.size(ob_blocks_bull), array.size(fvgs_bull)), 'BUS ObjectsCountPack', display = display.none)" in source
    assert "'BUS VolExpandRow', display = display.none" not in source
    assert "'BUS DdviRow', display = display.none" not in source
    assert "'BUS LtfDeltaRow', display = display.none" not in source
    assert "'BUS SwingRow', display = display.none" not in source
    assert "'BUS MicroProfileRow', display = display.none" not in source
    assert "'BUS QualityBoundsPack', display = display.none" not in source
    assert "'BUS ModulePackC', display = display.none" not in source
    assert "'BUS ModulePackD', display = display.none" not in source
    assert "'BUS ReadyStrictPack', display = display.none" not in source
    assert "'BUS LtfDeltaState', display = display.none" in source
    assert "'BUS SafeTrendState', display = display.none" in source
    assert "'BUS MicroProfileCode', display = display.none" in source
    assert "'BUS ReadyBlockerCode', display = display.none" in source
    assert "'BUS StrictBlockerCode', display = display.none" in source
    assert "'BUS VolExpansionState', display = display.none" in source
    assert "'BUS DdviContextState', display = display.none" in source
    assert "'BUS MicroModifierMask', display = display.none" not in source
    assert "'BUS ModulePackA', display = display.none" not in source
    assert "'BUS ModulePackB', display = display.none" not in source
    assert "'BUS DebugStateRow', display = display.none" not in source
    assert "'BUS ReadyGateRow', display = display.none" not in source
    assert "'BUS StrictGateRow', display = display.none" not in source
    assert "plot(resolve_bus_lean_pack_b(lib_obl_side, lib_obl_fresh, lib_obl_mitigation_state, lib_fvgl_side, lib_fvgl_fresh, lib_fvgl_invalidated, lib_scl_context_score, lib_scl_in_killzone, lib_sq_score), 'BUS LeanPackB', display = display.none)" in source
    assert 'resolve_bus_debug_state_row(' not in source
    assert source.endswith('/////////////////////////////////////////////////////////////////////////////////')
    assert "'BUS LeanPackB', display = display.none)\n\n// ── Mini Health Badge (v5.5a) ──" in source


def test_core_engine_moves_secondary_overlay_lines_off_plot_budget() -> None:
    source = _read_core_source()

    assert "plot(show_session_vwap_eff and intraday_time_chart ? session_vwap : na, 'Session VWAP'" not in source
    assert "plot(show_ema_support_eff ? ema_fast : na, 'EMA Fast'" not in source
    assert "plot(show_ema_support_eff ? ema_slow : na, 'EMA Slow'" not in source
    assert 'draw_overlay_line_tail(session_vwap_overlay_segments, show_session_vwap_eff and intraday_time_chart, session_vwap, color.new(color.blue, 0), 2, overlay_line_tail_segments)' in source
    assert 'draw_overlay_line_tail(ema_fast_overlay_segments, show_ema_support_eff, ema_fast, color.new(color.lime, 0), 2, overlay_line_tail_segments)' in source
    assert 'draw_overlay_line_tail(ema_slow_overlay_segments, show_ema_support_eff, ema_slow, color.new(color.teal, 0), 2, overlay_line_tail_segments)' in source


def test_core_engine_tracks_c4_gate_contract_helpers() -> None:
    source = _read_core_source()

    assert 'resolve_long_ready_lifecycle_reason_code(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent) =>' in source
    assert 'resolve_long_ready_gate_reason_code(bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'resolve_long_ready_reason_code(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'resolve_long_strict_reason_code(bool long_entry_strict_state, bool long_ready_state, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'resolve_bus_ready_blocker_code(bool long_ready_state, bool long_setup_confirmed, bool lifecycle_ready_ok, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'resolve_bus_strict_blocker_code(bool long_entry_strict_state, bool long_ready_state, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'resolve_bus_ready_gate_row(' not in source
    assert 'resolve_bus_strict_gate_row(' not in source
    assert 'resolve_bus_ready_strict_pack(' not in source
    assert 'resolve_bus_module_pack_d(' not in source
    assert 'resolve_long_execution_blocker_state(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe, bool long_entry_strict_state, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert '[long_ready_blocker_text, long_strict_blocker_text] = resolve_long_execution_blocker_state(long_ready_state, long_state.confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, scoring_accel_ready, scoring_sd_ready, scoring_vol_ready, scoring_stretch_ready, scoring_ddvi_ready, long_entry_strict_state, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source


def test_core_engine_tracks_c4_source_and_bus_pack_helpers() -> None:
    source = _read_core_source()

    assert 'compute_long_source_upgrade_state(bool allow_armed_source_upgrade, bool long_setup_armed, bool long_setup_confirmed, bool prev_locked_source_invalid_now, int prev_locked_source_kind, int prev_locked_source_id, bool bull_reclaim_ob_strict, bool touched_bull_ob_available, int touched_bull_ob_id, float touched_bull_ob_quality, bool bull_reclaim_fvg_strict, bool touched_bull_fvg_available, int touched_bull_fvg_id, float touched_bull_fvg_quality, float long_locked_source_quality, float min_source_upgrade_quality_gain) =>' in source
    assert 'resolve_long_source_runtime_state(int long_source_kind, int long_source_id, bool ob_source_alive, bool fvg_source_alive, bool ob_source_broken, bool fvg_source_broken, bool long_setup_armed, bool long_setup_confirmed) =>' in source
    assert 'resolve_long_invalidation_state(bool long_setup_armed, bool long_setup_confirmed, int long_setup_age, int long_setup_expiry_bars, int long_confirm_age, int long_confirm_expiry_bars, bool close_safe_mode, float long_invalidation_break_src, float long_invalidation_level, float long_invalidation_buffer, bool long_source_broken, bool long_source_lost) =>' in source
    assert 'resolve_bus_ltf_delta_state(bool show_dashboard_ltf_eff, bool ltf_sampling_active, bool ltf_price_only, float ltf_volume_delta) =>' in source
    assert 'resolve_bus_safe_trend_state(bool bullish_trend_safe, bool bearish_trend_safe) =>' in source
    assert 'resolve_bus_micro_profile_code(bool use_microstructure_profiles, string micro_profile_text, string micro_modifier_text) =>' in source
    assert 'resolve_bus_micro_modifier_mask(' not in source
    assert 'resolve_bus_vol_expansion_state(bool use_volatility_regime, bool vol_momentum_expanding_long, bool vol_stack_spread_rising) =>' in source
    assert 'resolve_bus_ddvi_context_state(bool use_ddvi_context, bool ddvi_bias_ok, bool ddvi_bull_divergence_any, bool ddvi_lower_extreme_context) =>' in source
    assert 'resolve_bus_stretch_support_mask(bool use_stretch_context, bool in_lower_extreme, bool lower_extreme_recent, bool anti_chase_ok_ready, bool anti_chase_ok_entry_best) =>' in source
    assert 'resolve_bus_module_pack_d(' not in source
    assert 'resolve_bus_module_pack_c(' not in source
    assert 'resolve_bus_module_pack_b(' not in source
    assert 'resolve_bus_engine_pack(' not in source
    assert "'BUS EnginePack', display = display.none" not in source


def test_core_engine_tracks_c5_arm_and_confirm_owner_helpers() -> None:
    source = _read_core_source()

    assert 'resolve_long_arm_source_state(bool bull_reclaim_ob_strict, float touched_bull_ob_bottom, int touched_bull_ob_id, bool bull_reclaim_fvg_strict, float touched_bull_fvg_bottom, int touched_bull_fvg_id, bool bull_reclaim_swing_low_strict, float long_reclaim_swing_level, bool bull_reclaim_internal_low_strict, float long_reclaim_internal_level, bool in_bull_ob_zone, bool in_bull_fvg_zone, int last_ob_zone_touch_bar_index, int last_fvg_zone_touch_bar_index, int active_bull_ob_id, int active_bull_fvg_id, bool touched_bull_ob_recent, bool touched_bull_fvg_recent, float default_arm_invalidation_candidate) =>' in source
    assert 'compute_long_arm_prequality_ok(bool tighten_armed_stage_eff, bool bullish_trend_safe, bool micro_session_gate_ok, bool zone_touch_quality_ok, bool bull_close_strong, bool ema_support_ok) =>' in source
    assert 'compute_long_arm_should_trigger(bool bull_reclaim_any_for_arm, bool use_strict_sequence_eff, bool zone_touch_event_recent, bool zone_recent, bool long_setup_armed, bool long_invalidated_this_bar, bool micro_session_gate_ok, bool sd_armed_gate_ok, bool armed_prequality_ok) =>' in source
    assert 'resolve_long_arm_transition_payload(int arm_backing_zone_kind, int arm_backing_zone_id, int active_ob_touch_id, int active_ob_touch_count, int touched_bull_ob_id, int touched_bull_ob_touch_count, int active_fvg_touch_id, int active_fvg_touch_count, int touched_bull_fvg_id, int touched_bull_fvg_touch_count, int active_bull_ob_id, float active_bull_ob_top, float active_bull_ob_bottom, int active_bull_fvg_id, float active_bull_fvg_top, float active_bull_fvg_bottom, float touched_bull_ob_top, float touched_bull_ob_bottom, float touched_bull_fvg_top, float touched_bull_fvg_bottom, int current_bar_index) =>' in source
    assert 'resolve_long_confirm_break_state(bool live_exec, bool effective_use_live_confirm_break, float close_price, float high_price, bool long_setup_armed, bool long_setup_confirmed, int current_bar_index, int long_arm_bar_index, float long_trigger) =>' in source
    assert 'resolve_long_confirm_structure_state(bool long_setup_armed, int current_bar_index, int long_arm_bar_index, int internal_choch_since_bars, int internal_bos_since_bars, bool internal_bull_choch_sig, bool internal_bull_bos_sig, string long_internal_structure_mode, bool require_internal_break_for_confirm_eff) =>' in source
    assert 'compute_long_confirm_transition_state(bool close_safe_mode, bool long_confirm_break, bool long_confirm_structure_ok, bool confirm_is_fresh, bool long_confirm_bearish_guard_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool accel_confirm_gate_ok, bool sd_confirmed_gate_ok) =>' in source
    assert '[arm_source_kind, arm_invalidation_candidate, arm_backing_zone_kind, arm_backing_zone_id] = resolve_long_arm_source_state(bull_reclaim_ob_strict, touched_bull_ob_bottom, touched_bull_ob_id, bull_reclaim_fvg_strict, touched_bull_fvg_bottom, touched_bull_fvg_id, bull_reclaim_swing_low_strict, long_reclaim_swing_level, bull_reclaim_internal_low_strict, long_reclaim_internal_level, in_bull_ob_zone, in_bull_fvg_zone, last_ob_zone_touch_bar_index, last_fvg_zone_touch_bar_index, active_bull_ob_id, active_bull_fvg_id, touched_bull_ob_recent, touched_bull_fvg_recent, arm_invalidation_candidate)' in source
    assert 'bool armed_prequality_ok = compute_long_arm_prequality_ok(tighten_armed_stage_eff, bullish_trend_safe, micro_session_gate_ok, zone_touch_quality_ok, bull_close_strong, ema_support_ok)' in source
    assert 'bool long_should_arm = compute_long_arm_should_trigger(bull_reclaim_any_for_arm, use_strict_sequence_eff, zone_touch_event_recent, zone_recent, long_state.armed, long_invalidated_this_bar, micro_session_gate_ok, sd_armed_gate_ok, armed_prequality_ok)' in source
    assert '[long_arm_backing_zone_touch_count, long_arm_locked_source_id, long_arm_locked_source_top, long_arm_locked_source_bottom, long_arm_locked_source_last_touch_bar_index] = resolve_long_arm_transition_payload(arm_backing_zone_kind, arm_backing_zone_id, active_ob_touch_id, active_ob_touch_count, touched_bull_ob_id, touched_bull_ob_touch_count, active_fvg_touch_id, active_fvg_touch_count, touched_bull_fvg_id, touched_bull_fvg_touch_count, active_bull_ob_id, active_bull_ob_top, active_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_top, active_bull_fvg_bottom, touched_bull_ob_top, touched_bull_ob_bottom, touched_bull_fvg_top, touched_bull_fvg_bottom, bar_index)' in source
    assert '[long_confirm_break_src, long_confirm_break] = resolve_long_confirm_break_state(live_exec, effective_use_live_confirm_break, close, high, long_state.armed, long_state.confirmed, bar_index, long_state.arm_bar_index, long_state.trigger)' in source
    assert '[internal_choch_since_arm, internal_bos_since_arm, long_internal_structure_ok, long_confirm_structure_ok] = resolve_long_confirm_structure_state(long_state.armed, bar_index, long_state.arm_bar_index, internal_choch_since_bars, internal_bos_since_bars, internal_bull_choch_sig, internal_bull_bos_sig, long_internal_structure_mode, require_internal_break_for_confirm_eff)' in source
    assert '[confirm_hard_gate_ok, confirm_upgrade_gate_ok, confirm_lifecycle_ok, confirm_filters_ok, long_should_confirm] = compute_long_confirm_transition_state(close_safe_mode, long_confirm_break, long_confirm_structure_ok, confirm_is_fresh, long_confirm_bearish_guard_ok, micro_session_gate_ok, micro_freshness_gate_ok, accel_confirm_gate_ok, sd_confirmed_gate_ok)' in source
    assert 'if long_should_confirm\n    long_state.confirm(bar_index)' in source
    assert 'if bull_reclaim_any_for_arm and (use_strict_sequence_eff ? zone_touch_event_recent : zone_recent) and not long_state.armed and not long_invalidated_this_bar and micro_session_gate_ok and sd_armed_gate_ok and armed_prequality_ok' not in source
    assert 'if close_safe_mode and long_confirm_break and long_confirm_structure_ok and confirm_is_fresh and long_confirm_bearish_guard_ok\n    confirm_lifecycle_ok := true' not in source


def test_core_engine_tracks_c6_plan_overhead_and_risk_plan_owners() -> None:
    source = _read_core_source()

    assert 'compute_long_plan_state(bool long_setup_armed, bool long_setup_confirmed, float long_trigger, float long_invalidation_level) =>' in source
    assert 'compute_long_overhead_context(bool long_plan_active, float close_price, float long_trigger, float long_invalidation_level, float ob_threshold_atr, float stop_buffer_atr_mult, OrderBlock[] ob_blocks_bear_param, int bear_ob_scan_start, FVG[] fvgs_bear_param, int bear_fvg_scan_start, bool use_overhead_zone_filter, float min_headroom_r) =>' in source
    assert 'compute_long_risk_plan_state(bool long_plan_active, float long_planned_stop_level, float planned_risk, float long_trigger, float target1_r, float target2_r) =>' in source
    assert 'long_plan_active := compute_long_plan_state(long_state.armed, long_state.confirmed, long_state.trigger, long_state.invalidation_level)' in source
    assert '[long_planned_stop_level, planned_risk, headroom_to_overhead, overhead_zone_ok] = compute_long_overhead_context(long_plan_active, close, long_state.trigger, long_state.invalidation_level, ob_threshold_atr, stop_buffer_atr_mult, ob_blocks_bear, bear_ob_scan_start, fvgs_bear, bear_fvg_scan_start, use_overhead_zone_filter_eff, min_headroom_r)' in source
    assert '[long_stop_level, long_risk_r, long_target_1, long_target_2] = compute_long_risk_plan_state(long_plan_active, long_planned_stop_level, planned_risk, long_state.trigger, target1_r, target2_r)' in source
    assert 'compute_overhead_context() =>' not in source
    assert 'long_plan_active := false\nif (long_state.armed or long_state.confirmed) and not na(long_state.trigger) and not na(long_state.invalidation_level)\n    long_plan_active := true' not in source
    assert 'if long_plan_active\n    long_stop_level := long_planned_stop_level\n    long_risk_r := math.max(long_state.trigger - long_stop_level, syminfo.mintick)\n    long_target_1 := long_state.trigger + long_risk_r * target1_r\n    long_target_2 := long_state.trigger + long_risk_r * target2_r' not in source


def test_core_engine_tracks_c7_execution_and_bus_projection_owners() -> None:
    source = _read_core_source()

    assert 'resolve_long_ready_projection_state(bool long_setup_armed, bool long_internal_structure_ok, bool long_setup_confirmed, int long_confirm_bar_index, int current_bar_index, bool use_scoring_over_blocking, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe, bool close_safe_mode, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool quality_gate_ok) =>' in source
    assert 'resolve_long_entry_projection_state(bool long_ready_state, bool best_signal_quality_gate_ok, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'resolve_long_execution_blocker_state(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe, bool long_entry_strict_state, bool strict_signal_quality_gate_ok, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'resolve_long_clean_tier(bool close_safe_mode, bool bullish_trend_safe, bool zone_recent, bool reclaim_recent, bool long_setup_confirmed, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool quality_gate_ok, bool bull_close_strong, bool ema_support_ok, bool adx_strong, bool relvol_ok, bool vwap_filter_ok) =>' in source
    assert 'resolve_long_bus_plan_levels(bool long_plan_active, float long_trigger, float long_invalidation_level, float long_stop_level, float long_target_1, float long_target_2) =>' in source
    assert 'resolve_bus_long_triggers_row(' not in source
    assert 'resolve_bus_risk_plan_row(' not in source
    assert 'resolve_bus_debug_flags_row(' not in source
    assert '[long_building_state, ready_bar_gap_ok, scoring_accel_ready, scoring_sd_ready, scoring_vol_ready, scoring_stretch_ready, scoring_ddvi_ready, lifecycle_ready_ok, long_ready_state] = resolve_long_ready_projection_state(long_state.armed, long_internal_structure_ok, long_state.confirmed, long_state.confirm_bar_index, bar_index, use_scoring_over_blocking, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe, close_safe_mode, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, quality_gate_ok)' in source
    assert '[long_entry_best_state, long_entry_strict_state] = resolve_long_entry_projection_state(long_ready_state, best_signal_quality_gate_ok, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert '[long_ready_blocker_text, long_strict_blocker_text] = resolve_long_execution_blocker_state(long_ready_state, long_state.confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, scoring_accel_ready, scoring_sd_ready, scoring_vol_ready, scoring_stretch_ready, scoring_ddvi_ready, long_entry_strict_state, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert 'bool long_quality_clean_tier = resolve_long_clean_tier(close_safe_mode, bullish_trend_safe, zone_recent, reclaim_recent, long_state.confirmed, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, quality_gate_ok, bull_close_strong, ema_support_ok, adx_strong, relvol_ok, vwap_filter_ok)' in source
    assert '[bus_trigger_level, bus_invalidation_level, bus_stop_level, bus_target_1, bus_target_2] = resolve_long_bus_plan_levels(long_plan_active, long_state.trigger, long_state.invalidation_level, long_stop_level, long_target_1, long_target_2)' in source
    assert "plot(bus_trigger_level, 'BUS Trigger', display = display.none)" in source
    assert "plot(bus_invalidation_level, 'BUS Invalidation', display = display.none)" in source
    assert "plot(bus_stop_level, 'BUS StopLevel', display = display.none)" in source
    assert "plot(bus_target_1, 'BUS Target1', display = display.none)" in source
    assert "plot(bus_target_2, 'BUS Target2', display = display.none)" in source
    assert "'BUS LongTriggersRow', display = display.none" not in source
    assert "'BUS RiskPlanRow', display = display.none" not in source
    assert "'BUS DebugFlagsRow', display = display.none" not in source
    assert "'BUS VolExpandRow', display = display.none" not in source
    assert "'BUS DdviRow', display = display.none" not in source
    assert "'BUS LtfDeltaRow', display = display.none" not in source
    assert "'BUS SwingRow', display = display.none" not in source
    assert "'BUS MicroProfileRow', display = display.none" not in source
    assert "'BUS ReadyGateRow', display = display.none" not in source
    assert "'BUS StrictGateRow', display = display.none" not in source
    assert "'BUS ModulePackD', display = display.none" not in source
    assert "'BUS ReadyStrictPack', display = display.none" not in source
    assert "plot(resolve_bus_ltf_delta_state(show_dashboard_ltf_eff, ltf_sampling_active, ltf_price_only, ltf_volume_delta), 'BUS LtfDeltaState', display = display.none)" in source
    assert "plot(resolve_bus_safe_trend_state(bullish_trend_safe, bearish_trend_safe), 'BUS SafeTrendState', display = display.none)" in source
    assert "plot(resolve_bus_micro_profile_code(use_microstructure_profiles, micro_profile_text, micro_modifier_text), 'BUS MicroProfileCode', display = display.none)" in source
    assert "plot(resolve_bus_ready_blocker_code(long_ready_state, long_state.confirmed, lifecycle_ready_ok, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe), 'BUS ReadyBlockerCode', display = display.none)" in source
    assert "plot(resolve_bus_strict_blocker_code(long_entry_strict_state, long_ready_state, strict_signal_quality_gate_ok, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe), 'BUS StrictBlockerCode', display = display.none)" in source
    assert "plot(resolve_bus_vol_expansion_state(use_volatility_regime, vol_momentum_expanding_long, vol_stack_spread_rising), 'BUS VolExpansionState', display = display.none)" in source
    assert "plot(resolve_bus_ddvi_context_state(use_ddvi_context, ddvi_bias_ok, ddvi_bull_divergence_any, ddvi_lower_extreme_context), 'BUS DdviContextState', display = display.none)" in source
    assert 'resolve_bus_long_triggers_row(long_plan_active)' not in source
    assert 'resolve_bus_risk_plan_row(long_plan_active)' not in source
    assert 'resolve_bus_module_pack_d(' not in source
    assert "plot(long_state.trigger, 'BUS Trigger', display = display.none)" not in source
    assert "plot(long_state.invalidation_level, 'BUS Invalidation', display = display.none)" not in source
    assert 'resolve_bus_ready_strict_pack(' not in source


def test_core_engine_tracks_c8_event_edge_and_debug_owners() -> None:
    source = _read_core_source()

    assert 'resolve_long_ready_signal_state(bool long_ready_state, bool prior_bar_ready_state, int ready_state_rt_prev, bool ready_fired_this_bar, bool current_bar_is_new) =>' in source
    assert 'emit_long_engine_debug_logs(bool show_long_engine_debug_eff, string long_engine_debug_mode_eff, bool long_source_upgrade_now, bool long_arm_signal, bool long_confirm_signal, bool long_ready_signal, bool long_invalidate_signal, bool long_state_armed, bool long_state_confirmed, bool long_ready_state, string long_setup_source_display, string long_debug_event_source_display, int long_state_backing_zone_touch_count, int long_debug_event_touch_count, float long_state_trigger, float long_debug_event_trigger, float long_state_invalidation_level, float long_debug_event_invalidation, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert '[long_ready_state_rt_prev, long_ready_fired_this_bar, long_ready_signal] = resolve_long_ready_signal_state(long_ready_state, long_ready_state[1], long_ready_state_rt_prev, long_ready_fired_this_bar, barstate.isnew)' in source
    assert 'string long_debug_summary_text = emit_long_engine_debug_logs(show_long_engine_debug_eff, long_engine_debug_mode_eff, long_source_upgrade_now, long_arm_signal, long_confirm_signal, long_ready_signal, long_invalidate_signal, long_state.armed, long_state.confirmed, long_ready_state, long_setup_source_display, long_debug_event_source_display, long_state.backing_zone_touch_count, long_debug_event_touch_count, long_state.trigger, long_debug_event_trigger, long_state.invalidation_level, long_debug_event_invalidation, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, long_source_upgrade_reason, long_state.last_invalid_source, long_ready_blocker_text, long_strict_blocker_text)' in source
    assert 'if long_ready_state and long_ready_state_rt_prev == 0 and not long_ready_fired_this_bar' not in source
    assert 'emit_long_engine_debug_logs() =>' not in source


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
    assert 'resolve_long_ready_blocker_display_text(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
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
    assert '[debug_log_source_display, debug_log_touch_count, debug_log_trigger, debug_log_invalidation] = resolve_long_debug_event_values(long_invalidate_signal, long_setup_source_display, long_debug_event_source_display, long_state_backing_zone_touch_count, long_debug_event_touch_count, long_state_trigger, long_debug_event_trigger, long_state_invalidation_level, long_debug_event_invalidation)' in source
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
    assert "reason_code := 2" in source
    assert "ready_blocker_text := compose_blocked_status_text('Touch Count')" in source
    assert "strict_blocker_text := compose_blocked_status_text('Signal Quality')" in source
    assert 'strict_blocker_text := compose_need_ready_status_text(long_ready_blocker_text)' in source
    assert 'string helper_long_environment_focus_display = resolve_long_environment_focus_text(market_regime_gate_ok, vola_regime_gate_safe, event_risk_gate_ok_param)' in source
    assert 'resolve_long_ready_blocker_display_text(long_ready_state, long_setup_confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)' in source
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
