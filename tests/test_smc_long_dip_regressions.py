from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
SMC_PATH = ROOT / 'SMC++.pine'


def _read_smc_source() -> str:
    return SMC_PATH.read_text(encoding = 'utf-8')


def _extract_function_body(source: str, function_name: str) -> str:
    start = source.find(f'{function_name}(')
    assert start != -1, f'{function_name} not found'
    body_start = source.index('\n', start) + 1
    lines = []
    for line in source[body_start:].splitlines():
        if line.strip() == '' or line.startswith('    '):
            lines.append(line)
        else:
            break
    return '\n'.join(lines)


def test_plot_equal_level_uses_named_label_arguments_for_font_family() -> None:
    source = _read_smc_source()
    body = _extract_function_body(source, 'plot_equal_level')

    named_calls = re.findall(r'label\.new\([^\n]+text_font_family\s*=\s*label_args\.text_font_family', body)
    assert len(named_calls) == 2, 'Expected both equal-level label.new calls to use named text_font_family'
    assert 'label_args.text_align, label_args.text_font_family' not in body


def test_atr_helper_uses_deterministic_warmup_accumulator() -> None:
    source = _read_smc_source()
    body = _extract_function_body(source, 'smc_lib_atr')

    assert 'float atr_value = ta.atr(length)' in body
    assert 'float tr_cum = ta.cum(ta.tr(true))' in body
    assert 'if bar_index < length' in body
    assert 'atr_value := tr_cum / (bar_index + 1)' in body
    assert 'var float sum = 0.0' not in body
    assert 'sum += ta.tr(true)' not in body


def test_strict_ltf_fallback_is_limited_to_missing_or_unverifiable_ltf() -> None:
    source = _read_smc_source()

    assert "allow_strict_entry_without_ltf = input.bool(false, 'Allow strict entry without LTF when unavailable'" in source
    assert 'Strict normally prefers confirmed LTF volume context; this fallback relaxes only that sub-requirement while the remaining strict gates stay active.' in source
    assert 'bool strict_ltf_unavailable = use_ltf_for_strict_entry and not strict_ltf_available' in source
    assert 'bool strict_ltf_unverifiable = use_ltf_for_strict_entry and not barstate.isrealtime and not strict_ltf_available' in source
    assert 'bool strict_entry_ltf_ok = not use_ltf_for_strict_entry or (strict_ltf_available and ltf_volume_delta >= 0) or (allow_strict_entry_without_ltf and (strict_ltf_unavailable or strict_ltf_unverifiable))' in source


def test_relvol_fallback_stays_split_from_strict_volume_scoring() -> None:
    source = _read_smc_source()

    assert 'score thresholds shrink by the unavailable RelVol component. Strict still prefers confirmed volume-backed context, but can be partially relaxed when the dedicated strict-entry LTF fallback is also enabled.' in source
    assert 'bool relvol_ok = not use_rel_volume ? true : not relvol_data_ok ? allow_relvol_without_volume_data : not na(rel_volume) and rel_volume >= effective_relvol_good' in source
    assert 'bool relvol_score_ok = not use_rel_volume ? true : relvol_data_ok and not na(rel_volume) and rel_volume >= effective_relvol_good' in source
    assert 'bool relvol_score_unavailable = use_rel_volume and not relvol_data_ok and allow_relvol_without_volume_data' in source


def test_ob_profile_freezes_when_volume_quality_is_weak() -> None:
    source = _read_smc_source()

    assert "bool use_ob_profile_effective = use_ob_profile and volume_feed_quality_ok" in source
    assert 'bool collect_ob_profile_current_bar = use_ob_profile_effective and volume_current_bar_ok' in source
    assert "'OB profiles keep last valid shape'" in source
    assert 'capture_profile = collect_ob_profile_current_bar' in source
    assert 'update_profile_current_bar = collect_ob_profile_current_bar' in source


def test_signal_and_long_state_contract_are_declared_for_safe_refactors() -> None:
    source = _read_smc_source()

    assert '// Signal / state contract' in source
    assert '// - *_raw      : raw condition, may be intrabar/transient' in source
    assert '// - *_latched  : intrabar-persisted event/state until bar close' in source
    assert 'type LongLifecycleState' in source
    assert "var LongLifecycleState long_state = LongLifecycleState.new(false, false, na, na, na, na, LONG_SOURCE_NONE, LONG_SOURCE_NONE, na, 0, LONG_SOURCE_NONE, na, na, na, 0, na, 0, 'None', na)" in source
    assert 'method clear(LongLifecycleState this) =>' in source
    assert 'method arm(LongLifecycleState this, int arm_bar_index, float trigger, float invalidation_level, int entry_origin_source, int backing_zone_kind, int backing_zone_id, int backing_zone_touch_count, int locked_source_kind, int locked_source_id, float locked_source_top, float locked_source_bottom, int locked_source_touch_count, int locked_source_last_touch_bar_index) =>' in source
    assert 'method confirm(LongLifecycleState this, int confirm_bar_index) =>' in source
    assert 'method invalidate(LongLifecycleState this, string reason, float level) =>' in source
    assert 'sync_long_state_from_legacy(LongLifecycleState st, bool armed, bool confirmed, int arm_bar_index, int confirm_bar_index, float trigger, float invalidation_level, int entry_origin_source, int backing_zone_kind, int backing_zone_id, int backing_zone_touch_count, int locked_source_kind, int locked_source_id, float locked_source_top, float locked_source_bottom, int locked_source_touch_count, int locked_source_last_touch_bar_index, int setup_serial, string last_invalid_source, float last_invalid_level) =>' in source
    assert 'project_long_state(LongLifecycleState st) =>' in source
    assert 'validate_long_state(LongLifecycleState st, bool enabled = true) =>' in source
    assert 'sync_long_state_from_legacy(long_state, long_setup_armed, long_setup_confirmed, long_setup_arm_bar_index, long_confirm_bar_index, long_setup_trigger, long_invalidation_level, long_entry_origin_source, long_setup_backing_zone_kind, long_setup_backing_zone_id, long_setup_backing_zone_touch_count, long_locked_source_kind, long_locked_source_id, long_locked_source_top, long_locked_source_bottom, long_locked_source_touch_count, long_locked_source_last_touch_bar_index, long_setup_serial, long_last_invalid_source, long_last_invalid_level)' in source
    assert 'validate_long_state(long_state, show_long_engine_debug)' in source


def test_backing_zone_identity_and_touch_count_persist_after_arm() -> None:
    source = _read_smc_source()

    assert 'int LONG_SOURCE_OB = 1' in source
    assert 'int LONG_SOURCE_FVG = 2' in source
    assert 'select_long_arm_backing_zone_touch_count(int arm_backing_zone_kind, int arm_backing_zone_id, int active_ob_touch_id, int active_ob_touch_count, int touched_bull_ob_id, int touched_bull_ob_touch_count, int active_fvg_touch_id, int active_fvg_touch_count, int touched_bull_fvg_id, int touched_bull_fvg_touch_count) =>' in source
    assert 'int long_arm_backing_zone_touch_count = select_long_arm_backing_zone_touch_count(arm_backing_zone_kind, arm_backing_zone_id, active_ob_touch_id, active_ob_touch_count, touched_bull_ob_id, touched_bull_ob_touch_count, active_fvg_touch_id, active_fvg_touch_count, touched_bull_fvg_id, touched_bull_fvg_touch_count)' in source
    assert 'resolve_long_zone_id(int long_zone_kind, int long_zone_id) =>' in source
    assert 'int long_arm_locked_source_id = resolve_long_zone_id(arm_backing_zone_kind, arm_backing_zone_id)' in source
    assert 'long_state.arm(bar_index, arm_trigger_candidate, arm_invalidation_candidate, arm_source_kind, arm_backing_zone_kind, arm_backing_zone_id, long_arm_backing_zone_touch_count, arm_backing_zone_kind, long_arm_locked_source_id, long_arm_locked_source_top, long_arm_locked_source_bottom, long_arm_backing_zone_touch_count, long_arm_locked_source_last_touch_bar_index)' in source
    assert 'method sync_locked_tracking(LongLifecycleState this, int backing_zone_kind, int backing_zone_id, int locked_source_kind, int locked_source_id, float locked_source_top, float locked_source_bottom, int locked_source_touch_count, int locked_source_last_touch_bar_index) =>' in source


def test_invalidation_path_records_specific_reason_and_clears_setup_state() -> None:
    source = _read_smc_source()

    assert 'resolve_long_invalidation_reason(bool long_source_broken, bool long_source_lost, bool long_setup_expired, bool long_confirm_expired, int long_validation_source, int long_entry_origin_source, string long_setup_source_display) =>' in source
    assert 'resolve_long_validation_source(int long_locked_source_kind) =>' in source
    assert "string long_validation_source_text = resolve_long_source_text(long_validation_source)" in source
    assert "string long_entry_origin_source_text = resolve_long_source_text(long_entry_origin_source)" in source
    assert "long_source_broken ? long_validation_source_text + ' source invalidated'" in source
    assert "long_source_lost ? long_validation_source_text + ' backing zone lost'" in source
    assert "long_setup_expired ? long_entry_origin_source_text + ' setup expired'" in source
    assert "long_confirm_expired ? long_entry_origin_source_text + ' confirm expired'" in source
    assert 'int long_validation_source_now = resolve_long_validation_source(long_locked_source_kind_final)' in source
    assert 'string long_setup_source_display_now = compose_long_setup_source_display(long_entry_origin_source, long_validation_source_now)' in source
    assert 'string long_invalidation_reason = resolve_long_invalidation_reason(long_source_broken, long_source_lost, long_setup_expired, long_confirm_expired, long_validation_source_now, long_entry_origin_source, long_setup_source_display_now)' in source
    assert 'long_invalidate_signal := long_setup_armed or long_setup_confirmed' in source
    assert 'long_state.invalidate(long_invalidation_reason, long_invalidation_level)' in source
    assert '[projected_long_setup_armed, projected_long_setup_confirmed, projected_long_setup_arm_bar_index, projected_long_confirm_bar_index, projected_long_setup_trigger, projected_long_invalidation_level, projected_long_entry_origin_source, projected_long_setup_backing_zone_kind, projected_long_setup_backing_zone_id, projected_long_setup_backing_zone_touch_count, projected_long_locked_source_kind, projected_long_locked_source_id, projected_long_locked_source_top, projected_long_locked_source_bottom, projected_long_locked_source_touch_count, projected_long_locked_source_last_touch_bar_index, projected_long_setup_serial, projected_long_last_invalid_source, projected_long_last_invalid_level] = project_long_state(long_state)' in source
    assert 'long_setup_armed := projected_long_setup_armed' in source
    assert "long_source_broken ? str.format('{0} source invalidated', long_validation_source)" not in source
    assert "long_source_lost ? str.format('{0} backing zone lost', long_validation_source)" not in source


def test_ob_confirmed_profiles_are_rebuilt_from_copied_ltf_data() -> None:
    source = _read_smc_source()

    assert source.count('bear_ob_confirmed.create_profile()') >= 2
    assert source.count('bull_ob_confirmed.create_profile()') >= 2
    assert 'bear_ob_confirmed.profile := bull_ob.profile' not in source
    assert 'bull_ob_confirmed.profile := bear_ob.profile' not in source
    assert 'bull_ob_confirmed.profile := bull_ob.profile' not in source
    assert 'bear_ob_confirmed.profile := bear_ob.profile' not in source
    assert 'bear_ob_confirmed.ltf_open := bull_ob.ltf_open.copy()' in source
    assert 'bull_ob_confirmed.ltf_open := bear_ob.ltf_open.copy()' in source
    assert 'resolve_confirmed_ob_break_price(bool align_edge_to_value_area, bool align_break_price_to_poc, float original_top, float original_bottom, float confirmed_top, float confirmed_bottom, float current_break_price) =>' in source
    assert 'bull_ob_confirmed.break_price := resolve_confirmed_ob_break_price(align_edge_to_value_area, align_break_price_to_poc, bull_ob.left_top.price, bull_ob.right_bottom.price, bull_ob_confirmed.left_top.price, bull_ob_confirmed.right_bottom.price, bull_ob_confirmed.break_price)' in source
    assert 'bear_ob_confirmed.break_price := resolve_confirmed_ob_break_price(align_edge_to_value_area, align_break_price_to_poc, bear_ob.left_top.price, bear_ob.right_bottom.price, bear_ob_confirmed.left_top.price, bear_ob_confirmed.right_bottom.price, bear_ob_confirmed.break_price)' in source
    assert 'bull_ob_confirmed.break_price := resolve_confirmed_ob_break_price(align_edge_to_value_area, align_break_price_to_poc, _check_top[2], _check_btm[2], bull_ob_confirmed.left_top.price, bull_ob_confirmed.right_bottom.price, bull_ob_confirmed.break_price)' in source
    assert 'bear_ob_confirmed.break_price := resolve_confirmed_ob_break_price(align_edge_to_value_area, align_break_price_to_poc, _check_top[2], _check_btm[2], bear_ob_confirmed.left_top.price, bear_ob_confirmed.right_bottom.price, bear_ob_confirmed.break_price)' in source


def test_udt_render_and_draw_helpers_guard_na_before_field_access() -> None:
    source = _read_smc_source()

    assert 'method delete(OrderBlock this) =>' in source
    assert 'this.plot := na' in source
    assert 'this.profile := na' in source
    assert 'method delete(Profile this) =>' in source
    assert 'this.hidden := false' in source
    # Draw methods moved to smc_draw library (d.SmcBox, d.SmcLabel)
    assert 'import preuss_steffen/smc_draw/1 as d' in source
    assert 'method rendered_right_time(OrderBlock this, bool extend_until_broken = true) =>' in source
    assert 'int base_right_time = math.max(this.left_top.time, this.right_bottom.time)' in source
    assert 'method rendered_right_time(FVG this, bool extend_until_filled = true) =>' in source
    assert 'int effective_fill_time = effective_live_event_time(this.fill_time, base_right_time)' in source


def test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods() -> None:
    source = _read_smc_source()

    assert 'draw(ob_blocks_bull, ob_config_bull, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    # bear draw calls removed (Patch 4)
    assert 'draw(fvgs_bull, fvg_config_bull, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    assert 'draw(htf_fvg_buffer_bull, htf_fvg_config_bull, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    assert 'contains_id(ob_blocks_bull, touched_bull_ob_id)' in source
    assert 'get_by_id(ob_blocks_bull, touched_bull_ob_id)' in source
    assert 'contains_id(filled_fvgs_bull, long_locked_source_id_final)' in source
    assert 'array.size(filled_fvgs_new_bull) > 0' in source
    assert 'FVG bull_filled_alert_gap = bullish_fvg_filled_alert ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1) : na' in source
    assert 'float bull_filled_alert_level = resolve_fvg_alert_level(bull_filled_alert_gap)' in source
    assert 'array.size(ob_blocks_bull) > 0' in source
    assert 'OrderBlock last_bull_ob = array.size(ob_blocks_bull) > 0 ? array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1) : na' in source
    assert 'last_bull_ob_break_level = resolve_ob_alert_level(last_bull_ob)' in source
    assert 'bull_ob_candidate = array.get(ob_blocks_bull, i)' in source
    assert 'array.clear(ob_discarded_bull)' in source
    assert 'array.clear(fvg_discarded_bull)' in source
    assert 'array.clear(htf_fvg_buffer_bull_discarded)' in source
    assert 'ob_blocks_bull.draw(' not in source
    assert 'fvgs_bull.draw(' not in source
    assert 'htf_fvg_buffer_bull.draw(' not in source
    assert 'array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1).break_price' not in source
    assert 'array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1).fill_target_level' not in source
    assert 'filled_fvgs_new_bull.size()' not in source
    assert 'filled_fvgs_new_bull.last()' not in source
    assert 'ob_blocks_bull.size()' not in source
    assert 'ob_blocks_bull.get(' not in source
    assert 'ob_discarded_bull.clear()' not in source
    assert 'fvg_discarded_bull.clear()' not in source
    assert 'htf_fvg_buffer_bull_discarded.clear()' not in source


def test_fvg_hide_and_orderblock_reset_are_cleanup_consistent() -> None:
    source = _read_smc_source()

    assert 'method hide(FVG this) =>' in source
    assert 'this.plot_fill_target_label.hide()' in source
    assert 'this.plot_fill_target_label.plot.set_text(na)' not in source
    assert 'method reset_tracking(OrderBlock this) =>' in source
    assert 'this.broken_time := na' in source
    assert 'this.broken_index := na' in source


def test_invalidated_alert_has_single_preset_definition_without_failed_alias() -> None:
    source = _read_smc_source()

    preset_defs = re.findall(r"alertcondition\(long_invalidate_alert_event, 'Long Invalidated', 'SMC\+\+: Long setup invalidated\.'\)", source)
    assert len(preset_defs) == 1, 'Expected exactly one Long Invalidated preset definition'
    assert "alertcondition(long_invalidate_alert_event, 'Long Dip Failed'" not in source
    assert "alertcondition(long_invalidated_close_safe, 'Long Invalidated (Close Safe)', 'SMC++: Long setup invalidated at candle close.')" in source
    assert "alertcondition(alert_long_watchlist_event_latched, 'Long Dip Watchlist', 'SMC++: Watchlist state active. Bullish trend with an active pullback zone.')" in source
    assert "alertcondition(bull_bos_sig, 'Bullish BOS Detected', 'SMC++: Bullish break of structure detected.')" in source
    assert "alertcondition(directional_trend_started, 'Trend Direction Changed', 'SMC++: Structure trend changed direction.')" in source


def test_confirmed_only_touch_state_updates_are_gated_by_state_update_bar_ok() -> None:
    source = _read_smc_source()

    assert "bool state_update_bar_ok = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? true : barstate.isconfirmed" in source
    assert 'if state_update_bar_ok and ob_zone_touch_event' in source
    assert 'if state_update_bar_ok and fvg_zone_touch_event' in source
    assert 'if state_update_bar_ok and zone_touch_event' in source
    assert 'if state_update_bar_ok and zone_touch_now and last_zone_touch_bar != bar_index and not na(zone_touch_tracking_id)' in source
    assert 'if state_update_bar_ok and ob_touch_now and last_ob_touch_bar != bar_index and not na(active_bull_ob_id)' in source
    assert 'if state_update_bar_ok and fvg_touch_now and last_fvg_touch_bar != bar_index and not na(active_bull_fvg_id)' in source


def test_active_backing_zones_are_protected_from_cleanup_rotation() -> None:
    source = _read_smc_source()

    assert '_ob_backing_zone_id = long_setup_backing_zone_kind == LONG_SOURCE_OB ? long_setup_backing_zone_id : na' in source
    assert 'protected_bull_id = _ob_backing_zone_id' in source
    assert '_fvg_backing_zone_id = long_setup_backing_zone_kind == LONG_SOURCE_FVG ? long_setup_backing_zone_id : na' in source
    assert 'tracking_blocks_bull.remove_insignificant(min_block_size, max_block_size, discarded_blocks_bull, protected_bull_id)' in source
    assert 'buffer_bull.clear_filled(buffer_bull_filled, buffer_bull_filled_new, filled_max_keep, buffer_bull_discarded, protected_bull_id)' in source
    assert 'buffer_bull.remove_insignificant(size_threshold, buffer_bull_discarded, protected_bull_id)' in source
    assert 'bool is_protected = not na(protected_id) and block.id == protected_id' in source
    assert 'bool is_protected = not na(protected_id) and fvg.id == protected_id' in source


def test_quality_score_api_replaces_legacy_probability_naming() -> None:
    source = _read_smc_source()

    assert 'float quality_score                          = 0' in source
    assert 'bool show_quality_score = false' in source
    assert 'float quality_score = na' in source
    assert 'ob_quality_score(OrderBlock block) =>' in source
    assert 'fvg_quality_score(FVG fvg, float size_threshold = 0.0) =>' in source
    assert 'config.show_quality_score ? ob_quality_score(this) : 0.0' in source
    assert 'config.show_quality_score ? fvg_quality_score(this, this.left_top.price - this.right_bottom.price) : 0.0' in source
    assert "str.format(' (Q {0,number,percent})', ob_quality)" in source
    assert "str.format('(Q {0,number,percent})', fvg_quality)" in source
    assert 'show_probability' not in source
    assert 'probability' not in source


def test_armed_stage_can_be_optionally_tightened() -> None:
    source = _read_smc_source()

    assert "var bool tighten_armed_stage = input.bool(true, 'Tighten Armed Stage'" in source
    assert 'bool armed_prequality_ok = not tighten_armed_stage or (bullish_trend_safe and micro_session_gate_ok and zone_touch_quality_ok and bull_close_strong and ema_support_ok)' in source
    assert 'and armed_prequality_ok' in source


def test_breadth_gate_supports_multiple_modes() -> None:
    source = _read_smc_source()

    assert "var string breadth_gate_mode = input.string('Above Zero', 'Breadth Mode', options = ['Above Zero', 'Above EMA', 'Rising']" in source
    assert "var int breadth_gate_len = input.int(20, 'Breadth EMA Len', minval = 2" in source


def test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard() -> None:
    source = _read_smc_source()

    assert "var bool show_long_engine_debug = input.bool(false, 'Show long engine debug'" in source
    assert "var string long_engine_debug_mode = input.string('Compact', 'Detail', options = ['Compact', 'Full']" in source
    assert "var bool show_ob_debug = input.bool(false, 'Show OB debug'" in source
    assert "var bool show_fvg_debug = input.bool(false, 'Show FVG debug'" in source
    assert 'compose_enabled_debug_modules_text(bool show_ob_debug, bool show_fvg_debug, bool show_long_engine_debug, string long_engine_debug_mode) =>' in source
    assert "debug_mode_is_full(string long_engine_debug_mode) =>" in source
    assert 'resolve_long_ready_blocker_text(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert "resolve_long_strict_blocker_text(bool long_entry_strict_state, bool long_ready_state, string long_ready_blocker_text, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>" in source
    assert "not session_structure_gate_ok ? 'Blocked: Session Gate'" in source
    assert "not market_regime_gate_ok ? 'Blocked: Market Gate'" in source
    assert "long_ready_state ? 'Passed' : not long_setup_confirmed ? 'Awaiting Confirm'" in source
    assert "not ddvi_ready_ok_safe ? 'Blocked: DDVI Context' : 'Eligible'" in source
    assert "long_entry_strict_state ? 'Passed' : not long_ready_state ? 'Need Ready: ' + long_ready_blocker_text" in source
    assert "not strict_entry_ltf_ok ? 'Blocked: LTF Confirmation'" in source
    assert 'compose_long_debug_summary_text(string long_engine_debug_mode, bool long_setup_armed, bool long_setup_confirmed, bool long_ready_state, string long_setup_source_display, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, int long_setup_backing_zone_touch_count, bool long_source_upgrade_now, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_engine_debug_label_text(string long_engine_debug_mode, string long_setup_text, string long_visual_text, string long_setup_source_display, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string overhead_text, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, bool long_source_upgrade_now, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert "log.info('{0}', compose_long_engine_event_log(long_engine_debug_mode, 'LONG ARMED'" in source
    assert "log.info('{0}', compose_long_engine_event_log(long_engine_debug_mode, 'LONG INVALID'" in source
    assert "plotshape(show_ob_debug and ob_zone_touch_event, title = 'OB Zone Touch Debug'" in source
    assert "plotshape(show_fvg_debug and bullish_fvg_filled_alert, title = 'Bullish FVG Filled Debug'" in source
    assert "plotshape(show_long_engine_debug and long_source_upgrade_now, title = 'Long Source Upgrade Debug'" in source
    assert "string long_ready_blocker_text = resolve_long_ready_blocker_text(long_ready_state, long_setup_confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)" in source
    assert "string long_strict_blocker_text = resolve_long_strict_blocker_text(long_entry_strict_state, long_ready_state, long_ready_blocker_text, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)" in source
    assert "string long_engine_debug_label_text = compose_long_engine_debug_label_text(long_engine_debug_mode, long_setup_text, long_visual_text, long_setup_source_display, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, overhead_text, long_setup_trigger, long_invalidation_level, long_setup_backing_zone_touch_count, long_source_upgrade_now, long_last_invalid_source, long_ready_blocker_text, long_strict_blocker_text)" in source
    assert "dashboard_row(tbl, 44, 'Ready Gate', long_ready_blocker_text" in source
    assert "dashboard_row(tbl, 45, 'Strict Gate', long_strict_blocker_text" in source
    assert "dashboard_row(tbl, 46, 'Debug Flags', compose_enabled_debug_modules_text(show_ob_debug, show_fvg_debug, show_long_engine_debug, long_engine_debug_mode)" in source
    assert "dashboard_row(tbl, 47, 'Long Debug', show_long_engine_debug ? long_debug_summary_text : 'off'" in source
    assert 'var table _smc_dashboard = table.new(position.bottom_right, 2, 48, border_width = 0)' in source
    assert 'table.clear(_smc_dashboard, 0, 0, 1, 47)' in source
    assert "[breadth_missing_calc, breadth_gate_ok_calc] = u.external_breadth_gate(breadth_gate_symbol, breadth_gate_mode, breadth_gate_len)" in source


def test_prepare_order_block_confirmation_runs_each_calc_without_shadowing_state() -> None:
    source = _read_smc_source()

    assert 'prepare_order_block_confirmation(OrderBlock block, float min_block_size, float max_block_size, bool round_size_bounds, bool update_profile_current_bar, bool align_edge_to_value_area, bool align_break_price_to_poc, bool should_prepare) =>' in source
    assert 'if should_prepare' in source
    assert 'if should_prepare and update_profile_current_bar and (align_edge_to_value_area or align_break_price_to_poc)' in source
    assert 'bool bull_prepare_confirmation = enabled and barstate.isconfirmed and bull_ob.trailing and bull_ob.extending and bull_ob.left_top.index < bar_index and is_red and not is_indecision and u.in_range(close, bull_ob.left_top.price, bull_ob.right_bottom.price)' in source
    assert 'bool bear_prepare_confirmation = enabled and barstate.isconfirmed and bear_ob.trailing and bear_ob.extending and bear_ob.left_top.index < bar_index and is_green and not is_indecision and u.in_range(close, bear_ob.left_top.price, bear_ob.right_bottom.price)' in source
    assert '[prepared_ob_size_min_bull, prepared_ob_size_max_bull] = prepare_order_block_confirmation(bull_ob, min_block_size, max_block_size, true, update_profile_current_bar, align_edge_to_value_area, align_break_price_to_poc, bull_prepare_confirmation)' in source
    assert '[prepared_ob_size_min_bear, prepared_ob_size_max_bear] = prepare_order_block_confirmation(bear_ob, min_block_size, max_block_size, false, update_profile_current_bar, align_edge_to_value_area, align_break_price_to_poc, bear_prepare_confirmation)' in source
    assert 'ob_size_min_bull := prepared_ob_size_min_bull' in source
    assert 'ob_size_max_bull := prepared_ob_size_max_bull' in source
    assert 'ob_size_min_bear := prepared_ob_size_min_bear' in source
    assert 'ob_size_max_bear := prepared_ob_size_max_bear' in source
    assert '[ob_size_min_bull, ob_size_max_bull] = prepare_order_block_confirmation(' not in source
    assert '[ob_size_min_bear, ob_size_max_bear] = prepare_order_block_confirmation(' not in source


def test_clean_tier_is_renamed_as_a_quality_diagnostic() -> None:
    source = _read_smc_source()

    assert 'bool long_quality_clean_tier =' in source
    # quality_clean_ok removed; alert_long_clean still driven by long_quality_clean_tier
    assert 'alert_long_clean = long_quality_clean_tier' in source
    assert 'long_clean_tier' not in source


def test_cleanup_protection_does_not_mask_genuine_break_migration() -> None:
    source = _read_smc_source()

    assert 'update_broken(int mode, OrderBlock[] tracking_blocks, OrderBlock[] broken_blocks, OrderBlock[] broken_blocks_new, simple ct.LevelBreakMode broken_by = ct.LevelBreakMode.HIGHLOW, int keep_broken_max = 5, OrderBlock[] discarded_buffer = na) =>' in source
    assert 'update_broken( 1, tracking_blocks_bull, broken_blocks_bull, broken_blocks_new_bull, broken_by, keep_broken_max, discarded_blocks_bull)' in source
    assert 'update_broken(-1, tracking_blocks_bear, broken_blocks_bear, broken_blocks_new_bear, broken_by, keep_broken_max, discarded_blocks_bear)' in source
    assert 'long_invalidate_signal := long_setup_armed or long_setup_confirmed' in source
    assert 'long_source_lost := (long_setup_armed or long_setup_confirmed) and long_source_tracked and not long_source_alive and not long_source_broken' in source


def test_source_lock_decouples_setup_source_from_live_active_ranking() -> None:
    source = _read_smc_source()

    assert 'int LONG_SOURCE_NONE = 0' in source
    assert 'var int long_locked_source_kind = LONG_SOURCE_NONE' in source
    assert 'var int long_locked_source_id = na' in source
    assert 'int prev_locked_source_kind = long_locked_source_kind' in source
    assert 'int prev_locked_source_id = long_locked_source_id' in source
    assert 'OrderBlock prev_locked_bull_ob = prev_locked_source_kind == LONG_SOURCE_OB ? get_by_id(ob_blocks_bull, prev_locked_source_id) : na' in source
    assert 'bool long_locked_source_alive_now = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_blocks_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(fvgs_bull, long_locked_source_id_final) : false' in source
    assert 'long_setup_source_zone_id' not in source
    assert 'armed_source_changed' not in source
    assert 'bool long_invalidated_now = long_source_broken or long_source_lost or (close_safe_mode and (long_broken_down or long_setup_expired or long_confirm_expired))' in source


def test_locked_source_drives_touch_history_and_strict_sweep() -> None:
    source = _read_smc_source()

    assert 'bool long_locked_source_touch_now = long_locked_source_in_zone and (not long_locked_source_in_zone[1] or long_locked_source_id_final != long_locked_source_id_final[1] or long_locked_source_kind_final != long_locked_source_kind_final[1])' in source
    assert 'long_locked_source_touch_count_effective += 1' in source
    assert 'bool long_locked_source_touch_recent = (long_setup_armed or long_setup_confirmed) and not na(long_locked_source_last_touch_bar_index_effective) and bar_index - long_locked_source_last_touch_bar_index_effective <= long_signal_window' in source
    # long_source_zone_touch_recent removed (Patch 5) — long_locked_source_touch_recent used directly
    assert 'long_state.sync_locked_tracking(long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final, long_locked_source_kind_final, long_locked_source_id_final, long_locked_source_top_effective, long_locked_source_bottom_effective, long_locked_source_touch_count_effective, long_locked_source_last_touch_bar_index_effective)' in source
    # fvg_zone_touch_sequence_ok uses touched_bull_fvg_id now (not long_setup_backing_zone_id)
    assert 'fvg_zone_touch_event_recent and fvg_zone_touch_sequence_time_ok and not na(touched_bull_fvg_id) and last_fvg_zone_touch_id == touched_bull_fvg_id' in source


def test_source_upgrade_is_explicit_and_quality_gated() -> None:
    source = _read_smc_source()

    assert "var bool allow_armed_source_upgrade = input.bool(false, 'Allow Armed Source Upgrade'" in source
    assert "var float min_source_upgrade_quality_gain = input.float(0.15, 'Min Q Gain'" in source
    assert 'float long_locked_source_quality = prev_locked_source_kind == LONG_SOURCE_OB ? ob_quality_score(prev_locked_bull_ob) : prev_locked_source_kind == LONG_SOURCE_FVG ? fvg_quality_score(prev_locked_bull_fvg, fvg_size_threshold) : 0.0' in source
    assert 'bool prev_locked_source_invalid_now = prev_locked_source_tracked and (prev_locked_source_broken or prev_locked_source_lost)' in source
    assert 'bool ob_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now and bull_reclaim_ob_strict' in source
    assert 'bool fvg_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now and bull_reclaim_fvg_strict' in source
    assert 'and touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'and touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'if long_source_upgrade_now' in source
    assert 'bool long_source_upgrade_now = ob_source_upgrade_ok or fvg_source_upgrade_ok' in source
    assert 'bool prefer_ob_upgrade = long_source_upgrade_now and ob_source_upgrade_ok and (not fvg_source_upgrade_ok or touched_bull_ob_quality >= touched_bull_fvg_quality)' in source
    assert 'stage_locked_source_transition(bool source_upgrade_now, bool prefer_ob_upgrade_now, int prev_locked_source_kind, int prev_locked_source_id, int current_backing_zone_kind, int current_backing_zone_id, int ob_candidate_id, int fvg_candidate_id) =>' in source
    assert '[long_locked_source_kind_final, long_locked_source_id_final, long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final] = stage_locked_source_transition(long_source_upgrade_now, prefer_ob_upgrade, prev_locked_source_kind, prev_locked_source_id, long_setup_backing_zone_kind, long_setup_backing_zone_id, touched_bull_ob_id, touched_bull_fvg_id)' in source
    assert '[long_source_upgrade_now, prefer_ob_upgrade] = select_source_upgrade(ob_source_upgrade_ok, fvg_source_upgrade_ok, touched_bull_ob_quality, touched_bull_fvg_quality)' not in source


def test_source_upgrade_requires_different_candidate_than_locked_source() -> None:
    source = _read_smc_source()

    assert '(prev_locked_source_kind != LONG_SOURCE_OB or prev_locked_source_id != touched_bull_ob_id)' in source
    assert '(prev_locked_source_kind != LONG_SOURCE_FVG or prev_locked_source_id != touched_bull_fvg_id)' in source


def test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain() -> None:
    source = _read_smc_source()

    assert 'bool ob_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now' in source
    assert 'bool fvg_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now' in source
    assert 'touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'long_entry_origin_source' in source


def test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks() -> None:
    source = _read_smc_source()

    assert '[long_locked_source_kind_final, long_locked_source_id_final, long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final] = stage_locked_source_transition(long_source_upgrade_now, prefer_ob_upgrade, prev_locked_source_kind, prev_locked_source_id, long_setup_backing_zone_kind, long_setup_backing_zone_id, touched_bull_ob_id, touched_bull_fvg_id)' in source
    assert 'bool long_locked_source_alive_now = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_blocks_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(fvgs_bull, long_locked_source_id_final) : false' in source
    assert 'resolve_long_zone_top(int long_zone_kind, int long_zone_id, int active_bull_ob_id, float active_bull_ob_top, int touched_bull_ob_id, float touched_bull_ob_top, int active_bull_fvg_id, float active_bull_fvg_top, int touched_bull_fvg_id, float touched_bull_fvg_top, bool preserve_prior_bounds = false, int prior_long_zone_kind = 0, int prior_long_zone_id = na, float prior_long_zone_top = na) =>' in source
    assert 'float long_locked_source_top_now = resolve_long_zone_top(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_top, touched_bull_ob_id, touched_bull_ob_top, active_bull_fvg_id, active_bull_fvg_top, touched_bull_fvg_id, touched_bull_fvg_top, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_locked_source_top)' in source
    assert 'resolve_long_zone_bottom(int long_zone_kind, int long_zone_id, int active_bull_ob_id, float active_bull_ob_bottom, int touched_bull_ob_id, float touched_bull_ob_bottom, int active_bull_fvg_id, float active_bull_fvg_bottom, int touched_bull_fvg_id, float touched_bull_fvg_bottom, bool preserve_prior_bounds = false, int prior_long_zone_kind = 0, int prior_long_zone_id = na, float prior_long_zone_bottom = na) =>' in source
    assert 'float long_locked_source_bottom_now = resolve_long_zone_bottom(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_bottom, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_locked_source_bottom)' in source
    assert 'bool long_source_broken = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_broken_bull, long_locked_source_id_final) or contains_id(ob_broken_new_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(filled_fvgs_bull, long_locked_source_id_final) or contains_id(filled_fvgs_new_bull, long_locked_source_id_final) : false' in source


def test_arm_and_confirm_transitions_route_through_long_state_methods() -> None:
    source = _read_smc_source()

    assert 'long_state.arm(bar_index, arm_trigger_candidate, arm_invalidation_candidate, arm_source_kind, arm_backing_zone_kind, arm_backing_zone_id, long_arm_backing_zone_touch_count, arm_backing_zone_kind, long_arm_locked_source_id, long_arm_locked_source_top, long_arm_locked_source_bottom, long_arm_backing_zone_touch_count, long_arm_locked_source_last_touch_bar_index)' in source
    assert 'long_state.confirm(bar_index)' in source
    assert 'sync_long_state_from_legacy(long_state, long_setup_armed, long_setup_confirmed, long_setup_arm_bar_index, long_confirm_bar_index, long_setup_trigger, long_invalidation_level, long_entry_origin_source, long_setup_backing_zone_kind, long_setup_backing_zone_id, long_setup_backing_zone_touch_count, long_locked_source_kind, long_locked_source_id, long_locked_source_top, long_locked_source_bottom, long_locked_source_touch_count, long_locked_source_last_touch_bar_index, long_setup_serial, long_last_invalid_source, long_last_invalid_level)' in source
    assert '[projected_long_setup_armed, projected_long_setup_confirmed, projected_long_setup_arm_bar_index, projected_long_confirm_bar_index, projected_long_setup_trigger, projected_long_invalidation_level, projected_long_entry_origin_source, projected_long_setup_backing_zone_kind, projected_long_setup_backing_zone_id, projected_long_setup_backing_zone_touch_count, projected_long_locked_source_kind, projected_long_locked_source_id, projected_long_locked_source_top, projected_long_locked_source_bottom, projected_long_locked_source_touch_count, projected_long_locked_source_last_touch_bar_index, projected_long_setup_serial, projected_long_last_invalid_source, projected_long_last_invalid_level] = project_long_state(long_state)' in source
    assert 'long_setup_confirmed := projected_long_setup_confirmed' in source


def test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation() -> None:
    source = _read_smc_source()

    assert 'var int long_entry_origin_source = LONG_SOURCE_NONE' in source
    assert 'int long_validation_source = LONG_SOURCE_NONE' in source
    assert "string long_setup_source_display = resolve_long_source_text(LONG_SOURCE_NONE)" in source
    assert 'long_validation_source := resolve_long_validation_source(long_locked_source_kind)' in source
    assert 'compose_long_setup_source_display(int long_entry_origin_source, int long_validation_source) =>' in source
    assert "string long_entry_origin_source_text = resolve_long_source_text(long_entry_origin_source)" in source
    assert "string long_validation_source_text = resolve_long_source_text(long_validation_source)" in source
    assert "long_entry_origin_source == LONG_SOURCE_NONE ? long_validation_source_text : long_validation_source == LONG_SOURCE_NONE or long_entry_origin_source == long_validation_source ? long_entry_origin_source_text : long_entry_origin_source_text + ' -> ' + long_validation_source_text" in source
    assert 'long_setup_source_display := compose_long_setup_source_display(long_entry_origin_source, long_validation_source)' in source
    assert 'compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>' in source
    assert "long_setup_text := compose_long_setup_text(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidated_now, invalidated_prior_setup, long_invalidated_this_bar, long_setup_source_display)" in source
    assert "str.format('{0} -> {1}', long_entry_origin_source, long_validation_source)" not in source


def test_display_and_status_text_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'describe_long_freshness(bool long_setup_armed, bool long_setup_confirmed, bool ready_is_fresh, bool confirm_is_fresh) =>' in source
    assert 'describe_long_source_state(bool long_source_tracked, bool long_source_alive, bool long_source_broken) =>' in source
    assert 'string freshness_text = describe_long_freshness(long_setup_armed, long_setup_confirmed, ready_is_fresh, confirm_is_fresh)' in source
    assert 'string source_state_text = describe_long_source_state(long_source_tracked, long_source_alive, long_source_broken)' in source


def test_confirm_and_ready_gate_logic_is_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'select_effective_long_touch_count(bool long_setup_armed, bool long_setup_confirmed, int long_setup_backing_zone_touch_count, bool bull_reclaim_ob_strict, bool in_bull_ob_zone, bool in_bull_fvg_zone, int active_ob_touch_count, bool bull_reclaim_fvg_strict, int active_fvg_touch_count, int active_zone_touch_count) =>' in source
    assert 'describe_long_zone_quality(bool long_zone_active, bool long_setup_armed, bool long_setup_confirmed, int effective_long_active_touch_count) =>' in source
    # confirm_long_filters, confirm_long_state, evaluate_long_ready_states helpers inlined
    assert 'int effective_long_active_touch_count = select_effective_long_touch_count(long_setup_armed, long_setup_confirmed, long_setup_backing_zone_touch_count, bull_reclaim_ob_strict, in_bull_ob_zone, in_bull_fvg_zone, active_ob_touch_count, bull_reclaim_fvg_strict, active_fvg_touch_count, active_zone_touch_count)' in source
    assert 'string zone_quality_text = describe_long_zone_quality(long_zone_active, long_setup_armed, long_setup_confirmed, effective_long_active_touch_count)' in source
    assert 'bool confirm_hard_gate_ok = micro_session_gate_ok and micro_freshness_gate_ok' in source
    assert 'bool confirm_upgrade_gate_ok = accel_confirm_gate_ok and sd_confirmed_gate_ok' in source
    assert 'bool confirm_lifecycle_ok = close_safe_mode and long_confirm_break and long_confirm_structure_ok and confirm_is_fresh and long_confirm_bearish_guard_ok' in source
    assert 'bool confirm_filters_ok = confirm_hard_gate_ok and confirm_upgrade_gate_ok' in source
    assert 'bool lifecycle_ready_ok = close_safe_mode and long_setup_confirmed and ready_bar_gap_ok and not long_confirm_expired and ready_is_fresh and long_confirm_bearish_guard_ok and (not require_main_break_for_ready or bull_bos_sig or main_bos_recent)' in source
    assert 'bool long_ready_state = lifecycle_ready_ok and setup_hard_gate_ok and trade_hard_gate_ok and environment_hard_gate_ok and quality_gate_ok and accel_ready_gate_ok and sd_ready_gate_ok and vol_ready_context_ok and stretch_ready_context_ok and ddvi_ready_ok_safe' in source
    assert 'bool long_entry_best_state = long_ready_state and accel_entry_best_gate_ok and sd_entry_best_gate_ok and vol_entry_best_context_ok_safe and stretch_entry_best_context_ok and ddvi_entry_best_ok_safe' in source
    assert 'bool long_entry_strict_state = long_ready_state and strict_entry_ltf_ok and htf_alignment_ok and accel_strict_entry_gate_ok and sd_entry_strict_gate_ok and vol_entry_strict_context_ok_safe and stretch_entry_strict_context_ok and ddvi_entry_strict_ok_safe' in source
    # tuple call negative assertions removed — helpers no longer exist


def test_setup_text_and_visual_state_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'resolve_long_state_code(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar, bool long_invalidate_signal = false) =>' in source
    assert 'compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>' in source
    assert "int state_code = resolve_long_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)" in source
    assert "state_code == -1 ? 'Invalidated'" in source
    assert "state_code == 2 ? 'Armed | ' + long_setup_source_display" in source
    assert "state_code == 3 ? 'Building | ' + long_setup_source_display" in source
    assert "state_code == 4 ? 'Confirmed | ' + long_setup_source_display" in source
    assert "state_code == 5 ? 'Ready | ' + long_setup_source_display" in source
    assert "state_code == 6 ? 'Entry Best | ' + long_setup_source_display" in source
    assert "state_code == 7 ? 'Entry Strict | ' + long_setup_source_display" in source
    assert 'resolve_long_visual_state(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidate_signal, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar) =>' in source
    assert 'resolve_long_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar, long_invalidate_signal)' in source
    assert "long_setup_text := compose_long_setup_text(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidated_now, invalidated_prior_setup, long_invalidated_this_bar, long_setup_source_display)" in source
    assert 'long_visual_state := resolve_long_visual_state(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidate_signal, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)' in source
    assert "setup_text := str.format('Armed | {0}', long_setup_source_display)" not in source
    assert "setup_text := str.format('Building | {0}', long_setup_source_display)" not in source
    assert "setup_text := str.format('Confirmed | {0}', long_setup_source_display)" not in source
    assert "setup_text := str.format('Ready | {0}', long_setup_source_display)" not in source
    assert "setup_text := str.format('Entry Best | {0}', long_setup_source_display)" not in source
    assert "setup_text := str.format('Entry Strict | {0}', long_setup_source_display)" not in source


def test_profile_and_track_obs_use_defensive_semantic_helpers() -> None:
    source = _read_smc_source()

    assert 'normalize_profile_resolution(int resolution) =>' in source
    assert 'normalize_profile_vah_pc(float vah_pc, float val_pc) =>' in source
    assert 'normalize_profile_val_pc(float vah_pc, float val_pc) =>' in source
    assert 'profile_data_ready(float[] highs, float[] lows, float[] values) =>' in source
    assert 'int profile_resolution = normalize_profile_resolution(resolution)' in source
    assert 'float profile_vah_pc = normalize_profile_vah_pc(vah_pc, val_pc)' in source
    assert 'float profile_val_pc = normalize_profile_val_pc(vah_pc, val_pc)' in source
    assert 'bool profile_has_range_data = profile_data_ready(highs, lows, values)' in source
    assert 'is_impulse_candle_now(float candle_body, float impulse_candle_size) =>' in source
    assert 'is_indecision_candle_now(float high_now, float low_now, float prior_high, float prior_low, float candle_top_now, float candle_btm_now, float prior_candle_top, float prior_candle_btm, float prior_candle_body, float candle_body, float candle_open, float candle_close) =>' in source
    assert 'profile_features_enabled(bool capture_profile_now, bool align_edge_to_value_area_now, bool align_break_price_to_poc_now) =>' in source
    assert 'bool is_impulse_candle = is_impulse_candle_now(candle_body, impulse_candle_size)' in source
    assert 'bool is_indecision = is_indecision_candle_now(high, low, high[1], low[1], candle_top, candle_btm, candle_top[1], candle_btm[1], candle_body[1], candle_body, open, close)' in source
    assert 'bool profile_features_active = profile_features_enabled(capture_profile, align_edge_to_value_area, align_break_price_to_poc)' in source


def test_track_obs_lifecycle_steps_are_split_into_small_helpers() -> None:
    source = _read_smc_source()

    assert 'method capture_profile_bar(OrderBlock this, bool enabled) =>' in source
    assert 'handle_pending_tracking_reset(OrderBlock block, bool reset_next_bar) =>' in source
    assert 'prepare_order_block_confirmation(OrderBlock block, float min_block_size, float max_block_size, bool round_size_bounds, bool update_profile_current_bar, bool align_edge_to_value_area, bool align_break_price_to_poc, bool should_prepare) =>' in source
    assert 'update_soft_confirmation(OrderBlock block, bool bullish_side, bool use_soft_confirm_big_candle, bool is_impulse_candle, bool is_trend_candle, float soft_confirm_offset, float impulse_candle_size) =>' in source
    assert 'confirmation_price_exited(OrderBlock block, bool bullish_side, float soft_confirm_offset) =>' in source
    assert 'confirmation_trigger_active(OrderBlock block, bool use_soft_confirm, float swing_confirmed, bool bos_alert, bool choch_alert, int swing_len) =>' in source
    assert 'ob_size_within_bounds(OrderBlock block, bool align_edge_to_value_area, float ob_size_max, float ob_size_min) =>' in source
    assert 'reset_bull_next_bar := handle_pending_tracking_reset(bull_ob, reset_bull_next_bar)' in source
    assert 'bull_ob.capture_profile_bar(profile_features_active and update_profile_current_bar)' in source
    assert 'bool bull_prepare_confirmation = enabled and barstate.isconfirmed and bull_ob.trailing and bull_ob.extending and bull_ob.left_top.index < bar_index and is_red and not is_indecision and u.in_range(close, bull_ob.left_top.price, bull_ob.right_bottom.price)' in source
    assert '[prepared_ob_size_min_bull, prepared_ob_size_max_bull] = prepare_order_block_confirmation(bull_ob, min_block_size, max_block_size, true, update_profile_current_bar, align_edge_to_value_area, align_break_price_to_poc, bull_prepare_confirmation)' in source
    assert 'update_soft_confirmation(bull_ob, true, use_soft_confirm_big_candle, is_impulse_candle, is_green, soft_confirm_offset, impulse_candle_size)' in source
    assert 'bull_confirm_trigger = confirmation_trigger_active(bull_ob, use_soft_confirm, swing_low_confirmed, bull_bos_alert, bull_choch_alert, swing_len)' in source
    assert 'if ob_size_within_bounds(bull_ob, align_edge_to_value_area, ob_size_max_bull, ob_size_min_bull)' in source


def test_watchlist_alert_level_follows_active_zone_preference() -> None:
    source = _read_smc_source()

    assert 'float long_watchlist_alert_level = na' in source
    assert 'if not na(active_bull_ob_id) and (na(active_bull_fvg_id) or prefer_active_ob_zone)' in source
    assert 'long_watchlist_alert_level := active_bull_ob_bottom' in source
    assert 'else if not na(active_bull_fvg_id)' in source
    assert 'long_watchlist_alert_level := active_bull_fvg_bottom' in source
    assert "long_watchlist_alert_level := not na(last_bull_ob_bottom) ? last_bull_ob_bottom : not na(last_bull_fvg_bottom) ? last_bull_fvg_bottom : low" in source
    assert "float long_watchlist_alert_level = not na(active_bull_ob_bottom) ? active_bull_ob_bottom : not na(active_bull_fvg_bottom) ? active_bull_fvg_bottom : not na(last_bull_ob_bottom) ? last_bull_ob_bottom : not na(last_bull_fvg_bottom) ? last_bull_fvg_bottom : low" not in source


def test_detect_pivot_resets_trend_concordant_before_optional_filter() -> None:
    source = _read_smc_source()

    assert 'detect_pivot(simple int mode, int trend, int hhll_x, float hhll, float super_hhll = na, bool filter_insignificant_internal_breaks = false) =>' in source
    assert 'var trend_concordant = true' in source
    assert 'if structure_detected and lvl_cross and y != sy' in source
    assert 'trend_concordant := true' in source
    assert 'if filter_insignificant_internal_breaks' in source
    assert 'trend_concordant := big_candle or impulse_wick' in source


def test_visual_text_dashboard_and_colors_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    # resolve_long_dashboard_state removed as dead code (Patch 4)
    assert 'resolve_long_visual_text(int long_visual_state) =>' in source
    assert 'resolve_long_bg_color(int long_visual_state, color long_color_building) =>' in source
    assert 'resolve_long_bar_color(int long_visual_state, color long_color_building) =>' in source
    assert 'long_visual_text := resolve_long_visual_text(long_visual_state)' in source
    assert 'long_bg_color := resolve_long_bg_color(long_visual_state, long_color_building)' in source
    assert 'long_bar_color := resolve_long_bar_color(long_visual_state, long_color_building)' in source


def test_dashboard_long_zone_summary_uses_shared_zone_text_helper() -> None:
    source = _read_smc_source()

    assert "compose_zone_summary_text(bool show_ob_zone, float ob_top, float ob_bottom, bool show_fvg_zone, float fvg_top, float fvg_bottom, string empty_text) =>" in source
    assert "zone_text := 'OB ' + u.format_level(ob_top) + ' / ' + u.format_level(ob_bottom)" in source
    assert "zone_text := 'FVG ' + u.format_level(fvg_top) + ' / ' + u.format_level(fvg_bottom)" in source
    assert "zone_text := 'OB ' + u.format_level(ob_top) + ' / ' + u.format_level(ob_bottom) + ' | FVG ' + u.format_level(fvg_top) + ' / ' + u.format_level(fvg_bottom)" in source
    assert "string _db_long_zones_text = compose_zone_summary_text(in_bull_ob_zone, active_bull_ob_top, active_bull_ob_bottom, in_bull_fvg_zone, active_bull_fvg_top, active_bull_fvg_bottom, 'No Long Zones')" in source


def test_arm_setup_resolution_is_extracted_into_helpers() -> None:
    source = _read_smc_source()

    # select_long_arm_source, resolve_long_arm_backing_zone, resolve_long_locked_source_bounds helpers inlined
    assert 'if bull_reclaim_ob_strict' in source
    assert 'int LONG_SOURCE_SWING_LOW = 3' in source
    assert 'int arm_source_kind = LONG_SOURCE_NONE' in source
    assert 'arm_source_kind := LONG_SOURCE_OB' in source
    assert 'arm_invalidation_candidate := touched_bull_ob_bottom' in source
    assert "arm_backing_zone_id := touched_bull_fvg_id" in source
    assert 'if arm_source_kind == LONG_SOURCE_SWING_LOW or arm_source_kind == LONG_SOURCE_INTERNAL_LOW' in source
    assert 'arm_backing_zone_kind := ob_more_recent ? LONG_SOURCE_OB : LONG_SOURCE_FVG' in source
    assert 'arm_backing_zone_id := ob_more_recent ? active_bull_ob_id : active_bull_fvg_id' in source
    # tuple call negative assertions removed — helpers no longer exist
    assert "arm_backing_zone_id := touched_bull_fvg_id" in source
    assert 'arm_source_text := arm_source_text_tmp' not in source
    assert 'arm_invalidation_candidate := arm_invalidation_candidate_tmp' not in source
    # tuple call negative assertions removed — helpers no longer exist
    assert "backing_zone_id := ob_more_recent ? active_bull_ob_id : active_bull_fvg_id" in source
    # tuple call negative assertion removed — helpers no longer exist
    assert 'arm_backing_zone_kind == LONG_SOURCE_FVG and arm_backing_zone_id == active_fvg_touch_id ? active_fvg_touch_count' in source
    assert 'int long_arm_locked_source_id = resolve_long_zone_id(arm_backing_zone_kind, arm_backing_zone_id)' in source
    assert 'float long_arm_locked_source_top = resolve_long_zone_top(arm_backing_zone_kind, arm_backing_zone_id, active_bull_ob_id, active_bull_ob_top, touched_bull_ob_id, touched_bull_ob_top, active_bull_fvg_id, active_bull_fvg_top, touched_bull_fvg_id, touched_bull_fvg_top)' in source
    assert 'float long_arm_locked_source_bottom = resolve_long_zone_bottom(arm_backing_zone_kind, arm_backing_zone_id, active_bull_ob_id, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_bottom)' in source
    assert 'bool long_locked_source_alive_now = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_blocks_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(fvgs_bull, long_locked_source_id_final) : false' in source
    assert 'float long_locked_source_top_now = resolve_long_zone_top(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_top, touched_bull_ob_id, touched_bull_ob_top, active_bull_fvg_id, active_bull_fvg_top, touched_bull_fvg_id, touched_bull_fvg_top, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_locked_source_top)' in source
    assert 'float long_locked_source_bottom_now = resolve_long_zone_bottom(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_bottom, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_locked_source_bottom)' in source
    assert "OrderBlock long_locked_bull_ob = long_locked_source_kind_final == 'OB' ? get_by_id(ob_blocks_bull, long_locked_source_id_final) : na" not in source
    assert "FVG long_locked_bull_fvg = long_locked_source_kind_final == 'FVG' ? get_by_id(fvgs_bull, long_locked_source_id_final) : na" not in source
    assert 'long_locked_bull_ob.left_top.price' not in source
    assert 'long_locked_bull_fvg.right_bottom.price' not in source


def test_long_alert_helpers_cover_close_safe_events_and_message_composition() -> None:
    source = _read_smc_source()

    # resolve_long_close_safe_alert_events, resolve_long_alert_identity, resolve_directional_dynamic_alert_identity helpers inlined
    assert "compose_long_invalidated_alert_detail(string long_last_invalid_source, string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert 'long_last_invalid_source + long_micro_alert_suffix + long_score_detail_suffix' in source
    assert "compose_long_ready_alert_detail(string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert "compose_long_confirmed_alert_detail(string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert "compose_long_watchlist_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert 'bool long_arm_close_safe = barstate.isconfirmed and long_setup_armed and not long_setup_armed[1]' in source
    assert 'bool long_confirm_close_safe = barstate.isconfirmed and long_setup_confirmed and not long_setup_confirmed[1]' in source
    assert 'bool long_ready_close_safe = barstate.isconfirmed and long_ready_state and not long_ready_state[1]' in source
    assert 'bool long_invalidated_close_safe = barstate.isconfirmed and not long_setup_armed and not long_setup_confirmed and (long_setup_armed[1] or long_setup_confirmed[1])' in source
    # tuple call negative assertions removed — helpers no longer exist
    assert "string bull_bos_alert_key = '|bull_bos|'" in source
    # bear dynamic alert keys removed (Patch 4)
    assert "string long_invalidated_alert_key = '|long_invalidated|'" in source
    assert "string long_watchlist_alert_name = 'Long Dip Watchlist'" in source
    # tuple call negative assertions removed — helpers no longer exist
    assert 'compose_long_invalidated_alert_detail(long_last_invalid_source, long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_entry_strict_alert_detail(long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_entry_best_alert_detail(long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_ready_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_confirmed_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_clean_alert_detail(long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_early_alert_detail(long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_armed_plus_alert_detail(long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_armed_alert_detail(long_setup_source_display, long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert 'compose_long_watchlist_alert_detail(long_micro_alert_suffix, long_score_detail_suffix)' in source
    assert "str.format('{0}{1}{2}', long_last_invalid_source, long_micro_alert_suffix, long_score_detail_suffix)" not in source
    assert "str.format('Ready for {0}: lifecycle, gates, context, upgrades passed{1}{2}{3}{4}', long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix)" not in source
    assert "str.format('Confirmed from {0}: confirm lifecycle and filters passed{1}{2}{3}{4}', long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix)" not in source
    assert "str.format('Armed from {0}: reclaim and zone confirmation in{1}{2}', long_setup_source_display, long_micro_alert_suffix, long_score_detail_suffix)" not in source
    assert "'Ready for ' + long_setup_source_display + ': lifecycle, gates, context, upgrades passed' + long_strict_alert_suffix + long_environment_alert_suffix + long_micro_alert_suffix + long_score_detail_suffix" in source
    assert "'Confirmed from ' + long_setup_source_display + ': confirm lifecycle and filters passed' + long_strict_alert_suffix + long_environment_alert_suffix + long_micro_alert_suffix + long_score_detail_suffix" in source
    assert "'Armed from ' + long_setup_source_display + ': reclaim and zone confirmation in' + long_micro_alert_suffix + long_score_detail_suffix" in source
    assert "Invalidated from {0}" not in source
    # bear_bos dynamic alert removed (Patch 4)
    assert 'resolve_ob_alert_level(OrderBlock block) =>' in source
    assert 'resolve_fvg_alert_level(FVG gap) =>' in source
    assert 'resolve_ob_top_boundary(OrderBlock block) =>' in source
    assert 'resolve_ob_bottom_boundary(OrderBlock block) =>' in source
    assert 'resolve_fvg_top_boundary(FVG gap) =>' in source
    assert 'resolve_fvg_bottom_boundary(FVG gap) =>' in source
    assert 'float new_ob_bull_alert_level = resolve_ob_alert_level(new_ob_bull)' in source
    # bear alert levels removed (Patch 4)
    assert 'float new_fvg_bull_alert_level = resolve_fvg_alert_level(new_fvg_bull)' in source
    assert 'FVG bull_filled_alert_gap = bullish_fvg_filled_alert ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1) : na' in source
    assert 'float bull_filled_alert_level = resolve_fvg_alert_level(bull_filled_alert_gap)' in source
    assert 'FVG last_bull_fvg_gap = array.size(fvgs_bull) > 0 ? array.get(fvgs_bull, array.size(fvgs_bull) - 1) : na' in source
    # bear last-zone patterns removed (Patch 4)
    assert 'OrderBlock last_bull_ob = array.size(ob_blocks_bull) > 0 ? array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1) : na' in source
    # bear last-ob/fvg removed (Patch 4)
    assert 'last_bull_ob_break_level = resolve_ob_alert_level(last_bull_ob)' in source
    # bear last-ob/fvg break/fill levels removed (Patch 4)
    assert 'last_bear_ob_break_level = resolve_ob_alert_level(last_bear_ob)' not in source
    assert 'last_bull_ob_top = resolve_ob_top_boundary(last_bull_ob)' in source
    assert 'last_bull_ob_bottom = resolve_ob_bottom_boundary(last_bull_ob)' in source
    assert 'last_bull_fvg_fill_level = resolve_fvg_alert_level(last_bull_fvg_gap)' in source
    # bear last-fvg removed (Patch 4)
    assert 'last_bear_fvg_fill_level = resolve_fvg_alert_level(last_bear_fvg_gap)' not in source
    assert 'last_bull_fvg_top = resolve_fvg_top_boundary(last_bull_fvg_gap)' in source
    assert 'last_bull_fvg_bottom = resolve_fvg_bottom_boundary(last_bull_fvg_gap)' in source
    assert 'active_bull_ob_break_level := resolve_ob_alert_level(best_bull_ob)' in source
    # bear active-closest scanning removed (Patch 4)
    assert 'OrderBlock active_bear_ob = array.get(ob_blocks_bear, best_bear_ob_idx)' not in source
    assert 'active_bear_ob_break_level := resolve_ob_alert_level(active_bear_ob)' not in source
    assert 'active_bull_fvg_fill_level := resolve_fvg_alert_level(best_bull_fvg)' in source
    assert 'FVG active_bear_fvg = array.get(fvgs_bear, best_bear_fvg_idx)' not in source
    assert 'active_bear_fvg_fill_level := resolve_fvg_alert_level(active_bear_fvg)' not in source
    # bear live event patterns removed (Patch 4)
    assert 'FVG bear_live_filled_gap = any_live_bear_fvg_fill' not in source
    assert 'OrderBlock bull_live_broken_ob = any_live_bull_ob_break ? array.get(ob_broken_new_bull, array.size(ob_broken_new_bull) - 1) : na' in source
    assert 'OrderBlock bear_live_broken_ob = any_live_bear_ob_break' not in source
    assert 'float bull_ob_live_event_level = any_live_bull_ob_break ? resolve_ob_alert_level(bull_live_broken_ob) : bull_ob_break_for_alert' in source
    assert 'float bear_ob_live_event_level = any_live_bear_ob_break' not in source
    assert 'float bull_fvg_live_event_level = any_live_bull_fvg_fill ? resolve_fvg_alert_level(bull_live_filled_gap) : bull_fvg_fill_for_alert' in source
    assert 'float bear_fvg_live_event_level = any_live_bear_fvg_fill' not in source
    assert 'float best_live_bull_ob_boundary = na' in source
    assert 'OrderBlock best_live_bull_ob = array.get(ob_blocks_bull, best_live_bull_ob_idx)' in source
    assert 'best_live_bull_ob_boundary := resolve_ob_bottom_boundary(best_live_bull_ob)' in source
    assert 'float bull_ob_live_candidate_level = resolve_ob_alert_level(bull_ob_live_candidate)' in source
    assert 'float bull_ob_live_candidate_boundary = resolve_ob_bottom_boundary(bull_ob_live_candidate)' in source
    # bear live scanning removed (Patch 4)
    assert 'float best_live_bear_ob_boundary = na' not in source
    assert 'OrderBlock best_live_bear_ob = array.get(ob_blocks_bear, best_live_bear_ob_idx)' not in source
    assert 'best_live_bear_ob_boundary := resolve_ob_top_boundary(best_live_bear_ob)' not in source
    assert 'float bear_ob_live_candidate_level = resolve_ob_alert_level(bear_ob_live_candidate)' not in source
    assert 'float bear_ob_live_candidate_boundary = resolve_ob_top_boundary(bear_ob_live_candidate)' not in source
    assert 'float bull_fvg_live_candidate_level = resolve_fvg_alert_level(bull_fvg_live_candidate)' in source
    assert 'float bull_fvg_live_candidate_boundary = resolve_fvg_bottom_boundary(bull_fvg_live_candidate)' in source
    # bear FVG live candidates removed (Patch 4)
    assert 'float bear_fvg_live_candidate_level = resolve_fvg_alert_level(bear_fvg_live_candidate)' not in source
    assert 'float bear_fvg_live_candidate_boundary = resolve_fvg_top_boundary(bear_fvg_live_candidate)' not in source
    assert 'float best_live_bull_fvg_boundary = na' in source
    assert 'FVG best_live_bull_fvg = array.get(fvgs_bull, best_live_bull_fvg_idx)' in source
    assert 'best_live_bull_fvg_boundary := resolve_fvg_bottom_boundary(best_live_bull_fvg)' in source
    assert 'FVG bull_live_fvg = array.get(fvgs_bull, best_live_bull_fvg_idx)' in source
    assert 'bull_fvg_live_event_level := resolve_fvg_alert_level(bull_live_fvg)' in source
    # bear fvg/ob live scan removed (Patch 4)
    assert 'float best_live_bear_fvg_boundary = na' not in source
    assert 'FVG best_live_bear_fvg = array.get(fvgs_bear, best_live_bear_fvg_idx)' not in source
    assert 'best_live_bear_fvg_boundary := resolve_fvg_top_boundary(best_live_bear_fvg)' not in source
    assert 'FVG bear_live_fvg = array.get(fvgs_bear, best_live_bear_fvg_idx)' not in source
    assert 'bear_fvg_live_event_level := resolve_fvg_alert_level(bear_live_fvg)' not in source
    assert 'OrderBlock bull_live_ob = array.get(ob_blocks_bull, best_live_bull_ob_idx)' in source
    assert 'bull_ob_live_event_level := resolve_ob_alert_level(bull_live_ob)' in source
    assert 'OrderBlock bear_live_ob = array.get(ob_blocks_bear, best_live_bear_ob_idx)' not in source
    assert 'bear_ob_live_event_level := resolve_ob_alert_level(bear_live_ob)' not in source
    assert 'best_live_bull_ob_boundary := best_live_bull_ob.right_bottom.price' not in source
    assert 'best_live_bear_ob_boundary := best_live_bear_ob.left_top.price' not in source
    assert 'best_live_bull_fvg_boundary := best_live_bull_fvg.right_bottom.price' not in source
    assert 'best_live_bear_fvg_boundary := best_live_bear_fvg.left_top.price' not in source
    assert 'bull_ob_live_candidate_boundary = bull_ob_live_candidate.right_bottom.price' not in source
    assert 'bear_ob_live_candidate_boundary = bear_ob_live_candidate.left_top.price' not in source
    assert 'bull_fvg_live_candidate_boundary = bull_fvg_live_candidate.right_bottom.price' not in source
    assert 'bear_fvg_live_candidate_boundary = bear_fvg_live_candidate.left_top.price' not in source
    assert 'active_bull_ob_top := best_bull_ob.left_top.price' not in source
    assert 'active_bull_ob_bottom := best_bull_ob.right_bottom.price' not in source
    assert 'active_bull_fvg_top := best_bull_fvg.left_top.price' not in source
    assert 'active_bull_fvg_bottom := best_bull_fvg.right_bottom.price' not in source
    assert 'bull_ob_candidate.left_top.price' not in source
    assert 'bull_ob_candidate.right_bottom.price' not in source
    assert 'bull_fvg_candidate.left_top.price' not in source
    assert 'bull_fvg_candidate.right_bottom.price' not in source
    assert 'bear_ob_candidate.left_top.price' not in source
    assert 'bear_ob_candidate.right_bottom.price' not in source
    assert 'bear_fvg_candidate.left_top.price' not in source
    assert 'bear_fvg_candidate.right_bottom.price' not in source
    assert 'bull_ob_candidate.right_bottom.index' not in source
    assert 'bull_fvg_candidate.right_bottom.index' not in source
    assert 'bear_ob_candidate.right_bottom.index' not in source
    assert 'bear_fvg_candidate.right_bottom.index' not in source
    assert 'best_bull_ob.right_bottom.index' not in source
    assert 'best_bull_fvg.right_bottom.index' not in source
    assert 'active_bull_ob_top := resolve_ob_top_boundary(best_bull_ob)' in source
    assert 'active_bull_ob_bottom := resolve_ob_bottom_boundary(best_bull_ob)' in source
    assert 'active_bull_ob_recency := resolve_ob_recency_index(best_bull_ob)' in source
    assert 'active_bull_fvg_top := resolve_fvg_top_boundary(best_bull_fvg)' in source
    assert 'active_bull_fvg_bottom := resolve_fvg_bottom_boundary(best_bull_fvg)' in source
    assert 'active_bull_fvg_recency := resolve_fvg_recency_index(best_bull_fvg)' in source
    assert 'resolve_ob_recency_index(OrderBlock block)' in source
    assert 'resolve_fvg_recency_index(FVG gap)' in source
    assert 'float bear_ob_blocker_level = resolve_ob_alert_level(bear_ob_blocker)' in source
    assert 'float bear_fvg_blocker_level = resolve_fvg_alert_level(bear_fvg_blocker)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and not na(new_ob_bull), bull_ob_alert_key, bull_ob_alert_name, bull_ob_alert_detail, new_ob_bull_alert_level, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    # bear dynamic alert emit removed (Patch 4)
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and not na(new_ob_bear)' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bullish_fvg_alert, bull_fvg_alert_key, bull_fvg_alert_name, bull_fvg_alert_detail, new_fvg_bull_alert_level, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bearish_fvg_alert, bear_fvg_alert_key' not in source
    assert 'new_ob_bull.break_price, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'new_ob_bear.break_price, -1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'float bear_ob_blocker_level = bear_ob_blocker.break_price' not in source
    assert 'float bear_fvg_blocker_level = bear_fvg_blocker.fill_target_level' not in source
    assert 'float new_ob_bull_alert_level = not na(new_ob_bull) ? new_ob_bull.break_price : na' not in source
    assert 'float new_ob_bear_alert_level = not na(new_ob_bear) ? new_ob_bear.break_price : na' not in source
    assert 'float new_fvg_bull_alert_level = not na(new_fvg_bull) ? new_fvg_bull.fill_target_level : na' not in source
    assert 'float new_fvg_bear_alert_level = not na(new_fvg_bear) ? new_fvg_bear.fill_target_level : na' not in source
    assert 'float bull_filled_alert_level = bullish_fvg_filled_alert ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1).fill_target_level : na' not in source
    assert 'float bear_filled_alert_level = bearish_fvg_filled_alert ? array.get(filled_fvgs_new_bear, array.size(filled_fvgs_new_bear) - 1).fill_target_level : na' not in source
    assert 'last_bull_ob_break_level = array.size(ob_blocks_bull) > 0 ? array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1).break_price : na' not in source
    assert 'last_bear_ob_break_level = array.size(ob_blocks_bear) > 0 ? array.get(ob_blocks_bear, array.size(ob_blocks_bear) - 1).break_price : na' not in source
    assert 'last_bull_ob_top = array.size(ob_blocks_bull) > 0 ? array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1).left_top.price : na' not in source
    assert 'last_bull_ob_bottom = array.size(ob_blocks_bull) > 0 ? array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1).right_bottom.price : na' not in source
    assert 'active_bull_ob_break_level := best_bull_ob.break_price' not in source
    assert 'active_bear_ob_break_level := array.get(ob_blocks_bear, best_bear_ob_idx).break_price' not in source
    assert 'last_bull_fvg_fill_level = array.size(fvgs_bull) > 0 ? array.get(fvgs_bull, array.size(fvgs_bull) - 1).fill_target_level : na' not in source
    assert 'last_bear_fvg_fill_level = array.size(fvgs_bear) > 0 ? array.get(fvgs_bear, array.size(fvgs_bear) - 1).fill_target_level : na' not in source
    assert 'last_bull_fvg_top = array.size(fvgs_bull) > 0 ? array.get(fvgs_bull, array.size(fvgs_bull) - 1).left_top.price : na' not in source
    assert 'last_bull_fvg_bottom = array.size(fvgs_bull) > 0 ? array.get(fvgs_bull, array.size(fvgs_bull) - 1).right_bottom.price : na' not in source
    assert 'active_bull_fvg_fill_level := best_bull_fvg.fill_target_level' not in source
    assert 'active_bear_fvg_fill_level := array.get(fvgs_bear, best_bear_fvg_idx).fill_target_level' not in source
    assert 'float bull_ob_live_event_level = any_live_bull_ob_break ? array.get(ob_broken_new_bull, array.size(ob_broken_new_bull) - 1).break_price : bull_ob_break_for_alert' not in source
    assert 'float bear_ob_live_event_level = any_live_bear_ob_break ? array.get(ob_broken_new_bear, array.size(ob_broken_new_bear) - 1).break_price : bear_ob_break_for_alert' not in source
    assert 'float bull_fvg_live_event_level = any_live_bull_fvg_fill ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1).fill_target_level : bull_fvg_fill_for_alert' not in source
    assert 'float bear_fvg_live_event_level = any_live_bear_fvg_fill ? array.get(filled_fvgs_new_bear, array.size(filled_fvgs_new_bear) - 1).fill_target_level : bear_fvg_fill_for_alert' not in source
    assert 'if low <= bull_ob_live_candidate.break_price and (na(best_live_bull_ob_idx) or bull_ob_live_candidate.right_bottom.price < array.get(ob_blocks_bull, best_live_bull_ob_idx).right_bottom.price)' not in source
    assert 'if low <= bull_ob_live_candidate.break_price and (na(best_live_bull_ob_idx) or bull_ob_live_candidate.right_bottom.price < best_live_bull_ob_boundary)' not in source
    assert 'if low <= bull_ob_live_candidate_level and (na(best_live_bull_ob_idx) or bull_ob_live_candidate.right_bottom.price < best_live_bull_ob_boundary)' not in source
    assert 'bull_ob_live_event_level := array.get(ob_blocks_bull, best_live_bull_ob_idx).break_price' not in source
    assert 'if high >= bear_ob_live_candidate.break_price and (na(best_live_bear_ob_idx) or bear_ob_live_candidate.left_top.price > array.get(ob_blocks_bear, best_live_bear_ob_idx).left_top.price)' not in source
    assert 'if high >= bear_ob_live_candidate.break_price and (na(best_live_bear_ob_idx) or bear_ob_live_candidate.left_top.price > best_live_bear_ob_boundary)' not in source
    assert 'if high >= bear_ob_live_candidate_level and (na(best_live_bear_ob_idx) or bear_ob_live_candidate.left_top.price > best_live_bear_ob_boundary)' not in source
    assert 'bear_ob_live_event_level := array.get(ob_blocks_bear, best_live_bear_ob_idx).break_price' not in source
    assert 'if low <= bull_fvg_live_candidate.fill_target_level and (na(best_live_bull_fvg_idx) or bull_fvg_live_candidate.right_bottom.price < array.get(fvgs_bull, best_live_bull_fvg_idx).right_bottom.price)' not in source
    assert 'if low <= bull_fvg_live_candidate_level and (na(best_live_bull_fvg_idx) or bull_fvg_live_candidate.right_bottom.price < array.get(fvgs_bull, best_live_bull_fvg_idx).right_bottom.price)' not in source
    assert 'if low <= bull_fvg_live_candidate_level and (na(best_live_bull_fvg_idx) or bull_fvg_live_candidate.right_bottom.price < best_live_bull_fvg_boundary)' not in source
    assert 'bull_fvg_live_event_level := array.get(fvgs_bull, best_live_bull_fvg_idx).fill_target_level' not in source
    assert 'if high >= bear_fvg_live_candidate.fill_target_level and (na(best_live_bear_fvg_idx) or bear_fvg_live_candidate.left_top.price > array.get(fvgs_bear, best_live_bear_fvg_idx).left_top.price)' not in source
    assert 'if high >= bear_fvg_live_candidate_level and (na(best_live_bear_fvg_idx) or bear_fvg_live_candidate.left_top.price > array.get(fvgs_bear, best_live_bear_fvg_idx).left_top.price)' not in source
    assert 'if high >= bear_fvg_live_candidate_level and (na(best_live_bear_fvg_idx) or bear_fvg_live_candidate.left_top.price > best_live_bear_fvg_boundary)' not in source
    assert 'bear_fvg_live_event_level := array.get(fvgs_bear, best_live_bear_fvg_idx).fill_target_level' not in source
    assert "string long_strict_alert_suffix = (use_strict_sequence or use_strict_sweep_for_zone_reclaim or use_strict_confirm_guard) ? ' | strict=on' : ''" in source
    assert "string long_environment_alert_suffix = ' | env=' + long_environment_focus_display + ' | overhead=' + overhead_text" in source
    assert "string long_micro_alert_suffix = use_microstructure_profiles ? ' | micro=' + micro_profile_text + ' | freshness=' + freshness_text + ' | source=' + source_state_text + ' | zone=' + zone_quality_text : ''" in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and long_ready_signal, long_ready_alert_key, long_ready_alert_name, compose_long_ready_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_setup_trigger, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert "if dynamic_long_alert_mode == 'Priority'" in source
    assert 'priority_seen_keys_confirmed = emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, not long_dynamic_alert_sent, long_confirmed_alert_key, long_confirmed_alert_name, compose_long_confirmed_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_setup_trigger, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_watchlist != dynamic_alert_seen_keys' in source
    assert 'emit_priority_dynamic_alert_if_allowed(' not in source
    # Old detailed dashboard display patterns removed (Patch 5 compact dashboard rebuild)
    # prefer_level, quality_score_display, quality_env_display, etc. all replaced by compact dashboard
    assert 'dashboard_row(table tbl, int row, string name, string value, color bg, color txt) =>' in source
    assert 'render_smc_dashboard_documented(' in source
    assert "string overhead_text = not use_overhead_zone_filter ? 'off' : na(headroom_to_overhead) or na(planned_risk) ? 'clear' : str.tostring(headroom_to_overhead / planned_risk, '#.##') + 'R'" in source
    assert "string long_score_detail_suffix = ' | ctx=' + str.tostring(context_quality_score) + '/' + str.tostring(effective_min_context_quality_score)" in source
    assert "format_level(not na(active_bull_ob_break_level) ? active_bull_ob_break_level : last_bull_ob_break_level)" not in source
    assert "format_level(not na(active_bull_fvg_fill_level) ? active_bull_fvg_fill_level : last_bull_fvg_fill_level)" not in source
    assert "string quality_score_display = not quality_axis_active ? 'n/a' : str.format('Ctx {0}/{1}\\nMin {2}\\n{3}', context_quality_score, effective_context_quality_max_score, effective_min_context_quality_score, quality_score_ok ? 'OK' : 'Blocked')" not in source
    assert "string quality_env_display = not quality_axis_active ? 'n/a' : str.format('Trade {0}\\nEnv {1}', trade_hard_gate_ok ? 'OK' : not session_structure_gate_ok ? 'Session Block' : not microstructure_entry_gate_ok ? 'Micro Block' : not overhead_zone_ok ? 'Headroom Block' : 'Trade Blocked', environment_hard_gate_ok ? 'OK' : long_environment_focus_display)" not in source
    assert "string quality_strict_display = not quality_axis_active ? 'n/a' : str.format('{0}\\nZone {1}\\nSweep {2}\\nGuard {3}', quality_strict_ok ? 'Strict OK' : strict_flow_focus_display, strict_sequence_display, strict_sweep_display, strict_guard_display)" not in source
    assert "string long_strict_alert_suffix = strict_flow_active ? str.format(' | strict={0}', strict_flow_focus_display) : ''" not in source
    assert "string long_environment_alert_suffix = long_gate_features_active ? str.format(' | env={0}', long_environment_focus_display) : ''" not in source
    assert "string long_micro_alert_suffix = use_microstructure_profiles ? str.format(' | micro={0}', microstructure_focus_display) : ''" not in source
    assert "string overhead_text = not use_overhead_zone_filter ? 'off' : na(headroom_to_overhead) or na(planned_risk) ? 'clear' : str.format('{0}R', headroom_to_overhead / planned_risk)" not in source
    assert "string long_score_detail_suffix = str.format(' | ctx={0}/{1}', context_quality_score, effective_min_context_quality_score)" not in source
    assert "str.length(micro_modifier_text) > 0 ? str.format('{0} | {1}', micro_profile_text, micro_modifier_text) : micro_profile_text == 'Default' ? 'Micro OK' : micro_profile_text" not in source
    assert "string micro_profile_display = not use_microstructure_profiles ? 'Off' : str.length(micro_modifier_text) > 0 ? str.format('{0}\nMods {1}', micro_profile_text, micro_modifier_text) : micro_profile_text" not in source
    assert "string volume_quality_display = volume_data_ok ? str.format('OK\n{0} | Strict {1}', profile_volume_display, strict_ltf_display)" not in source
    assert "string stretch_display = not use_stretch_context ? 'Off' : stretch_entry_strict_context_ok ? str.format('Strict OK\nz={0,number,#.##}\nMean {1}', distance_to_mean_z, format_level(stretch_mean))" not in source
    assert "string dashboard_swing_levels_display = str.format('Swing {0}/{1}\\nInt {2}/{3}', dashboard_swing_up_text, dashboard_swing_down_text, dashboard_internal_up_text, dashboard_internal_down_text)" not in source
    assert "string dashboard_long_zones_display = str.format('OB {0}/{1}\\nFVG {2}/{3}', dashboard_long_ob_top_text, dashboard_long_ob_bottom_text, dashboard_long_fvg_top_text, dashboard_long_fvg_bottom_text)" not in source
    assert "string dashboard_long_triggers_display = str.format('OB mid {0}\\nFVG fill {1}\\nInvalid {2}', format_level(dashboard_long_ob_trigger_level), format_level(dashboard_long_fvg_trigger_level), format_level(long_invalidation_level))" not in source
    assert "string dashboard_long_triggers_display = str.format('OB mid {0}\\nFVG fill {1}\\nInvalid {2}', dashboard_long_ob_trigger_text, dashboard_long_fvg_trigger_text, dashboard_long_invalid_text)" not in source
    assert "string risk_display = not long_plan_active ? 'n/a' : str.format('Trig {0}\\nStop {1}\\nT1 {2}\\nT2 {3}', format_level(long_setup_trigger), format_level(long_stop_level), format_level(long_target_1), format_level(long_target_2))" not in source
    assert "string risk_display = not long_plan_active ? 'n/a' : str.format('Trig {0}\\nStop {1}\\nT1 {2}\\nT2 {3}', risk_trigger_text, risk_stop_text, risk_target_1_text, risk_target_2_text)" not in source
    assert 'bool alert_long_early_event = alert_long_early and long_setup_serial > 0 and last_long_early_alert_serial != long_setup_serial' in source
    assert 'last_long_early_alert_serial := alert_long_early_event ? long_setup_serial : last_long_early_alert_serial' in source
    assert 'bool alert_long_armed_event = alert_long_armed and not suppress_armed_plus_event and long_setup_serial > 0 and last_long_armed_alert_serial != long_setup_serial' in source
    assert 'last_long_armed_alert_serial := alert_long_armed_event ? long_setup_serial : last_long_armed_alert_serial' in source
    assert 'bool alert_long_clean_event = alert_long_clean and long_setup_serial > 0 and last_long_clean_alert_serial != long_setup_serial' in source
    assert 'last_long_clean_alert_serial := alert_long_clean_event ? long_setup_serial : last_long_clean_alert_serial' in source
    assert 'bool alert_long_entry_best_event = alert_long_entry_best and long_setup_serial > 0 and last_long_entry_best_alert_serial != long_setup_serial' in source
    assert 'last_long_entry_best_alert_serial := alert_long_entry_best_event ? long_setup_serial : last_long_entry_best_alert_serial' in source
    assert 'bool alert_long_entry_strict_event = alert_long_entry_strict and long_setup_serial > 0 and last_long_entry_strict_alert_serial != long_setup_serial' in source
    assert 'last_long_entry_strict_alert_serial := alert_long_entry_strict_event ? long_setup_serial : last_long_entry_strict_alert_serial' in source
    assert '[next_alert_long_early_event, next_last_long_early_alert_serial] = next_serial_event(alert_long_early, long_setup_serial, last_long_early_alert_serial)' not in source
    assert '[next_alert_long_armed_event, next_last_long_armed_alert_serial] = next_serial_event(alert_long_armed and not suppress_armed_plus_event, long_setup_serial, last_long_armed_alert_serial)' not in source
    assert '[next_alert_long_clean_event, next_last_long_clean_alert_serial] = next_serial_event(alert_long_clean, long_setup_serial, last_long_clean_alert_serial)' not in source
    assert '[next_alert_long_entry_best_event, next_last_long_entry_best_alert_serial] = next_serial_event(alert_long_entry_best, long_setup_serial, last_long_entry_best_alert_serial)' not in source
    assert '[next_alert_long_entry_strict_event, next_last_long_entry_strict_alert_serial] = next_serial_event(alert_long_entry_strict, long_setup_serial, last_long_entry_strict_alert_serial)' not in source


def test_intrabar_ready_and_watchlist_events_are_debounced_and_latched() -> None:
    source = _read_smc_source()

    assert 'varip bool long_ready_fired_this_bar = false' in source
    assert 'bool long_ready_signal = long_ready_state and long_ready_state_rt_prev == 0 and not long_ready_fired_this_bar' in source
    assert 'if long_ready_signal' in source
    assert 'long_ready_fired_this_bar := true' in source
    assert 'varip bool long_watchlist_fired_this_bar = false' in source
    assert 'bool long_watchlist_started = alert_long_watchlist and long_watchlist_rt_prev_active == 0 and not long_watchlist_fired_this_bar' in source
    assert 'long_watchlist_fired_this_bar := true' in source
    assert 'varip bool alert_long_watchlist_event_latched = false' in source
    assert 'alert_long_watchlist_event_latched := update_latched_flag(alert_long_watchlist_event_latched, alert_long_watchlist_event, live_exec, barstate.isconfirmed)' in source
    assert 'alert_long_watchlist_event_latched := false' in source


def test_pre_arm_ob_selection_prefers_touch_anchor_then_recency_then_quality() -> None:
    source = _read_smc_source()

    assert 'bool ob_candidate_touch_anchor = not na(touched_bull_ob_id) and ob_candidate_id == touched_bull_ob_id' in source
    assert 'zone_candidate_preferred(bool candidate_touch_anchor, int candidate_recency, float candidate_quality, float candidate_overlap, int candidate_id, bool best_touch_anchor, int best_recency, float best_quality, float best_overlap, int best_id) =>' in source
    assert 'prefer_ob_candidate := zone_candidate_preferred(ob_candidate_touch_anchor, ob_candidate_recency, ob_candidate_quality, ob_candidate_overlap, ob_candidate_id, best_bull_ob_touch_anchor, best_bull_ob_recency, best_bull_ob_quality, best_bull_ob_overlap, best_bull_ob_id)' in source


def test_pre_arm_fvg_and_combined_active_zone_use_deterministic_priority() -> None:
    source = _read_smc_source()

    assert 'bool fvg_candidate_touch_anchor = not na(touched_bull_fvg_id) and fvg_candidate_id == touched_bull_fvg_id' in source
    assert 'prefer_fvg_candidate := zone_candidate_preferred(fvg_candidate_touch_anchor, fvg_candidate_recency, fvg_candidate_quality, fvg_candidate_overlap, fvg_candidate_id, best_bull_fvg_touch_anchor, best_bull_fvg_recency, best_bull_fvg_quality, best_bull_fvg_overlap, best_bull_fvg_id)' in source
    assert 'prefer_primary_zone(bool primary_touch_anchor, int primary_recency, float primary_quality, float primary_overlap, int primary_id, bool secondary_touch_anchor, int secondary_recency, float secondary_quality, float secondary_overlap, int secondary_id) =>' in source
    assert 'bool prefer_active_ob_zone = not na(active_bull_ob_id)' in source
    assert 'prefer_active_ob_zone := prefer_primary_zone(active_bull_ob_touch_anchor, active_bull_ob_recency, active_bull_ob_quality, best_bull_ob_overlap, active_bull_ob_id, active_bull_fvg_touch_anchor, active_bull_fvg_recency, active_bull_fvg_quality, best_bull_fvg_overlap, active_bull_fvg_id)' in source
    assert 'int active_long_zone_id = not na(active_bull_ob_id) and (na(active_bull_fvg_id) or prefer_active_ob_zone) ? active_bull_ob_id : not na(active_bull_fvg_id) ? -active_bull_fvg_id : na' in source


def test_bear_pre_arm_selection_uses_same_deterministic_priority_without_touch_anchor() -> None:
    """Bear active-closest scanning removed (Patch 4), but blocker scanning must stay."""
    source = _read_smc_source()

    # Blocker scanning still present (long-only overhead zone filter)
    assert 'nearest_bear_ob_blocker_level' in source
    assert 'nearest_bear_fvg_blocker_level' in source
    # Active-closest scanning loops removed
    assert 'int best_bear_ob_idx = na' not in source
    assert 'int best_bear_fvg_idx = na' not in source


def test_locked_source_touch_count_selection_is_extracted() -> None:
    source = _read_smc_source()

    assert 'select_locked_source_touch_count(bool source_upgrade_now, bool prefer_ob_upgrade_now, int ob_candidate_id, int active_ob_touch_id, int active_ob_touch_count, int touched_ob_touch_count, int fvg_candidate_id, int active_fvg_touch_id, int active_fvg_touch_count, int touched_fvg_touch_count, int locked_source_touch_count) =>' in source
    assert 'int long_locked_source_touch_count_effective = select_locked_source_touch_count(long_source_upgrade_now, prefer_ob_upgrade, touched_bull_ob_id, active_ob_touch_id, active_ob_touch_count, touched_bull_ob_touch_count, touched_bull_fvg_id, active_fvg_touch_id, active_fvg_touch_count, touched_bull_fvg_touch_count, long_locked_source_touch_count)' in source


