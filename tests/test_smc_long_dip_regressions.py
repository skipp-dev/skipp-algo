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
    assert 'bool update_ob_profile_current_bar = use_ob_profile_effective and volume_current_bar_ok' in source
    assert "'OB profiles keep last valid shape'" in source
    assert "string profile_volume_display = not use_ob_profile ? 'Prof Off' : not volume_feed_quality_ok ? 'Prof Feed Weak' : not volume_current_bar_ok ? 'Prof Frozen' : use_ob_profile_effective ? 'Prof OK' : 'Prof Paused'" in source
    assert 'capture_profile = update_ob_profile_current_bar' in source
    assert 'update_profile_current_bar = update_ob_profile_current_bar' in source


def test_backing_zone_identity_and_touch_count_persist_after_arm() -> None:
    source = _read_smc_source()

    assert 'long_setup_backing_zone_kind := arm_backing_zone_kind' in source
    assert 'long_setup_backing_zone_id := arm_backing_zone_id' in source
    assert 'select_long_arm_backing_zone_touch_count(string arm_backing_zone_kind, int arm_backing_zone_id, int active_ob_touch_id, int active_ob_touch_count, int touched_bull_ob_id, int touched_bull_ob_touch_count, int active_fvg_touch_id, int active_fvg_touch_count, int touched_bull_fvg_id, int touched_bull_fvg_touch_count) =>' in source
    assert 'long_setup_backing_zone_touch_count := select_long_arm_backing_zone_touch_count(arm_backing_zone_kind, arm_backing_zone_id, active_ob_touch_id, active_ob_touch_count, touched_bull_ob_id, touched_bull_ob_touch_count, active_fvg_touch_id, active_fvg_touch_count, touched_bull_fvg_id, touched_bull_fvg_touch_count)' in source
    assert "long_locked_source_kind := arm_backing_zone_kind" in source
    assert "long_locked_source_id := arm_backing_zone_kind == 'OB' ? arm_backing_zone_id : arm_backing_zone_kind == 'FVG' ? arm_backing_zone_id : na" in source
    assert 'long_locked_source_touch_count := long_setup_backing_zone_touch_count' in source
    assert 'long_setup_backing_zone_touch_count := long_locked_source_touch_count' in source


def test_invalidation_path_records_specific_reason_and_clears_setup_state() -> None:
    source = _read_smc_source()

    assert 'resolve_long_invalidation_reason(bool long_source_broken, bool long_source_lost, bool long_setup_expired, bool long_confirm_expired, string long_validation_source, string long_entry_origin_source, string long_setup_source_display) =>' in source
    assert "string long_validation_source_now = long_locked_source_kind_final == 'OB' ? 'OB' : long_locked_source_kind_final == 'FVG' ? 'FVG' : 'None'" in source
    assert 'string long_setup_source_display_now = compose_long_setup_source_display(long_entry_origin_source, long_validation_source_now)' in source
    assert 'long_last_invalid_source := resolve_long_invalidation_reason(long_source_broken, long_source_lost, long_setup_expired, long_confirm_expired, long_validation_source_now, long_entry_origin_source, long_setup_source_display_now)' in source
    assert 'long_invalidate_signal := long_setup_armed or long_setup_confirmed' in source
    assert "long_entry_origin_source := 'None'" in source
    assert "long_setup_backing_zone_kind := 'None'" in source
    assert 'long_setup_backing_zone_id := na' in source


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
    assert 'method draw(Box this, BoxArgs args = na, BoxTextArgs text_args = na, bool extend_only = true, simple bool force_overlay = false) =>' in source
    assert 'if not na(this)' in source
    assert 'this.plot.set_text(this.txt)' in source
    assert 'method draw(Label this, LabelArgs args = na, simple bool force_overlay = false) =>' in source
    assert 'this.plot.set_tooltip(this.tooltip)' in source
    assert 'method rendered_right_time(OrderBlock this, bool extend_until_broken = true) =>' in source
    assert 'int base_right_time = math.max(this.left_top.time, this.right_bottom.time)' in source
    assert 'method rendered_right_time(FVG this, bool extend_until_filled = true) =>' in source
    assert 'int effective_fill_time = effective_live_event_time(this.fill_time, base_right_time)' in source


def test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods() -> None:
    source = _read_smc_source()

    assert 'draw(ob_blocks_bull, ob_config_bull, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    assert 'draw(ob_blocks_bear, ob_config_bear, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    assert 'draw(fvgs_bull, fvg_config_bull, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    assert 'draw(htf_fvg_buffer_bull, htf_fvg_config_bull, visible_left = visible_left_time, visible_right = visible_right_time)' in source
    assert 'contains_id(ob_blocks_bull, touched_bull_ob_id)' in source
    assert 'get_by_id(ob_blocks_bull, touched_bull_ob_id)' in source
    assert 'contains_id(filled_fvgs_bull, long_locked_source_id_final)' in source
    assert 'array.size(filled_fvgs_new_bull) > 0' in source
    assert 'array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1).fill_target_level' in source
    assert 'array.size(ob_blocks_bull) > 0' in source
    assert 'array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1).break_price' in source
    assert 'bull_ob_candidate = array.get(ob_blocks_bull, i)' in source
    assert 'array.clear(ob_discarded_bull)' in source
    assert 'array.clear(fvg_discarded_bull)' in source
    assert 'array.clear(htf_fvg_buffer_bull_discarded)' in source
    assert 'ob_blocks_bull.draw(' not in source
    assert 'fvgs_bull.draw(' not in source
    assert 'htf_fvg_buffer_bull.draw(' not in source
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

    assert "bool state_update_bar_ok = signal_mode == SignalMode.AGGRESSIVE_LIVE ? true : barstate.isconfirmed" in source
    assert 'if state_update_bar_ok and ob_zone_touch_event' in source
    assert 'if state_update_bar_ok and fvg_zone_touch_event' in source
    assert 'if state_update_bar_ok and zone_touch_event' in source
    assert 'if state_update_bar_ok and zone_touch_now and last_zone_touch_bar != bar_index and not na(zone_touch_tracking_id)' in source
    assert 'if state_update_bar_ok and ob_touch_now and last_ob_touch_bar != bar_index and not na(active_bull_ob_id)' in source
    assert 'if state_update_bar_ok and fvg_touch_now and last_fvg_touch_bar != bar_index and not na(active_bull_fvg_id)' in source


def test_active_backing_zones_are_protected_from_cleanup_rotation() -> None:
    source = _read_smc_source()

    assert 'protected_bull_id = long_setup_backing_zone_kind == \'OB\' ? long_setup_backing_zone_id : na' in source
    assert 'long_setup_backing_zone_kind == \'FVG\' ? long_setup_backing_zone_id : na' in source
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

    assert "external_breadth_gate(simple string symbol, simple string mode, simple int len) =>" in source
    assert "var string breadth_gate_mode = input.string('Above Zero', 'Breadth Mode', options = ['Above Zero', 'Above EMA', 'Rising']" in source
    assert "var int breadth_gate_len = input.int(20, 'Breadth EMA Len', minval = 2" in source
    assert "[breadth_missing_calc, breadth_gate_ok_calc] = external_breadth_gate(breadth_gate_symbol, breadth_gate_mode, breadth_gate_len)" in source
    assert "bool breadth_pass = mode == 'Above EMA' ? ext_breadth > ext_ema : mode == 'Rising' ? ext_breadth > ext_breadth[1] : ext_breadth > 0" in source


def test_clean_tier_is_renamed_as_a_quality_diagnostic() -> None:
    source = _read_smc_source()

    assert 'bool long_quality_clean_tier =' in source
    assert 'quality_clean_ok = quality_axis_active and long_quality_clean_tier' in source
    assert 'alert_long_clean = long_quality_clean_tier' in source
    assert 'long_clean_tier' not in source


def test_cleanup_protection_does_not_mask_genuine_break_migration() -> None:
    source = _read_smc_source()

    assert 'update_broken(int mode, OrderBlock[] tracking_blocks, OrderBlock[] broken_blocks, OrderBlock[] broken_blocks_new, simple LevelBreakMode broken_by = LevelBreakMode.HIGHLOW, int keep_broken_max = 5, OrderBlock[] discarded_buffer = na) =>' in source
    assert 'update_broken( 1, tracking_blocks_bull, broken_blocks_bull, broken_blocks_new_bull, broken_by, keep_broken_max, discarded_blocks_bull)' in source
    assert 'update_broken(-1, tracking_blocks_bear, broken_blocks_bear, broken_blocks_new_bear, broken_by, keep_broken_max, discarded_blocks_bear)' in source
    assert 'long_invalidate_signal := long_setup_armed or long_setup_confirmed' in source
    assert 'long_source_lost := (long_setup_armed or long_setup_confirmed) and long_source_tracked and not long_source_alive and not long_source_broken' in source


def test_source_lock_decouples_setup_source_from_live_active_ranking() -> None:
    source = _read_smc_source()

    assert "var string long_locked_source_kind = 'None'" in source
    assert 'var int long_locked_source_id = na' in source
    assert "string prev_locked_source_kind = long_locked_source_kind" in source
    assert 'int prev_locked_source_id = long_locked_source_id' in source
    assert "OrderBlock prev_locked_bull_ob = prev_locked_source_kind == 'OB' ? get_by_id(ob_blocks_bull, prev_locked_source_id) : na" in source
    assert "OrderBlock long_locked_bull_ob = long_locked_source_kind_final == 'OB' ? get_by_id(ob_blocks_bull, long_locked_source_id_final) : na" in source
    assert 'long_setup_source_zone_id' not in source
    assert 'armed_source_changed' not in source
    assert 'bool long_invalidated_now = long_source_broken or long_source_lost or (close_safe_mode and (long_broken_down or long_setup_expired or long_confirm_expired))' in source


def test_locked_source_drives_touch_history_and_strict_sweep() -> None:
    source = _read_smc_source()

    assert 'bool long_locked_source_touch_now = long_locked_source_in_zone and (not long_locked_source_in_zone[1] or long_locked_source_id_final != long_locked_source_id_final[1] or long_locked_source_kind_final != long_locked_source_kind_final[1])' in source
    assert 'long_locked_source_touch_count_effective += 1' in source
    assert 'bool long_locked_source_touch_recent = (long_setup_armed or long_setup_confirmed) and not na(long_locked_source_last_touch_bar_index_effective) and bar_index - long_locked_source_last_touch_bar_index_effective <= long_signal_window' in source
    assert 'bool long_source_zone_touch_recent = (long_setup_armed or long_setup_confirmed) and not na(long_locked_source_id) ? long_locked_source_touch_recent' in source
    assert 'long_setup_backing_zone_touch_count := long_locked_source_touch_count' in source
    assert "bool strict_sweep_ok = long_locked_source_kind == 'OB' ? long_locked_ob_real_sweep : long_locked_source_kind == 'FVG' ? long_locked_fvg_real_sweep" in source
    assert "fvg_zone_touch_event_recent and last_fvg_zone_touch_id == long_setup_backing_zone_id" in source


def test_source_upgrade_is_explicit_and_quality_gated() -> None:
    source = _read_smc_source()

    assert "var bool allow_armed_source_upgrade = input.bool(false, 'Allow Armed Source Upgrade'" in source
    assert "var float min_source_upgrade_quality_gain = input.float(0.15, 'Min Q Gain'" in source
    assert 'float long_locked_source_quality = prev_locked_source_kind == \'OB\' ? ob_quality_score(prev_locked_bull_ob) : prev_locked_source_kind == \'FVG\' ? fvg_quality_score(prev_locked_bull_fvg, fvg_size_threshold) : 0.0' in source
    assert 'bool prev_locked_source_invalid_now = prev_locked_source_tracked and (prev_locked_source_broken or prev_locked_source_lost)' in source
    assert 'bool ob_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now and bull_reclaim_ob_strict' in source
    assert 'bool fvg_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now and bull_reclaim_fvg_strict' in source
    assert 'and touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'and touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'select_source_upgrade(bool ob_source_upgrade_ok, bool fvg_source_upgrade_ok, float ob_upgrade_quality, float fvg_upgrade_quality) =>' in source
    assert 'if long_source_upgrade_now' in source
    assert '[long_source_upgrade_now, prefer_ob_upgrade] = select_source_upgrade(ob_source_upgrade_ok, fvg_source_upgrade_ok, touched_bull_ob_quality, touched_bull_fvg_quality)' in source
    assert '[long_locked_source_kind_final, long_locked_source_id_final, long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final] = stage_locked_source_transition(long_source_upgrade_now, prefer_ob_upgrade, prev_locked_source_kind, prev_locked_source_id, long_setup_backing_zone_kind, long_setup_backing_zone_id, touched_bull_ob_id, touched_bull_fvg_id)' in source


def test_source_upgrade_requires_different_candidate_than_locked_source() -> None:
    source = _read_smc_source()

    assert "(prev_locked_source_kind != 'OB' or prev_locked_source_id != touched_bull_ob_id)" in source
    assert "(prev_locked_source_kind != 'FVG' or prev_locked_source_id != touched_bull_fvg_id)" in source


def test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain() -> None:
    source = _read_smc_source()

    assert 'bool ob_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now' in source
    assert 'bool fvg_source_upgrade_ok = allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed and not prev_locked_source_invalid_now' in source
    assert 'touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'long_entry_origin_source' in source


def test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks() -> None:
    source = _read_smc_source()

    assert 'stage_locked_source_transition(bool source_upgrade_now, bool prefer_ob_upgrade_now, string locked_source_kind, int locked_source_id, string setup_backing_zone_kind, int setup_backing_zone_id, int ob_candidate_id, int fvg_candidate_id) =>' in source
    assert '[long_locked_source_kind_final, long_locked_source_id_final, long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final] = stage_locked_source_transition(long_source_upgrade_now, prefer_ob_upgrade, prev_locked_source_kind, prev_locked_source_id, long_setup_backing_zone_kind, long_setup_backing_zone_id, touched_bull_ob_id, touched_bull_fvg_id)' in source
    assert "OrderBlock long_locked_bull_ob = long_locked_source_kind_final == 'OB' ? get_by_id(ob_blocks_bull, long_locked_source_id_final) : na" in source
    assert "bool long_locked_source_alive_now = long_locked_source_kind_final == 'OB' ? not na(long_locked_bull_ob) : long_locked_source_kind_final == 'FVG' ? not na(long_locked_bull_fvg) : false" in source
    assert "bool long_source_broken = long_locked_source_kind_final == 'OB' ? contains_id(ob_broken_bull, long_locked_source_id_final) or contains_id(ob_broken_new_bull, long_locked_source_id_final) : long_locked_source_kind_final == 'FVG' ? contains_id(filled_fvgs_bull, long_locked_source_id_final) or contains_id(filled_fvgs_new_bull, long_locked_source_id_final) : false" in source


def test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation() -> None:
    source = _read_smc_source()

    assert "var string long_entry_origin_source = 'None'" in source
    assert "string long_validation_source = 'None'" in source
    assert "string long_setup_source_display = 'None'" in source
    assert "long_validation_source := long_locked_source_kind == 'OB' ? 'OB' : long_locked_source_kind == 'FVG' ? 'FVG' : 'None'" in source
    assert 'compose_long_setup_source_display(string long_entry_origin_source, string long_validation_source) =>' in source
    assert 'long_setup_source_display := compose_long_setup_source_display(long_entry_origin_source, long_validation_source)' in source
    assert 'compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, string long_setup_source_display) =>' in source
    assert "long_setup_text := compose_long_setup_text(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_setup_source_display)" in source


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
    assert 'confirm_long_filters(bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool accel_confirm_gate_ok, bool sd_confirmed_gate_ok) =>' in source
    assert 'confirm_long_state(bool close_safe_mode, bool long_confirm_break, bool long_confirm_structure_ok, bool confirm_is_fresh, bool long_confirm_bearish_guard_ok, bool confirm_hard_gate_ok, bool confirm_upgrade_gate_ok) =>' in source
    assert 'evaluate_long_ready_states(bool close_safe_mode, bool long_setup_confirmed, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'int effective_long_active_touch_count = select_effective_long_touch_count(long_setup_armed, long_setup_confirmed, long_setup_backing_zone_touch_count, bull_reclaim_ob_strict, in_bull_ob_zone, in_bull_fvg_zone, active_ob_touch_count, bull_reclaim_fvg_strict, active_fvg_touch_count, active_zone_touch_count)' in source
    assert 'string zone_quality_text = describe_long_zone_quality(long_zone_active, long_setup_armed, long_setup_confirmed, effective_long_active_touch_count)' in source
    assert '[confirm_hard_gate_ok, confirm_upgrade_gate_ok] = confirm_long_filters(micro_session_gate_ok, micro_freshness_gate_ok, accel_confirm_gate_ok, sd_confirmed_gate_ok)' in source
    assert '[confirm_lifecycle_ok, confirm_filters_ok] = confirm_long_state(close_safe_mode, long_confirm_break, long_confirm_structure_ok, confirm_is_fresh, long_confirm_bearish_guard_ok, confirm_hard_gate_ok, confirm_upgrade_gate_ok)' in source
    assert '[lifecycle_ready_ok, long_ready_state, long_entry_best_state, long_entry_strict_state] = evaluate_long_ready_states(close_safe_mode, long_setup_confirmed, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source


def test_setup_text_and_visual_state_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, string long_setup_source_display) =>' in source
    assert 'resolve_long_visual_state(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidate_signal, bool invalidated_prior_setup, bool long_invalidated_now) =>' in source
    assert "long_setup_text := compose_long_setup_text(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_setup_source_display)" in source
    assert 'long_visual_state := resolve_long_visual_state(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidate_signal, invalidated_prior_setup, long_invalidated_now)' in source


def test_visual_text_dashboard_and_colors_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'resolve_long_dashboard_state(int long_visual_state) =>' in source
    assert 'resolve_long_visual_text(int long_visual_state) =>' in source
    assert 'resolve_long_bg_color(int long_visual_state, color long_color_building) =>' in source
    assert 'resolve_long_bar_color(int long_visual_state, color long_color_building) =>' in source
    assert 'long_setup_dashboard_state := resolve_long_dashboard_state(long_visual_state)' in source
    assert 'long_visual_text := resolve_long_visual_text(long_visual_state)' in source
    assert 'long_bg_color := resolve_long_bg_color(long_visual_state, long_color_building)' in source
    assert 'long_bar_color := resolve_long_bar_color(long_visual_state, long_color_building)' in source


def test_arm_setup_resolution_is_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'select_long_arm_source(bool bull_reclaim_ob_strict, bool bull_reclaim_fvg_strict, bool bull_reclaim_swing_low_strict, bool bull_reclaim_internal_low_strict, float touched_bull_ob_bottom, int touched_bull_ob_id, float touched_bull_fvg_bottom, int touched_bull_fvg_id, float long_reclaim_swing_level, float long_reclaim_internal_level) =>' in source
    assert 'resolve_long_arm_backing_zone(string arm_source_text, bool in_bull_ob_zone, bool in_bull_fvg_zone, int last_ob_zone_touch_bar_index, int last_fvg_zone_touch_bar_index, int active_bull_ob_id, int active_bull_fvg_id, bool touched_bull_ob_recent, int touched_bull_ob_id, bool touched_bull_fvg_recent, int touched_bull_fvg_id, string arm_backing_zone_kind, int arm_backing_zone_id) =>' in source
    assert 'resolve_long_locked_source_bounds(string arm_backing_zone_kind, int arm_backing_zone_id, int active_bull_ob_id, float active_bull_ob_top, float active_bull_ob_bottom, int touched_bull_ob_id, float touched_bull_ob_top, float touched_bull_ob_bottom, int active_bull_fvg_id, float active_bull_fvg_top, float active_bull_fvg_bottom, int touched_bull_fvg_id, float touched_bull_fvg_top, float touched_bull_fvg_bottom) =>' in source
    assert '[arm_source_text_tmp, arm_invalidation_candidate_tmp, arm_backing_zone_kind_tmp, arm_backing_zone_id_tmp] = select_long_arm_source(bull_reclaim_ob_strict, bull_reclaim_fvg_strict, bull_reclaim_swing_low_strict, bull_reclaim_internal_low_strict, touched_bull_ob_bottom, touched_bull_ob_id, touched_bull_fvg_bottom, touched_bull_fvg_id, long_reclaim_swing_level, long_reclaim_internal_level)' in source
    assert "arm_backing_zone_id := touched_bull_fvg_id" in source
    assert 'arm_source_text := arm_source_text_tmp' in source
    assert 'arm_invalidation_candidate := arm_invalidation_candidate_tmp' in source
    assert '[arm_backing_zone_kind_resolved, arm_backing_zone_id_resolved] = resolve_long_arm_backing_zone(arm_source_text, in_bull_ob_zone, in_bull_fvg_zone, last_ob_zone_touch_bar_index, last_fvg_zone_touch_bar_index, active_bull_ob_id, active_bull_fvg_id, touched_bull_ob_recent, touched_bull_ob_id, touched_bull_fvg_recent, touched_bull_fvg_id, arm_backing_zone_kind, arm_backing_zone_id)' in source
    assert 'arm_backing_zone_kind := arm_backing_zone_kind_resolved' in source
    assert "backing_zone_id := ob_more_recent ? active_bull_ob_id : active_bull_fvg_id" in source
    assert '[long_locked_source_top_tmp, long_locked_source_bottom_tmp] = resolve_long_locked_source_bounds(arm_backing_zone_kind, arm_backing_zone_id, active_bull_ob_id, active_bull_ob_top, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_top, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_top, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_top, touched_bull_fvg_bottom)' in source
    assert "arm_backing_zone_kind == 'FVG' and arm_backing_zone_id == active_fvg_touch_id ? active_fvg_touch_count" in source
    assert "arm_backing_zone_kind == 'FVG' and arm_backing_zone_id == active_bull_fvg_id ? active_bull_fvg_top" in source
    assert 'long_locked_source_top := long_locked_source_top_tmp' in source


def test_long_alert_helpers_cover_close_safe_events_and_message_composition() -> None:
    source = _read_smc_source()

    assert 'resolve_long_close_safe_alert_events(bool bar_confirmed, bool long_setup_armed, bool long_setup_confirmed, bool long_ready_state, bool long_setup_armed_prev, bool long_setup_confirmed_prev, bool long_ready_state_prev) =>' in source
    assert "resolve_long_alert_identity(string long_alert_kind) =>" in source
    assert "resolve_directional_dynamic_alert_identity(string alert_kind, bool bullish) =>" in source
    assert "compose_long_invalidated_alert_detail(string long_last_invalid_source, string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert "str.format('{0}{1}{2}', long_last_invalid_source, long_micro_alert_suffix, long_score_detail_suffix)" in source
    assert "compose_long_ready_alert_detail(string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert "compose_long_confirmed_alert_detail(string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert "compose_long_watchlist_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix) =>" in source
    assert '[long_arm_close_safe, long_confirm_close_safe, long_ready_close_safe, long_invalidated_close_safe] = resolve_long_close_safe_alert_events(barstate.isconfirmed, long_setup_armed, long_setup_confirmed, long_ready_state, long_setup_armed[1], long_setup_confirmed[1], long_ready_state[1])' in source
    assert "[bull_bos_alert_key, bull_bos_alert_name, bull_bos_alert_detail] = resolve_directional_dynamic_alert_identity('bos', true)" in source
    assert "[bear_live_fvg_alert_key, bear_live_fvg_alert_name, bear_live_fvg_alert_detail] = resolve_directional_dynamic_alert_identity('live_fvg_fill', false)" in source
    assert "[long_invalidated_alert_key, long_invalidated_alert_name] = resolve_long_alert_identity('invalidated')" in source
    assert "[long_watchlist_alert_key, long_watchlist_alert_name] = resolve_long_alert_identity('watchlist')" in source
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
    assert "Invalidated from {0}" not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bear_bos_sig, bear_bos_alert_key, bear_bos_alert_name, bear_bos_alert_detail, btm, -1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'resolve_ob_alert_level(OrderBlock block) =>' in source
    assert 'resolve_fvg_alert_level(FVG gap) =>' in source
    assert 'float new_ob_bull_alert_level = resolve_ob_alert_level(new_ob_bull)' in source
    assert 'float new_ob_bear_alert_level = resolve_ob_alert_level(new_ob_bear)' in source
    assert 'float new_fvg_bull_alert_level = resolve_fvg_alert_level(new_fvg_bull)' in source
    assert 'float new_fvg_bear_alert_level = resolve_fvg_alert_level(new_fvg_bear)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and not na(new_ob_bull), bull_ob_alert_key, bull_ob_alert_name, bull_ob_alert_detail, new_ob_bull_alert_level, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and not na(new_ob_bear), bear_ob_alert_key, bear_ob_alert_name, bear_ob_alert_detail, new_ob_bear_alert_level, -1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bullish_fvg_alert, bull_fvg_alert_key, bull_fvg_alert_name, bull_fvg_alert_detail, new_fvg_bull_alert_level, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bearish_fvg_alert, bear_fvg_alert_key, bear_fvg_alert_name, bear_fvg_alert_detail, new_fvg_bear_alert_level, -1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'new_ob_bull.break_price, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'new_ob_bear.break_price, -1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'float new_ob_bull_alert_level = not na(new_ob_bull) ? new_ob_bull.break_price : na' not in source
    assert 'float new_ob_bear_alert_level = not na(new_ob_bear) ? new_ob_bear.break_price : na' not in source
    assert 'float new_fvg_bull_alert_level = not na(new_fvg_bull) ? new_fvg_bull.fill_target_level : na' not in source
    assert 'float new_fvg_bear_alert_level = not na(new_fvg_bear) ? new_fvg_bear.fill_target_level : na' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and long_ready_signal, long_ready_alert_key, long_ready_alert_name, compose_long_ready_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_setup_trigger, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert "if dynamic_long_alert_mode == 'Priority'" in source
    assert 'priority_seen_keys_confirmed = emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, not long_dynamic_alert_sent, long_confirmed_alert_key, long_confirmed_alert_name, compose_long_confirmed_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_setup_trigger, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_watchlist != dynamic_alert_seen_keys' in source
    assert 'emit_priority_dynamic_alert_if_allowed(' not in source


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

    assert 'bool ob_candidate_touch_anchor = not na(touched_bull_ob_id) and bull_ob_candidate.id == touched_bull_ob_id' in source
    assert 'zone_candidate_preferred(bool candidate_touch_anchor, int candidate_recency, float candidate_quality, float candidate_overlap, int candidate_id, bool best_touch_anchor, int best_recency, float best_quality, float best_overlap, int best_id) =>' in source
    assert 'prefer_ob_candidate := zone_candidate_preferred(ob_candidate_touch_anchor, ob_candidate_recency, ob_candidate_quality, ob_candidate_overlap, bull_ob_candidate.id, best_bull_ob_touch_anchor, best_bull_ob_recency, best_bull_ob_quality, best_bull_ob_overlap, best_bull_ob_id)' in source


def test_pre_arm_fvg_and_combined_active_zone_use_deterministic_priority() -> None:
    source = _read_smc_source()

    assert 'bool fvg_candidate_touch_anchor = not na(touched_bull_fvg_id) and bull_fvg_candidate.id == touched_bull_fvg_id' in source
    assert 'prefer_fvg_candidate := zone_candidate_preferred(fvg_candidate_touch_anchor, fvg_candidate_recency, fvg_candidate_quality, fvg_candidate_overlap, bull_fvg_candidate.id, best_bull_fvg_touch_anchor, best_bull_fvg_recency, best_bull_fvg_quality, best_bull_fvg_overlap, best_bull_fvg_id)' in source
    assert 'prefer_primary_zone(bool primary_touch_anchor, int primary_recency, float primary_quality, float primary_overlap, int primary_id, bool secondary_touch_anchor, int secondary_recency, float secondary_quality, float secondary_overlap, int secondary_id) =>' in source
    assert 'bool prefer_active_ob_zone = not na(active_bull_ob_id)' in source
    assert 'prefer_active_ob_zone := prefer_primary_zone(active_bull_ob_touch_anchor, active_bull_ob_recency, active_bull_ob_quality, best_bull_ob_overlap, active_bull_ob_id, active_bull_fvg_touch_anchor, active_bull_fvg_recency, active_bull_fvg_quality, best_bull_fvg_overlap, active_bull_fvg_id)' in source
    assert 'int active_long_zone_id = not na(active_bull_ob_id) and (na(active_bull_fvg_id) or prefer_active_ob_zone) ? active_bull_ob_id : not na(active_bull_fvg_id) ? -active_bull_fvg_id : na' in source


def test_bear_pre_arm_selection_uses_same_deterministic_priority_without_touch_anchor() -> None:
    source = _read_smc_source()

    assert 'int best_bear_ob_recency = na' in source
    assert 'float best_bear_ob_quality = na' in source
    assert 'prefer_bear_ob_candidate := zone_candidate_preferred(false, bear_ob_candidate_recency, bear_ob_candidate_quality, bear_ob_candidate_overlap, bear_ob_candidate.id, false, best_bear_ob_recency, best_bear_ob_quality, best_bear_ob_overlap, best_bear_ob_id)' in source
    assert 'int best_bear_fvg_recency = na' in source
    assert 'float best_bear_fvg_quality = na' in source
    assert 'prefer_bear_fvg_candidate := zone_candidate_preferred(false, bear_fvg_candidate_recency, bear_fvg_candidate_quality, bear_fvg_candidate_overlap, bear_fvg_candidate.id, false, best_bear_fvg_recency, best_bear_fvg_quality, best_bear_fvg_overlap, best_bear_fvg_id)' in source


def test_locked_source_touch_count_selection_is_extracted() -> None:
    source = _read_smc_source()

    assert 'select_locked_source_touch_count(bool source_upgrade_now, bool prefer_ob_upgrade_now, int ob_candidate_id, int active_ob_touch_id, int active_ob_touch_count, int touched_ob_touch_count, int fvg_candidate_id, int active_fvg_touch_id, int active_fvg_touch_count, int touched_fvg_touch_count, int locked_source_touch_count) =>' in source
    assert 'int long_locked_source_touch_count_effective = select_locked_source_touch_count(long_source_upgrade_now, prefer_ob_upgrade, touched_bull_ob_id, active_ob_touch_id, active_ob_touch_count, touched_bull_ob_touch_count, touched_bull_fvg_id, active_fvg_touch_id, active_fvg_touch_count, touched_bull_fvg_touch_count, long_locked_source_touch_count)' in source


