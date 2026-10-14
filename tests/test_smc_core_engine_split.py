from __future__ import annotations

import re

from tests.smc_manifest_test_utils import (
    ROOT,
    load_manifest,
    published_micro_profiles_import_line,
)

CORE_PATH = ROOT / 'SMC_Long_Dip_Suite.pine'
ENGINE_PRIVATE_PATH = ROOT / 'SMC++' / 'smc_engine_private.pine'
LIFECYCLE_PRIVATE_PATH = ROOT / 'SMC++' / 'smc_lifecycle_private.pine'
OBSERVABILITY_PRIVATE_PATH = ROOT / 'SMC++' / 'smc_observability_private.pine'
RESOLVERS_PATH = ROOT / 'SMC++' / 'smc_context_resolvers.pine'
PROFILE_ENGINE_PATH = ROOT / 'SMC++' / 'smc_profile_engine.pine'
UTILS_PATH = ROOT / 'SMC++' / 'smc_utils.pine'


MANIFEST = load_manifest()
EXPECTED_BUS_LABELS = list(MANIFEST.ENGINE_BUS_LABELS)


def _read_core_source() -> str:
    return CORE_PATH.read_text(encoding = 'utf-8')


def _read_engine_private_source() -> str:
    return ENGINE_PRIVATE_PATH.read_text(encoding = 'utf-8')


def _read_lifecycle_private_source() -> str:
    return LIFECYCLE_PRIVATE_PATH.read_text(encoding = 'utf-8')


def _read_observability_private_source() -> str:
    return OBSERVABILITY_PRIVATE_PATH.read_text(encoding = 'utf-8')


def _nonempty_lines_before(lines: list[str], index: int, count: int = 3) -> list[str]:
    previous: list[str] = []
    cursor = index - 1
    while cursor >= 0 and len(previous) < count:
        if lines[cursor].strip():
            previous.append(lines[cursor])
        cursor -= 1
    return previous


def test_core_engine_file_exists_and_uses_core_header() -> None:
    assert CORE_PATH.exists(), 'SMC_Long_Dip_Suite.pine must exist'
    source = _read_core_source()

    assert 'indicator("SMC Long-Dip Suite", overlay = true' in source
    assert 'indicator("Smart Money Concepts (Highly Advanced)", "SMC++", overlay = true' not in source


def test_core_engine_header_restores_import_prelude_and_blocks_stray_method_body() -> None:
    source = _read_core_source()
    lines = source.splitlines()
    indicator_index = next(i for i, line in enumerate(lines) if line.startswith('indicator("SMC Long-Dip Suite"'))
    following_nonempty = [line for line in lines[indicator_index + 1:] if line.strip()][:6]
    assert following_nonempty[:3] == [
        'import preuss_steffen/smc_core_types/5 as ct',
        'import preuss_steffen/smc_utils/3 as u',
        'import preuss_steffen/smc_draw/3 as d',
    ]
    assert not following_nonempty[0].startswith((' ', '\t'))
    assert 'method hide(pe.Profile this) =>' not in source

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
    assert published_micro_profiles_import_line() in source
    assert 'input.string(\'\', \'Clean reclaim tickers\'' not in source
    assert 'string clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS' in source
    assert 'string stop_hunt_tickers_effective = mp.STOP_HUNT_PRONE_TICKERS' in source
    assert 'string weak_afterhours_tickers_effective = mp.WEAK_AFTERHOURS_TICKERS' in source
    assert 'u.csv_has_symbol_token(clean_reclaim_tickers_effective, current_symbol_key, current_symbol_key_qualified)' in source

def test_core_engine_any_overlaps_guards_empty_arrays_before_reverse_iteration() -> None:
    engine_source = _read_engine_private_source()
    assert 'method any_overlaps(OrderBlock[] this, float range_top, float range_btm) =>' in engine_source
    assert 'if not na(this) and this.size() > 0' in engine_source
    assert 'for i = this.size() - 1 to 0' in engine_source
    assert 'if not na(this)\n        for i = this.size() - 1 to 0' not in engine_source

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
            or (f'na({array_name}) ? false :' in context and f'{array_name}.size() > 0' in context)
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

    assert 'cr.pack_bus_row(' not in source
    assert 'cr.pack_bus_four(' not in source
    assert 'cr.pack_bus_counts(' in source
    assert 'cr.pack_bus_trend_set(' not in source


def test_core_engine_uses_signal_quality_as_primary_gate() -> None:
    source = _read_core_source()
    lifecycle_source = _read_lifecycle_private_source()
    assert "var bool use_lean_signal_quality_gate = input.bool(true, 'Use Signal Quality Gate'" in source
    assert '// [v5.5b] Signal Quality is the primary quality surface; local context quality stays diagnostic only.' in source
    assert 'bool primary_quality_gate_ok = not use_lean_signal_quality_gate or signal_quality_ok' in source
    assert 'bool best_signal_quality_gate_ok = not use_lean_signal_quality_gate or signal_quality_good' in source
    assert 'bool strict_signal_quality_gate_ok = not use_lean_signal_quality_gate or signal_quality_high' in source
    assert 'export compute_long_environment_context(' in lifecycle_source
    assert '= ll.compute_long_environment_context(' in source
    assert 'export resolve_long_ready_projection_state(' in lifecycle_source
    assert '= ll.resolve_long_ready_projection_state(' in source
    assert 'export resolve_long_entry_projection_state(' in lifecycle_source
    assert '= ll.resolve_long_entry_projection_state(' in source
    assert 'bool combined_quality_gate_ok' not in source
    assert 'signal_bias_bullish' not in source

def test_core_engine_has_no_dashboard_or_alert_transport_layer() -> None:
    source = _read_core_source()

    # Static alertcondition() calls are allowed (WP-A2 MVP), but dynamic
    # alert infrastructure must remain absent.
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
    assert "plot(cr.resolve_bus_ltf_delta_state(" in source
    assert "plot(cr.resolve_bus_safe_trend_state(" in source
    assert "plot(cr.resolve_bus_micro_profile_code(" in source
    assert "plot(eng.resolve_bus_ready_blocker_code(" in source
    assert "plot(eng.resolve_bus_strict_blocker_code(" in source
    assert "plot(cr.resolve_bus_vol_expansion_state(" in source
    assert "plot(cr.resolve_bus_ddvi_context_state(" in source
    assert "plot(cr.pack_bus_counts(" in source
    assert "plot(cr.resolve_bus_lean_pack_b(" in source
    assert "'BUS ReadyGateRow', display = display.none" not in source
    assert "'BUS StrictGateRow', display = display.none" not in source
    assert "'BUS ReadyStrictPack', display = display.none" not in source
    assert source.endswith('/////////////////////////////////////////////////////////////////////////////////')
    assert "'BUS PresetVolRegimeDef', display = display.none)\n\n// ── Mini Health Badge (v5.5a) ──" in source

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
    lifecycle_source = _read_lifecycle_private_source()
    engine_source = _read_engine_private_source()
    for helper in ('resolve_long_ready_lifecycle_reason_code', 'resolve_long_ready_gate_reason_code', 'resolve_long_ready_reason_code', 'resolve_long_strict_reason_code', 'resolve_long_execution_blocker_state'):
        assert f'export {helper}(' in lifecycle_source
    assert 'export resolve_bus_ready_blocker_code(' in engine_source
    assert 'export resolve_bus_strict_blocker_code(' in engine_source
    assert '= ll.resolve_long_execution_blocker_state(' in source
    assert 'plot(eng.resolve_bus_ready_blocker_code(' in source
    assert 'plot(eng.resolve_bus_strict_blocker_code(' in source
    assert 'resolve_bus_ready_gate_row(' not in source
    assert 'resolve_bus_strict_gate_row(' not in source

def test_core_engine_tracks_c4_source_and_bus_pack_helpers() -> None:
    source = _read_core_source()
    engine_source = _read_engine_private_source()
    lifecycle_source = _read_lifecycle_private_source()
    resolver_source = RESOLVERS_PATH.read_text(encoding='utf-8')
    assert 'export compute_long_source_upgrade_state(' in engine_source
    assert 'export resolve_long_source_runtime_state(' in lifecycle_source
    assert 'export resolve_long_invalidation_state(' in lifecycle_source
    assert '= eng.compute_long_source_upgrade_state(' in source
    assert '= ll.resolve_long_source_runtime_state(' in source
    assert '= ll.resolve_long_invalidation_state(' in source
    for helper in ('resolve_bus_ltf_delta_state', 'resolve_bus_safe_trend_state', 'resolve_bus_micro_profile_code', 'resolve_bus_vol_expansion_state', 'resolve_bus_ddvi_context_state', 'resolve_bus_stretch_support_mask'):
        assert f'{helper}(' in resolver_source
    assert "'BUS EnginePack', display = display.none" not in source

def test_core_engine_tracks_c5_arm_and_confirm_owner_helpers() -> None:
    source = _read_core_source()
    engine_source = _read_engine_private_source()
    lifecycle_source = _read_lifecycle_private_source()
    for helper in ('resolve_long_arm_source_state', 'resolve_long_arm_transition_payload'):
        assert f'export {helper}(' in engine_source
        assert f'= eng.{helper}(' in source
    for helper in ('compute_long_arm_prequality_ok', 'compute_long_arm_should_trigger', 'resolve_long_confirm_break_state', 'resolve_long_confirm_structure_state', 'compute_long_confirm_transition_state'):
        assert f'export {helper}(' in lifecycle_source
        assert f'= ll.{helper}(' in source
    assert 'if long_should_confirm\n    long_state.confirm(bar_index)' in source

def test_core_engine_tracks_c6_plan_overhead_and_risk_plan_owners() -> None:
    source = _read_core_source()
    lifecycle_source = _read_lifecycle_private_source()
    assert 'export compute_long_plan_state(' in lifecycle_source
    assert 'export compute_long_risk_plan_state(' in lifecycle_source
    assert 'long_plan_active := ll.compute_long_plan_state(' in source
    assert '= ll.compute_long_risk_plan_state(' in source
    assert 'compute_long_overhead_context(' in source
    assert '= compute_long_overhead_context(' in source
    assert 'compute_overhead_context() =>' not in source

def test_core_engine_tracks_c7_execution_and_bus_projection_owners() -> None:
    source = _read_core_source()
    lifecycle_source = _read_lifecycle_private_source()
    engine_source = _read_engine_private_source()
    for helper in ('resolve_long_ready_projection_state', 'resolve_long_entry_projection_state', 'resolve_long_execution_blocker_state', 'resolve_long_clean_tier', 'resolve_long_bus_plan_levels'):
        assert f'export {helper}(' in lifecycle_source
        assert f'= ll.{helper}(' in source
    assert 'export resolve_bus_ready_blocker_code(' in engine_source
    assert 'export resolve_bus_strict_blocker_code(' in engine_source
    assert "plot(eng.resolve_bus_ready_blocker_code(" in source
    assert "plot(eng.resolve_bus_strict_blocker_code(" in source
    for label in ('Trigger', 'Invalidation', 'StopLevel', 'Target1', 'Target2'):
        assert f"'BUS {label}', display = display.none" in source

def test_core_engine_tracks_c8_event_edge_and_debug_owners() -> None:
    source = _read_core_source()
    observability_source = _read_observability_private_source()
    assert 'import preuss_steffen/smc_observability_private/3 as obv' in source
    assert 'export resolve_long_ready_signal_state(' in observability_source
    assert 'export emit_long_engine_debug_logs(' in observability_source
    assert '= obv.resolve_long_ready_signal_state(' in source
    assert 'obv.emit_long_engine_debug_logs(' in source
    assert 'dynamic_alert_seen_keys' not in source

def test_core_engine_extracts_remaining_display_helpers() -> None:
    source = _read_core_source()
    engine_source = _read_engine_private_source()
    lifecycle_source = _read_lifecycle_private_source()
    for helper in ('resolve_long_source_text', 'compose_long_setup_source_display', 'describe_long_freshness', 'describe_long_source_state', 'describe_long_zone_quality', 'compose_long_alert_text_suffixes', 'resolve_long_visual_state', 'resolve_core_product_state'):
        assert f'export {helper}(' in engine_source
    assert 'eng.resolve_long_source_text(' in source
    assert 'eng.compose_long_setup_source_display(' in source
    assert 'eng.describe_long_freshness(' in source
    assert 'eng.describe_long_source_state(' in source
    assert 'eng.describe_long_zone_quality(' in source
    assert 'eng.compose_long_alert_text_suffixes(' in source
    assert 'eng.resolve_long_visual_state(' in source
    assert 'export resolve_long_strict_blocker_display_text(' in lifecycle_source
    assert 'resolve_long_source_text(int long_source_kind) =>' not in source

# ── Export-surface coverage for split libraries ──────────────────────────────


def _read_profile_engine_source() -> str:
    return PROFILE_ENGINE_PATH.read_text(encoding='utf-8')


def _read_utils_source() -> str:
    return UTILS_PATH.read_text(encoding='utf-8')


def test_profile_engine_exports_types_and_methods() -> None:
    """Guard that smc_profile_engine.pine exports its full type + method surface."""
    source = _read_profile_engine_source()

    # ── Exported types ──
    assert 'export type Bucket' in source
    assert 'export type ProfileConfig' in source
    assert 'export type Profile' in source

    # ── Bucket methods ──
    assert 'export method update(Bucket this, float top, float bottom, float value, float fraction) =>' in source
    assert 'export method update(Bucket this, float value, float fraction) =>' in source

    # ── ProfileConfig methods ──
    assert 'export method init(ProfileConfig this) =>' in source

    # ── Profile methods ──
    assert 'export method apply_style(Profile this, ProfileConfig args) =>' in source
    assert 'export method delete(Profile this) =>' in source
    assert 'export method hide(Profile this) =>' in source
    assert 'export method init(Profile this, bool update_buckets = false) =>' in source
    assert 'export method calculate(Profile this, simple int use_open_close_data_for_ranges_shorter_than_bars = 4) =>' in source
    assert 'export method update(Profile this, float[] opens = na, float[] highs = na, float[] lows = na, float[] closes = na, float[] values = na) =>' in source
    assert 'export method draw(Profile this, ProfileConfig config, int left = na, int right = na, bool extend_only = true, simple bool force_overlay = false, string poc_text_override = na) =>' in source

    # ── Standalone exported helpers ──
    assert 'export normalize_profile_resolution(int resolution) =>' in source
    assert 'export normalize_profile_vah_pc(float vah_pc, float val_pc) =>' in source
    assert 'export normalize_profile_val_pc(float vah_pc, float val_pc) =>' in source
    assert 'export profile_data_ready(float[] highs, float[] lows, float[] values) =>' in source
    assert 'export is_impulse_candle_now(float candle_body, float impulse_candle_size) =>' in source
    assert 'export is_indecision_candle_now(' in source
    assert 'export profile_features_enabled(' in source
    assert 'export create_profile(' in source


def test_utils_exports_moved_helpers() -> None:
    """Guard that smc_utils.pine exports the helpers moved during WP-SPLIT3."""
    source = _read_utils_source()

    # ── WP-SPLIT3 moved helpers (previously embedded in Core Engine) ──
    assert 'export smc_lib_atr(simple int length) =>' in source
    assert 'export smc_lib_ehma(float source, simple int length) =>' in source
    assert 'export smc_lib_thma(float source, simple int length) =>' in source
    assert 'export smc_lib_get_ma(' in source
    assert 'export smc_lib_bb(float source, simple int length, float mult, simple ct.SmcLibMovingAverage select_ma) =>' in source
    assert 'export smc_lib_dmi(simple int di_length = 17, simple int adx_smoothing = 14) =>' in source
    assert 'export smc_lib_detect_divergence(' in source

    # ── Pre-existing utility exports that must remain stable ──
    assert 'export in_range(float value, float max, float min = 0.0) =>' in source
    assert 'export trend_text(int trend_value) =>' in source
    assert 'export format_level(float value) =>' in source
    assert 'export edge(bool condition) =>' in source
    assert 'export ltf_stats(float[] opens, float[] closes, float[] volumes) =>' in source
    assert 'export external_trend_gate(' in source
    assert 'export external_breadth_gate(' in source
    assert 'export normalize_csv_token(string s) =>' in source
    assert 'export csv_has_symbol_token(' in source
    assert 'export htf_fvg_key(' in source
    assert 'export push_capped_label(' in source
    assert 'export trim_label_history(' in source
