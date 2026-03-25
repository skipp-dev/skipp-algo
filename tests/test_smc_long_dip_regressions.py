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


def _find_required(source: str, marker: str) -> int:
    idx = source.find(marker)
    assert idx != -1, f'Marker not found: {marker}'
    return idx


def _assert_markers_before(indices: dict[str, int], earlier: list[str], later: list[str]) -> None:
    for earlier_name in earlier:
        for later_name in later:
            assert indices[earlier_name] < indices[later_name], f'{earlier_name} must appear before {later_name}'


def test_plot_equal_level_uses_named_label_arguments_for_font_family() -> None:
    source = _read_smc_source()
    body = _extract_function_body(source, 'plot_equal_level')

    named_calls = re.findall(r'label\.new\([^\n]+text_font_family\s*=\s*label_args\.text_font_family', body)
    assert len(named_calls) == 2, 'Expected both equal-level label.new calls to use named text_font_family'
    assert 'label_args.text_align, label_args.text_font_family' not in body


def test_refactored_helpers_preserve_dependency_order() -> None:
    source = _read_smc_source()

    indices = {
        'compose_long_invalidated': _find_required(source, 'compose_long_invalidated_alert_detail('),
        'compose_long_strict': _find_required(source, 'compose_long_entry_strict_alert_detail('),
        'compose_long_best': _find_required(source, 'compose_long_entry_best_alert_detail('),
        'compose_long_ready': _find_required(source, 'compose_long_ready_alert_detail('),
        'compose_long_confirmed': _find_required(source, 'compose_long_confirmed_alert_detail('),
        'compose_long_clean': _find_required(source, 'compose_long_clean_alert_detail('),
        'compose_long_early': _find_required(source, 'compose_long_early_alert_detail('),
        'compose_long_armed_plus': _find_required(source, 'compose_long_armed_plus_alert_detail('),
        'compose_long_armed': _find_required(source, 'compose_long_armed_alert_detail('),
        'compose_long_watchlist': _find_required(source, 'compose_long_watchlist_alert_detail('),
        'build_dynamic_alert': _find_required(source, 'build_dynamic_alert_message('),
        'emit_dynamic_alert': _find_required(source, 'emit_dynamic_alert_if_allowed('),
        'priority_alert': _find_required(source, 'emit_priority_long_dynamic_alerts('),
        'linear_alert': _find_required(source, 'emit_linear_long_dynamic_alerts('),
        'db_trend_text': _find_required(source, 'db_trend_text('),
        'db_trend_state': _find_required(source, 'db_trend_state('),
        'db_exec_tier': _find_required(source, 'db_exec_tier_text() =>'),
        'db_setup_age': _find_required(source, 'db_setup_age_text() =>'),
        'db_ready_gate': _find_required(source, 'db_ready_gate_state('),
        'db_strict_gate': _find_required(source, 'db_strict_gate_state('),
        'db_long_debug': _find_required(source, 'db_long_debug_state('),
        'compose_zone_summary': _find_required(source, 'compose_zone_summary_text('),
        'compose_debug_modules': _find_required(source, 'compose_enabled_debug_modules_text('),
        'long_state': _find_required(source, 'var LongLifecycleState long_state ='),
        'long_plan': _find_required(source, 'bool long_plan_active = false'),
        'dashboard_modules': _find_required(source, 'compute_dashboard_modules_structure_prep() =>'),
        'dashboard_lifecycle': _find_required(source, 'compute_dashboard_lifecycle_prep() =>'),
        'dashboard_engine': _find_required(source, 'compute_dashboard_engine_debug_prep() =>'),
    }

    _assert_markers_before(indices, ['build_dynamic_alert', 'emit_dynamic_alert'], ['priority_alert', 'linear_alert'])
    _assert_markers_before(
        indices,
        [
            'compose_long_invalidated',
            'compose_long_strict',
            'compose_long_best',
            'compose_long_ready',
            'compose_long_confirmed',
            'compose_long_clean',
            'compose_long_early',
            'compose_long_armed_plus',
            'compose_long_armed',
            'compose_long_watchlist',
        ],
        ['priority_alert', 'linear_alert'],
    )
    _assert_markers_before(indices, ['db_trend_text', 'db_trend_state', 'db_exec_tier', 'db_setup_age', 'long_state'], ['dashboard_lifecycle'])
    _assert_markers_before(indices, ['compose_zone_summary', 'long_state', 'long_plan'], ['dashboard_modules'])
    _assert_markers_before(indices, ['db_ready_gate', 'db_strict_gate', 'db_long_debug', 'compose_debug_modules', 'long_state'], ['dashboard_engine'])


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
    assert 'bool ltf_needed_for_logic = false' in source
    assert 'if (show_dashboard and show_dashboard_ltf_eff) or use_ltf_for_strict_entry_eff' in source
    assert 'ltf_needed_for_logic := true' in source
    assert 'bool ltf_needed_for_messages = false' in source
    assert 'if enable_dynamic_alerts and use_ltf_for_dynamic_alerts' in source
    assert 'ltf_needed_for_messages := true' in source
    assert 'bool ltf_needed = false' in source
    assert 'if ltf_needed_for_logic or ltf_needed_for_messages' in source
    assert 'ltf_needed := true' in source
    assert 'bool ltf_ratio_ok = false' in source
    assert 'if not na(ltf_ratio) and ltf_ratio > 0 and ltf_ratio <= max_ltf_ratio_eff' in source
    assert 'ltf_ratio_ok := true' in source
    assert 'bool ltf_sample_count_ok = false' in source
    assert 'if not na(ltf_ratio) and ltf_ratio <= max_ltf_samples_per_bar_eff' in source
    assert 'ltf_sample_count_ok := true' in source
    assert 'ltf_sampling_active = false' in source
    assert 'if enable_ltf_sampling and ltf_timeframe_valid and ltf_needed and ltf_ratio_ok and ltf_sample_count_ok' in source
    assert 'ltf_sampling_active := true' in source
    assert 'bool strict_ltf_available = false' in source
    assert 'if ltf_sampling_active and ltf_volume_ok' in source
    assert 'strict_ltf_available := true' in source
    assert 'bool strict_ltf_unavailable = false' in source
    assert 'if use_ltf_for_strict_entry_eff and not strict_ltf_available' in source
    assert 'strict_ltf_unavailable := true' in source
    assert 'bool strict_ltf_unverifiable = false' in source
    assert 'if use_ltf_for_strict_entry_eff and not barstate.isrealtime and not strict_ltf_available' in source
    assert 'strict_ltf_unverifiable := true' in source
    assert "string strict_ltf_reason_text = 'LTF sampling is unavailable'" in source
    assert "if not enable_ltf_sampling" in source
    assert "else if not ltf_timeframe_valid" in source
    assert "else if not ltf_ratio_ok or not ltf_sample_count_ok" in source
    assert "else if not ltf_price_ok" in source
    assert "else if not ltf_volume_ok" in source
    assert "string strict_ltf_warning_text = str.format('Strict entry is blocked\\n{0}\\nAdjust chart/LTF settings or enable the strict-entry fallback', strict_ltf_reason_text)" in source
    assert "string strict_ltf_reason_text = not enable_ltf_sampling ? 'LTF sampling is turned off' : not ltf_timeframe_valid ? 'LTF timeframe is unavailable on this chart' : not ltf_ratio_ok or not ltf_sample_count_ok ? 'LTF sampling is guarded by ratio/sample limits' : not ltf_price_ok ? 'LTF intrabars are unavailable on this bar/history window' : not ltf_volume_ok ? 'LTF volume is unavailable on this bar' : 'LTF sampling is unavailable'" not in source
    assert 'bool _ltf_ok = true' in source
    assert 'if use_ltf_for_strict_entry_eff' in source
    assert '_ltf_ok := false' in source
    assert 'if strict_ltf_available and ltf_volume_delta >= 0' in source
    assert '_ltf_ok := true' in source
    assert 'else if allow_strict_entry_without_ltf and (strict_ltf_unavailable or strict_ltf_unverifiable)' in source
    assert 'bool ltf_ratio_ok = not na(ltf_ratio) and ltf_ratio > 0 and ltf_ratio <= max_ltf_ratio_eff' not in source
    assert 'bool ltf_sample_count_ok = not na(ltf_ratio) and ltf_ratio <= max_ltf_samples_per_bar_eff' not in source
    assert 'ltf_sampling_active = enable_ltf_sampling and ltf_timeframe_valid and ltf_needed and ltf_ratio_ok and ltf_sample_count_ok' not in source
    assert 'bool strict_ltf_available = ltf_sampling_active and ltf_volume_ok' not in source
    assert 'bool strict_ltf_unavailable = use_ltf_for_strict_entry_eff and not strict_ltf_available' not in source
    assert 'bool strict_ltf_unverifiable = use_ltf_for_strict_entry_eff and not barstate.isrealtime and not strict_ltf_available' not in source
    assert 'bool ltf_needed_for_logic = (show_dashboard and show_dashboard_ltf_eff) or use_ltf_for_strict_entry_eff' not in source
    assert 'bool ltf_needed_for_messages = enable_dynamic_alerts and use_ltf_for_dynamic_alerts' not in source
    assert 'bool ltf_needed = ltf_needed_for_logic or ltf_needed_for_messages' not in source
    assert 'bool strict_entry_ltf_ok = not use_ltf_for_strict_entry_eff or (strict_ltf_available and ltf_volume_delta >= 0) or (allow_strict_entry_without_ltf and (strict_ltf_unavailable or strict_ltf_unverifiable))' not in source


def test_relvol_fallback_stays_split_from_strict_volume_scoring() -> None:
    source = _read_smc_source()

    assert 'score thresholds shrink by the unavailable RelVol component. Strict still prefers confirmed volume-backed context, but can be partially relaxed when the dedicated strict-entry LTF fallback is also enabled.' in source
    assert 'bool relvol_data_ok = false' in source
    assert 'if volume_current_bar_ok and not na(rel_volume_ma_raw) and rel_volume_ma_raw > 0' in source
    assert 'relvol_data_ok := true' in source
    assert 'float rel_volume_ma = float(na)' in source
    assert 'if relvol_data_ok' in source
    assert 'rel_volume_ma := rel_volume_ma_raw' in source
    assert 'float rel_volume = float(na)' in source
    assert 'rel_volume := volume / rel_volume_ma' in source
    assert 'bool relvol_ok = true' in source
    assert 'if not na(rel_volume) and rel_volume >= effective_relvol_good' in source
    assert 'relvol_ok := true' in source
    assert 'bool relvol_score_ok = true' in source
    assert 'if relvol_data_ok and not na(rel_volume) and rel_volume >= effective_relvol_good' in source
    assert 'relvol_score_ok := true' in source
    assert "string relvol_value_text = 'n/a'" in source
    assert "string relvol_value_label = str.tostring(rel_volume, '#.##') + 'x'" in source
    assert 'relvol_value_text := relvol_value_label' in source
    assert "string relvol_text = 'off'" in source
    assert "relvol_text := 'fallback'" in source
    assert "relvol_text := 'blocked'" in source
    assert 'relvol_text := relvol_value_text' in source
    assert 'bool _relvol_unavail = false' in source
    assert 'if use_rel_volume and not relvol_data_ok and allow_relvol_without_volume_data' in source
    assert '_relvol_unavail := true' in source
    assert 'relvol_score_unavailable := not relvol_data_ok and allow_relvol_without_volume_data' not in source
    assert 'bool relvol_ok = not use_rel_volume ? true : not relvol_data_ok ? allow_relvol_without_volume_data : not na(rel_volume) and rel_volume >= effective_relvol_good' not in source
    assert 'bool relvol_score_ok = not use_rel_volume ? true : relvol_data_ok and not na(rel_volume) and rel_volume >= effective_relvol_good' not in source
    assert 'relvol_ok := not na(rel_volume) and rel_volume >= effective_relvol_good' not in source
    assert 'relvol_score_ok := relvol_data_ok and not na(rel_volume) and rel_volume >= effective_relvol_good' not in source
    assert "string relvol_value_text = na(rel_volume) ? 'n/a' : str.tostring(rel_volume, '#.##') + 'x'" not in source
    assert "relvol_value_text := str.tostring(rel_volume, '#.##') + 'x'" not in source
    assert "string relvol_text = not use_rel_volume ? 'off' : not relvol_data_ok ? allow_relvol_without_volume_data ? 'fallback' : 'blocked' : relvol_value_text" not in source
    assert 'bool relvol_score_unavailable = use_rel_volume and not relvol_data_ok and allow_relvol_without_volume_data' not in source
    assert 'float rel_volume_ma = relvol_data_ok ? rel_volume_ma_raw : na' not in source
    assert 'float rel_volume = not relvol_data_ok ? float(na) : volume / rel_volume_ma' not in source
    assert 'bool relvol_data_ok = volume_current_bar_ok and not na(rel_volume_ma_raw) and rel_volume_ma_raw > 0' not in source


def test_ob_profile_freezes_when_volume_quality_is_weak() -> None:
    source = _read_smc_source()

    assert "bool use_ob_profile_effective = use_ob_profile and volume_feed_quality_ok" in source
    assert 'bool collect_ob_profile_current_bar = use_ob_profile_effective and volume_current_bar_ok' in source
    assert "string profile_warning_text = 'OB profiles are on'" in source
    assert "if not use_ob_profile" in source
    assert "else if not volume_feed_quality_ok" in source
    assert "else if not volume_current_bar_ok" in source
    assert "string relvol_warning_text = 'RelVol can stay blocked'" in source
    assert "if not use_rel_volume" in source
    assert "else if volume_current_bar_ok" in source
    assert "else if allow_relvol_without_volume_data" in source
    assert "'OB profiles keep last valid shape'" in source
    assert "string profile_warning_text = not use_ob_profile ? 'OB profiles are already off' : not volume_feed_quality_ok ? 'OB profiles are paused from weak feed' : not volume_current_bar_ok ? 'OB profiles keep last valid shape' : 'OB profiles are on'" not in source
    assert "string relvol_warning_text = not use_rel_volume ? 'RelVol is off' : volume_current_bar_ok ? allow_relvol_without_volume_data ? 'RelVol can fall back' : 'RelVol can stay blocked' : allow_relvol_without_volume_data ? 'RelVol falls back on this bar' : 'RelVol is blocked on this bar'" not in source
    assert 'capture_profile = collect_ob_profile_current_bar' in source
    assert 'update_profile_current_bar = collect_ob_profile_current_bar' in source


def test_session_quality_gate_texts_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'float session_vwap_raw = ta.vwap(hlc3)' in source
    assert 'float session_vwap = float(na)' in source
    assert 'if intraday_time_chart' in source
    assert 'session_vwap := session_vwap_raw' in source
    assert 'bool vwap_session_active = false' in source
    assert 'if intraday_time_chart and not na(time(timeframe.period, vwap_session))' in source
    assert 'vwap_session_active := true' in source
    assert 'bool trade_entry_session_active = false' in source
    assert 'if intraday_time_chart and not na(time(timeframe.period, trade_entry_session))' in source
    assert 'trade_entry_session_active := true' in source
    assert 'bool micro_midday_block_active = false' in source
    assert 'if intraday_time_chart and not na(time(timeframe.period, micro_midday_block_session))' in source
    assert 'micro_midday_block_active := true' in source
    assert 'bool micro_premarket_active = false' in source
    assert 'if intraday_time_chart and not na(time(timeframe.period, micro_premarket_session))' in source
    assert 'micro_premarket_active := true' in source
    assert 'bool micro_afterhours_active = false' in source
    assert 'if intraday_time_chart and not na(time(timeframe.period, micro_afterhours_session))' in source
    assert 'micro_afterhours_active := true' in source
    assert 'int opening_range_bars = 1' in source
    assert 'if chart_tf_sec > 0' in source
    assert 'opening_range_bars := math.max(1, int(math.ceil(opening_range_minutes * 60.0 / chart_tf_sec)))' in source
    assert 'bool regular_session_just_opened = false' in source
    assert 'if vwap_session_active and not vwap_session_active[1]' in source
    assert 'regular_session_just_opened := true' in source
    assert 'if na(opening_range_high)' in source
    assert 'opening_range_high := high' in source
    assert 'opening_range_high := math.max(opening_range_high, high)' in source
    assert 'if na(opening_range_low)' in source
    assert 'opening_range_low := low' in source
    assert 'opening_range_low := math.min(opening_range_low, low)' in source
    assert 'bool opening_range_ready = false' in source
    assert 'if vwap_session_active and not na(regular_session_open_bar) and bar_index - regular_session_open_bar >= opening_range_bars and not na(opening_range_high) and not na(opening_range_low)' in source
    assert 'opening_range_ready := true' in source
    assert 'float opening_range_mid = float(na)' in source
    assert 'if opening_range_ready' in source
    assert 'opening_range_mid := math.avg(opening_range_high, opening_range_low)' in source
    assert 'bool session_gate_ok = true' in source
    assert 'if use_trade_session_gate and intraday_time_chart and block_entries_outside_session' in source
    assert 'session_gate_ok := trade_entry_session_active' in source
    assert 'bool opening_range_gate_ok = true' in source
    assert 'if use_opening_range_gate and intraday_time_chart and vwap_session_active' in source
    assert 'opening_range_gate_ok := false' in source
    assert "if opening_range_bias_mode == 'Above OR High'" in source
    assert 'opening_range_gate_ok := close > opening_range_high' in source
    assert 'opening_range_gate_ok := close > opening_range_mid' in source
    assert 'bool micro_rth_gate_ok = true' in source
    assert 'if micro_is_rth_only and intraday_time_chart' in source
    assert 'micro_rth_gate_ok := vwap_session_active' in source
    assert 'bool micro_midday_gate_ok = true' in source
    assert 'if micro_is_midday_dead and intraday_time_chart' in source
    assert 'micro_midday_gate_ok := not micro_midday_block_active' in source
    assert 'bool micro_premarket_gate_ok = true' in source
    assert 'if micro_is_weak_premarket and intraday_time_chart' in source
    assert 'micro_premarket_gate_ok := not micro_premarket_active' in source
    assert 'bool micro_afterhours_gate_ok = true' in source
    assert 'if micro_is_weak_afterhours and intraday_time_chart' in source
    assert 'micro_afterhours_gate_ok := not micro_afterhours_active' in source
    assert 'bool micro_session_gate_ok = true' in source
    assert 'if use_microstructure_profiles and intraday_time_chart' in source
    assert 'micro_session_gate_ok := micro_rth_gate_ok and micro_midday_gate_ok and micro_premarket_gate_ok and micro_afterhours_gate_ok' in source
    assert 'bool vwap_filter_ok = true' in source
    assert 'if use_vwap_filter and intraday_time_chart and vwap_session_active' in source
    assert 'vwap_filter_ok := not na(session_vwap) and close >= session_vwap' in source
    assert 'opening_range_high := na(opening_range_high) ? high : math.max(opening_range_high, high)' not in source
    assert 'opening_range_low := na(opening_range_low) ? low : math.min(opening_range_low, low)' not in source
    assert 'bool bull_close_strong = true' in source
    assert 'if use_strong_close_filter' in source
    assert "string close_state_text = 'off'" in source
    assert "close_state_text := 'Strong Close'" in source
    assert "close_state_text := 'Weak Close'" in source
    assert 'bool ema_support_ok = true' in source
    assert 'if show_ema_support' in source
    assert 'ema_support_ok := false' in source
    assert 'if close >= ema_fast and ema_fast >= ema_slow and ema_fast > ema_fast[1]' in source
    assert 'ema_support_ok := true' in source
    assert "string ema_state_text = 'off'" in source
    assert "ema_state_text := 'OK'" in source
    assert "ema_state_text := 'No'" in source
    assert "string vwap_state_text = 'off'" in source
    assert 'if use_vwap_filter' in source
    assert "vwap_state_text := 'off session'" in source
    assert "vwap_state_text := 'Above VWAP'" in source
    assert "vwap_state_text := 'Below VWAP'" in source
    assert "bool session_gate_ok = not use_trade_session_gate ? true : not intraday_time_chart ? true : not block_entries_outside_session ? true : trade_entry_session_active" not in source
    assert "bool opening_range_gate_ok = not use_opening_range_gate ? true : not intraday_time_chart ? true : not vwap_session_active ? true : not opening_range_ready ? false : opening_range_bias_mode == 'Above OR High' ? close > opening_range_high : close > opening_range_mid" not in source
    assert 'bool micro_rth_gate_ok = not micro_is_rth_only or not intraday_time_chart or vwap_session_active' not in source
    assert 'bool micro_midday_gate_ok = not micro_is_midday_dead or not intraday_time_chart or not micro_midday_block_active' not in source
    assert 'bool micro_premarket_gate_ok = not micro_is_weak_premarket or not intraday_time_chart or not micro_premarket_active' not in source
    assert 'bool micro_afterhours_gate_ok = not micro_is_weak_afterhours or not intraday_time_chart or not micro_afterhours_active' not in source
    assert 'bool micro_session_gate_ok = not use_microstructure_profiles or not intraday_time_chart or (micro_rth_gate_ok and micro_midday_gate_ok and micro_premarket_gate_ok and micro_afterhours_gate_ok)' not in source
    assert "bool vwap_filter_ok = not use_vwap_filter ? true : not intraday_time_chart ? true : not vwap_session_active ? true : not na(session_vwap) and close >= session_vwap" not in source
    assert "bool bull_close_strong = not use_strong_close_filter ? true : bull_close_in_range >= min_close_in_range_pct" not in source
    assert "string close_state_text = not use_strong_close_filter ? 'off' : bull_close_strong ? 'Strong Close' : 'Weak Close'" not in source
    assert "bool ema_support_ok = not show_ema_support ? true : close >= ema_fast and ema_fast >= ema_slow and ema_fast > ema_fast[1]" not in source
    assert "string ema_state_text = not show_ema_support ? 'off' : ema_support_ok ? 'OK' : 'No'" not in source
    assert "string vwap_state_text = not use_vwap_filter ? 'off' : not intraday_time_chart ? 'n/a' : not vwap_session_active ? 'off session' : na(session_vwap) ? 'n/a' : close >= session_vwap ? 'Above VWAP' : 'Below VWAP'" not in source
    assert 'float session_vwap = intraday_time_chart ? ta.vwap(hlc3) : na' not in source
    assert 'int opening_range_bars = chart_tf_sec > 0 ? math.max(1, int(math.ceil(opening_range_minutes * 60.0 / chart_tf_sec))) : 1' not in source
    assert 'bool vwap_session_active = intraday_time_chart and not na(time(timeframe.period, vwap_session))' not in source
    assert 'bool opening_range_ready = vwap_session_active and not na(regular_session_open_bar) and bar_index - regular_session_open_bar >= opening_range_bars and not na(opening_range_high) and not na(opening_range_low)' not in source
    assert 'bool regular_session_just_opened = vwap_session_active and not vwap_session_active[1]' not in source
    assert 'float opening_range_mid = opening_range_ready ? math.avg(opening_range_high, opening_range_low) : na' not in source
    assert 'bool trade_entry_session_active = intraday_time_chart and not na(time(timeframe.period, trade_entry_session))' not in source
    assert 'bool micro_midday_block_active = intraday_time_chart and not na(time(timeframe.period, micro_midday_block_session))' not in source
    assert 'bool micro_premarket_active = intraday_time_chart and not na(time(timeframe.period, micro_premarket_session))' not in source
    assert 'bool micro_afterhours_active = intraday_time_chart and not na(time(timeframe.period, micro_afterhours_session))' not in source


def test_micro_modifier_and_ltf_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'string micro_modifier_text = \'' in source
    assert "if micro_is_stop_hunt and micro_profile_text != 'Stop-Hunt Sensitive'" in source
    assert "micro_modifier_text += ', Stop-Hunt'" in source
    assert "micro_modifier_text := 'Stop-Hunt'" in source
    assert "micro_modifier_text += ', Clean Reclaim'" in source
    assert "micro_modifier_text := 'Clean Reclaim'" in source
    assert "micro_modifier_text += ', Fast Decay'" in source
    assert "micro_modifier_text := 'Fast Decay'" in source
    assert "micro_modifier_text += ', RTH Only'" in source
    assert "micro_modifier_text := 'RTH Only'" in source
    assert "micro_modifier_text += ', Midday Dead'" in source
    assert "micro_modifier_text := 'Midday Dead'" in source
    assert "micro_modifier_text += ', Weak Premarket'" in source
    assert "micro_modifier_text := 'Weak Premarket'" in source
    assert "micro_modifier_text += ', Weak Afterhours'" in source
    assert "micro_modifier_text := 'Weak Afterhours'" in source
    assert "effective_ltf_timeframe = ltf_timeframe" in source
    assert 'if ltf_auto_select' in source
    assert 'effective_ltf_timeframe := auto_selected_ltf' in source
    assert 'ltf_ratio = na' in source
    assert 'if effective_ltf_tf_sec > 0' in source
    assert 'ltf_ratio := int(math.floor(chart_tf_sec / effective_ltf_tf_sec))' in source
    assert 'float[] ltf_opens = array.new<float>(0)' in source
    assert 'float[] ltf_closes = array.new<float>(0)' in source
    assert 'float[] ltf_volumes = array.new<float>(0)' in source
    assert 'bool ltf_price_ok = false' in source
    assert 'if ltf_sampling_active and ltf_open_count > 0 and ltf_open_count == ltf_close_count' in source
    assert 'ltf_price_ok := true' in source
    assert 'bool ltf_volume_ok = false' in source
    assert 'if ltf_price_ok and ltf_volume_count > 0 and ltf_volume_count == ltf_open_count' in source
    assert 'ltf_volume_ok := true' in source
    assert 'bool ltf_price_only = false' in source
    assert 'if ltf_price_ok and not ltf_volume_ok' in source
    assert 'ltf_price_only := true' in source
    assert 'if ltf_price_ok' in source
    assert 'ltf_opens := ltf_opens_raw' in source
    assert 'ltf_closes := ltf_closes_raw' in source
    assert 'if ltf_volume_ok' in source
    assert 'ltf_volumes := ltf_volumes_raw' in source
    assert 'ltf_sample_count = 0' in source
    assert 'ltf_sample_count := ltf_sample_count_raw' in source
    assert 'float ltf_bull_share = float(na)' in source
    assert 'ltf_bull_share := ltf_bull_share_raw' in source
    assert 'float ltf_volume_delta = float(na)' in source
    assert 'ltf_volume_delta := ltf_volume_delta_raw' in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', Stop-Hunt' : 'Stop-Hunt'" not in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', Clean Reclaim' : 'Clean Reclaim'" not in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', Fast Decay' : 'Fast Decay'" not in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', RTH Only' : 'RTH Only'" not in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', Midday Dead' : 'Midday Dead'" not in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', Weak Premarket' : 'Weak Premarket'" not in source
    assert "micro_modifier_text += str.length(micro_modifier_text) > 0 ? ', Weak Afterhours' : 'Weak Afterhours'" not in source
    assert 'effective_ltf_timeframe = ltf_auto_select ? auto_selected_ltf : ltf_timeframe' not in source
    assert 'ltf_ratio = effective_ltf_tf_sec > 0 ? int(math.floor(chart_tf_sec / effective_ltf_tf_sec)) : na' not in source
    assert 'float[] ltf_opens = ltf_price_ok ? ltf_opens_raw : array.new<float>(0)' not in source
    assert 'float[] ltf_closes = ltf_price_ok ? ltf_closes_raw : array.new<float>(0)' not in source
    assert 'float[] ltf_volumes = ltf_volume_ok ? ltf_volumes_raw : array.new<float>(0)' not in source
    assert 'ltf_sample_count = ltf_price_ok ? ltf_sample_count_raw : 0' not in source
    assert 'bool ltf_price_ok = ltf_sampling_active and ltf_open_count > 0 and ltf_open_count == ltf_close_count' not in source
    assert 'bool ltf_volume_ok = ltf_price_ok and ltf_volume_count > 0 and ltf_volume_count == ltf_open_count' not in source
    assert 'bool ltf_price_only = ltf_price_ok and not ltf_volume_ok' not in source
    assert 'ltf_bull_share = ltf_price_ok ? ltf_bull_share_raw : na' not in source
    assert 'ltf_volume_delta = ltf_volume_ok ? ltf_volume_delta_raw : na' not in source


def test_adx_quality_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool adx_data_ok = false' in source
    assert 'if not na(adx_value) and not na(plus_di) and not na(minus_di)' in source
    assert 'adx_data_ok := true' in source
    assert 'bool adx_strong = true' in source
    assert 'if use_adx' in source
    assert 'adx_strong := false' in source
    assert 'if adx_data_ok and adx_value >= adx_strong_min and plus_di >= minus_di' in source
    assert 'adx_strong := true' in source
    assert "string adx_state_text = 'off'" in source
    assert 'if not adx_data_ok' in source
    assert "adx_state_text := 'n/a'" in source
    assert "adx_state_text := 'Bearish pressure'" in source
    assert "adx_state_text := 'Sideways'" in source
    assert "adx_state_text := 'Trend building'" in source
    assert "adx_state_text := 'Trend'" in source
    assert 'bool adx_data_ok = not na(adx_value) and not na(plus_di) and not na(minus_di)' not in source
    assert 'adx_strong := adx_data_ok and adx_value >= adx_strong_min and plus_di >= minus_di' not in source
    assert "bool adx_strong = not use_adx ? true : adx_data_ok and adx_value >= adx_strong_min and plus_di >= minus_di" not in source
    assert "string adx_state_text = not use_adx ? 'off' : not adx_data_ok ? 'n/a' : plus_di < minus_di ? 'Bearish pressure' : adx_value < adx_trend_min ? 'Sideways' : adx_value < adx_strong_min ? 'Trend building' : 'Trend'" not in source


def test_accel_context_and_gate_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool accel_above_zero = false' in source
    assert 'if not na(accel_value) and accel_value > accel_cross_threshold' in source
    assert 'accel_above_zero := true' in source
    assert 'bool accel_below_zero = false' in source
    assert 'if not na(accel_value) and accel_value < accel_cross_threshold' in source
    assert 'accel_below_zero := true' in source
    assert 'bool accel_rising = false' in source
    assert 'if not na(accel_value) and accel_value > accel_value[1]' in source
    assert 'accel_rising := true' in source
    assert 'bool accel_below_zero_rising = false' in source
    assert 'if accel_below_zero and accel_rising' in source
    assert 'accel_below_zero_rising := true' in source
    assert 'int accel_cross_since_bars = ta.barssince(accel_cross_up)' in source
    assert 'bool accel_cross_up_recent = false' in source
    assert 'if not na(accel_cross_since_bars) and accel_cross_since_bars <= accel_recent_cross_bars' in source
    assert 'accel_cross_up_recent := true' in source
    assert 'bool accel_pullback_exhaustion_long = false' in source
    assert 'accel_pullback_exhaustion_long := accel_below_zero_rising_safe' in source
    assert 'bool accel_zero_cross_up = false' in source
    assert 'if accel_cross_up_safe' in source
    assert 'accel_zero_cross_up := true' in source
    assert 'bool accel_reaccel_confirm_long = false' in source
    assert 'accel_reaccel_confirm_long := accel_cross_up_safe' in source
    assert 'bool accel_recent_cross_long = false' in source
    assert 'if accel_cross_up_recent_safe' in source
    assert 'accel_recent_cross_long := true' in source
    assert 'bool accel_mode_early_only = false' in source
    assert "if accel_integration_mode == 'Early only'" in source
    assert 'accel_mode_early_only := true' in source
    assert 'bool accel_mode_strict_entries_only = false' in source
    assert "if accel_integration_mode == 'Strict entries only'" in source
    assert 'accel_mode_strict_entries_only := true' in source
    assert 'bool accel_early_context_ok = true' in source
    assert 'if use_accel_module and accel_use_for_early' in source
    assert 'accel_early_context_ok := accel_below_zero_rising_safe or accel_cross_up_recent_safe' in source
    assert 'bool accel_ready_context_ok = true' in source
    assert 'if use_accel_module and accel_use_for_ready' in source
    assert 'accel_ready_context_ok := accel_below_zero_rising_safe or accel_cross_up_recent_safe' in source
    assert 'bool accel_entry_best_context_ok = true' in source
    assert 'if use_accel_module and accel_use_for_entry_best' in source
    assert 'accel_entry_best_context_ok := accel_below_zero_rising_safe or accel_cross_up_safe or accel_cross_up_recent_safe' in source
    assert 'bool accel_entry_strict_context_ok = true' in source
    assert 'if use_accel_module and accel_use_for_entry_strict' in source
    assert 'accel_entry_strict_context_ok := accel_cross_up_safe or accel_cross_up_recent_safe' in source
    assert 'bool accel_early_gate_ok = true' in source
    assert 'if not accel_early_context_ok' in source
    assert 'accel_early_gate_ok := false' in source
    assert 'bool accel_confirm_gate_ok = true' in source
    assert 'if use_accel_module and not accel_mode_early_only and not accel_mode_strict_entries_only' in source
    assert 'accel_confirm_gate_ok := accel_cross_up_safe or accel_cross_up_recent_safe' in source
    assert 'bool accel_ready_gate_ok = true' in source
    assert 'if use_accel_module and not accel_mode_strict_entries_only' in source
    assert 'if require_accel_above_zero_for_ready' in source
    assert 'accel_ready_gate_ok := (not na(accel_value_safe) and accel_value_safe > accel_cross_threshold) or accel_cross_up_recent_safe' in source
    assert 'accel_ready_gate_ok := accel_ready_context_ok' in source
    assert 'bool accel_entry_best_gate_ok = true' in source
    assert 'if not accel_entry_best_context_ok' in source
    assert 'accel_entry_best_gate_ok := false' in source
    assert 'bool accel_strict_entry_gate_ok = true' in source
    assert 'if not accel_entry_strict_context_ok' in source
    assert 'accel_strict_entry_gate_ok := false' in source
    assert 'bool accel_pullback_exhaustion_long = use_accel_module and accel_below_zero_rising_safe' not in source
    assert 'bool accel_zero_cross_up = accel_cross_up_safe' not in source
    assert 'bool accel_reaccel_confirm_long = use_accel_module and accel_cross_up_safe' not in source
    assert 'bool accel_recent_cross_long = accel_cross_up_recent_safe' not in source
    assert "bool accel_mode_early_only = accel_integration_mode == 'Early only'" not in source
    assert "bool accel_mode_strict_entries_only = accel_integration_mode == 'Strict entries only'" not in source
    assert 'bool accel_above_zero = not na(accel_value) and accel_value > accel_cross_threshold' not in source
    assert 'bool accel_below_zero = not na(accel_value) and accel_value < accel_cross_threshold' not in source
    assert 'bool accel_rising = not na(accel_value) and accel_value > accel_value[1]' not in source
    assert 'bool accel_below_zero_rising = not na(accel_value) and accel_value < accel_cross_threshold and accel_value > accel_value[1]' not in source
    assert 'bool accel_cross_up_recent = not na(accel_cross_since_bars) and accel_cross_since_bars <= accel_recent_cross_bars' not in source
    assert 'bool accel_early_context_ok = not use_accel_module or not accel_use_for_early or accel_below_zero_rising_safe or accel_cross_up_recent_safe' not in source
    assert 'bool accel_ready_context_ok = not use_accel_module or not accel_use_for_ready or accel_below_zero_rising_safe or accel_cross_up_recent_safe' not in source
    assert 'bool accel_entry_best_context_ok = not use_accel_module or not accel_use_for_entry_best or accel_below_zero_rising_safe or accel_cross_up_safe or accel_cross_up_recent_safe' not in source
    assert 'bool accel_entry_strict_context_ok = not use_accel_module or not accel_use_for_entry_strict or accel_cross_up_safe or accel_cross_up_recent_safe' not in source
    assert 'bool accel_early_gate_ok = accel_early_context_ok' not in source
    assert 'bool accel_confirm_gate_ok = not use_accel_module or accel_mode_early_only or accel_mode_strict_entries_only or accel_cross_up_safe or accel_cross_up_recent_safe' not in source
    assert 'bool accel_ready_gate_ok = not use_accel_module or accel_mode_strict_entries_only or (require_accel_above_zero_for_ready ? ((not na(accel_value_safe) and accel_value_safe > accel_cross_threshold) or accel_cross_up_recent_safe) : accel_ready_context_ok)' not in source
    assert 'bool accel_entry_best_gate_ok = accel_entry_best_context_ok' not in source
    assert 'bool accel_strict_entry_gate_ok = accel_entry_strict_context_ok' not in source


def test_sd_context_and_gate_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool sd_above_zero = false' in source
    assert 'if not na(sd_value) and sd_value > 0' in source
    assert 'sd_above_zero := true' in source
    assert 'bool sd_below_zero = false' in source
    assert 'if not na(sd_value) and sd_value < 0' in source
    assert 'sd_below_zero := true' in source
    assert 'bool sd_rising = false' in source
    assert 'if not na(sd_value) and sd_value > sd_value[1]' in source
    assert 'sd_rising := true' in source
    assert 'bool sd_falling = false' in source
    assert 'if not na(sd_value) and sd_value < sd_value[1]' in source
    assert 'sd_falling := true' in source
    assert 'bool sd_bullish_divergence_recent = false' in source
    assert 'if not na(sd_bull_div_since_bars) and sd_bull_div_since_bars <= sd_recent_window' in source
    assert 'sd_bullish_divergence_recent := true' in source
    assert 'bool sd_higher_lows_recent = false' in source
    assert 'if not na(sd_higher_lows_since_bars) and sd_higher_lows_since_bars <= sd_recent_window' in source
    assert 'sd_higher_lows_recent := true' in source
    assert 'bool sd_support_any_recent = false' in source
    assert 'if sd_bullish_divergence_recent or sd_higher_lows_recent' in source
    assert 'sd_support_any_recent := true' in source
    assert 'bool sd_support_both_recent = false' in source
    assert 'if sd_bullish_divergence_recent and sd_higher_lows_recent' in source
    assert 'sd_support_both_recent := true' in source
    assert 'bool sd_ready_context_ok = sd_support_any_recent' in source
    assert 'if sd_require_osc_rising_for_ready' in source
    assert 'sd_ready_context_ok := sd_support_any_recent and sd_rising' in source
    assert 'bool sd_armed_gate_ok = true' in source
    assert 'if use_sd_confluence and sd_require_for_armed' in source
    assert 'if not sd_support_any_recent' in source
    assert 'sd_armed_gate_ok := false' in source
    assert 'bool sd_early_gate_ok = true' in source
    assert 'if use_sd_confluence and sd_require_for_early' in source
    assert 'if not sd_support_any_recent' in source
    assert 'sd_early_gate_ok := false' in source
    assert 'bool sd_confirmed_gate_ok = true' in source
    assert 'if use_sd_confluence and sd_require_for_confirmed' in source
    assert 'if not sd_support_any_recent' in source
    assert 'sd_confirmed_gate_ok := false' in source
    assert 'bool sd_ready_gate_ok = true' in source
    assert 'if use_sd_confluence and sd_require_for_ready' in source
    assert 'if not sd_ready_context_ok' in source
    assert 'sd_ready_gate_ok := false' in source
    assert 'bool sd_entry_best_context_ok = true' in source
    assert 'if not sd_support_any_recent' in source
    assert 'sd_entry_best_context_ok := false' in source
    assert 'if sd_require_for_ready' in source
    assert 'if not sd_ready_context_ok' in source
    assert 'sd_entry_best_context_ok := false' in source
    assert 'bool sd_entry_best_gate_ok = true' in source
    assert 'if use_sd_confluence and sd_require_for_entry_best' in source
    assert 'if not sd_entry_best_context_ok' in source
    assert 'sd_entry_best_gate_ok := false' in source
    assert 'bool sd_entry_strict_context_ok = true' in source
    assert 'if not sd_support_any_recent' in source
    assert 'sd_entry_strict_context_ok := false' in source
    assert 'if sd_require_both_for_entry_strict' in source
    assert 'if not sd_support_both_recent' in source
    assert 'sd_entry_strict_context_ok := false' in source
    assert 'if not sd_ready_context_ok' in source
    assert 'sd_entry_strict_context_ok := false' in source
    assert 'bool sd_entry_strict_gate_ok = true' in source
    assert 'if use_sd_confluence' in source
    assert 'if not sd_entry_strict_context_ok' in source
    assert 'sd_entry_strict_gate_ok := false' in source
    assert 'bool sd_ready_context_ok = sd_support_any_recent and (not sd_require_osc_rising_for_ready or sd_rising)' not in source
    assert 'bool sd_above_zero = not na(sd_value) and sd_value > 0' not in source
    assert 'bool sd_below_zero = not na(sd_value) and sd_value < 0' not in source
    assert 'bool sd_rising = not na(sd_value) and sd_value > sd_value[1]' not in source
    assert 'bool sd_falling = not na(sd_value) and sd_value < sd_value[1]' not in source
    assert 'bool sd_bullish_divergence_recent = not na(sd_bull_div_since_bars) and sd_bull_div_since_bars <= sd_recent_window' not in source
    assert 'bool sd_higher_lows_recent = not na(sd_higher_lows_since_bars) and sd_higher_lows_since_bars <= sd_recent_window' not in source
    assert 'bool sd_support_any_recent = sd_bullish_divergence_recent or sd_higher_lows_recent' not in source
    assert 'bool sd_support_both_recent = sd_bullish_divergence_recent and sd_higher_lows_recent' not in source
    assert 'bool sd_armed_gate_ok = not use_sd_confluence or not sd_require_for_armed or sd_support_any_recent' not in source
    assert 'bool sd_early_gate_ok = not use_sd_confluence or not sd_require_for_early or sd_support_any_recent' not in source
    assert 'bool sd_confirmed_gate_ok = not use_sd_confluence or not sd_require_for_confirmed or sd_support_any_recent' not in source
    assert 'bool sd_ready_gate_ok = not use_sd_confluence or not sd_require_for_ready or sd_ready_context_ok' not in source
    assert 'sd_armed_gate_ok := sd_support_any_recent' not in source
    assert 'sd_early_gate_ok := sd_support_any_recent' not in source
    assert 'sd_confirmed_gate_ok := sd_support_any_recent' not in source
    assert 'sd_ready_gate_ok := sd_ready_context_ok' not in source
    assert 'bool sd_entry_best_context_ok = (not sd_require_for_ready or sd_ready_context_ok) and sd_support_any_recent' not in source
    assert 'bool sd_entry_best_context_ok = sd_support_any_recent' not in source
    assert 'sd_entry_best_context_ok := sd_ready_context_ok and sd_support_any_recent' not in source
    assert 'bool sd_entry_best_gate_ok = not use_sd_confluence or not sd_require_for_entry_best or sd_entry_best_context_ok' not in source
    assert 'sd_entry_best_gate_ok := sd_entry_best_context_ok' not in source
    assert 'bool sd_entry_strict_context_ok = (not sd_require_for_ready or sd_ready_context_ok) and (sd_require_both_for_entry_strict ? sd_support_both_recent : sd_support_any_recent)' not in source
    assert 'bool sd_entry_strict_context_ok = sd_support_any_recent' not in source
    assert 'sd_entry_strict_context_ok := sd_support_both_recent' not in source
    assert 'sd_entry_strict_context_ok := sd_ready_context_ok and sd_entry_strict_context_ok' not in source
    assert 'bool sd_entry_strict_gate_ok = not use_sd_confluence or sd_entry_strict_context_ok' not in source
    assert 'sd_entry_strict_gate_ok := sd_entry_strict_context_ok' not in source


def test_effective_live_break_overrides_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'float effective_ob_reclaim_min_penetration = 0.0' in source
    assert 'effective_ob_reclaim_min_penetration := ob_reclaim_min_penetration' in source
    assert 'float effective_fvg_reclaim_min_penetration = 0.0' in source
    assert 'effective_fvg_reclaim_min_penetration := fvg_reclaim_min_penetration' in source
    assert 'float effective_relvol_good = 0.0' in source
    assert 'effective_relvol_good := relvol_good' in source
    assert 'float effective_long_invalidation_atr_mult = 0.0' in source
    assert 'effective_long_invalidation_atr_mult := long_invalidation_atr_mult' in source
    assert 'bool effective_use_live_confirm_break = true' in source
    assert 'if not use_live_confirm_break' in source
    assert 'effective_use_live_confirm_break := false' in source
    assert 'bool effective_use_live_invalidation_break = true' in source
    assert 'if not use_live_invalidation_break' in source
    assert 'effective_use_live_invalidation_break := false' in source
    assert 'int effective_fast_decay_setup_age_max = 0' in source
    assert 'effective_fast_decay_setup_age_max := long_setup_expiry_bars' in source
    assert 'int effective_fast_decay_confirm_age_max = 0' in source
    assert 'effective_fast_decay_confirm_age_max := long_confirm_expiry_bars' in source
    assert 'if micro_stop_hunt_force_close_confirm' in source
    assert 'if micro_stop_hunt_disable_live_invalid' in source
    assert 'if use_microstructure_profiles and micro_is_fast_decay' in source
    assert 'effective_fast_decay_setup_age_max := math.min(effective_fast_decay_setup_age_max, micro_fast_decay_setup_age_max)' in source
    assert 'effective_fast_decay_confirm_age_max := math.min(effective_fast_decay_confirm_age_max, micro_fast_decay_confirm_age_max)' in source
    assert 'float effective_ob_reclaim_min_penetration = ob_reclaim_min_penetration' not in source
    assert 'float effective_fvg_reclaim_min_penetration = fvg_reclaim_min_penetration' not in source
    assert 'float effective_relvol_good = relvol_good' not in source
    assert 'float effective_long_invalidation_atr_mult = long_invalidation_atr_mult' not in source
    assert 'bool effective_use_live_confirm_break = use_live_confirm_break' not in source
    assert 'bool effective_use_live_invalidation_break = use_live_invalidation_break' not in source
    assert 'int effective_fast_decay_setup_age_max = long_setup_expiry_bars' not in source
    assert 'int effective_fast_decay_confirm_age_max = long_confirm_expiry_bars' not in source


def test_volatility_context_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'compute_vol_regime() =>' in source
    assert 'float _ma1 = _ma1e' in source
    assert "if vol_ma_mode == 'QEMA-like'" in source
    assert '_ma1 := _ma1q' in source
    assert 'float _ma2 = _ma2e' in source
    assert '_ma2 := _ma2q' in source
    assert 'float _ma3 = _ma3e' in source
    assert '_ma3 := _ma3q' in source
    assert 'float _ma4 = _ma4e' in source
    assert '_ma4 := _ma4q' in source
    assert 'bool _stack_order = false' in source
    assert 'if _ma1 > _ma2 and _ma2 > _ma3 and _ma3 > _ma4' in source
    assert '_stack_order := true' in source
    assert 'bool _stack_slopes = false' in source
    assert 'if _ma1 > _ma1[1] and _ma2 > _ma2[1] and _ma3 > _ma3[1] and _ma4 > _ma4[1]' in source
    assert '_stack_slopes := true' in source
    assert 'bool _spread_rising = false' in source
    assert 'if not na(_spread_pct) and _spread_pct > _spread_pct[1]' in source
    assert '_spread_rising := true' in source
    assert 'bool _mom_expanding = false' in source
    assert 'if not na(_mom) and _mom > 0 and _mom > _mom[1]' in source
    assert '_mom_expanding := true' in source
    assert 'bool _squeeze = false' in source
    assert 'if _bb_upper < _kc_upper and _bb_lower > _kc_lower' in source
    assert '_squeeze := true' in source
    assert 'bool _released = false' in source
    assert 'if not _squeeze and _squeeze[1]' in source
    assert '_released := true' in source
    assert 'bool _sq_recent = false' in source
    assert 'if not na(_sq_since) and _sq_since <= vol_squeeze_recent_bars' in source
    assert '_sq_recent := true' in source
    assert 'bool _rel_recent = false' in source
    assert 'if not na(_rel_since) and _rel_since <= vol_release_recent_bars' in source
    assert '_rel_recent := true' in source
    assert 'bool _trend_ok = false' in source
    assert 'if _stack_order and (not vol_require_all_stack_slopes or _stack_slopes)' in source
    assert '_trend_ok := true' in source
    assert 'bool vol_watchlist_context_ok = true' in source
    assert 'if use_volatility_regime' in source
    assert 'if not vol_regime_trend_ok' in source
    assert 'vol_watchlist_context_ok := false' in source
    assert 'if vol_require_squeeze_for_watchlist' in source
    assert 'vol_watchlist_context_ok := vol_watchlist_context_ok and (vol_squeeze_on or vol_squeeze_recent or vol_squeeze_release_recent)' in source
    assert 'bool vol_ready_context_ok = true' in source
    assert 'vol_ready_context_ok := false' in source
    assert 'if vol_regime_trend_ok and vol_momentum_expanding_long and vol_stack_spread_rising' in source
    assert 'vol_ready_context_ok := true' in source
    assert 'if vol_require_squeeze_for_ready' in source
    assert 'vol_ready_context_ok := vol_ready_context_ok and (vol_squeeze_on or vol_squeeze_recent or vol_squeeze_release_recent)' in source
    assert 'bool vol_entry_best_context_ok = true' in source
    assert 'if not vol_ready_context_ok' in source
    assert 'vol_entry_best_context_ok := false' in source
    assert 'if vol_require_release_for_entry_best' in source
    assert 'vol_entry_best_context_ok := vol_entry_best_context_ok and vol_squeeze_release_recent' in source
    assert 'bool vol_entry_strict_context_ok = true' in source
    assert 'vol_entry_strict_context_ok := false' in source
    assert 'if vol_entry_best_context_ok and vol_bull_stack_slopes' in source
    assert 'vol_entry_strict_context_ok := true' in source
    assert 'if vol_require_release_for_entry_strict' in source
    assert 'vol_entry_strict_context_ok := vol_entry_strict_context_ok and vol_squeeze_release_recent' in source
    assert 'bool vol_watchlist_context_ok_safe = true' in source
    assert 'if not vol_watchlist_context_ok' in source
    assert 'vol_watchlist_context_ok_safe := false' in source
    assert 'if signal_mode != ct.SignalMode.AGGRESSIVE_LIVE and not barstate.isconfirmed' in source
    assert 'if bar_index > 0' in source
    assert 'vol_watchlist_context_ok_safe := vol_watchlist_context_ok[1]' in source
    assert 'bool vol_entry_best_context_ok_safe = true' in source
    assert 'if not vol_entry_best_context_ok' in source
    assert 'vol_entry_best_context_ok_safe := false' in source
    assert 'vol_entry_best_context_ok_safe := vol_entry_best_context_ok[1]' in source
    assert 'bool vol_entry_strict_context_ok_safe = true' in source
    assert 'if not vol_entry_strict_context_ok' in source
    assert 'vol_entry_strict_context_ok_safe := false' in source
    assert 'vol_entry_strict_context_ok_safe := vol_entry_strict_context_ok[1]' in source
    assert 'bool vol_watchlist_context_ok = not use_volatility_regime or (vol_regime_trend_ok and (not vol_require_squeeze_for_watchlist or vol_squeeze_on or vol_squeeze_recent or vol_squeeze_release_recent))' not in source
    assert 'bool vol_ready_context_ok = not use_volatility_regime or (vol_regime_trend_ok and vol_momentum_expanding_long and vol_stack_spread_rising and (not vol_require_squeeze_for_ready or vol_squeeze_on or vol_squeeze_recent or vol_squeeze_release_recent))' not in source
    assert 'vol_ready_context_ok := vol_regime_trend_ok and vol_momentum_expanding_long and vol_stack_spread_rising' not in source
    assert 'bool vol_entry_best_context_ok = not use_volatility_regime or (vol_ready_context_ok and (not vol_require_release_for_entry_best or vol_squeeze_release_recent))' not in source
    assert 'vol_entry_best_context_ok := vol_ready_context_ok' not in source
    assert 'bool vol_entry_strict_context_ok = not use_volatility_regime or (vol_entry_best_context_ok and vol_bull_stack_slopes and (not vol_require_release_for_entry_strict or vol_squeeze_release_recent))' not in source
    assert 'vol_entry_strict_context_ok := vol_entry_best_context_ok and vol_bull_stack_slopes' not in source
    assert 'bool vol_regime_trend_ok = vol_bull_stack_order and (not vol_require_all_stack_slopes or vol_bull_stack_slopes)' not in source
    assert 'vol_watchlist_context_ok := vol_regime_trend_ok' not in source
    assert 'bool vol_watchlist_context_ok_safe = vol_watchlist_context_ok' not in source
    assert 'bool vol_entry_best_context_ok_safe = vol_entry_best_context_ok' not in source
    assert 'bool vol_entry_strict_context_ok_safe = vol_entry_strict_context_ok' not in source
    assert "float vol_ma_1 = vol_ma_mode == 'QEMA-like' ? vol_ma_1_qema : vol_ma_1_ema" not in source
    assert "float vol_ma_2 = vol_ma_mode == 'QEMA-like' ? vol_ma_2_qema : vol_ma_2_ema" not in source
    assert "float vol_ma_3 = vol_ma_mode == 'QEMA-like' ? vol_ma_3_qema : vol_ma_3_ema" not in source
    assert "float vol_ma_4 = vol_ma_mode == 'QEMA-like' ? vol_ma_4_qema : vol_ma_4_ema" not in source
    assert 'bool vol_bull_stack_order = vol_ma_1 > vol_ma_2 and vol_ma_2 > vol_ma_3 and vol_ma_3 > vol_ma_4' not in source
    assert 'bool vol_bull_stack_slopes = vol_ma_1 > vol_ma_1[1] and vol_ma_2 > vol_ma_2[1] and vol_ma_3 > vol_ma_3[1] and vol_ma_4 > vol_ma_4[1]' not in source
    assert 'bool vol_stack_spread_rising = not na(vol_stack_spread_pct) and vol_stack_spread_pct > vol_stack_spread_pct[1]' not in source
    assert 'bool vol_momentum_expanding_long = not na(vol_momentum) and vol_momentum > 0 and vol_momentum > vol_momentum[1]' not in source
    assert 'bool vol_squeeze_on = vol_bb_upper < vol_kc_upper and vol_bb_lower > vol_kc_lower' not in source
    assert 'bool vol_squeeze_released = not vol_squeeze_on and vol_squeeze_on[1]' not in source
    assert 'bool vol_squeeze_recent = not na(vol_squeeze_since_bars) and vol_squeeze_since_bars <= vol_squeeze_recent_bars' not in source
    assert 'bool vol_squeeze_release_recent = not na(vol_release_since_bars) and vol_release_since_bars <= vol_release_recent_bars' not in source
    assert "float vol_ma_2 = vol_ma_mode == 'QEMA-like' ? vol_ma_2_qema : vol_ma_2_ema" not in source


def test_stretch_context_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'float stretch_lower_threshold = float(na)' in source
    assert 'if not na(stretch_mean) and not na(stretch_std)' in source
    assert 'stretch_lower_threshold := stretch_mean - lower_extreme_z * stretch_std' in source
    assert 'bool in_lower_extreme = false' in source
    assert 'if not na(stretch_lower_threshold) and low <= stretch_lower_threshold' in source
    assert 'in_lower_extreme := true' in source
    assert 'bool lower_extreme_recent = false' in source
    assert 'if not na(lower_extreme_since_bars) and lower_extreme_since_bars <= lower_extreme_recent_bars' in source
    assert 'lower_extreme_recent := true' in source
    assert 'float distance_to_mean_z = float(na)' in source
    assert 'if not na(stretch_mean) and not na(stretch_std) and stretch_std > 0' in source
    assert 'distance_to_mean_z := (close - stretch_mean) / stretch_std' in source
    assert 'bool anti_chase_ok_ready = true' in source
    assert 'bool anti_chase_ok_entry_best = true' in source
    assert 'bool anti_chase_ok_entry_strict = true' in source
    assert 'if use_stretch_context and not na(distance_to_mean_z)' in source
    assert 'anti_chase_ok_ready := distance_to_mean_z <= anti_chase_max_z_ready' in source
    assert 'anti_chase_ok_entry_best := distance_to_mean_z <= anti_chase_max_z_best' in source
    assert 'anti_chase_ok_entry_strict := distance_to_mean_z <= anti_chase_max_z_strict' in source
    assert 'bool stretch_watchlist_context_ok = true' in source
    assert 'if use_stretch_context and stretch_require_lower_extreme_for_watchlist' in source
    assert 'stretch_watchlist_context_ok := in_lower_extreme or lower_extreme_recent' in source
    assert 'bool stretch_ready_context_ok = true' in source
    assert 'if use_stretch_context' in source
    assert 'stretch_ready_context_ok := anti_chase_ok_ready' in source
    assert 'if stretch_require_lower_extreme_for_ready' in source
    assert 'stretch_ready_context_ok := stretch_ready_context_ok and (in_lower_extreme or lower_extreme_recent)' in source
    assert 'bool stretch_entry_best_context_ok = true' in source
    assert 'stretch_entry_best_context_ok := stretch_ready_context_ok and anti_chase_ok_entry_best' in source
    assert 'if stretch_require_lower_extreme_for_entry_best' in source
    assert 'stretch_entry_best_context_ok := stretch_entry_best_context_ok and (in_lower_extreme or lower_extreme_recent)' in source
    assert 'bool stretch_entry_strict_context_ok = true' in source
    assert 'stretch_entry_strict_context_ok := stretch_entry_best_context_ok and anti_chase_ok_entry_strict' in source
    assert 'if stretch_require_lower_extreme_for_entry_strict' in source
    assert 'stretch_entry_strict_context_ok := stretch_entry_strict_context_ok and (in_lower_extreme or lower_extreme_recent)' in source
    assert 'bool anti_chase_ok_ready = not use_stretch_context or na(distance_to_mean_z) or distance_to_mean_z <= anti_chase_max_z_ready' not in source
    assert 'bool anti_chase_ok_entry_best = not use_stretch_context or na(distance_to_mean_z) or distance_to_mean_z <= anti_chase_max_z_best' not in source
    assert 'bool anti_chase_ok_entry_strict = not use_stretch_context or na(distance_to_mean_z) or distance_to_mean_z <= anti_chase_max_z_strict' not in source
    assert 'float stretch_lower_threshold = not na(stretch_mean) and not na(stretch_std) ? stretch_mean - lower_extreme_z * stretch_std : na' not in source
    assert 'bool lower_extreme_recent = not na(lower_extreme_since_bars) and lower_extreme_since_bars <= lower_extreme_recent_bars' not in source
    assert 'float distance_to_mean_z = not na(stretch_mean) and not na(stretch_std) and stretch_std > 0 ? (close - stretch_mean) / stretch_std : na' not in source
    assert 'bool stretch_watchlist_context_ok = not use_stretch_context or (not stretch_require_lower_extreme_for_watchlist or in_lower_extreme or lower_extreme_recent)' not in source
    assert 'bool stretch_ready_context_ok = not use_stretch_context or ((not stretch_require_lower_extreme_for_ready or in_lower_extreme or lower_extreme_recent) and anti_chase_ok_ready)' not in source
    assert 'bool stretch_entry_best_context_ok = not use_stretch_context or (stretch_ready_context_ok and (not stretch_require_lower_extreme_for_entry_best or in_lower_extreme or lower_extreme_recent) and anti_chase_ok_entry_best)' not in source
    assert 'bool stretch_entry_strict_context_ok = not use_stretch_context or (stretch_entry_best_context_ok and (not stretch_require_lower_extreme_for_entry_strict or in_lower_extreme or lower_extreme_recent) and anti_chase_ok_entry_strict)' not in source
    assert 'bool in_lower_extreme = not na(stretch_lower_threshold) and low <= stretch_lower_threshold' not in source


def test_ddvi_context_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool ddvi_bias_bull = false' in source
    assert 'if use_ddvi_context and not na(ddvi) and ddvi > 0' in source
    assert 'ddvi_bias_bull := true' in source
    assert 'bool ddvi_bias_rising = false' in source
    assert 'if use_ddvi_context and not na(ddvi) and not na(ddvi[1]) and ddvi > ddvi[1]' in source
    assert 'ddvi_bias_rising := true' in source
    assert 'bool ddvi_bias_cross_up = false' in source
    assert 'if use_ddvi_context and ddvi_event_bar_ok and not na(ddvi) and ddvi_bias_cross_up_raw' in source
    assert 'ddvi_bias_cross_up := true' in source
    assert 'bool ddvi_bias_ok = false' in source
    assert 'if ddvi_bias_bull and ddvi_bias_rising' in source
    assert 'ddvi_bias_ok := true' in source
    assert 'bool ddvi_bias_transition_ok = false' in source
    assert 'if ddvi_bias_cross_up or (ddvi_bias_bull and ddvi_bias_rising)' in source
    assert 'ddvi_bias_transition_ok := true' in source
    assert 'bool ddvi_lower_extreme_now = false' in source
    assert 'if use_ddvi_context and not na(ddvi) and not na(ddvi_bb_lower) and ddvi <= ddvi_bb_lower' in source
    assert 'ddvi_lower_extreme_now := true' in source
    assert 'bool ddvi_lower_extreme_recent = false' in source
    assert 'if use_ddvi_context and not na(ddvi_lower_extreme_since) and ddvi_lower_extreme_since <= ddvi_lower_extreme_lookback' in source
    assert 'ddvi_lower_extreme_recent := true' in source
    assert 'bool ddvi_recover_from_lower_extreme = false' in source
    assert 'if use_ddvi_context and ddvi_event_bar_ok and not na(ddvi) and not na(ddvi_bb_lower) and ddvi_recover_from_lower_extreme_raw' in source
    assert 'ddvi_recover_from_lower_extreme := true' in source
    assert 'bool ddvi_lower_extreme_context = false' in source
    assert 'if ddvi_lower_extreme_now or ddvi_lower_extreme_recent or ddvi_recover_from_lower_extreme' in source
    assert 'ddvi_lower_extreme_context := true' in source
    assert 'bool hidden_bull_divergence = false' in source
    assert 'if use_ddvi_context and use_ddvi_hidden_bull and ddvi_hidden_bull' in source
    assert 'hidden_bull_divergence := true' in source
    assert 'bool strong_bull_divergence = false' in source
    assert 'if use_ddvi_context and use_ddvi_strong_bull and ddvi_strong_bull' in source
    assert 'strong_bull_divergence := true' in source
    assert 'bool ddvi_bull_divergence_any = false' in source
    assert 'if hidden_bull_divergence or strong_bull_divergence' in source
    assert 'ddvi_bull_divergence_any := true' in source
    assert 'bool ddvi_watchlist_ok = true' in source
    assert 'ddvi_watchlist_ok := ddvi_lower_extreme_context or ddvi_bias_rising' in source
    assert 'bool ddvi_ready_ok = true' in source
    assert 'ddvi_ready_ok := ddvi_recover_from_lower_extreme or (ddvi_bias_rising and not ddvi_lower_extreme_now)' in source
    assert 'bool ddvi_entry_best_ok = true' in source
    assert 'ddvi_entry_best_ok := ddvi_ready_ok and (ddvi_bias_transition_ok or hidden_bull_divergence or strong_bull_divergence)' in source
    assert 'bool ddvi_entry_strict_ok = true' in source
    assert 'ddvi_entry_strict_ok := ddvi_entry_best_ok and ddvi_bias_ok and not ddvi_lower_extreme_now' in source
    assert 'if ddvi_close_safe_only and not barstate.isconfirmed' in source
    assert 'if bar_index > 0' in source
    assert 'ddvi_watchlist_ok := ddvi_watchlist_ok[1]' in source
    assert 'ddvi_ready_ok := ddvi_ready_ok[1]' in source
    assert 'ddvi_entry_best_ok := ddvi_entry_best_ok[1]' in source
    assert 'ddvi_entry_strict_ok := ddvi_entry_strict_ok[1]' in source
    assert 'bool ddvi_watchlist_ok = not use_ddvi_context ? true : (ddvi_lower_extreme_context or ddvi_bias_rising)' not in source
    assert 'bool ddvi_ready_ok = not use_ddvi_context ? true : (ddvi_recover_from_lower_extreme or (ddvi_bias_rising and not ddvi_lower_extreme_now))' not in source
    assert 'bool ddvi_entry_best_ok = not use_ddvi_context ? true : (ddvi_ready_ok and (ddvi_bias_transition_ok or hidden_bull_divergence or strong_bull_divergence))' not in source
    assert 'bool ddvi_entry_strict_ok = not use_ddvi_context ? true : (ddvi_entry_best_ok and ddvi_bias_ok and not ddvi_lower_extreme_now)' not in source
    assert 'bool ddvi_bias_bull = use_ddvi_context and not na(ddvi) and ddvi > 0' not in source
    assert 'bool ddvi_bias_rising = use_ddvi_context and not na(ddvi) and not na(ddvi[1]) and ddvi > ddvi[1]' not in source
    assert 'bool ddvi_bias_cross_up = use_ddvi_context and ddvi_event_bar_ok and not na(ddvi) and ddvi_bias_cross_up_raw' not in source
    assert 'bool ddvi_bias_ok = ddvi_bias_bull and ddvi_bias_rising' not in source
    assert 'bool ddvi_bias_transition_ok = ddvi_bias_cross_up or (ddvi_bias_bull and ddvi_bias_rising)' not in source
    assert 'bool ddvi_lower_extreme_now = use_ddvi_context and not na(ddvi) and not na(ddvi_bb_lower) and ddvi <= ddvi_bb_lower' not in source
    assert 'bool ddvi_lower_extreme_recent = use_ddvi_context and not na(ddvi_lower_extreme_since) and ddvi_lower_extreme_since <= ddvi_lower_extreme_lookback' not in source
    assert 'bool ddvi_recover_from_lower_extreme = use_ddvi_context and ddvi_event_bar_ok and not na(ddvi) and not na(ddvi_bb_lower) and ddvi_recover_from_lower_extreme_raw' not in source
    assert 'bool ddvi_lower_extreme_context = ddvi_lower_extreme_now or ddvi_lower_extreme_recent or ddvi_recover_from_lower_extreme' not in source
    assert 'bool hidden_bull_divergence = use_ddvi_context and use_ddvi_hidden_bull and ddvi_hidden_bull' not in source
    assert 'bool strong_bull_divergence = use_ddvi_context and use_ddvi_strong_bull and ddvi_strong_bull' not in source
    assert 'bool ddvi_bull_divergence_any = hidden_bull_divergence or strong_bull_divergence' not in source
    assert 'ddvi_watchlist_ok := bar_index > 0 ? ddvi_watchlist_ok[1] : ddvi_watchlist_ok' not in source
    assert 'ddvi_ready_ok := bar_index > 0 ? ddvi_ready_ok[1] : ddvi_ready_ok' not in source
    assert 'ddvi_entry_best_ok := bar_index > 0 ? ddvi_entry_best_ok[1] : ddvi_entry_best_ok' not in source
    assert 'ddvi_entry_strict_ok := bar_index > 0 ? ddvi_entry_strict_ok[1] : ddvi_entry_strict_ok' not in source


def test_ddvi_and_market_safe_fallbacks_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool vola_compression_now = false' in source
    assert 'if not na(atr_baseline) and not na(range_baseline) and atr_baseline > 0 and range_baseline > 0 and atr_now <= atr_baseline * compression_ratio_max and bar_range <= range_baseline * compression_ratio_max' in source
    assert 'vola_compression_now := true' in source
    assert 'int compression_since_bars = ta.barssince(vola_compression_now)' in source
    assert 'bool vola_compression_recent = false' in source
    assert 'if not na(compression_since_bars) and compression_since_bars <= compression_recent_bars' in source
    assert 'vola_compression_recent := true' in source
    assert 'bool vola_expansion_now = false' in source
    assert 'if not na(range_baseline) and range_baseline > 0 and bar_range >= range_baseline * expansion_range_mult and bull_close_strong' in source
    assert 'vola_expansion_now := true' in source
    assert 'bool vola_regime_gate_ok = true' in source
    assert 'if use_vola_compression_gate' in source
    assert 'vola_regime_gate_ok := vola_compression_recent' in source
    assert 'if require_expansion_on_confirm_or_ready' in source
    assert 'vola_regime_gate_ok := vola_regime_gate_ok and vola_expansion_now' in source
    assert 'bool ddvi_event_bar_ok = barstate.isconfirmed' in source
    assert 'if not ddvi_close_safe_only and signal_mode == ct.SignalMode.AGGRESSIVE_LIVE' in source
    assert 'ddvi_event_bar_ok := true' in source
    assert 'bool ddvi_watchlist_ok_safe = ddvi_watchlist_ok' in source
    assert 'bool ddvi_ready_ok_safe = ddvi_ready_ok' in source
    assert 'bool ddvi_entry_best_ok_safe = ddvi_entry_best_ok' in source
    assert 'bool ddvi_entry_strict_ok_safe = ddvi_entry_strict_ok' in source
    assert 'if signal_mode != ct.SignalMode.AGGRESSIVE_LIVE and not barstate.isconfirmed' in source
    assert 'if bar_index > 0' in source
    assert 'ddvi_watchlist_ok_safe := ddvi_watchlist_ok[1]' in source
    assert 'ddvi_ready_ok_safe := ddvi_ready_ok[1]' in source
    assert 'ddvi_entry_best_ok_safe := ddvi_entry_best_ok[1]' in source
    assert 'ddvi_entry_strict_ok_safe := ddvi_entry_strict_ok[1]' in source
    assert 'bool index_gate_effective_ok = true' in source
    assert 'bool index_gate_ok_raw = true' in source
    assert 'if use_index_gate' in source
    assert 'index_gate_ok_raw := index_gate_ok_calc' in source
    assert 'index_gate_effective_ok := index_gate_ok_raw' in source
    assert 'if index_missing' in source
    assert 'index_gate_effective_ok := not block_on_missing_market_symbol' in source
    assert 'bool sector_gate_effective_ok = true' in source
    assert 'bool sector_gate_ok_raw = true' in source
    assert 'sector_gate_ok_raw := sector_gate_ok_calc' in source
    assert 'sector_gate_effective_ok := sector_gate_ok_raw' in source
    assert 'if sector_missing' in source
    assert 'sector_gate_effective_ok := not block_on_missing_market_symbol' in source
    assert 'bool breadth_gate_effective_ok = true' in source
    assert 'bool breadth_gate_ok_raw = true' in source
    assert 'breadth_gate_ok_raw := breadth_gate_ok_calc' in source
    assert 'breadth_gate_effective_ok := breadth_gate_ok_raw' in source
    assert 'if breadth_missing' in source
    assert 'breadth_gate_effective_ok := not block_on_missing_market_symbol' in source
    assert 'bool market_symbols_missing = false' in source
    assert 'if (use_index_gate and index_missing) or (use_sector_gate and sector_missing) or (use_breadth_symbol_gate and breadth_missing)' in source
    assert 'market_symbols_missing := true' in source
    assert 'bool market_regime_gate_ok_raw = false' in source
    assert 'if index_gate_effective_ok and sector_gate_effective_ok and breadth_gate_effective_ok' in source
    assert 'market_regime_gate_ok_raw := true' in source
    assert 'bool market_regime_gate_ok = market_regime_gate_ok_raw' in source
    assert 'market_regime_gate_ok := market_regime_gate_ok_raw[1]' in source
    assert 'bool vola_regime_gate_safe = vola_regime_gate_ok' in source
    assert 'vola_regime_gate_safe := vola_regime_gate_ok[1]' in source
    assert 'ddvi_watchlist_ok_safe := bar_index > 0 ? ddvi_watchlist_ok[1] : ddvi_watchlist_ok' not in source
    assert 'ddvi_ready_ok_safe := bar_index > 0 ? ddvi_ready_ok[1] : ddvi_ready_ok' not in source
    assert 'ddvi_entry_best_ok_safe := bar_index > 0 ? ddvi_entry_best_ok[1] : ddvi_entry_best_ok' not in source
    assert 'ddvi_entry_strict_ok_safe := bar_index > 0 ? ddvi_entry_strict_ok[1] : ddvi_entry_strict_ok' not in source
    assert 'bool index_gate_ok_raw = not use_index_gate or index_gate_ok_calc' not in source
    assert 'bool sector_gate_ok_raw = not use_sector_gate or sector_gate_ok_calc' not in source
    assert 'bool breadth_gate_ok_raw = not use_breadth_symbol_gate or breadth_gate_ok_calc' not in source
    assert 'bool market_symbols_missing = (use_index_gate and index_missing) or (use_sector_gate and sector_missing) or (use_breadth_symbol_gate and breadth_missing)' not in source
    assert 'bool market_regime_gate_ok_raw = index_gate_effective_ok and sector_gate_effective_ok and breadth_gate_effective_ok' not in source
    assert 'bool index_gate_effective_ok = not use_index_gate or (index_missing ? not block_on_missing_market_symbol : index_gate_ok_raw)' not in source
    assert 'bool sector_gate_effective_ok = not use_sector_gate or (sector_missing ? not block_on_missing_market_symbol : sector_gate_ok_raw)' not in source
    assert 'bool breadth_gate_effective_ok = not use_breadth_symbol_gate or (breadth_missing ? not block_on_missing_market_symbol : breadth_gate_ok_raw)' not in source
    assert 'bool vola_compression_now = not na(atr_baseline) and not na(range_baseline) and atr_baseline > 0 and range_baseline > 0 and atr_now <= atr_baseline * compression_ratio_max and bar_range <= range_baseline * compression_ratio_max' not in source
    assert 'bool vola_compression_recent = not na(compression_since_bars) and compression_since_bars <= compression_recent_bars' not in source
    assert 'bool vola_expansion_now = not na(range_baseline) and range_baseline > 0 and bar_range >= range_baseline * expansion_range_mult and bull_close_strong' not in source
    assert 'bool vola_regime_gate_ok = not use_vola_compression_gate ? true : vola_compression_recent and (not require_expansion_on_confirm_or_ready or vola_expansion_now)' not in source
    assert 'bool ddvi_event_bar_ok = ddvi_close_safe_only ? barstate.isconfirmed : (signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? true : barstate.isconfirmed)' not in source
    assert 'market_regime_gate_ok := bar_index > 0 ? market_regime_gate_ok_raw[1] : market_regime_gate_ok_raw' not in source
    assert 'vola_regime_gate_safe := bar_index > 0 ? vola_regime_gate_ok[1] : vola_regime_gate_ok' not in source


def test_signal_and_long_state_contract_are_declared_for_safe_refactors() -> None:
    source = _read_smc_source()

    assert 'indicator("Smart Money Concepts (Highly Advanced)", "SMC++", overlay = true, max_bars_back = 500, max_lines_count = 300, max_boxes_count = 300, max_labels_count = 500)' in source
    assert '// - Market structure, OB/FVG engines, dashboards, alerts, and the long-dip lifecycle are coordinated locally.' in source
    assert '// - The long lifecycle flows as: zone detection -> reclaim/arm -> confirm -> ready/entry -> invalidated/reset.' in source
    assert '// Signal / state contract' in source
    assert '// - *_raw      : raw condition, may be intrabar/transient' in source
    assert '// - *_latched  : intrabar-persisted event/state until bar close' in source
    assert 'type LongLifecycleState' in source
    assert "var LongLifecycleState long_state = LongLifecycleState.new(false, false, na, na, na, na, LONG_SOURCE_NONE, LONG_SOURCE_NONE, na, 0, LONG_SOURCE_NONE, na, na, na, 0, na, 0, 'None', na)" in source
    assert 'method clear(LongLifecycleState this) =>' in source
    assert 'method arm(LongLifecycleState this, int arm_bar_index, float trigger, float invalidation_level, int entry_origin_source, int backing_zone_kind, int backing_zone_id, int backing_zone_touch_count, int locked_source_kind, int locked_source_id, float locked_source_top, float locked_source_bottom, int locked_source_touch_count, int locked_source_last_touch_bar_index) =>' in source
    assert 'method confirm(LongLifecycleState this, int confirm_bar_index) =>' in source
    assert 'method invalidate(LongLifecycleState this, string reason, float level) =>' in source
    assert 'validate_long_state(LongLifecycleState st, bool enabled = true) =>' in source
    assert 'sync_long_state_from_legacy(LongLifecycleState st' not in source
    assert 'project_long_state(LongLifecycleState st) =>' not in source
    assert 'var bool long_setup_armed = false' not in source
    assert 'var int long_setup_serial = 0' not in source
    assert 'validate_long_state(long_state, show_long_engine_debug)' in source
    assert "state_code == -1 ? 'Invalidated' : state_code == 0 ? 'No Setup' :" not in source
    assert "long_visual_state == -1 ? 'Fail' :" not in source
    assert 'string setup_text = \'No Setup\'' in source
    assert 'string visual_text = \'Ready\'' in source


def test_backing_zone_identity_and_touch_count_persist_after_arm() -> None:
    source = _read_smc_source()

    assert 'int LONG_SOURCE_OB = 1' in source
    assert 'int LONG_SOURCE_FVG = 2' in source
    assert 'select_long_arm_backing_zone_touch_count(int arm_backing_zone_kind, int arm_backing_zone_id, int active_ob_touch_id, int active_ob_touch_count, int touched_bull_ob_id, int touched_bull_ob_touch_count, int active_fvg_touch_id, int active_fvg_touch_count, int touched_bull_fvg_id, int touched_bull_fvg_touch_count) =>' in source
    assert 'int _ob_backing_zone_id = na' in source
    assert 'if long_state.backing_zone_kind == LONG_SOURCE_OB' in source
    assert '_ob_backing_zone_id := long_state.backing_zone_id' in source
    assert 'int _fvg_backing_zone_id = na' in source
    assert 'if long_state.backing_zone_kind == LONG_SOURCE_FVG' in source
    assert '_fvg_backing_zone_id := long_state.backing_zone_id' in source
    assert 'int long_arm_locked_source_id = resolve_long_zone_id(arm_backing_zone_kind, arm_backing_zone_id)' in source
    assert 'int long_arm_locked_source_last_touch_bar_index = na' in source
    assert 'if not na(long_arm_locked_source_id)' in source
    assert 'long_arm_locked_source_last_touch_bar_index := bar_index' in source
    assert 'int long_arm_locked_source_last_touch_bar_index = not na(long_arm_locked_source_id) ? bar_index : na' not in source
    assert 'long_state.arm(bar_index, arm_trigger_candidate, arm_invalidation_candidate, arm_source_kind, arm_backing_zone_kind, arm_backing_zone_id, long_arm_backing_zone_touch_count, arm_backing_zone_kind, long_arm_locked_source_id, long_arm_locked_source_top, long_arm_locked_source_bottom, long_arm_backing_zone_touch_count, long_arm_locked_source_last_touch_bar_index)' in source
    assert 'bool bullish_fvg_filled_alert = false' in source
    assert 'if array.size(filled_fvgs_new_bull) > 0' in source
    assert 'bullish_fvg_filled_alert := true' in source
    assert 'FVG bull_filled_alert_gap = na' in source
    assert 'if bullish_fvg_filled_alert' in source
    assert 'bull_filled_alert_gap := array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1)' in source


def test_invalidation_path_records_specific_reason_and_clears_setup_state() -> None:
    source = _read_smc_source()

    assert 'resolve_long_invalidation_reason(bool long_source_broken, bool long_source_lost, bool long_setup_expired, bool long_confirm_expired, int long_validation_source, int long_entry_origin_source, string long_setup_source_display) =>' in source
    assert 'resolve_long_validation_source(int long_locked_source_kind) =>' in source
    assert "string long_validation_source_text = resolve_long_source_text(long_validation_source)" in source
    assert "string long_entry_origin_source_text = resolve_long_source_text(long_entry_origin_source)" in source
    assert "string invalidation_reason = long_setup_source_display" in source
    assert "invalidation_reason := long_validation_source_text + ' source invalidated'" in source
    assert "invalidation_reason := long_validation_source_text + ' backing zone lost'" in source
    assert "invalidation_reason := long_entry_origin_source_text + ' setup expired'" in source
    assert "invalidation_reason := long_entry_origin_source_text + ' confirm expired'" in source
    assert "long_source_broken ? long_validation_source_text + ' source invalidated'" not in source
    assert 'int long_validation_source_now = resolve_long_validation_source(long_locked_source_kind_final)' in source
    assert 'string long_setup_source_display_now = compose_long_setup_source_display(long_state.entry_origin_source, long_validation_source_now)' in source
    assert 'string long_invalidation_reason = resolve_long_invalidation_reason(long_source_broken, long_source_lost, long_setup_expired, long_confirm_expired, long_validation_source_now, long_state.entry_origin_source, long_setup_source_display_now)' in source
    assert 'long_invalidate_signal := long_state.armed or long_state.confirmed' in source
    assert 'long_state.invalidate(long_invalidation_reason, long_state.invalidation_level)' in source
    assert 'project_long_state(long_state)' not in source
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
    assert 'array.clear(this.buckets)' in source
    assert 'this.buckets := na' in source
    assert 'array.clear(this.data_values)' in source
    assert 'this.hidden := false' in source
    # Draw methods moved to smc_draw library (d.SmcBox, d.SmcLabel)
    assert 'import preuss_steffen/smc_draw/1 as d' in source
    assert 'method rendered_right_time(OrderBlock this, bool extend_until_broken = true) =>' in source
    assert 'int base_right_time = math.max(this.left_top.time, this.right_bottom.time)' in source
    assert 'else if not na(this.profile)' in source
    assert 'this.profile.hide()' in source
    assert 'method rendered_right_time(FVG this, bool extend_until_filled = true) =>' in source
    assert 'int effective_fill_time = effective_live_event_time(this.fill_time, base_right_time)' in source
    assert 'int right = not na(right_override) ? right_override :\n             config.extend_until_filled ?' not in source
    assert 'int right = na' in source


def test_indicator_resource_caps_match_runtime_history_behavior() -> None:
    source = _read_smc_source()

    assert 'max_lines_count = 300' in source
    assert 'max_boxes_count = 300' in source
    assert 'max_labels_count = 500' in source
    assert "var int long_marker_history_limit = input.int(100, 'Marker History Limit', minval = 0, maxval = 500, group = g_long, inline = 'viz2')" in source
    assert 'u.trim_label_history(reclaim_marker_history, show_reclaim_markers ? long_marker_history_limit_eff : 0)' in source
    assert 'u.trim_label_history(long_state_marker_history, show_long_confirmation_markers ? long_marker_history_limit_eff : 0)' in source
    assert 'u.trim_label_history(long_ready_marker_history, show_long_confirmation_markers ? long_marker_history_limit_eff : 0)' in source
    assert 'state <= -1 ? color.new(color.red, 75) :' not in source
    assert 'color bg = color.new(color.green, 60)' in source


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
    assert 'bool bullish_fvg_filled_alert = false' in source
    assert 'if array.size(filled_fvgs_new_bull) > 0' in source
    assert 'bullish_fvg_filled_alert := true' in source
    assert 'FVG bull_filled_alert_gap = na' in source
    assert 'if bullish_fvg_filled_alert' in source
    assert 'bull_filled_alert_gap := array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1)' in source
    assert 'float bull_filled_alert_level = resolve_fvg_alert_level(bull_filled_alert_gap)' in source
    assert 'array.size(ob_blocks_bull) > 0' in source
    assert 'OrderBlock last_bull_ob = na' in source
    assert 'if array.size(ob_blocks_bull) > 0' in source
    assert 'last_bull_ob := array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1)' in source
    assert 'last_bull_ob_break_level = resolve_ob_alert_level(last_bull_ob)' in source
    assert 'scan_active_bull_ob() =>' in source
    assert 'delete(discarded_blocks_bull)' in source
    assert 'array.clear(ob_discarded_bull)' in source
    assert 'delete(buffer_bull_discarded)' in source
    assert 'array.clear(fvg_discarded_bull)' in source
    assert 'delete(htf_buffer_bull_discarded)' in source
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

    assert 'bool state_update_bar_ok = barstate.isconfirmed' in source
    assert 'if signal_mode == ct.SignalMode.AGGRESSIVE_LIVE' in source
    assert 'state_update_bar_ok := true' in source
    assert 'if state_update_bar_ok and ob_zone_touch_event' in source
    assert 'if state_update_bar_ok and fvg_zone_touch_event' in source
    assert 'if state_update_bar_ok and zone_touch_event' in source
    assert 'if state_update_bar_ok and zone_touch_now and last_zone_touch_bar != bar_index and not na(zone_touch_tracking_id)' in source
    assert 'if state_update_bar_ok and ob_touch_now and last_ob_touch_bar != bar_index and not na(active_bull_ob_id)' in source
    assert 'if state_update_bar_ok and fvg_touch_now and last_fvg_touch_bar != bar_index and not na(active_bull_fvg_id)' in source
    assert "bool state_update_bar_ok = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? true : barstate.isconfirmed" not in source


def test_signal_mode_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'active_break_mode = ct.LevelBreakMode.HIGHLOW' in source
    assert 'if signal_mode == ct.SignalMode.CONFIRMED_ONLY' in source
    assert 'active_break_mode := ct.LevelBreakMode.CLOSE' in source
    assert "string signal_mode_text = 'live rt-only'" in source
    assert "signal_mode_text := 'confirmed'" in source
    assert 'active_break_mode = signal_mode == ct.SignalMode.CONFIRMED_ONLY ? ct.LevelBreakMode.CLOSE : ct.LevelBreakMode.HIGHLOW' not in source
    assert "signal_mode_text = signal_mode == ct.SignalMode.CONFIRMED_ONLY ? 'confirmed' : 'live rt-only'" not in source


def test_visible_range_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'int visible_left_time = na' in source
    assert 'int visible_right_time = na' in source
    assert 'if render_visible_only_eff' in source
    assert 'visible_left_time := chart.left_visible_bar_time' in source
    assert 'visible_right_time := chart.right_visible_bar_time' in source
    assert 'visible_left_time = render_visible_only_eff ? chart.left_visible_bar_time : na' not in source
    assert 'visible_right_time = render_visible_only_eff ? chart.right_visible_bar_time : na' not in source


def test_structure_signal_derivations_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool bullish_structure_break = false' in source
    assert 'if bull_bos_alert or bull_choch_alert' in source
    assert 'bullish_structure_break := true' in source
    assert 'bool bearish_structure_break = false' in source
    assert 'if bear_bos_alert or bear_choch_alert' in source
    assert 'bearish_structure_break := true' in source
    assert 'bool structure_break_detected = false' in source
    assert 'if bullish_structure_break or bearish_structure_break' in source
    assert 'structure_break_detected := true' in source
    assert 'int structure_display_trend = 0' in source
    assert 'if not na(ta.barssince(structure_break_detected))' in source
    assert 'structure_display_trend := trend' in source
    assert 'bool bullish_trend_condition = false' in source
    assert 'if structure_display_trend == 1' in source
    assert 'bullish_trend_condition := true' in source
    assert 'bool bearish_trend_condition = false' in source
    assert 'if structure_display_trend == -1' in source
    assert 'bearish_trend_condition := true' in source
    assert 'bool live_exec = false' in source
    assert 'if signal_mode == ct.SignalMode.AGGRESSIVE_LIVE and barstate.isrealtime' in source
    assert 'live_exec := true' in source
    assert 'bool bull_bos_sig = false' in source
    assert 'bull_bos_sig := bull_bos_alert' in source
    assert 'bool bull_choch_sig = false' in source
    assert 'bull_choch_sig := bull_choch_alert' in source
    assert 'bool bear_bos_sig = false' in source
    assert 'bear_bos_sig := bear_bos_alert' in source
    assert 'bool bear_choch_sig = false' in source
    assert 'bear_choch_sig := bear_choch_alert' in source
    assert 'bool internal_bull_bos_sig = false' in source
    assert 'internal_bull_bos_sig := internal_bull_bos_alert' in source
    assert 'bool internal_bull_choch_sig = false' in source
    assert 'internal_bull_choch_sig := internal_bull_choch_alert' in source
    assert 'bool internal_bear_bos_sig = false' in source
    assert 'internal_bear_bos_sig := internal_bear_bos_alert' in source
    assert 'bool internal_bear_choch_sig = false' in source
    assert 'internal_bear_choch_sig := internal_bear_choch_alert' in source
    assert 'bool bullish_trend_started = false' in source
    assert 'if bullish_trend_safe and not bullish_trend_safe[1]' in source
    assert 'bullish_trend_started := true' in source
    assert 'bool bearish_trend_started = false' in source
    assert 'if bearish_trend_safe and not bearish_trend_safe[1]' in source
    assert 'bearish_trend_started := true' in source
    assert 'bool directional_trend_started = false' in source
    assert 'if bullish_trend_started or bearish_trend_started' in source
    assert 'directional_trend_started := true' in source
    assert 'bool internal_structure_break_detected = false' in source
    assert 'if internal_bull_bos_alert or internal_bull_choch_alert or internal_bear_bos_alert or internal_bear_choch_alert' in source
    assert 'internal_structure_break_detected := true' in source
    assert 'bool show_internal_bull_bos = false' in source
    assert "if show_internals and (show_bull == 'All' or show_bull == 'BOS')" in source
    assert 'show_internal_bull_bos := true' in source
    assert 'bool show_internal_bull_choch = false' in source
    assert "if show_internals and (show_bull == 'All' or show_bull == 'CHoCH')" in source
    assert 'show_internal_bull_choch := true' in source
    assert 'bool show_chart_swing_levels = false' in source
    assert 'if show_latest_swings_levels or show_swing_points' in source
    assert 'show_chart_swing_levels := true' in source
    assert 'int internal_display_trend = 0' in source
    assert 'if not na(ta.barssince(internal_structure_break_detected))' in source
    assert 'internal_display_trend := internal_trend' in source
    assert 'structure_display_trend = not na(ta.barssince(structure_break_detected)) ? trend : 0' not in source
    assert 'bool bullish_structure_break = bull_bos_alert or bull_choch_alert' not in source
    assert 'bool bearish_structure_break = bear_bos_alert or bear_choch_alert' not in source
    assert 'bool structure_break_detected = bullish_structure_break or bearish_structure_break' not in source
    assert 'bool bullish_trend_condition = structure_display_trend == 1' not in source
    assert 'bool bearish_trend_condition = structure_display_trend == -1' not in source
    assert 'bool live_exec = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE and barstate.isrealtime' not in source
    assert 'bool bull_bos_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? bull_bos_alert : barstate.isconfirmed and bull_bos_alert' not in source
    assert 'bool bull_choch_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? bull_choch_alert : barstate.isconfirmed and bull_choch_alert' not in source
    assert 'bool bear_bos_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? bear_bos_alert : barstate.isconfirmed and bear_bos_alert' not in source
    assert 'bool bear_choch_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? bear_choch_alert : barstate.isconfirmed and bear_choch_alert' not in source
    assert 'bool internal_bull_bos_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? internal_bull_bos_alert : barstate.isconfirmed and internal_bull_bos_alert' not in source
    assert 'bool internal_bull_choch_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? internal_bull_choch_alert : barstate.isconfirmed and internal_bull_choch_alert' not in source
    assert 'bool internal_bear_bos_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? internal_bear_bos_alert : barstate.isconfirmed and internal_bear_bos_alert' not in source
    assert 'bool internal_bear_choch_sig = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? internal_bear_choch_alert : barstate.isconfirmed and internal_bear_choch_alert' not in source
    assert 'bool bullish_trend_started = bullish_trend_safe and not bullish_trend_safe[1]' not in source
    assert 'bool bearish_trend_started = bearish_trend_safe and not bearish_trend_safe[1]' not in source
    assert 'bool directional_trend_started = bullish_trend_started or bearish_trend_started' not in source
    assert 'bool internal_structure_break_detected = internal_bull_bos_alert or internal_bull_choch_alert or internal_bear_bos_alert or internal_bear_choch_alert' not in source
    assert "bool show_internal_bull_bos = show_internals and (show_bull == 'All' or show_bull == 'BOS')" not in source
    assert "bool show_internal_bull_choch = show_internals and (show_bull == 'All' or show_bull == 'CHoCH')" not in source
    assert 'bool show_chart_swing_levels = show_latest_swings_levels or show_swing_points' not in source
    assert 'internal_display_trend = not na(ta.barssince(internal_structure_break_detected)) ? internal_trend : 0' not in source


def test_htf_fvg_confirmation_gate_uses_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'bool htf_fvg_confirmed = false' in source
    assert 'if signal_mode == ct.SignalMode.AGGRESSIVE_LIVE' in source
    assert 'htf_fvg_confirmed := true' in source
    assert 'else if barstate.isconfirmed' in source
    assert 'htf_fvg_confirmed := htf_bar_changed or htf_fvg_tf_sec == chart_tf_sec' in source
    assert 'bool htf_update_ok = false' in source
    assert 'if fill_mode == ct.LevelBreakMode.HIGHLOW or signal_mode == ct.SignalMode.AGGRESSIVE_LIVE or barstate.isconfirmed' in source
    assert 'htf_update_ok := true' in source
    assert 'bool htf_insert_ok = true' in source
    assert 'if fill_mode == ct.LevelBreakMode.CLOSE' in source
    assert 'htf_insert_ok := htf_is_confirmed' in source
    assert "string bull_htf_key = ''" in source
    assert 'if htf_bull_found' in source
    assert 'bull_htf_key := u.htf_fvg_key(htf_bull_left_time, htf_bull_right_time, htf_bull_top, htf_bull_btm)' in source
    assert "string bear_htf_key = ''" in source
    assert 'if htf_bear_found' in source
    assert 'bear_htf_key := u.htf_fvg_key(htf_bear_left_time, htf_bear_right_time, htf_bear_top, htf_bear_btm)' in source
    assert 'htf_fvg_confirmed = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE ? true : barstate.isconfirmed and (htf_bar_changed or htf_fvg_tf_sec == chart_tf_sec)' not in source
    assert 'bool htf_update_ok = fill_mode == ct.LevelBreakMode.HIGHLOW or signal_mode == ct.SignalMode.AGGRESSIVE_LIVE or barstate.isconfirmed' not in source
    assert 'bool htf_insert_ok = fill_mode == ct.LevelBreakMode.CLOSE ? htf_is_confirmed : true' not in source
    assert "string bull_htf_key = htf_bull_found ? u.htf_fvg_key(htf_bull_left_time, htf_bull_right_time, htf_bull_top, htf_bull_btm) : ''" not in source
    assert "string bear_htf_key = htf_bear_found ? u.htf_fvg_key(htf_bear_left_time, htf_bear_right_time, htf_bear_top, htf_bear_btm) : ''" not in source


def test_active_backing_zones_are_protected_from_cleanup_rotation() -> None:
    source = _read_smc_source()

    assert 'int _ob_backing_zone_id = na' in source
    assert 'if long_state.backing_zone_kind == LONG_SOURCE_OB' in source
    assert '_ob_backing_zone_id := long_state.backing_zone_id' in source
    assert 'protected_bull_id = _ob_backing_zone_id' in source
    assert 'int _fvg_backing_zone_id = na' in source
    assert 'if long_state.backing_zone_kind == LONG_SOURCE_FVG' in source
    assert '_fvg_backing_zone_id := long_state.backing_zone_id' in source
    assert 'tracking_blocks_bull.remove_insignificant(min_block_size, max_block_size, discarded_blocks_bull, protected_bull_id)' in source
    assert 'buffer_bull.clear_filled(buffer_bull_filled, buffer_bull_filled_new, filled_max_keep, buffer_bull_discarded, protected_bull_id)' in source
    assert 'buffer_bull.remove_insignificant(size_threshold, buffer_bull_discarded, protected_bull_id)' in source
    assert 'bool is_protected = not na(protected_id) and block.id == protected_id' in source
    assert 'bool is_protected = not na(protected_id) and fvg.id == protected_id' in source
    assert 'int _ob_backing_zone_id = long_state.backing_zone_kind == LONG_SOURCE_OB ? long_state.backing_zone_id : na' not in source
    assert 'int _fvg_backing_zone_id = long_state.backing_zone_kind == LONG_SOURCE_FVG ? long_state.backing_zone_id : na' not in source


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
    assert 'bool armed_prequality_ok = true' in source
    assert 'if tighten_armed_stage_eff' in source
    assert 'armed_prequality_ok := bullish_trend_safe and micro_session_gate_ok and zone_touch_quality_ok and bull_close_strong and ema_support_ok' in source
    assert 'and armed_prequality_ok' in source
    assert 'bool armed_prequality_ok = not tighten_armed_stage_eff or (bullish_trend_safe and micro_session_gate_ok and zone_touch_quality_ok and bull_close_strong and ema_support_ok)' not in source


def test_user_presets_and_performance_modes_drive_effective_runtime_layers() -> None:
    source = _read_smc_source()

    assert "var string long_user_preset = input.string('Standard', 'User Preset', options = ['Easy', 'Standard', 'Pro']" in source
    assert "var string performance_mode = input.string('Balanced', 'Performance Mode', options = ['Light', 'Balanced', 'Pro', 'Debug']" in source
    assert "tooltip = 'Easy keeps the long engine permissive and easier to operate. Standard preserves the current balanced workflow. Pro enables stricter lifecycle and execution gating for cleaner but rarer setups.'" in source
    assert "tooltip = 'Light cuts rendering and lower-timeframe workload. Balanced preserves the manual limits. Pro raises object and sampling budgets. Debug keeps the richest diagnostics and history.'" in source
    assert "bool preset_is_easy = long_user_preset == 'Easy'" in source
    assert "bool preset_is_standard = long_user_preset == 'Standard'" in source
    assert "bool preset_is_pro = long_user_preset == 'Pro'" in source
    assert "bool use_strict_sequence_eff = use_strict_sequence" in source
    assert "bool tighten_armed_stage_eff = tighten_armed_stage" in source
    assert "bool use_strict_sweep_for_zone_reclaim_eff = use_strict_sweep_for_zone_reclaim" in source
    assert "bool block_third_touch_eff = block_third_touch" in source
    assert "bool use_context_quality_score_eff = use_context_quality_score" in source
    assert "bool require_internal_break_for_confirm_eff = require_internal_break_for_confirm" in source
    assert "bool require_main_break_for_ready_eff = require_main_break_for_ready" in source
    assert "bool use_ltf_for_strict_entry_eff = use_ltf_for_strict_entry" in source
    assert 'if preset_is_easy' in source
    assert 'else if preset_is_pro' in source
    assert "use_strict_sequence_eff := false" in source
    assert "block_third_touch_eff := true" in source
    assert "use_ltf_for_strict_entry_eff := true" in source
    assert "bool use_strict_sequence_eff = preset_is_easy ? false : use_strict_sequence" not in source
    assert "bool tighten_armed_stage_eff = preset_is_easy ? false : tighten_armed_stage" not in source
    assert "bool block_third_touch_eff = preset_is_easy ? false : preset_is_pro ? true : block_third_touch" not in source
    assert "bool use_context_quality_score_eff = preset_is_easy ? false : preset_is_pro ? true : use_context_quality_score" not in source
    assert "bool require_internal_break_for_confirm_eff = preset_is_easy ? false : preset_is_pro ? true : require_internal_break_for_confirm" not in source
    assert "bool require_main_break_for_ready_eff = preset_is_easy ? false : preset_is_pro ? true : require_main_break_for_ready" not in source
    assert "bool use_ltf_for_strict_entry_eff = preset_is_easy ? false : preset_is_pro ? true : use_ltf_for_strict_entry" not in source
    assert "bool performance_mode_light = performance_mode == 'Light'" in source
    assert "bool performance_mode_balanced = performance_mode == 'Balanced'" in source
    assert "bool performance_mode_pro = performance_mode == 'Pro'" in source
    assert "bool performance_mode_debug = performance_mode == 'Debug'" in source
    assert "bool render_visible_only_eff = false" in source
    assert "bool keep_visual_history_eff = keep_visual_history" in source
    assert "int object_gc_cycle_eff = object_gc_cycle" in source
    assert "int max_ltf_ratio_eff = max_ltf_ratio" in source
    assert "int max_ltf_samples_per_bar_eff = max_ltf_samples_per_bar" in source
    assert "bool show_dashboard_ltf_eff = show_dashboard_ltf" in source
    assert "int long_marker_history_limit_eff = long_marker_history_limit" in source
    assert "string long_engine_debug_mode_eff = long_engine_debug_mode" in source
    assert "render_visible_only_eff := true" in source
    assert "keep_visual_history_eff := true" in source
    assert "object_gc_cycle_eff := math.min(object_gc_cycle, 100)" in source
    assert "object_gc_cycle_eff := math.max(object_gc_cycle, 500)" in source
    assert "max_ltf_ratio_eff := math.max(max_ltf_ratio, 180)" in source
    assert "show_dashboard_ltf_eff := true" in source
    assert "long_engine_debug_mode_eff := 'Full'" in source
    assert "bool render_visible_only_eff = performance_mode_light ? true : performance_mode_balanced ? render_visible_only : false" not in source
    assert "bool keep_visual_history_eff = performance_mode_debug ? true : performance_mode_light ? false : keep_visual_history" not in source
    assert "int object_gc_cycle_eff = performance_mode_light ? (object_gc_cycle == 0 ? 100 : math.min(object_gc_cycle, 100)) : performance_mode_pro ? (object_gc_cycle == 0 ? 0 : math.max(object_gc_cycle, 250)) : performance_mode_debug ? (object_gc_cycle == 0 ? 0 : math.max(object_gc_cycle, 500)) : object_gc_cycle" not in source
    assert "int max_ltf_ratio_eff = performance_mode_light ? math.min(max_ltf_ratio, 30) : performance_mode_pro ? math.max(max_ltf_ratio, 120) : performance_mode_debug ? math.max(max_ltf_ratio, 180) : max_ltf_ratio" not in source
    assert "int max_ltf_samples_per_bar_eff = performance_mode_light ? math.min(max_ltf_samples_per_bar, 120) : performance_mode_pro ? math.max(max_ltf_samples_per_bar, 500) : performance_mode_debug ? math.max(max_ltf_samples_per_bar, 800) : max_ltf_samples_per_bar" not in source
    assert "bool show_dashboard_ltf_eff = performance_mode_light ? false : performance_mode_debug ? true : show_dashboard_ltf" not in source
    assert "int long_marker_history_limit_eff = performance_mode_light ? math.min(long_marker_history_limit, 25) : performance_mode_pro ? math.max(long_marker_history_limit, 150) : performance_mode_debug ? math.max(long_marker_history_limit, 250) : long_marker_history_limit" not in source
    assert "string long_engine_debug_mode_eff = performance_mode_light ? 'Compact' : performance_mode_debug ? 'Full' : long_engine_debug_mode" not in source


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
    assert "string long_debug_mode_suffix = ' Compact'" in source
    assert "if long_engine_debug_mode == 'Full'" in source
    assert "if debug_text == 'off'" in source
    assert "debug_text := 'Long' + long_debug_mode_suffix" in source
    assert "string long_debug_mode_suffix = long_engine_debug_mode == 'Full' ? ' Full' : ' Compact'" not in source
    assert "debug_mode_is_full(string long_engine_debug_mode) =>" in source
    assert 'compute_long_environment_context(bool market_regime_gate_ok, bool vola_regime_gate_safe, bool context_quality_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok) =>' in source
    assert 'resolve_long_ready_lifecycle_reason(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent) =>' in source
    assert 'resolve_long_ready_gate_reason(bool setup_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'resolve_long_strict_gate_reason(bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'compose_long_debug_compact_text(string long_setup_source_display, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_debug_source_touch_text(string long_setup_source_display, int long_setup_backing_zone_touch_count) =>' in source
    assert 'compose_long_debug_ready_strict_text(string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_debug_fresh_source_text(string freshness_text, string source_state_text) =>' in source
    assert 'compose_long_debug_zone_env_text(string zone_quality_text, string long_environment_focus_display) =>' in source
    assert 'compose_long_debug_upgrade_text(string long_source_upgrade_reason) =>' in source
    assert 'compose_long_debug_event_context_text(int long_setup_backing_zone_touch_count, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display) =>' in source
    assert 'compose_long_debug_levels_text(float long_setup_trigger, float long_invalidation_level, string overhead_text) =>' in source
    assert 'resolve_long_upgrade_reason(bool long_source_upgrade_now, bool prefer_ob_upgrade, bool ob_source_upgrade_ok, bool fvg_source_upgrade_ok, float touched_bull_ob_quality, float touched_bull_fvg_quality, float long_locked_source_quality) =>' in source
    assert 'compute_long_ready_state(bool close_safe_mode, bool long_setup_confirmed, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'compute_long_entry_best_state(bool long_ready_state, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe) =>' in source
    assert 'compute_long_entry_strict_state(bool long_ready_state, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'resolve_long_ready_blocker_text(bool long_ready_state, bool long_setup_confirmed, bool close_safe_mode, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert "resolve_long_strict_blocker_text(bool long_entry_strict_state, bool long_ready_state, string long_ready_blocker_text, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>" in source
    assert "string trade_gate_reason = 'Trade OK'" in source
    assert "trade_gate_reason := 'Blocked: Session Gate'" in source
    assert "string environment_gate_reason = 'Env OK'" in source
    assert "environment_gate_reason := 'Blocked: Market Gate'" in source
    assert "string lifecycle_reason = ''" in source
    assert "lifecycle_reason := 'Awaiting Confirm'" in source
    assert "resolve_long_ready_gate_reason(setup_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)" in source
    assert "ready_gate_reason := 'Blocked: DDVI Context'" in source
    assert "string strict_blocker_text = 'Passed'" in source
    assert "strict_blocker_text := 'Need Ready: ' + long_ready_blocker_text" in source
    assert "string strict_gate_reason = 'Eligible'" in source
    assert "strict_gate_reason := 'Blocked: LTF Confirmation'" in source
    assert "not session_structure_gate_ok ? 'Blocked: Session Gate'" not in source
    assert "not market_regime_gate_ok ? 'Blocked: Market Gate'" not in source
    assert "long_ready_state ? 'Passed' : not long_setup_confirmed ? 'Awaiting Confirm'" not in source
    assert "not ddvi_ready_ok_safe ? 'Blocked: DDVI Context' : 'Eligible'" not in source
    assert "long_entry_strict_state ? 'Passed' : not long_ready_state ? 'Need Ready: ' + long_ready_blocker_text : resolve_long_strict_gate_reason(strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)" not in source
    assert "not strict_entry_ltf_ok ? 'Blocked: LTF Confirmation'" not in source
    assert 'compose_long_debug_summary_text(string long_engine_debug_mode, bool long_setup_armed, bool long_setup_confirmed, bool long_ready_state, string long_setup_source_display, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, int long_setup_backing_zone_touch_count, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_engine_debug_label_text(string long_engine_debug_mode, string long_setup_text, string long_visual_text, string long_setup_source_display, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, string overhead_text, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'compose_long_engine_event_log(string long_engine_debug_mode, string event_name, string long_setup_source_display, float long_setup_trigger, float long_invalidation_level, int long_setup_backing_zone_touch_count, string freshness_text, string source_state_text, string zone_quality_text, string long_environment_focus_display, bool long_source_upgrade_now, string long_source_upgrade_reason, string long_last_invalid_source, string long_ready_blocker_text, string long_strict_blocker_text) =>' in source
    assert 'emit_long_engine_debug_logs() =>' in source
    assert 'string _src = long_setup_source_display' in source
    assert '_src := long_debug_event_source_display' in source
    assert 'int _tc = long_state.backing_zone_touch_count' in source
    assert '_tc := long_debug_event_touch_count' in source
    assert 'float _trg = long_state.trigger' in source
    assert '_trg := long_debug_event_trigger' in source
    assert 'float _inv = long_state.invalidation_level' in source
    assert '_inv := long_debug_event_invalidation' in source
    assert 'string long_debug_log_source_display = long_invalidate_signal ? long_debug_event_source_display : long_setup_source_display' not in source
    assert 'int long_debug_log_touch_count = long_invalidate_signal ? long_debug_event_touch_count : long_state.backing_zone_touch_count' not in source
    assert 'float long_debug_log_trigger = long_invalidate_signal ? long_debug_event_trigger : long_state.trigger' not in source
    assert 'float long_debug_log_invalidation = long_invalidate_signal ? long_debug_event_invalidation : long_state.invalidation_level' not in source
    assert "compose_long_debug_compact_text(long_setup_source_display, long_ready_blocker_text, long_strict_blocker_text)" in source
    assert "compose_long_debug_source_touch_text(long_setup_source_display, long_setup_backing_zone_touch_count)" in source
    assert "compose_long_debug_ready_strict_text(long_ready_blocker_text, long_strict_blocker_text)" in source
    assert "compose_long_debug_fresh_source_text(freshness_text, source_state_text)" in source
    assert "compose_long_debug_zone_env_text(zone_quality_text, long_environment_focus_display)" in source
    assert "compose_long_debug_upgrade_text(long_source_upgrade_reason)" in source
    assert "compose_long_debug_event_context_text(long_setup_backing_zone_touch_count, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display)" in source
    assert "compose_long_debug_levels_text(long_setup_trigger, long_invalidation_level, overhead_text)" in source
    assert "string upgrade_reason = 'none'" in source
    assert 'int target_source_kind = LONG_SOURCE_FVG' in source
    assert 'float target_quality = touched_bull_fvg_quality' in source
    assert "string edge_text = 'beat locked source confluence'" in source
    assert "string target_source_text = resolve_long_source_text(prefer_ob_upgrade ? LONG_SOURCE_OB : LONG_SOURCE_FVG)" not in source
    assert 'float target_quality = prefer_ob_upgrade ? touched_bull_ob_quality : touched_bull_fvg_quality' not in source
    assert "string edge_text = ob_source_upgrade_ok and fvg_source_upgrade_ok ? 'won tie on stronger confluence' : 'beat locked source confluence'" not in source
    assert 'if debug_mode_full' in source
    assert 'debug_text := compose_long_debug_compact_text(long_setup_source_display, long_ready_blocker_text, long_strict_blocker_text)' in source
    assert "debug_text := debug_mode_full ? compose_long_debug_source_touch_text(long_setup_source_display, long_setup_backing_zone_touch_count) + ' | ' + compose_long_debug_fresh_source_text(freshness_text, source_state_text) + ' | ' + compose_long_debug_zone_env_text(zone_quality_text, long_environment_focus_display) + ' | ' + compose_long_debug_ready_strict_text(long_ready_blocker_text, long_strict_blocker_text) : compose_long_debug_compact_text(long_setup_source_display, long_ready_blocker_text, long_strict_blocker_text)" not in source
    assert "debug_text += debug_mode_full ? '\\n' + compose_long_debug_source_touch_text(long_setup_source_display, long_setup_backing_zone_touch_count) : '\\n' + compose_long_debug_compact_text(long_setup_source_display, long_ready_blocker_text, long_strict_blocker_text)" not in source
    assert "event_text += debug_mode_full ? ' | ' + compose_long_debug_event_context_text(long_setup_backing_zone_touch_count, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display) : ''" not in source
    assert "string long_source_upgrade_reason = resolve_long_upgrade_reason(long_source_upgrade_now, prefer_ob_upgrade, ob_source_upgrade_ok, fvg_source_upgrade_ok, touched_bull_ob_quality, touched_bull_fvg_quality, long_locked_source_quality)" in source
    assert "log.info('{0}', compose_long_engine_event_log(long_engine_debug_mode_eff, 'LONG ARMED'" in source
    assert "log.info('{0}', compose_long_engine_event_log(long_engine_debug_mode_eff, 'LONG INVALID'" in source
    assert "plotshape(show_ob_debug and ob_zone_touch_event, title = 'OB Zone Touch Debug'" in source
    assert "plotshape(show_fvg_debug and bullish_fvg_filled_alert, title = 'Bullish FVG Filled Debug'" in source
    assert "plotshape(show_long_engine_debug and long_source_upgrade_now, title = 'Long Source Upgrade Debug'" in source
    assert '[environment_hard_gate_ok, quality_gate_ok, microstructure_entry_gate_ok, trade_hard_gate_ok, long_environment_focus_display] = compute_long_environment_context(market_regime_gate_ok, vola_regime_gate_safe, context_quality_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok)' in source
    assert '[lifecycle_ready_ok, long_ready_state] = compute_long_ready_state(close_safe_mode, long_state.confirmed, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)' in source
    assert 'bool long_entry_best_state = compute_long_entry_best_state(long_ready_state, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe)' in source
    assert 'bool long_entry_strict_state = compute_long_entry_strict_state(long_ready_state, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert "string long_ready_blocker_text = resolve_long_ready_blocker_text(long_ready_state, long_state.confirmed, close_safe_mode, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok, market_regime_gate_ok, vola_regime_gate_safe, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)" in source
    assert "string long_strict_blocker_text = resolve_long_strict_blocker_text(long_entry_strict_state, long_ready_state, long_ready_blocker_text, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)" in source
    assert "string long_debug_summary_text = emit_long_engine_debug_logs()" in source
    assert "string long_engine_debug_label_text = compose_long_engine_debug_label_text(long_engine_debug_mode_eff, long_setup_text, long_visual_text, long_setup_source_display, freshness_text, source_state_text, zone_quality_text, long_environment_focus_display, overhead_text, long_state.trigger, long_state.invalidation_level, long_state.backing_zone_touch_count, long_source_upgrade_now, long_source_upgrade_reason, long_state.last_invalid_source, long_ready_blocker_text, long_strict_blocker_text)" in source
    assert 'db_ready_gate_state(bool long_ready_state, bool long_setup_confirmed, bool lifecycle_ready_ok, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok) =>' in source
    assert 'db_strict_gate_state(bool long_entry_strict_state, bool long_ready_state, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'db_long_debug_state(bool show_long_engine_debug, int long_visual_state, bool long_setup_armed, bool long_setup_confirmed, bool long_ready_state) =>' in source
    assert 'render_dashboard_engine_section(table tbl, color txt) =>' in source
    assert 'render_dashboard_engine_section(_smc_dashboard, _db_text)' in source
    assert "dashboard_section_row(tbl, 44, 0, 'Ready Gate', long_ready_blocker_text, status_bg(_db_ready_gate_state), txt)" in source
    assert "dashboard_section_row(tbl, 44, 1, 'Strict Gate', long_strict_blocker_text, status_bg(_db_strict_gate_state), txt)" in source
    assert "dashboard_header(_smc_dashboard, 0, 'SMC++ | ' + signal_mode_text + ' | ' + long_user_preset + ' | ' + performance_mode, _db_header_bg, _db_text)" in source
    assert 'string _db_debug_flags_text = compose_enabled_debug_modules_text(show_ob_debug, show_fvg_debug, show_long_engine_debug, long_engine_debug_mode_eff)' in source
    assert "dashboard_section_row(tbl, 44, 2, 'Debug Flags', _db_debug_flags_text, status_bg(_db_debug_flags_state), txt)" in source
    assert "string _db_ltf_bias_text = 'off'" in source
    assert "if show_dashboard_ltf_eff" in source
    assert "if not ltf_sampling_active or not ltf_price_ok" in source
    assert "_db_ltf_bias_text := str.tostring(ltf_bull_share * 100.0, '#') + '%'" in source
    assert "if ltf_price_only" in source
    assert "_db_ltf_bias_text += ' price-only'" in source
    assert "string _db_ltf_delta_text = 'off'" in source
    assert "else if ltf_price_only" in source
    assert "_db_ltf_delta_text := str.format('{0,number,percent}', ltf_volume_delta)" in source
    assert "string _db_swing_trail_up_text = 'n/a'" in source
    assert 'if not na(trail_up)' in source
    assert '_db_swing_trail_up_text := u.format_level(trail_up)' in source
    assert "string _db_swing_trail_dn_text = 'n/a'" in source
    assert 'if not na(trail_dn)' in source
    assert '_db_swing_trail_dn_text := u.format_level(trail_dn)' in source
    assert "string _db_swing_internal_up_text = 'n/a'" in source
    assert 'if not na(internal_trail_up)' in source
    assert '_db_swing_internal_up_text := u.format_level(internal_trail_up)' in source
    assert "string _db_swing_internal_dn_text = 'n/a'" in source
    assert 'if not na(internal_trail_dn)' in source
    assert '_db_swing_internal_dn_text := u.format_level(internal_trail_dn)' in source
    assert "string _db_swing_text = 'S ' + _db_swing_trail_up_text + ' / ' + _db_swing_trail_dn_text + ' | I ' + _db_swing_internal_up_text + ' / ' + _db_swing_internal_dn_text" in source
    assert "string _db_long_debug_text = 'off'" in source
    assert 'int _db_long_debug_state = db_long_debug_state(show_long_engine_debug, long_visual_state, long_state.armed, long_state.confirmed, long_ready_state)' in source
    assert 'render_dashboard_engine_section(table tbl, color txt) =>' in source
    assert "dashboard_section_row(tbl, 44, 3, 'Long Debug', _db_long_debug_text, status_bg(_db_long_debug_state), txt)" in source
    assert 'status_bg(_db_ready_gate_state)' in source
    assert 'status_bg(_db_strict_gate_state)' in source
    assert 'status_bg(_db_long_debug_state)' in source
    assert "dashboard_row(_smc_dashboard, 47, 'Long Debug', show_long_engine_debug ? long_debug_summary_text : 'off'" not in source
    assert "string _db_long_debug_text = show_long_engine_debug ? long_debug_summary_text : 'off'" not in source
    assert "status_bg(db_ready_gate_state(long_ready_state, long_state.confirmed, lifecycle_ready_ok, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok))" not in source
    assert "status_bg(db_strict_gate_state(long_entry_strict_state, long_ready_state, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe))" not in source
    assert "status_bg(db_long_debug_state(show_long_engine_debug, long_visual_state, long_state.armed, long_state.confirmed, long_ready_state))" not in source
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
    assert '[prepared_ob_size_min_bear, prepared_ob_size_max_bear] = prepare_order_block_confirmation(bear_ob, min_block_size, max_block_size, true, update_profile_current_bar, align_edge_to_value_area, align_break_price_to_poc, bear_prepare_confirmation)' in source
    assert 'ob_size_min_bull := prepared_ob_size_min_bull' in source
    assert 'ob_size_max_bull := prepared_ob_size_max_bull' in source
    assert 'ob_size_min_bear := prepared_ob_size_min_bear' in source
    assert 'ob_size_max_bear := prepared_ob_size_max_bear' in source
    assert '[ob_size_min_bull, ob_size_max_bull] = prepare_order_block_confirmation(' not in source
    assert '[ob_size_min_bear, ob_size_max_bear] = prepare_order_block_confirmation(' not in source


def test_clean_tier_is_renamed_as_a_quality_diagnostic() -> None:
    source = _read_smc_source()

    assert 'bool long_quality_clean_tier = false' in source
    assert 'if close_safe_mode and bullish_trend_safe and zone_recent and reclaim_recent and long_state.confirmed and setup_hard_gate_ok and trade_hard_gate_ok and environment_hard_gate_ok and quality_gate_ok and bull_close_strong and ema_support_ok and adx_strong and relvol_ok and vwap_filter_ok' in source
    assert 'long_quality_clean_tier := true' in source
    # quality_clean_ok removed; alert_long_clean still driven by long_quality_clean_tier
    assert 'alert_long_clean = long_quality_clean_tier' in source
    assert 'bool long_quality_clean_tier = close_safe_mode and bullish_trend_safe and zone_recent and reclaim_recent and long_state.confirmed and setup_hard_gate_ok and trade_hard_gate_ok and environment_hard_gate_ok and quality_gate_ok and bull_close_strong and ema_support_ok and adx_strong and relvol_ok and vwap_filter_ok' not in source
    assert 'long_clean_tier' not in source


def test_cleanup_protection_does_not_mask_genuine_break_migration() -> None:
    source = _read_smc_source()

    assert 'update_broken(int mode, OrderBlock[] tracking_blocks, OrderBlock[] broken_blocks, OrderBlock[] broken_blocks_new, simple ct.LevelBreakMode broken_by = ct.LevelBreakMode.HIGHLOW, int keep_broken_max = 5, OrderBlock[] discarded_buffer = na) =>' in source
    assert 'update_broken( 1, tracking_blocks_bull, broken_blocks_bull, broken_blocks_new_bull, broken_by, keep_broken_max, discarded_blocks_bull)' in source
    assert 'update_broken(-1, tracking_blocks_bear, broken_blocks_bear, broken_blocks_new_bear, broken_by, keep_broken_max, discarded_blocks_bear)' in source
    assert 'long_invalidate_signal := long_state.armed or long_state.confirmed' in source
    assert 'long_source_tracked := false' in source
    assert 'if not na(long_state.locked_source_id)' in source
    assert 'long_source_tracked := true' in source
    assert 'long_source_tracked := not na(long_state.locked_source_id)' not in source
    assert 'bool prev_locked_source_tracked = false' in source
    assert 'if not na(prev_locked_source_id)' in source
    assert 'prev_locked_source_tracked := true' in source
    assert 'long_source_alive := true' in source
    assert 'if long_source_tracked' in source
    assert 'long_source_alive := long_locked_source_alive_now' in source
    assert 'long_source_alive := not long_source_tracked ? true : long_locked_source_alive_now' not in source
    assert 'long_source_lost := false' in source
    assert 'if (long_state.armed or long_state.confirmed) and long_source_tracked' in source
    assert 'long_source_lost := not long_source_alive and not long_source_broken' in source
    assert 'long_source_lost := (long_state.armed or long_state.confirmed) and long_source_tracked and not long_source_alive and not long_source_broken' not in source
    assert 'bool long_setup_expired = false' in source
    assert 'if long_state.armed and not long_state.confirmed' in source
    assert 'long_setup_expired := long_setup_age > long_setup_expiry_bars' in source
    assert 'bool long_confirm_expired = false' in source
    assert 'if long_state.confirmed' in source
    assert 'long_confirm_expired := long_confirm_age > long_confirm_expiry_bars' in source
    assert 'bool long_setup_expired = long_state.armed and not long_state.confirmed and long_setup_age > long_setup_expiry_bars' not in source
    assert 'bool long_confirm_expired = long_state.confirmed and long_confirm_age > long_confirm_expiry_bars' not in source
    assert 'float long_invalidation_break_src = close' in source
    assert 'if live_exec and effective_use_live_invalidation_break' in source
    assert 'long_invalidation_break_src := low' in source
    assert 'float long_invalidation_break_src = live_exec and effective_use_live_invalidation_break ? low : close' not in source
    assert 'bool long_broken_down = false' in source
    assert 'if not na(long_state.invalidation_level)' in source
    assert 'long_broken_down := long_invalidation_break_src < long_state.invalidation_level - long_invalidation_buffer' in source
    assert 'bool long_broken_down = not na(long_state.invalidation_level) and long_invalidation_break_src < long_state.invalidation_level - long_invalidation_buffer' not in source
    assert 'bool long_invalidated_now = false' in source
    assert 'if long_source_broken or long_source_lost' in source
    assert 'long_invalidated_now := true' in source
    assert 'bool long_invalidated_now = long_source_broken or long_source_lost' not in source


def test_source_lock_decouples_setup_source_from_live_active_ranking() -> None:
    source = _read_smc_source()

    assert 'int LONG_SOURCE_NONE = 0' in source
    assert 'var int long_locked_source_kind = LONG_SOURCE_NONE' not in source
    assert 'var int long_locked_source_id = na' not in source
    assert 'int _ob_backing_zone_id = na' in source
    assert 'if long_state.backing_zone_kind == LONG_SOURCE_OB' in source
    assert '_ob_backing_zone_id := long_state.backing_zone_id' in source
    assert 'int _fvg_backing_zone_id = na' in source
    assert 'if long_state.backing_zone_kind == LONG_SOURCE_FVG' in source
    assert '_fvg_backing_zone_id := long_state.backing_zone_id' in source
    assert 'int prev_locked_source_kind = long_state.locked_source_kind' in source
    assert 'int prev_locked_source_id = long_state.locked_source_id' in source
    assert 'OrderBlock prev_locked_bull_ob = na' in source
    assert 'if prev_locked_source_kind == LONG_SOURCE_OB' in source
    assert 'prev_locked_bull_ob := get_by_id(ob_blocks_bull, prev_locked_source_id)' in source
    assert 'FVG prev_locked_bull_fvg = na' in source
    assert 'if prev_locked_source_kind == LONG_SOURCE_FVG' in source
    assert 'prev_locked_bull_fvg := get_by_id(fvgs_bull, prev_locked_source_id)' in source
    assert 'bool long_locked_source_alive_now = false' in source
    assert 'if long_locked_source_kind_final == LONG_SOURCE_OB' in source
    assert 'long_locked_source_alive_now := contains_id(ob_blocks_bull, long_locked_source_id_final)' in source
    assert 'else if long_locked_source_kind_final == LONG_SOURCE_FVG' in source
    assert 'long_locked_source_alive_now := contains_id(fvgs_bull, long_locked_source_id_final)' in source
    assert 'bool long_locked_source_alive_now = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_blocks_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(fvgs_bull, long_locked_source_id_final) : false' not in source
    assert 'OrderBlock prev_locked_bull_ob = prev_locked_source_kind == LONG_SOURCE_OB ? get_by_id(ob_blocks_bull, prev_locked_source_id) : na' not in source
    assert 'FVG prev_locked_bull_fvg = prev_locked_source_kind == LONG_SOURCE_FVG ? get_by_id(fvgs_bull, prev_locked_source_id) : na' not in source
    assert 'long_setup_source_zone_id' not in source
    assert 'armed_source_changed' not in source
    assert 'bool long_invalidated_now = false' in source
    assert 'if long_source_broken or long_source_lost' in source
    assert 'long_invalidated_now := true' in source
    assert 'if close_safe_mode' in source
    assert 'long_invalidated_now := long_invalidated_now or long_broken_down or long_setup_expired or long_confirm_expired' in source
    assert 'bool long_invalidated_now = long_source_broken or long_source_lost or (close_safe_mode and (long_broken_down or long_setup_expired or long_confirm_expired))' not in source


def test_locked_source_drives_touch_history_and_strict_sweep() -> None:
    source = _read_smc_source()

    assert 'bool long_locked_source_in_zone = false' in source
    assert 'if long_locked_source_alive_now and not na(long_locked_source_top_now) and not na(long_locked_source_bottom_now)' in source
    assert 'long_locked_source_in_zone := math.min(high, long_locked_source_top_now) - math.max(low, long_locked_source_bottom_now) >= 0' in source
    assert 'bool long_locked_source_touch_now = false' in source
    assert 'if long_locked_source_in_zone' in source
    assert 'long_locked_source_touch_now := not long_locked_source_in_zone[1] or long_locked_source_id_final != long_locked_source_id_final[1] or long_locked_source_kind_final != long_locked_source_kind_final[1]' in source
    assert 'long_locked_source_touch_count_effective += 1' in source
    assert 'bool long_locked_source_touch_recent = false' in source
    assert 'if (long_state.armed or long_state.confirmed) and not na(long_locked_source_last_touch_bar_index_effective)' in source
    assert 'long_locked_source_touch_recent := bar_index - long_locked_source_last_touch_bar_index_effective <= long_signal_window' in source
    assert 'bool long_locked_source_in_zone = long_locked_source_alive_now and not na(long_locked_source_top_now) and not na(long_locked_source_bottom_now) and math.min(high, long_locked_source_top_now) - math.max(low, long_locked_source_bottom_now) >= 0' not in source
    assert 'bool long_locked_source_touch_now = long_locked_source_in_zone and (not long_locked_source_in_zone[1] or long_locked_source_id_final != long_locked_source_id_final[1] or long_locked_source_kind_final != long_locked_source_kind_final[1])' not in source
    assert 'bool long_locked_source_touch_recent = (long_state.armed or long_state.confirmed) and not na(long_locked_source_last_touch_bar_index_effective) and bar_index - long_locked_source_last_touch_bar_index_effective <= long_signal_window' not in source
    assert 'float long_locked_source_zone_height = na' in source
    assert 'if not na(long_locked_source_top_now) and not na(long_locked_source_bottom_now)' in source
    assert 'long_locked_source_zone_height := math.max(long_locked_source_top_now - long_locked_source_bottom_now, syminfo.mintick)' in source
    assert 'float long_locked_source_zone_height = not na(long_locked_source_top_now) and not na(long_locked_source_bottom_now) ? math.max(long_locked_source_top_now - long_locked_source_bottom_now, syminfo.mintick) : na' not in source
    assert 'float long_locked_ob_required_sweep_level = na' in source
    assert 'if long_locked_source_kind_final == LONG_SOURCE_OB and not na(long_locked_source_zone_height)' in source
    assert 'long_locked_ob_required_sweep_level := long_locked_source_top_now - long_locked_source_zone_height * effective_ob_reclaim_min_penetration' in source
    assert 'float long_locked_fvg_required_sweep_level = na' in source
    assert 'if long_locked_source_kind_final == LONG_SOURCE_FVG and not na(long_locked_source_zone_height)' in source
    assert 'long_locked_fvg_required_sweep_level := long_locked_source_top_now - long_locked_source_zone_height * effective_fvg_reclaim_min_penetration' in source
    assert 'float long_locked_ob_required_sweep_level = long_locked_source_kind_final == LONG_SOURCE_OB and not na(long_locked_source_zone_height) ? long_locked_source_top_now - long_locked_source_zone_height * effective_ob_reclaim_min_penetration : na' not in source
    assert 'float long_locked_fvg_required_sweep_level = long_locked_source_kind_final == LONG_SOURCE_FVG and not na(long_locked_source_zone_height) ? long_locked_source_top_now - long_locked_source_zone_height * effective_fvg_reclaim_min_penetration : na' not in source
    assert 'bool long_locked_ob_real_sweep = false' in source
    assert 'if long_locked_source_kind_final == LONG_SOURCE_OB and long_locked_source_alive_now and not na(long_locked_ob_required_sweep_level)' in source
    assert 'long_locked_ob_real_sweep := low <= long_locked_ob_required_sweep_level' in source
    assert 'bool long_locked_fvg_real_sweep = false' in source
    assert 'if long_locked_source_kind_final == LONG_SOURCE_FVG and long_locked_source_alive_now and not na(long_locked_fvg_required_sweep_level)' in source
    assert 'long_locked_fvg_real_sweep := low <= long_locked_fvg_required_sweep_level' in source
    assert 'bool long_locked_ob_real_sweep = long_locked_source_kind_final == LONG_SOURCE_OB and long_locked_source_alive_now and not na(long_locked_ob_required_sweep_level) and low <= long_locked_ob_required_sweep_level' not in source
    assert 'bool long_locked_fvg_real_sweep = long_locked_source_kind_final == LONG_SOURCE_FVG and long_locked_source_alive_now and not na(long_locked_fvg_required_sweep_level) and low <= long_locked_fvg_required_sweep_level' not in source
    assert 'float long_locked_source_top_effective = long_state.locked_source_top' in source
    assert 'if long_locked_source_alive_now' in source
    assert 'long_locked_source_top_effective := long_locked_source_top_now' in source
    assert 'float long_locked_source_bottom_effective = long_state.locked_source_bottom' in source
    assert 'long_locked_source_bottom_effective := long_locked_source_bottom_now' in source
    assert 'float long_locked_source_top_effective = long_locked_source_alive_now ? long_locked_source_top_now : long_state.locked_source_top' not in source
    assert 'float long_locked_source_bottom_effective = long_locked_source_alive_now ? long_locked_source_bottom_now : long_state.locked_source_bottom' not in source
    # long_source_zone_touch_recent removed (Patch 5) — long_locked_source_touch_recent used directly
    assert 'long_state.sync_locked_tracking(long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final, long_locked_source_kind_final, long_locked_source_id_final, long_locked_source_top_effective, long_locked_source_bottom_effective, long_locked_source_touch_count_effective, long_locked_source_last_touch_bar_index_effective)' in source
    # fvg_zone_touch_sequence_ok uses touched_bull_fvg_id now (not long_setup_backing_zone_id)
    assert 'fvg_zone_touch_event_recent and fvg_zone_touch_sequence_time_ok and not na(touched_bull_fvg_id) and last_fvg_zone_touch_id == touched_bull_fvg_id' in source


def test_source_upgrade_is_explicit_and_quality_gated() -> None:
    source = _read_smc_source()

    assert "var bool allow_armed_source_upgrade = input.bool(false, 'Allow Armed Source Upgrade'" in source
    assert "var float min_source_upgrade_quality_gain = input.float(0.15, 'Min Q Gain'" in source
    assert 'float long_locked_source_quality = 0.0' in source
    assert 'long_locked_source_quality := ob_quality_score(prev_locked_bull_ob)' in source
    assert 'long_locked_source_quality := fvg_quality_score(prev_locked_bull_fvg, fvg_size_threshold)' in source
    assert 'bool prev_locked_source_alive = false' in source
    assert 'prev_locked_source_alive := not na(prev_locked_bull_ob)' in source
    assert 'prev_locked_source_alive := not na(prev_locked_bull_fvg)' in source
    assert 'bool prev_locked_source_broken = false' in source
    assert 'prev_locked_source_broken := contains_id(ob_broken_bull, prev_locked_source_id) or contains_id(ob_broken_new_bull, prev_locked_source_id)' in source
    assert 'prev_locked_source_broken := contains_id(filled_fvgs_bull, prev_locked_source_id) or contains_id(filled_fvgs_new_bull, prev_locked_source_id)' in source
    assert 'bool prev_locked_source_lost = false' in source
    assert 'if (long_state.armed or long_state.confirmed) and prev_locked_source_tracked' in source
    assert 'prev_locked_source_lost := not prev_locked_source_alive and not prev_locked_source_broken' in source
    assert 'bool prev_locked_source_invalid_now = false' in source
    assert 'if prev_locked_source_tracked' in source
    assert 'prev_locked_source_invalid_now := prev_locked_source_broken or prev_locked_source_lost' in source
    assert 'float long_locked_source_quality = prev_locked_source_kind == LONG_SOURCE_OB ? ob_quality_score(prev_locked_bull_ob) : prev_locked_source_kind == LONG_SOURCE_FVG ? fvg_quality_score(prev_locked_bull_fvg, fvg_size_threshold) : 0.0' not in source
    assert 'bool prev_locked_source_alive = prev_locked_source_kind == LONG_SOURCE_OB ? not na(prev_locked_bull_ob) : prev_locked_source_kind == LONG_SOURCE_FVG ? not na(prev_locked_bull_fvg) : false' not in source
    assert 'bool prev_locked_source_broken = prev_locked_source_kind == LONG_SOURCE_OB ? contains_id(ob_broken_bull, prev_locked_source_id) or contains_id(ob_broken_new_bull, prev_locked_source_id) : prev_locked_source_kind == LONG_SOURCE_FVG ? contains_id(filled_fvgs_bull, prev_locked_source_id) or contains_id(filled_fvgs_new_bull, prev_locked_source_id) : false' not in source
    assert 'bool prev_locked_source_lost = (long_state.armed or long_state.confirmed) and prev_locked_source_tracked and not prev_locked_source_alive and not prev_locked_source_broken' not in source
    assert 'bool prev_locked_source_invalid_now = prev_locked_source_tracked and (prev_locked_source_broken or prev_locked_source_lost)' not in source
    assert 'bool ob_source_upgrade_ok = false' in source
    assert 'if allow_armed_source_upgrade and long_state.armed and not long_state.confirmed and not prev_locked_source_invalid_now and bull_reclaim_ob_strict and not na(touched_bull_ob_block)' in source
    assert 'if prev_locked_source_kind != LONG_SOURCE_OB or prev_locked_source_id != touched_bull_ob_id' in source
    assert 'ob_source_upgrade_ok := touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'bool ob_source_upgrade_ok = allow_armed_source_upgrade and long_state.armed and not long_state.confirmed and not prev_locked_source_invalid_now and bull_reclaim_ob_strict' not in source


def test_script_text_is_english_only_for_known_long_lifecycle_regressions() -> None:
    source = _read_smc_source()

    assert '// Snapshot the currently locked source before any source-upgrade decision.' in source
    assert 'Snapshot des aktuell gelockten Sources VOR einer moeglichen Source-Upgrade-Entscheidung.' not in source
    assert 'bool fvg_source_upgrade_ok = false' in source
    assert 'if allow_armed_source_upgrade and long_state.armed and not long_state.confirmed and not prev_locked_source_invalid_now and bull_reclaim_fvg_strict and not na(touched_bull_fvg_block)' in source
    assert 'if prev_locked_source_kind != LONG_SOURCE_FVG or prev_locked_source_id != touched_bull_fvg_id' in source
    assert 'fvg_source_upgrade_ok := touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'bool fvg_source_upgrade_ok = allow_armed_source_upgrade and long_state.armed and not long_state.confirmed and not prev_locked_source_invalid_now and bull_reclaim_fvg_strict' not in source
    assert 'ob_source_upgrade_ok := touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'fvg_source_upgrade_ok := touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'if long_source_upgrade_now' in source
    assert 'bool long_source_upgrade_now = false' in source
    assert 'if ob_source_upgrade_ok or fvg_source_upgrade_ok' in source
    assert 'long_source_upgrade_now := true' in source
    assert 'bool prefer_ob_upgrade = false' in source
    assert 'if long_source_upgrade_now and ob_source_upgrade_ok' in source
    assert 'prefer_ob_upgrade := not fvg_source_upgrade_ok or touched_bull_ob_quality >= touched_bull_fvg_quality' in source
    assert 'bool prefer_ob_upgrade = long_source_upgrade_now and ob_source_upgrade_ok and (not fvg_source_upgrade_ok or touched_bull_ob_quality >= touched_bull_fvg_quality)' not in source
    assert 'bool long_source_upgrade_now = ob_source_upgrade_ok or fvg_source_upgrade_ok' not in source
    assert 'stage_locked_source_transition(bool source_upgrade_now, bool prefer_ob_upgrade_now, int prev_locked_source_kind, int prev_locked_source_id, int current_backing_zone_kind, int current_backing_zone_id, int ob_candidate_id, int fvg_candidate_id) =>' in source
    assert '[long_locked_source_kind_final, long_locked_source_id_final, long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final] = stage_locked_source_transition(long_source_upgrade_now, prefer_ob_upgrade, prev_locked_source_kind, prev_locked_source_id, long_state.backing_zone_kind, long_state.backing_zone_id, touched_bull_ob_id, touched_bull_fvg_id)' in source
    assert 'int long_locked_source_last_touch_bar_index_effective = long_state.locked_source_last_touch_bar_index' in source
    assert 'if long_source_upgrade_now and not na(long_locked_source_id_final)' in source
    assert 'long_locked_source_last_touch_bar_index_effective := bar_index' in source
    assert 'int long_locked_source_last_touch_bar_index_effective = long_source_upgrade_now and not na(long_locked_source_id_final) ? bar_index : long_state.locked_source_last_touch_bar_index' not in source
    assert '[long_source_upgrade_now, prefer_ob_upgrade] = select_source_upgrade(ob_source_upgrade_ok, fvg_source_upgrade_ok, touched_bull_ob_quality, touched_bull_fvg_quality)' not in source


def test_source_upgrade_requires_different_candidate_than_locked_source() -> None:
    source = _read_smc_source()

    assert 'if prev_locked_source_kind != LONG_SOURCE_OB or prev_locked_source_id != touched_bull_ob_id' in source
    assert 'if prev_locked_source_kind != LONG_SOURCE_FVG or prev_locked_source_id != touched_bull_fvg_id' in source


def test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain() -> None:
    source = _read_smc_source()

    assert 'bool ob_source_upgrade_ok = false' in source
    assert 'bool fvg_source_upgrade_ok = false' in source
    assert 'allow_armed_source_upgrade and long_state.armed and not long_state.confirmed and not prev_locked_source_invalid_now' in source
    assert 'touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain' in source
    assert 'long_entry_origin_source' in source


def test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks() -> None:
    source = _read_smc_source()

    assert '[long_locked_source_kind_final, long_locked_source_id_final, long_setup_backing_zone_kind_final, long_setup_backing_zone_id_final] = stage_locked_source_transition(long_source_upgrade_now, prefer_ob_upgrade, prev_locked_source_kind, prev_locked_source_id, long_state.backing_zone_kind, long_state.backing_zone_id, touched_bull_ob_id, touched_bull_fvg_id)' in source
    assert 'bool long_locked_source_alive_now = false' in source
    assert 'long_locked_source_alive_now := contains_id(ob_blocks_bull, long_locked_source_id_final)' in source
    assert 'long_locked_source_alive_now := contains_id(fvgs_bull, long_locked_source_id_final)' in source
    assert 'bool long_locked_source_alive_now = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_blocks_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(fvgs_bull, long_locked_source_id_final) : false' not in source
    assert 'resolve_long_zone_top(int long_zone_kind, int long_zone_id, int active_bull_ob_id, float active_bull_ob_top, int touched_bull_ob_id, float touched_bull_ob_top, int active_bull_fvg_id, float active_bull_fvg_top, int touched_bull_fvg_id, float touched_bull_fvg_top, bool preserve_prior_bounds = false, int prior_long_zone_kind = 0, int prior_long_zone_id = na, float prior_long_zone_top = na) =>' in source
    assert 'float long_locked_source_top_now = resolve_long_zone_top(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_top, touched_bull_ob_id, touched_bull_ob_top, active_bull_fvg_id, active_bull_fvg_top, touched_bull_fvg_id, touched_bull_fvg_top, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_state.locked_source_top)' in source
    assert 'resolve_long_zone_bottom(int long_zone_kind, int long_zone_id, int active_bull_ob_id, float active_bull_ob_bottom, int touched_bull_ob_id, float touched_bull_ob_bottom, int active_bull_fvg_id, float active_bull_fvg_bottom, int touched_bull_fvg_id, float touched_bull_fvg_bottom, bool preserve_prior_bounds = false, int prior_long_zone_kind = 0, int prior_long_zone_id = na, float prior_long_zone_bottom = na) =>' in source
    assert 'float long_locked_source_bottom_now = resolve_long_zone_bottom(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_bottom, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_state.locked_source_bottom)' in source
    assert 'bool long_source_broken = false' in source
    assert 'if long_locked_source_kind_final == LONG_SOURCE_OB' in source
    assert 'long_source_broken := contains_id(ob_broken_bull, long_locked_source_id_final) or contains_id(ob_broken_new_bull, long_locked_source_id_final)' in source
    assert 'else if long_locked_source_kind_final == LONG_SOURCE_FVG' in source
    assert 'long_source_broken := contains_id(filled_fvgs_bull, long_locked_source_id_final) or contains_id(filled_fvgs_new_bull, long_locked_source_id_final)' in source
    assert 'bool long_source_broken = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_broken_bull, long_locked_source_id_final) or contains_id(ob_broken_new_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(filled_fvgs_bull, long_locked_source_id_final) or contains_id(filled_fvgs_new_bull, long_locked_source_id_final) : false' not in source


def test_arm_and_confirm_transitions_route_through_long_state_methods() -> None:
    source = _read_smc_source()

    assert 'long_state.arm(bar_index, arm_trigger_candidate, arm_invalidation_candidate, arm_source_kind, arm_backing_zone_kind, arm_backing_zone_id, long_arm_backing_zone_touch_count, arm_backing_zone_kind, long_arm_locked_source_id, long_arm_locked_source_top, long_arm_locked_source_bottom, long_arm_backing_zone_touch_count, long_arm_locked_source_last_touch_bar_index)' in source
    assert 'long_state.confirm(bar_index)' in source
    assert 'sync_long_state_from_legacy(long_state' not in source
    assert 'project_long_state(long_state)' not in source


def test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation() -> None:
    source = _read_smc_source()

    assert 'var int long_entry_origin_source = LONG_SOURCE_NONE' not in source
    assert 'int long_validation_source = LONG_SOURCE_NONE' in source
    assert "string long_setup_source_display = resolve_long_source_text(LONG_SOURCE_NONE)" in source
    assert 'long_validation_source := resolve_long_validation_source(long_state.locked_source_kind)' in source
    assert 'compose_long_setup_source_display(int long_entry_origin_source, int long_validation_source) =>' in source
    assert "string long_entry_origin_source_text = resolve_long_source_text(long_entry_origin_source)" in source
    assert "string long_validation_source_text = resolve_long_source_text(long_validation_source)" in source
    assert "string source_display = long_validation_source_text" in source
    assert 'if long_entry_origin_source == LONG_SOURCE_NONE' in source
    assert "source_display := long_entry_origin_source_text + ' -> ' + long_validation_source_text" in source
    assert "long_entry_origin_source == LONG_SOURCE_NONE ? long_validation_source_text : long_validation_source == LONG_SOURCE_NONE or long_entry_origin_source == long_validation_source ? long_entry_origin_source_text : long_entry_origin_source_text + ' -> ' + long_validation_source_text" not in source
    assert 'long_setup_source_display := compose_long_setup_source_display(long_state.entry_origin_source, long_validation_source)' in source
    assert 'compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>' in source
    assert "long_setup_text := compose_long_setup_text(long_zone_active, long_state.armed, long_building_state, long_state.confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidated_now, invalidated_prior_setup, long_invalidated_this_bar, long_setup_source_display)" in source
    assert "str.format('{0} -> {1}', long_entry_origin_source, long_validation_source)" not in source


def test_display_and_status_text_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'describe_long_freshness(bool long_setup_armed, bool long_setup_confirmed, bool ready_is_fresh, bool confirm_is_fresh) =>' in source
    assert 'describe_long_source_state(bool long_source_tracked, bool long_source_alive, bool long_source_broken) =>' in source
    assert "string freshness_text = 'n/a'" in source
    assert 'if ready_is_fresh' in source
    assert "freshness_text := 'confirm fresh'" in source
    assert "freshness_text := 'confirm stale'" in source
    assert "string source_state_text = 'n/a'" in source
    assert "source_state_text := 'source invalid'" in source
    assert "not long_setup_armed and not long_setup_confirmed ? 'n/a' : long_setup_confirmed ? ready_is_fresh ? 'confirm fresh' : 'confirm stale' : confirm_is_fresh ? 'armed fresh' : 'armed stale'" not in source
    assert "freshness_text := ready_is_fresh ? 'confirm fresh' : 'confirm stale'" not in source
    assert "freshness_text := confirm_is_fresh ? 'armed fresh' : 'armed stale'" not in source
    assert "not long_source_tracked ? 'n/a' : long_source_alive ? 'source alive' : long_source_broken ? 'source invalid' : 'source lost'" not in source
    assert 'string freshness_text = describe_long_freshness(long_state.armed, long_state.confirmed, ready_is_fresh, confirm_is_fresh)' in source
    assert 'string source_state_text = describe_long_source_state(long_source_tracked, long_source_alive, long_source_broken)' in source


def test_confirm_and_ready_gate_logic_is_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'select_effective_long_touch_count(bool long_setup_armed, bool long_setup_confirmed, int long_setup_backing_zone_touch_count, bool bull_reclaim_ob_strict, bool in_bull_ob_zone, bool in_bull_fvg_zone, int active_ob_touch_count, bool bull_reclaim_fvg_strict, int active_fvg_touch_count, int active_zone_touch_count) =>' in source
    assert 'describe_long_zone_quality(bool long_zone_active, bool long_setup_armed, bool long_setup_confirmed, int effective_long_active_touch_count) =>' in source
    assert 'int effective_touch_count = active_zone_touch_count' in source
    assert "string zone_quality_text = 'n/a'" in source
    assert "zone_quality_text := 'crowded'" in source
    assert 'long_setup_armed or long_setup_confirmed ? long_setup_backing_zone_touch_count : bull_reclaim_ob_strict or (in_bull_ob_zone and not in_bull_fvg_zone) ? active_ob_touch_count : bull_reclaim_fvg_strict or (in_bull_fvg_zone and not in_bull_ob_zone) ? active_fvg_touch_count : active_zone_touch_count' not in source
    assert "not long_zone_active and not long_setup_armed and not long_setup_confirmed ? 'n/a' : effective_long_active_touch_count <= 1 ? 'fresh touch' : effective_long_active_touch_count == 2 ? '2nd touch' : 'crowded'" not in source
    # confirm_long_filters, confirm_long_state, evaluate_long_ready_states helpers inlined
    assert 'int effective_long_active_touch_count = select_effective_long_touch_count(long_state.armed, long_state.confirmed, long_state.backing_zone_touch_count, bull_reclaim_ob_strict, in_bull_ob_zone, in_bull_fvg_zone, active_ob_touch_count, bull_reclaim_fvg_strict, active_fvg_touch_count, active_zone_touch_count)' in source
    assert 'string zone_quality_text = describe_long_zone_quality(long_zone_active, long_state.armed, long_state.confirmed, effective_long_active_touch_count)' in source
    assert 'bool confirm_hard_gate_ok = false' in source
    assert 'if micro_session_gate_ok and micro_freshness_gate_ok' in source
    assert 'confirm_hard_gate_ok := true' in source
    assert 'bool confirm_upgrade_gate_ok = false' in source
    assert 'if accel_confirm_gate_ok and sd_confirmed_gate_ok' in source
    assert 'confirm_upgrade_gate_ok := true' in source
    assert 'float long_confirm_break_src = close' in source
    assert 'if live_exec and effective_use_live_confirm_break' in source
    assert 'long_confirm_break_src := high' in source
    assert 'bool confirm_is_fresh = false' in source
    assert 'if long_state.armed and not na(long_state.arm_bar_index) and long_setup_age <= max_bars_arm_to_confirm' in source
    assert 'confirm_is_fresh := true' in source
    assert 'bool ready_is_fresh = false' in source
    assert 'if long_state.confirmed and not na(long_state.confirm_bar_index) and long_confirm_age <= max_bars_confirm_to_ready' in source
    assert 'ready_is_fresh := true' in source
    assert 'bool micro_setup_fresh_enough = true' in source
    assert 'if use_microstructure_profiles and micro_is_fast_decay and long_state.armed and not long_state.confirmed' in source
    assert 'micro_setup_fresh_enough := long_setup_age <= effective_fast_decay_setup_age_max' in source
    assert 'bool micro_confirm_fresh_enough = true' in source
    assert 'if use_microstructure_profiles and micro_is_fast_decay and long_state.confirmed' in source
    assert 'micro_confirm_fresh_enough := long_confirm_age <= effective_fast_decay_confirm_age_max' in source
    assert 'bool micro_freshness_gate_ok = false' in source
    assert 'if micro_setup_fresh_enough and micro_confirm_fresh_enough' in source
    assert 'micro_freshness_gate_ok := true' in source
    assert 'long_confirm_break := false' in source
    assert 'if long_state.armed and not long_state.confirmed and not na(long_state.arm_bar_index) and bar_index > long_state.arm_bar_index' in source
    assert 'long_confirm_break := long_confirm_break_src > long_state.trigger' in source
    assert 'internal_choch_since_arm := false' in source
    assert 'if long_state.armed and not na(long_state.arm_bar_index) and not na(internal_choch_since_bars)' in source
    assert 'internal_choch_since_arm := internal_choch_since_bars <= bar_index - long_state.arm_bar_index' in source
    assert 'internal_bos_since_arm := false' in source
    assert 'if long_state.armed and not na(long_state.arm_bar_index) and not na(internal_bos_since_bars)' in source
    assert 'internal_bos_since_arm := internal_bos_since_bars <= bar_index - long_state.arm_bar_index' in source
    assert 'long_internal_structure_ok := false' in source
    assert 'if internal_bull_choch_sig or internal_bull_bos_sig or internal_choch_since_arm or internal_bos_since_arm' in source
    assert 'long_internal_structure_ok := true' in source
    assert "if long_internal_structure_mode == 'Internal CHoCH only'" in source
    assert 'if internal_bull_choch_sig or internal_choch_since_arm' in source
    assert 'long_plan_active := false' in source
    assert 'if (long_state.armed or long_state.confirmed) and not na(long_state.trigger) and not na(long_state.invalidation_level)' in source
    assert 'long_plan_active := true' in source
    assert 'compute_overhead_context() =>' in source
    assert 'float _stop = na' in source
    assert '_stop := long_state.invalidation_level - ob_threshold_atr * stop_buffer_atr_mult' in source
    assert 'float _scan_ref = close' in source
    assert 'if long_plan_active and not na(long_state.trigger)' in source
    assert '_scan_ref := long_state.trigger' in source
    assert 'bool confirm_lifecycle_ok = false' in source
    assert 'if close_safe_mode and long_confirm_break and long_confirm_structure_ok and confirm_is_fresh and long_confirm_bearish_guard_ok' in source
    assert 'confirm_lifecycle_ok := true' in source
    assert 'bool confirm_filters_ok = false' in source
    assert 'if confirm_hard_gate_ok and confirm_upgrade_gate_ok' in source
    assert 'confirm_filters_ok := true' in source
    assert 'float long_confirm_break_src = live_exec and effective_use_live_confirm_break ? high : close' not in source
    assert 'bool confirm_is_fresh = long_state.armed and not na(long_state.arm_bar_index) and long_setup_age <= max_bars_arm_to_confirm' not in source
    assert 'bool ready_is_fresh = long_state.confirmed and not na(long_state.confirm_bar_index) and long_confirm_age <= max_bars_confirm_to_ready' not in source
    assert 'bool micro_setup_fresh_enough = not use_microstructure_profiles or not micro_is_fast_decay or not long_state.armed or long_state.confirmed or long_setup_age <= effective_fast_decay_setup_age_max' not in source
    assert 'bool micro_confirm_fresh_enough = not use_microstructure_profiles or not micro_is_fast_decay or not long_state.confirmed or long_confirm_age <= effective_fast_decay_confirm_age_max' not in source
    assert 'bool micro_freshness_gate_ok = micro_setup_fresh_enough and micro_confirm_fresh_enough' not in source
    assert 'long_confirm_break := long_state.armed and not long_state.confirmed and not na(long_state.arm_bar_index) and bar_index > long_state.arm_bar_index and long_confirm_break_src > long_state.trigger' not in source
    assert 'internal_choch_since_arm := long_state.armed and not na(long_state.arm_bar_index) and not na(internal_choch_since_bars) and internal_choch_since_bars <= bar_index - long_state.arm_bar_index' not in source
    assert 'internal_bos_since_arm := long_state.armed and not na(long_state.arm_bar_index) and not na(internal_bos_since_bars) and internal_bos_since_bars <= bar_index - long_state.arm_bar_index' not in source
    assert "long_internal_structure_ok := long_internal_structure_mode == 'Internal CHoCH only' ? (internal_bull_choch_sig or internal_choch_since_arm) : (internal_bull_choch_sig or internal_bull_bos_sig or internal_choch_since_arm or internal_bos_since_arm)" not in source
    assert 'long_plan_active := (long_state.armed or long_state.confirmed) and not na(long_state.trigger) and not na(long_state.invalidation_level)' not in source
    assert 'bool confirm_hard_gate_ok = micro_session_gate_ok and micro_freshness_gate_ok' not in source
    assert 'bool confirm_upgrade_gate_ok = accel_confirm_gate_ok and sd_confirmed_gate_ok' not in source
    assert 'bool confirm_lifecycle_ok = close_safe_mode and long_confirm_break and long_confirm_structure_ok and confirm_is_fresh and long_confirm_bearish_guard_ok' not in source
    assert 'bool confirm_filters_ok = confirm_hard_gate_ok and confirm_upgrade_gate_ok' not in source
    assert 'float long_planned_stop_level = long_plan_active ? long_state.invalidation_level - ob_threshold_atr * stop_buffer_atr_mult : na' not in source
    assert 'float overhead_scan_reference = long_plan_active and not na(long_state.trigger) ? long_state.trigger : close' not in source
    assert 'float _overhead = na' in source
    assert '_overhead := math.min(_bear_ob_lvl, _bear_fvg_lvl)' in source
    assert '_overhead := _bear_fvg_lvl' in source
    assert 'if not na(_bear_ob_lvl)' in source
    assert 'nearest_overhead_level := not na(nearest_bear_ob_blocker_level) ? nearest_bear_ob_blocker_level : nearest_bear_fvg_blocker_level' not in source
    assert 'float _risk = na' in source
    assert 'if long_plan_active and not na(_stop)' in source
    assert '_risk := math.max(long_state.trigger - _stop, syminfo.mintick)' in source
    assert 'float planned_risk = long_plan_active and not na(long_planned_stop_level) ? math.max(long_state.trigger - long_planned_stop_level, syminfo.mintick) : na' not in source
    assert 'float _headroom = na' in source
    assert 'if not na(_overhead) and long_plan_active' in source
    assert '_headroom := _overhead - long_state.trigger' in source
    assert 'float headroom_to_overhead = not na(nearest_overhead_level) and long_plan_active ? nearest_overhead_level - long_state.trigger : na' not in source
    assert 'bool _overhead_ok = true' in source
    assert 'if use_overhead_zone_filter_eff and not na(_headroom) and not na(_risk)' in source
    assert '_overhead_ok := _headroom >= _risk * min_headroom_r' in source
    assert 'bool overhead_zone_ok = not use_overhead_zone_filter_eff or na(headroom_to_overhead) or na(planned_risk) or headroom_to_overhead >= planned_risk * min_headroom_r' not in source
    assert 'int _htf_count = 0' in source
    assert 'if mtf_trend_1 > 0' in source
    assert 'if mtf_trend_2 > 0' in source
    assert 'if mtf_trend_3 > 0' in source
    assert 'bool _htf_ok = _htf_count >= 2' in source
    assert 'bool htf_alignment_ok = (mtf_trend_1 > 0 ? 1 : 0) + (mtf_trend_2 > 0 ? 1 : 0) + (mtf_trend_3 > 0 ? 1 : 0) >= 2' not in source
    assert 'bool htf_alignment_ok = htf_bullish_alignment_count >= 2' not in source
    assert 'int _vwap_w = 0' in source
    assert 'if use_vwap_filter' in source
    assert '_vwap_w := 1' in source
    assert 'int context_quality_vwap_weight = use_vwap_filter ? 1 : 0' not in source
    assert 'if bullish_trend_safe' in source
    assert '_score += score_weight_structure' in source
    assert 'if _htf_ok' in source
    assert '_score += score_weight_htf' in source
    assert 'if ema_support_ok' in source
    assert '_score += score_weight_ema' in source
    assert 'if adx_strong' in source
    assert '_score += score_weight_adx' in source
    assert 'if bull_close_strong' in source
    assert '_score += score_weight_close' in source
    assert 'if relvol_score_ok' in source
    assert '_score += score_weight_relvol' in source
    assert 'if vwap_filter_ok' in source
    assert '_score += _vwap_w' in source
    assert 'context_quality_score += bullish_trend_safe ? score_weight_structure : 0' not in source
    assert 'context_quality_score += htf_alignment_ok ? score_weight_htf : 0' not in source
    assert 'context_quality_score += ema_support_ok ? score_weight_ema : 0' not in source
    assert 'context_quality_score += adx_strong ? score_weight_adx : 0' not in source
    assert 'context_quality_score += bull_close_strong ? score_weight_close : 0' not in source
    assert 'context_quality_score += relvol_score_ok ? score_weight_relvol : 0' not in source
    assert 'context_quality_score += vwap_filter_ok ? context_quality_vwap_weight : 0' not in source
    assert 'int _eff_max = _max' in source
    assert 'if _relvol_unavail' in source
    assert '_eff_max -= score_weight_relvol' in source
    assert 'int effective_context_quality_max_score = context_quality_max_score - (relvol_score_unavailable ? score_weight_relvol : 0)' not in source
    assert "str.tostring(effective_context_quality_max_score)" in source
    assert 'bool _gate_ok = true' in source
    assert 'if use_context_quality_score_eff' in source
    assert '_gate_ok := _score >= _eff_min' in source
    assert '[_score, _gate_ok, _htf_ok, _ltf_ok, _eff_min, _eff_max]' in source
    assert '[context_quality_score, context_quality_gate_ok, htf_alignment_ok, strict_entry_ltf_ok, effective_min_context_quality_score, effective_context_quality_max_score] = compute_context_quality()' in source
    assert 'bool long_setup_in_progress = false' in source
    assert 'if long_state.armed and not long_state.confirmed' in source
    assert 'long_setup_in_progress := true' in source
    assert 'long_building_state := false' in source
    assert 'if long_state.armed and long_internal_structure_ok and not long_state.confirmed' in source
    assert 'long_building_state := true' in source
    assert 'bool ready_bar_gap_ok = false' in source
    assert 'if not na(long_state.confirm_bar_index)' in source
    assert 'ready_bar_gap_ok := bar_index > long_state.confirm_bar_index' in source
    assert 'bool long_setup_in_progress = long_state.armed and not long_state.confirmed' not in source
    assert 'long_building_state := long_state.armed and long_internal_structure_ok and not long_state.confirmed' not in source
    assert 'bool ready_bar_gap_ok = not na(long_state.confirm_bar_index) and bar_index > long_state.confirm_bar_index' not in source
    assert 'bool context_quality_gate_ok = not use_context_quality_score_eff or context_quality_score >= effective_min_context_quality_score' not in source
    assert 'bool effective_zone_touch_quality_ok = true' in source
    assert 'if block_third_touch_eff' in source
    assert 'effective_zone_touch_quality_ok := effective_long_active_touch_count <= max_zone_touches_for_entry' in source
    assert 'bool effective_zone_touch_quality_ok = not block_third_touch_eff or effective_long_active_touch_count <= max_zone_touches_for_entry' not in source
    assert 'float long_mean_target = na' in source
    assert 'if long_plan_active and show_mean_target_overlay and not na(stretch_mean)' in source
    assert 'if stretch_mean > long_state.trigger' in source
    assert 'long_mean_target := stretch_mean' in source
    assert 'long_mean_target := stretch_mean > long_state.trigger ? stretch_mean : na' not in source
    assert 'compute_long_environment_context(bool market_regime_gate_ok, bool vola_regime_gate_safe, bool context_quality_gate_ok, bool session_structure_gate_ok, bool micro_session_gate_ok, bool micro_freshness_gate_ok, bool overhead_zone_ok) =>' in source
    assert '[environment_hard_gate_ok, quality_gate_ok, microstructure_entry_gate_ok, trade_hard_gate_ok, long_environment_focus_display] = compute_long_environment_context(market_regime_gate_ok, vola_regime_gate_safe, context_quality_gate_ok, session_structure_gate_ok, micro_session_gate_ok, micro_freshness_gate_ok, overhead_zone_ok)' in source
    assert 'compute_long_ready_state(bool close_safe_mode, bool long_setup_confirmed, bool ready_bar_gap_ok, bool long_confirm_expired, bool ready_is_fresh, bool long_confirm_bearish_guard_ok, bool require_main_break_for_ready, bool bull_bos_sig, bool main_bos_recent, bool setup_hard_gate_ok, bool trade_hard_gate_ok, bool environment_hard_gate_ok, bool quality_gate_ok, bool accel_ready_gate_ok, bool sd_ready_gate_ok, bool vol_ready_context_ok, bool stretch_ready_context_ok, bool ddvi_ready_ok_safe) =>' in source
    assert 'bool helper_lifecycle_ready_ok = close_safe_mode and long_setup_confirmed and ready_bar_gap_ok and not long_confirm_expired and ready_is_fresh and long_confirm_bearish_guard_ok and (not require_main_break_for_ready or bull_bos_sig or main_bos_recent)' in source
    assert 'bool helper_long_ready_state = helper_lifecycle_ready_ok and setup_hard_gate_ok and trade_hard_gate_ok and environment_hard_gate_ok and quality_gate_ok and accel_ready_gate_ok and sd_ready_gate_ok and vol_ready_context_ok and stretch_ready_context_ok and ddvi_ready_ok_safe' in source
    assert '[lifecycle_ready_ok, long_ready_state] = compute_long_ready_state(close_safe_mode, long_state.confirmed, ready_bar_gap_ok, long_confirm_expired, ready_is_fresh, long_confirm_bearish_guard_ok, require_main_break_for_ready_eff, bull_bos_sig, main_bos_recent, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok, quality_gate_ok, accel_ready_gate_ok, sd_ready_gate_ok, vol_ready_context_ok, stretch_ready_context_ok, ddvi_ready_ok_safe)' in source
    assert 'compute_long_entry_best_state(bool long_ready_state, bool accel_entry_best_gate_ok, bool sd_entry_best_gate_ok, bool vol_entry_best_context_ok_safe, bool stretch_entry_best_context_ok, bool ddvi_entry_best_ok_safe) =>' in source
    assert 'bool long_entry_best_state = compute_long_entry_best_state(long_ready_state, accel_entry_best_gate_ok, sd_entry_best_gate_ok, vol_entry_best_context_ok_safe, stretch_entry_best_context_ok, ddvi_entry_best_ok_safe)' in source
    assert 'compute_long_entry_strict_state(bool long_ready_state, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe) =>' in source
    assert 'bool long_entry_strict_state = compute_long_entry_strict_state(long_ready_state, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    # tuple call negative assertions removed — helpers no longer exist


def test_setup_text_and_visual_state_are_extracted_into_helpers() -> None:
    source = _read_smc_source()

    assert 'resolve_long_state_code(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar, bool long_invalidate_signal = false) =>' in source
    assert 'compose_long_setup_text(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidated_now, bool invalidated_prior_setup, bool long_invalidated_this_bar, string long_setup_source_display) =>' in source
    assert "int state_code = resolve_long_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)" in source
    assert "string setup_text = 'No Setup'" in source
    assert "if state_code == -1" in source
    assert "setup_text := 'Invalidated'" in source
    assert "setup_text := 'Armed | ' + long_setup_source_display" in source
    assert "setup_text := 'Building | ' + long_setup_source_display" in source
    assert "setup_text := 'Confirmed | ' + long_setup_source_display" in source
    assert "setup_text := 'Ready | ' + long_setup_source_display" in source
    assert "setup_text := 'Entry Best | ' + long_setup_source_display" in source
    assert "setup_text := 'Entry Strict | ' + long_setup_source_display" in source
    assert 'resolve_long_visual_state(bool long_zone_active, bool long_setup_armed, bool long_building_state, bool long_setup_confirmed, bool long_ready_state, bool long_entry_best_state, bool long_entry_strict_state, bool long_invalidate_signal, bool invalidated_prior_setup, bool long_invalidated_now, bool long_invalidated_this_bar) =>' in source
    assert 'resolve_long_state_code(long_zone_active, long_setup_armed, long_building_state, long_setup_confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar, long_invalidate_signal)' in source
    assert 'resolve_long_visual_text(int long_visual_state) =>' in source
    assert "string visual_text = 'Ready'" in source
    assert "visual_text := 'Fail'" in source
    assert "visual_text := 'Neutral'" in source
    assert "visual_text := 'In Zone'" in source
    assert "visual_text := 'Armed'" in source
    assert "visual_text := 'Building'" in source
    assert "visual_text := 'Confirmed'" in source
    assert "long_setup_text := compose_long_setup_text(long_zone_active, long_state.armed, long_building_state, long_state.confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidated_now, invalidated_prior_setup, long_invalidated_this_bar, long_setup_source_display)" in source
    assert 'long_visual_state := resolve_long_visual_state(long_zone_active, long_state.armed, long_building_state, long_state.confirmed, long_ready_state, long_entry_best_state, long_entry_strict_state, long_invalidate_signal, invalidated_prior_setup, long_invalidated_now, long_invalidated_this_bar)' in source
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
    assert 'long_watchlist_alert_level := low' in source
    assert 'if not na(last_bull_fvg_bottom)' in source
    assert 'long_watchlist_alert_level := last_bull_fvg_bottom' in source
    assert 'if not na(last_bull_ob_bottom)' in source
    assert 'long_watchlist_alert_level := last_bull_ob_bottom' in source
    assert 'float long_early_alert_level = long_watchlist_alert_level' in source
    assert 'float long_clean_alert_level = long_watchlist_alert_level' in source
    assert 'float long_entry_best_alert_level = long_watchlist_alert_level' in source
    assert 'float long_entry_strict_alert_level = long_watchlist_alert_level' in source
    assert 'if not na(long_state.trigger)' in source
    assert 'long_early_alert_level := long_state.trigger' in source
    assert 'long_clean_alert_level := long_state.trigger' in source
    assert 'long_entry_best_alert_level := long_state.trigger' in source
    assert 'long_entry_strict_alert_level := long_state.trigger' in source
    assert "long_watchlist_alert_level := not na(last_bull_ob_bottom) ? last_bull_ob_bottom : not na(last_bull_fvg_bottom) ? last_bull_fvg_bottom : low" not in source
    assert 'float long_early_alert_level = not na(long_state.trigger) ? long_state.trigger : long_watchlist_alert_level' not in source
    assert 'float long_clean_alert_level = not na(long_state.trigger) ? long_state.trigger : long_watchlist_alert_level' not in source
    assert 'float long_entry_best_alert_level = not na(long_state.trigger) ? long_state.trigger : long_watchlist_alert_level' not in source
    assert 'float long_entry_strict_alert_level = not na(long_state.trigger) ? long_state.trigger : long_watchlist_alert_level' not in source
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
    assert 'bool ob_more_recent = false' in source
    assert 'if na(last_fvg_zone_touch_bar_index) or (not na(last_ob_zone_touch_bar_index) and last_ob_zone_touch_bar_index >= last_fvg_zone_touch_bar_index)' in source
    assert 'ob_more_recent := true' in source
    assert 'arm_backing_zone_kind := LONG_SOURCE_FVG' in source
    assert 'arm_backing_zone_id := active_bull_fvg_id' in source
    assert 'if ob_more_recent' in source
    assert 'arm_backing_zone_kind := LONG_SOURCE_OB' in source
    assert 'arm_backing_zone_id := active_bull_ob_id' in source
    # tuple call negative assertions removed — helpers no longer exist
    assert "arm_backing_zone_id := touched_bull_fvg_id" in source
    assert 'arm_source_text := arm_source_text_tmp' not in source
    assert 'arm_invalidation_candidate := arm_invalidation_candidate_tmp' not in source
    # tuple call negative assertions removed — helpers no longer exist
    assert "backing_zone_id := ob_more_recent ? active_bull_ob_id : active_bull_fvg_id" not in source
    assert 'arm_backing_zone_kind := ob_more_recent ? LONG_SOURCE_OB : LONG_SOURCE_FVG' not in source
    assert 'arm_backing_zone_id := ob_more_recent ? active_bull_ob_id : active_bull_fvg_id' not in source
    # tuple call negative assertion removed — helpers no longer exist
    assert 'int touch_count = 0' in source
    assert 'else if arm_backing_zone_kind == LONG_SOURCE_FVG and arm_backing_zone_id == active_fvg_touch_id' in source
    assert 'touch_count := active_fvg_touch_count' in source
    assert 'arm_backing_zone_kind == LONG_SOURCE_FVG and arm_backing_zone_id == active_fvg_touch_id ? active_fvg_touch_count' not in source
    assert 'int long_arm_locked_source_id = resolve_long_zone_id(arm_backing_zone_kind, arm_backing_zone_id)' in source
    assert 'float long_arm_locked_source_top = resolve_long_zone_top(arm_backing_zone_kind, arm_backing_zone_id, active_bull_ob_id, active_bull_ob_top, touched_bull_ob_id, touched_bull_ob_top, active_bull_fvg_id, active_bull_fvg_top, touched_bull_fvg_id, touched_bull_fvg_top)' in source
    assert 'float long_arm_locked_source_bottom = resolve_long_zone_bottom(arm_backing_zone_kind, arm_backing_zone_id, active_bull_ob_id, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_bottom)' in source
    assert 'bool long_locked_source_alive_now = false' in source
    assert 'long_locked_source_alive_now := contains_id(ob_blocks_bull, long_locked_source_id_final)' in source
    assert 'long_locked_source_alive_now := contains_id(fvgs_bull, long_locked_source_id_final)' in source
    assert 'bool long_locked_source_alive_now = long_locked_source_kind_final == LONG_SOURCE_OB ? contains_id(ob_blocks_bull, long_locked_source_id_final) : long_locked_source_kind_final == LONG_SOURCE_FVG ? contains_id(fvgs_bull, long_locked_source_id_final) : false' not in source
    assert 'float long_locked_source_top_now = resolve_long_zone_top(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_top, touched_bull_ob_id, touched_bull_ob_top, active_bull_fvg_id, active_bull_fvg_top, touched_bull_fvg_id, touched_bull_fvg_top, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_state.locked_source_top)' in source
    assert 'float long_locked_source_bottom_now = resolve_long_zone_bottom(long_locked_source_kind_final, long_locked_source_id_final, active_bull_ob_id, active_bull_ob_bottom, touched_bull_ob_id, touched_bull_ob_bottom, active_bull_fvg_id, active_bull_fvg_bottom, touched_bull_fvg_id, touched_bull_fvg_bottom, long_locked_source_alive_now and not long_source_upgrade_now, prev_locked_source_kind, prev_locked_source_id, long_state.locked_source_bottom)' in source
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
    assert 'bool long_arm_close_safe = false' in source
    assert 'if barstate.isconfirmed and long_state.armed and not (long_state[1]).armed' in source
    assert 'long_arm_close_safe := true' in source
    assert 'bool long_confirm_close_safe = false' in source
    assert 'if barstate.isconfirmed and long_state.confirmed and not (long_state[1]).confirmed' in source
    assert 'long_confirm_close_safe := true' in source
    assert 'bool long_ready_close_safe = false' in source
    assert 'if barstate.isconfirmed and long_ready_state and not long_ready_state[1]' in source
    assert 'long_ready_close_safe := true' in source
    assert 'bool long_invalidated_close_safe = false' in source
    assert 'if barstate.isconfirmed and not long_state.armed and not long_state.confirmed and ((long_state[1]).armed or (long_state[1]).confirmed)' in source
    assert 'long_invalidated_close_safe := true' in source
    assert 'bool long_arm_alert_event = false' in source
    assert 'if long_arm_signal_latched' in source
    assert 'long_arm_alert_event := true' in source
    assert 'bool long_confirm_alert_event = false' in source
    assert 'if long_confirm_signal_latched' in source
    assert 'long_confirm_alert_event := true' in source
    assert 'bool long_ready_alert_event = false' in source
    assert 'if long_ready_signal_latched' in source
    assert 'long_ready_alert_event := true' in source
    assert 'bool long_invalidate_alert_event = false' in source
    assert 'if long_invalidate_signal_latched' in source
    assert 'long_invalidate_alert_event := true' in source
    assert 'bool live_bull_ob_break_alert_event = false' in source
    assert 'if live_bull_ob_break_latched' in source
    assert 'live_bull_ob_break_alert_event := true' in source
    assert 'bool live_bull_fvg_fill_alert_event = false' in source
    assert 'if live_bull_fvg_fill_latched' in source
    assert 'live_bull_fvg_fill_alert_event := true' in source
    assert 'bool long_arm_close_safe = barstate.isconfirmed and long_state.armed and not (long_state[1]).armed' not in source
    assert 'bool long_confirm_close_safe = barstate.isconfirmed and long_state.confirmed and not (long_state[1]).confirmed' not in source
    assert 'bool long_ready_close_safe = barstate.isconfirmed and long_ready_state and not long_ready_state[1]' not in source
    assert 'bool long_invalidated_close_safe = barstate.isconfirmed and not long_state.armed and not long_state.confirmed and ((long_state[1]).armed or (long_state[1]).confirmed)' not in source
    assert 'bool long_arm_alert_event = long_arm_signal_latched' not in source
    assert 'bool long_confirm_alert_event = long_confirm_signal_latched' not in source
    assert 'bool long_ready_alert_event = long_ready_signal_latched' not in source
    assert 'bool long_invalidate_alert_event = long_invalidate_signal_latched' not in source
    assert 'bool live_bull_ob_break_alert_event = live_bull_ob_break_latched' not in source
    assert 'bool live_bull_fvg_fill_alert_event = live_bull_fvg_fill_latched' not in source
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
    assert 'bool bullish_fvg_filled_alert = false' in source
    assert 'if array.size(filled_fvgs_new_bull) > 0' in source
    assert 'bullish_fvg_filled_alert := true' in source
    assert 'FVG bull_filled_alert_gap = na' in source
    assert 'if bullish_fvg_filled_alert' in source
    assert 'bull_filled_alert_gap := array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1)' in source
    assert 'float bull_filled_alert_level = resolve_fvg_alert_level(bull_filled_alert_gap)' in source
    assert 'FVG last_bull_fvg_gap = na' in source
    assert 'if array.size(fvgs_bull) > 0' in source
    assert 'last_bull_fvg_gap := array.get(fvgs_bull, array.size(fvgs_bull) - 1)' in source
    # bear last-zone patterns removed (Patch 4)
    assert 'OrderBlock last_bull_ob = na' in source
    assert 'if array.size(ob_blocks_bull) > 0' in source
    assert 'last_bull_ob := array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1)' in source
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
    assert 'scan_active_bull_ob() =>' in source
    assert '_break_level := resolve_ob_alert_level(_ob)' in source
    # bear active-closest scanning removed (Patch 4)
    assert 'OrderBlock active_bear_ob = array.get(ob_blocks_bear, best_bear_ob_idx)' not in source
    assert 'active_bear_ob_break_level := resolve_ob_alert_level(active_bear_ob)' not in source
    assert '_fill_level := resolve_fvg_alert_level(_fvg)' in source
    assert 'FVG active_bear_fvg = array.get(fvgs_bear, best_bear_fvg_idx)' not in source
    assert 'active_bear_fvg_fill_level := resolve_fvg_alert_level(active_bear_fvg)' not in source
    # bear live event patterns removed (Patch 4)
    assert 'FVG bear_live_filled_gap = any_live_bear_fvg_fill' not in source
    assert 'scan_live_bull_events() =>' in source
    assert 'OrderBlock _live_broken_ob = _any_ob ? array.get(ob_broken_new_bull, array.size(ob_broken_new_bull) - 1) : na' in source
    assert 'OrderBlock bear_live_broken_ob = any_live_bear_ob_break' not in source
    assert 'float _ob_level = _any_ob ? resolve_ob_alert_level(_live_broken_ob) : _ob_alert' in source
    assert 'float bear_ob_live_event_level = any_live_bear_ob_break' not in source
    assert 'float _fvg_level = _any_fvg ? resolve_fvg_alert_level(_live_filled_gap) : _fvg_alert' in source
    assert 'float bear_fvg_live_event_level = any_live_bear_fvg_fill' not in source
    assert 'float _best_ob_boundary = na' in source
    assert 'OrderBlock _best_ob = array.get(ob_blocks_bull, _best_ob_idx)' in source
    assert '_best_ob_boundary := resolve_ob_bottom_boundary(_best_ob)' in source
    assert 'float _ob_cand_level = resolve_ob_alert_level(_ob_cand)' in source
    assert 'float _ob_cand_boundary = resolve_ob_bottom_boundary(_ob_cand)' in source
    # bear live scanning removed (Patch 4)
    assert 'float best_live_bear_ob_boundary = na' not in source
    assert 'OrderBlock best_live_bear_ob = array.get(ob_blocks_bear, best_live_bear_ob_idx)' not in source
    assert 'best_live_bear_ob_boundary := resolve_ob_top_boundary(best_live_bear_ob)' not in source
    assert 'float bear_ob_live_candidate_level = resolve_ob_alert_level(bear_ob_live_candidate)' not in source
    assert 'float bear_ob_live_candidate_boundary = resolve_ob_top_boundary(bear_ob_live_candidate)' not in source
    assert 'float _fvg_cand_level = resolve_fvg_alert_level(_fvg_cand)' in source
    assert 'float _fvg_cand_boundary = resolve_fvg_bottom_boundary(_fvg_cand)' in source
    # bear FVG live candidates removed (Patch 4)
    assert 'float bear_fvg_live_candidate_level = resolve_fvg_alert_level(bear_fvg_live_candidate)' not in source
    assert 'float bear_fvg_live_candidate_boundary = resolve_fvg_top_boundary(bear_fvg_live_candidate)' not in source
    assert 'float _best_fvg_boundary = na' in source
    assert 'FVG _best_fvg = array.get(fvgs_bull, _best_fvg_idx)' in source
    assert '_best_fvg_boundary := resolve_fvg_bottom_boundary(_best_fvg)' in source
    assert 'FVG _best_live_fvg = array.get(fvgs_bull, _best_fvg_idx)' in source
    assert '_fvg_level := resolve_fvg_alert_level(_best_live_fvg)' in source
    # bear fvg/ob live scan removed (Patch 4)
    assert 'float best_live_bear_fvg_boundary = na' not in source
    assert 'FVG best_live_bear_fvg = array.get(fvgs_bear, best_live_bear_fvg_idx)' not in source
    assert 'best_live_bear_fvg_boundary := resolve_fvg_top_boundary(best_live_bear_fvg)' not in source
    assert 'FVG bear_live_fvg = array.get(fvgs_bear, best_live_bear_fvg_idx)' not in source
    assert 'bear_fvg_live_event_level := resolve_fvg_alert_level(bear_live_fvg)' not in source
    assert 'OrderBlock _best_live_ob = array.get(ob_blocks_bull, _best_ob_idx)' in source
    assert '_ob_level := resolve_ob_alert_level(_best_live_ob)' in source
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
    assert 'scan_active_bull_ob() =>' in source
    assert '_top := resolve_ob_top_boundary(_ob)' in source
    assert '_bottom := resolve_ob_bottom_boundary(_ob)' in source
    assert '_recency := resolve_ob_recency_index(_ob)' in source
    assert '_top := resolve_fvg_top_boundary(_fvg)' in source
    assert '_bottom := resolve_fvg_bottom_boundary(_fvg)' in source
    assert '_recency := resolve_fvg_recency_index(_fvg)' in source
    assert 'resolve_ob_recency_index(OrderBlock block)' in source
    assert 'resolve_fvg_recency_index(FVG gap)' in source
    assert 'float _blvl = resolve_ob_alert_level(_blocker)' in source
    assert 'float _flvl = resolve_fvg_alert_level(_fblocker)' in source
    assert 'compute_bullish_dynamic_alert_gates(bool enable_dynamic_alerts, bool bull_bos_sig, bool bull_choch_sig, OrderBlock new_ob_bull, bool bullish_fvg_alert, bool bullish_fvg_filled_alert, bool enable_live_break_alerts, bool live_exec, bool live_bull_ob_break, bool live_bull_fvg_fill, bool use_sd_confluence, bool sd_bullish_divergence_event, bool sd_higher_lows_event) =>' in source
    assert '[dynamic_bull_bos_alert_active, dynamic_bull_choch_alert_active, dynamic_new_bull_ob_alert_active, dynamic_new_bull_fvg_alert_active, dynamic_bull_fvg_filled_alert_active, dynamic_live_bull_ob_break_alert_active, dynamic_live_bull_fvg_fill_alert_active, dynamic_sd_bull_divergence_alert_active, dynamic_sd_higher_lows_alert_active] = compute_bullish_dynamic_alert_gates(enable_dynamic_alerts, bull_bos_sig, bull_choch_sig, new_ob_bull, bullish_fvg_alert, bullish_fvg_filled_alert, enable_live_break_alerts, live_exec, live_bull_ob_break, live_bull_fvg_fill, use_sd_confluence, sd_bullish_divergence_event, sd_higher_lows_event)' in source
    assert 'emit_bullish_dynamic_alerts(string seen_keys, float ltf_bull_share_context, float ltf_volume_delta_context, bool ltf_price_only_context, string signal_mode_text) =>' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, dynamic_new_bull_ob_alert_active, bull_ob_alert_key, bull_ob_alert_name, bull_ob_alert_detail, new_ob_bull_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    # bear dynamic alert emit removed (Patch 4)
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and not na(new_ob_bear)' not in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, dynamic_new_bull_fvg_alert_active, bull_fvg_alert_key, bull_fvg_alert_name, bull_fvg_alert_detail, new_fvg_bull_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bearish_fvg_alert, bear_fvg_alert_key' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and not na(new_ob_bull), bull_ob_alert_key, bull_ob_alert_name, bull_ob_alert_detail, new_ob_bull_alert_level, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and bullish_fvg_alert, bull_fvg_alert_key, bull_fvg_alert_name, bull_fvg_alert_detail, new_fvg_bull_alert_level, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'new_ob_bull.break_price, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'new_ob_bear.break_price, -1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'float bear_ob_blocker_level = bear_ob_blocker.break_price' not in source
    assert 'float bear_fvg_blocker_level = bear_fvg_blocker.fill_target_level' not in source
    assert 'float new_ob_bull_alert_level = not na(new_ob_bull) ? new_ob_bull.break_price : na' not in source
    assert 'float new_ob_bear_alert_level = not na(new_ob_bear) ? new_ob_bear.break_price : na' not in source
    assert 'float new_fvg_bull_alert_level = not na(new_fvg_bull) ? new_fvg_bull.fill_target_level : na' not in source
    assert 'float new_fvg_bear_alert_level = not na(new_fvg_bear) ? new_fvg_bear.fill_target_level : na' not in source
    assert 'FVG bull_filled_alert_gap = bullish_fvg_filled_alert ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1) : na' not in source
    assert 'float bull_filled_alert_level = bullish_fvg_filled_alert ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1).fill_target_level : na' not in source
    assert 'float bear_filled_alert_level = bearish_fvg_filled_alert ? array.get(filled_fvgs_new_bear, array.size(filled_fvgs_new_bear) - 1).fill_target_level : na' not in source
    assert 'OrderBlock last_bull_ob = array.size(ob_blocks_bull) > 0 ? array.get(ob_blocks_bull, array.size(ob_blocks_bull) - 1) : na' not in source
    assert 'FVG last_bull_fvg_gap = array.size(fvgs_bull) > 0 ? array.get(fvgs_bull, array.size(fvgs_bull) - 1) : na' not in source
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
    assert 'float _ob_alert = last_bull_ob_break_level' in source
    assert 'if not na(active_bull_ob_break_level)' in source
    assert '_ob_alert := active_bull_ob_break_level' in source
    assert 'float _fvg_alert = last_bull_fvg_fill_level' in source
    assert 'if not na(active_bull_fvg_fill_level)' in source
    assert '_fvg_alert := active_bull_fvg_fill_level' in source
    assert 'float bull_ob_live_event_level = any_live_bull_ob_break ? array.get(ob_broken_new_bull, array.size(ob_broken_new_bull) - 1).break_price : bull_ob_break_for_alert' not in source
    assert 'float bear_ob_live_event_level = any_live_bear_ob_break ? array.get(ob_broken_new_bear, array.size(ob_broken_new_bear) - 1).break_price : bear_ob_break_for_alert' not in source
    assert 'float bull_fvg_live_event_level = any_live_bull_fvg_fill ? array.get(filled_fvgs_new_bull, array.size(filled_fvgs_new_bull) - 1).fill_target_level : bull_fvg_fill_for_alert' not in source
    assert 'float bull_ob_break_for_alert = not na(active_bull_ob_break_level) ? active_bull_ob_break_level : last_bull_ob_break_level' not in source
    assert 'float bull_fvg_fill_for_alert = not na(active_bull_fvg_fill_level) ? active_bull_fvg_fill_level : last_bull_fvg_fill_level' not in source

    assert 'compute_bull_reclaim_state() =>' in source
    assert 'float _ob_h = na' in source
    assert 'if not na(touched_bull_ob_top) and not na(touched_bull_ob_bottom)' in source
    assert '_ob_h := math.max(touched_bull_ob_top - touched_bull_ob_bottom, syminfo.mintick)' in source
    assert 'float _fvg_h = na' in source
    assert 'if not na(touched_bull_fvg_top) and not na(touched_bull_fvg_bottom)' in source
    assert '_fvg_h := math.max(touched_bull_fvg_top - touched_bull_fvg_bottom, syminfo.mintick)' in source
    assert 'float _ob_sweep_lvl = na' in source
    assert 'if not na(_ob_h)' in source
    assert '_ob_sweep_lvl := touched_bull_ob_top - _ob_h * effective_ob_reclaim_min_penetration' in source
    assert 'float _fvg_sweep_lvl = na' in source
    assert 'if not na(_fvg_h)' in source
    assert '_fvg_sweep_lvl := touched_bull_fvg_top - _fvg_h * effective_fvg_reclaim_min_penetration' in source
    assert 'bool _ob_sweep = false' in source
    assert 'if touched_bull_ob_still_active and not na(_ob_sweep_lvl) and low <= _ob_sweep_lvl' in source
    assert '_ob_sweep := true' in source
    assert 'bool _fvg_sweep = false' in source
    assert 'if touched_bull_fvg_still_active and not na(_fvg_sweep_lvl) and low <= _fvg_sweep_lvl' in source
    assert '_fvg_sweep := true' in source
    assert 'bool _ob_strict = false' in source
    assert 'if _r_ob and (not use_strict_sequence_eff or ob_zone_touch_sequence_ok) and (not use_strict_sweep_for_zone_reclaim_eff or _ob_sweep)' in source
    assert '_ob_strict := true' in source
    assert 'bool _fvg_strict = false' in source
    assert 'if _r_fvg and (not use_strict_sequence_eff or fvg_zone_touch_sequence_ok) and (not use_strict_sweep_for_zone_reclaim_eff or _fvg_sweep)' in source
    assert '_fvg_strict := true' in source
    assert 'bool _int_strict = false' in source
    assert 'if _r_int and (not use_strict_sequence_eff or generic_zone_touch_sequence_ok)' in source
    assert '_int_strict := true' in source
    assert 'bool _sw_strict = false' in source
    assert 'if _r_sw and (not use_strict_sequence_eff or generic_zone_touch_sequence_ok)' in source
    assert '_sw_strict := true' in source
    assert 'bool _any = false' in source
    assert 'if _ob_strict or _fvg_strict or _int_strict or _sw_strict' in source
    assert '_any := true' in source
    assert 'bool _any_arm = false' in source
    assert 'if _ob_strict or _fvg_strict or ((_int_strict or _sw_strict) and long_zone_active)' in source
    assert '_any_arm := true' in source
    assert 'bool zone_recent = false' in source
    assert 'if not na(zone_since_bars) and zone_since_bars <= long_signal_window' in source
    assert 'zone_recent := true' in source
    assert 'bool reclaim_recent = false' in source
    assert 'if not na(reclaim_since_bars) and reclaim_since_bars <= long_signal_window' in source
    assert 'reclaim_recent := true' in source
    assert 'bool internal_choch_recent = false' in source
    assert 'if not na(internal_choch_since_bars) and internal_choch_since_bars <= long_signal_window' in source
    assert 'internal_choch_recent := true' in source
    assert 'bool internal_bos_recent = false' in source
    assert 'if not na(internal_bos_since_bars) and internal_bos_since_bars <= long_signal_window' in source
    assert 'internal_bos_recent := true' in source
    assert 'bool main_bos_recent = false' in source
    assert 'if not na(main_bos_since_bars) and main_bos_since_bars <= long_signal_window' in source
    assert 'main_bos_recent := true' in source
    assert 'bool bearish_abort_recent = false' in source
    assert 'if not na(bearish_abort_since_bars) and bearish_abort_since_bars <= long_signal_window' in source
    assert 'bearish_abort_recent := true' in source
    assert 'bool long_confirm_bearish_guard_ok = true' in source
    assert 'if use_strict_confirm_guard' in source
    assert 'long_confirm_bearish_guard_ok := not bearish_abort_signal and not bearish_abort_recent' in source
    assert 'float bull_ob_zone_height = not na(touched_bull_ob_top) and not na(touched_bull_ob_bottom) ? math.max(touched_bull_ob_top - touched_bull_ob_bottom, syminfo.mintick) : na' not in source
    assert 'float bull_fvg_zone_height = not na(touched_bull_fvg_top) and not na(touched_bull_fvg_bottom) ? math.max(touched_bull_fvg_top - touched_bull_fvg_bottom, syminfo.mintick) : na' not in source
    assert 'float bull_ob_required_sweep_level = not na(bull_ob_zone_height) ? touched_bull_ob_top - bull_ob_zone_height * effective_ob_reclaim_min_penetration : na' not in source
    assert 'float bull_fvg_required_sweep_level = not na(bull_fvg_zone_height) ? touched_bull_fvg_top - bull_fvg_zone_height * effective_fvg_reclaim_min_penetration : na' not in source
    assert 'bool bull_ob_real_sweep = touched_bull_ob_still_active and not na(bull_ob_required_sweep_level) and low <= bull_ob_required_sweep_level' not in source
    assert 'bool bull_fvg_real_sweep = touched_bull_fvg_still_active and not na(bull_fvg_required_sweep_level) and low <= bull_fvg_required_sweep_level' not in source
    assert 'bool bull_reclaim_ob_strict = bull_reclaim_ob and (not use_strict_sequence_eff or ob_zone_touch_sequence_ok) and (not use_strict_sweep_for_zone_reclaim_eff or bull_ob_real_sweep)' not in source
    assert 'bool bull_reclaim_fvg_strict = bull_reclaim_fvg and (not use_strict_sequence_eff or fvg_zone_touch_sequence_ok) and (not use_strict_sweep_for_zone_reclaim_eff or bull_fvg_real_sweep)' not in source
    assert 'bool bull_reclaim_internal_low_strict = bull_reclaim_internal_low and (not use_strict_sequence_eff or generic_zone_touch_sequence_ok)' not in source
    assert 'bool bull_reclaim_swing_low_strict = bull_reclaim_swing_low and (not use_strict_sequence_eff or generic_zone_touch_sequence_ok)' not in source
    assert 'bool bull_reclaim_any = bull_reclaim_ob_strict or bull_reclaim_fvg_strict or bull_reclaim_internal_low_strict or bull_reclaim_swing_low_strict' not in source
    assert 'bool bull_reclaim_any_for_arm = bull_reclaim_ob_strict or bull_reclaim_fvg_strict or ((bull_reclaim_internal_low_strict or bull_reclaim_swing_low_strict) and long_zone_active)' not in source
    assert 'bool zone_recent = not na(zone_since_bars) and zone_since_bars <= long_signal_window' not in source
    assert 'bool reclaim_recent = not na(reclaim_since_bars) and reclaim_since_bars <= long_signal_window' not in source
    assert 'bool internal_choch_recent = not na(internal_choch_since_bars) and internal_choch_since_bars <= long_signal_window' not in source
    assert 'bool internal_bos_recent = not na(internal_bos_since_bars) and internal_bos_since_bars <= long_signal_window' not in source
    assert 'bool main_bos_recent = not na(main_bos_since_bars) and main_bos_since_bars <= long_signal_window' not in source
    assert 'bool bearish_abort_recent = not na(bearish_abort_since_bars) and bearish_abort_since_bars <= long_signal_window' not in source
    assert 'bool long_confirm_bearish_guard_ok = not use_strict_confirm_guard or (not bearish_abort_signal and not bearish_abort_recent)' not in source
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
    assert 'compute_alert_text_suffixes() =>' in source
    assert "string _strict = ''" in source
    assert 'if use_strict_sequence_eff or use_strict_sweep_for_zone_reclaim_eff or use_strict_confirm_guard' in source
    assert "_strict := ' | strict=on'" in source
    assert "string long_strict_alert_suffix = (use_strict_sequence_eff or use_strict_sweep_for_zone_reclaim_eff or use_strict_confirm_guard) ? ' | strict=on' : ''" not in source
    assert "string _env = ' | env=' + long_environment_focus_display + ' | overhead=' + _overhead" in source
    assert "string _micro = ''" in source
    assert 'if use_microstructure_profiles' in source
    assert "_micro := ' | micro=' + micro_profile_text + ' | freshness=' + freshness_text + ' | source=' + source_state_text + ' | zone=' + zone_quality_text" in source
    assert "string long_micro_alert_suffix = use_microstructure_profiles ? ' | micro=' + micro_profile_text + ' | freshness=' + freshness_text + ' | source=' + source_state_text + ' | zone=' + zone_quality_text : ''" not in source
    assert "if dynamic_long_alert_mode == 'Priority'" in source
    assert 'compute_long_dynamic_alert_gates(bool enable_dynamic_alerts, bool long_invalidate_signal, bool alert_long_entry_strict_event, bool alert_long_entry_best_event, bool long_ready_signal, bool long_confirm_signal, bool alert_long_clean_event, bool alert_long_early_event, bool alert_long_armed_event, bool long_arm_signal, bool alert_long_watchlist_event) =>' in source
    assert 'emit_priority_long_dynamic_alerts(string seen_keys, bool already_sent, bool invalidated_active, bool strict_active, bool best_active, bool ready_active, bool confirmed_active, bool clean_active, bool early_active, bool armed_plus_active, bool armed_active, bool watchlist_active, string long_invalidated_alert_key, string long_invalidated_alert_name, string long_entry_strict_alert_key, string long_entry_strict_alert_name, string long_entry_best_alert_key, string long_entry_best_alert_name, string long_ready_alert_key, string long_ready_alert_name, string long_confirmed_alert_key, string long_confirmed_alert_name, string long_clean_alert_key, string long_clean_alert_name, string long_early_alert_key, string long_early_alert_name, string long_armed_plus_alert_key, string long_armed_plus_alert_name, string long_armed_alert_key, string long_armed_alert_name, string long_watchlist_alert_key, string long_watchlist_alert_name, string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix, string signal_mode_text, float ltf_bull_share_context, float ltf_volume_delta_context, bool ltf_price_only_context, string long_last_invalid_source, float long_last_invalid_level, float long_trigger_level, float long_invalidation_level, float long_entry_strict_alert_level, float long_entry_best_alert_level, float long_clean_alert_level, float long_early_alert_level, float long_watchlist_alert_level) =>' in source
    assert 'emit_linear_long_dynamic_alerts(string seen_keys, bool invalidated_active, bool strict_active, bool best_active, bool ready_active, bool clean_active, bool confirmed_active, bool early_active, bool armed_plus_active, bool armed_active, bool watchlist_active, string long_invalidated_alert_key, string long_invalidated_alert_name, string long_entry_strict_alert_key, string long_entry_strict_alert_name, string long_entry_best_alert_key, string long_entry_best_alert_name, string long_ready_alert_key, string long_ready_alert_name, string long_clean_alert_key, string long_clean_alert_name, string long_confirmed_alert_key, string long_confirmed_alert_name, string long_early_alert_key, string long_early_alert_name, string long_armed_plus_alert_key, string long_armed_plus_alert_name, string long_armed_alert_key, string long_armed_alert_name, string long_watchlist_alert_key, string long_watchlist_alert_name, string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix, string signal_mode_text, float ltf_bull_share_context, float ltf_volume_delta_context, bool ltf_price_only_context, string long_last_invalid_source, float long_last_invalid_level, float long_trigger_level, float long_invalidation_level, float long_entry_strict_alert_level, float long_entry_best_alert_level, float long_clean_alert_level, float long_early_alert_level, float long_watchlist_alert_level) =>' in source
    assert 'emit_long_dynamic_alerts(string seen_keys, bool already_sent, float ltf_bull_share_context, float ltf_volume_delta_context, bool ltf_price_only_context, string signal_mode_text) =>' in source
    assert '[priority_invalidated_alert_active, priority_strict_alert_active, priority_best_alert_active, priority_ready_alert_active, priority_confirmed_alert_active, priority_clean_alert_active, priority_early_alert_active, priority_armed_plus_alert_active, priority_armed_alert_active, priority_watchlist_alert_active] = compute_long_dynamic_alert_gates(enable_dynamic_alerts, long_invalidate_signal, alert_long_entry_strict_event, alert_long_entry_best_event, long_ready_signal, long_confirm_signal, alert_long_clean_event, alert_long_early_event, alert_long_armed_event, long_arm_signal, alert_long_watchlist_event)' in source
    assert '[dynamic_long_invalidated_alert_active, dynamic_long_strict_alert_active, dynamic_long_best_alert_active, dynamic_long_ready_alert_active, dynamic_long_confirmed_alert_active, dynamic_long_clean_alert_active, dynamic_long_early_alert_active, dynamic_long_armed_plus_alert_active, dynamic_long_armed_alert_active, dynamic_long_watchlist_alert_active] = compute_long_dynamic_alert_gates(enable_dynamic_alerts, long_invalidate_signal, alert_long_entry_strict_event, alert_long_entry_best_event, long_ready_signal, long_confirm_signal, alert_long_clean_event, alert_long_early_event, alert_long_armed_event, long_arm_signal, alert_long_watchlist_event)' in source
    assert 'next_seen_keys := emit_priority_long_dynamic_alerts(next_seen_keys, already_sent, priority_invalidated_alert_active, priority_strict_alert_active, priority_best_alert_active, priority_ready_alert_active, priority_confirmed_alert_active, priority_clean_alert_active, priority_early_alert_active, priority_armed_plus_alert_active, priority_armed_alert_active, priority_watchlist_alert_active, long_invalidated_alert_key, long_invalidated_alert_name, long_entry_strict_alert_key, long_entry_strict_alert_name, long_entry_best_alert_key, long_entry_best_alert_name, long_ready_alert_key, long_ready_alert_name, long_confirmed_alert_key, long_confirmed_alert_name, long_clean_alert_key, long_clean_alert_name, long_early_alert_key, long_early_alert_name, long_armed_plus_alert_key, long_armed_plus_alert_name, long_armed_alert_key, long_armed_alert_name, long_watchlist_alert_key, long_watchlist_alert_name, long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix, signal_mode_text, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, long_state.last_invalid_source, long_state.last_invalid_level, long_state.trigger, long_state.invalidation_level, long_entry_strict_alert_level, long_entry_best_alert_level, long_clean_alert_level, long_early_alert_level, long_watchlist_alert_level)' in source
    assert 'dynamic_alert_seen_keys := emit_bullish_dynamic_alerts(dynamic_alert_seen_keys, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'string next_long_dynamic_alert_seen_keys = emit_long_dynamic_alerts(dynamic_alert_seen_keys, long_dynamic_alert_sent, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' in source
    assert 'long_dynamic_alert_sent := long_dynamic_alert_sent or next_long_dynamic_alert_seen_keys != dynamic_alert_seen_keys' in source
    assert 'dynamic_alert_seen_keys := next_long_dynamic_alert_seen_keys' in source
    assert 'bool next_dynamic_alert_sent = already_sent' not in source
    assert '[next_seen_keys, next_dynamic_alert_sent]' not in source
    assert 'next_seen_keys := emit_linear_long_dynamic_alerts(next_seen_keys, dynamic_long_invalidated_alert_active, dynamic_long_strict_alert_active, dynamic_long_best_alert_active, dynamic_long_ready_alert_active, dynamic_long_clean_alert_active, dynamic_long_confirmed_alert_active, dynamic_long_early_alert_active, dynamic_long_armed_plus_alert_active, dynamic_long_armed_alert_active, dynamic_long_watchlist_alert_active, long_invalidated_alert_key, long_invalidated_alert_name, long_entry_strict_alert_key, long_entry_strict_alert_name, long_entry_best_alert_key, long_entry_best_alert_name, long_ready_alert_key, long_ready_alert_name, long_clean_alert_key, long_clean_alert_name, long_confirmed_alert_key, long_confirmed_alert_name, long_early_alert_key, long_early_alert_name, long_armed_plus_alert_key, long_armed_plus_alert_name, long_armed_alert_key, long_armed_alert_name, long_watchlist_alert_key, long_watchlist_alert_name, long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix, signal_mode_text, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, long_state.last_invalid_source, long_state.last_invalid_level, long_state.trigger, long_state.invalidation_level, long_entry_strict_alert_level, long_entry_best_alert_level, long_clean_alert_level, long_early_alert_level, long_watchlist_alert_level)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, true, long_invalidated_alert_key, long_invalidated_alert_name, compose_long_invalidated_alert_detail(long_last_invalid_source, long_micro_alert_suffix, long_score_detail_suffix), long_last_invalid_level, -1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_entry_strict_alert_key, long_entry_strict_alert_name, compose_long_entry_strict_alert_detail(long_micro_alert_suffix, long_score_detail_suffix), long_entry_strict_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_entry_best_alert_key, long_entry_best_alert_name, compose_long_entry_best_alert_detail(long_micro_alert_suffix, long_score_detail_suffix), long_entry_best_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_ready_alert_key, long_ready_alert_name, compose_long_ready_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_trigger_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_confirmed_alert_key, long_confirmed_alert_name, compose_long_confirmed_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_trigger_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_clean_alert_key, long_clean_alert_name, compose_long_clean_alert_detail(long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_clean_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_early_alert_key, long_early_alert_name, compose_long_early_alert_detail(long_micro_alert_suffix, long_score_detail_suffix), long_early_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_armed_plus_alert_key, long_armed_plus_alert_name, compose_long_armed_plus_alert_detail(long_micro_alert_suffix, long_score_detail_suffix), long_invalidation_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_armed_alert_key, long_armed_alert_name, compose_long_armed_alert_detail(long_setup_source_display, long_micro_alert_suffix, long_score_detail_suffix), long_invalidation_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, not already_sent, long_watchlist_alert_key, long_watchlist_alert_name, compose_long_watchlist_alert_detail(long_micro_alert_suffix, long_score_detail_suffix), long_watchlist_alert_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'string priority_seen_keys_confirmed = emit_dynamic_alert_if_allowed(' not in source
    assert 'bool invalidated_sent_now = false' not in source
    assert 'bool strict_sent_now = false' not in source
    assert 'bool best_sent_now = false' not in source
    assert 'bool ready_sent_now = false' not in source
    assert 'bool confirmed_sent_now = false' not in source
    assert 'bool clean_sent_now = false' not in source
    assert 'bool early_sent_now = false' not in source
    assert 'bool armed_plus_sent_now = false' not in source
    assert 'bool armed_sent_now = false' not in source
    assert 'bool watchlist_sent_now = false' not in source
    assert 'next_dynamic_alert_sent := watchlist_sent_now' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_strict != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_best != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_ready != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_confirmed != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_clean != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_early != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_armed_plus != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_armed != dynamic_alert_seen_keys' not in source
    assert 'long_dynamic_alert_sent := priority_seen_keys_watchlist != dynamic_alert_seen_keys' not in source
    assert 'if invalidated_active' in source
    assert 'else if enable_dynamic_alerts and alert_long_entry_strict_event' not in source
    assert 'else if enable_dynamic_alerts and alert_long_entry_best_event' not in source
    assert 'else if enable_dynamic_alerts and long_ready_signal' not in source
    assert 'else if enable_dynamic_alerts and long_confirm_signal' not in source
    assert 'else if enable_dynamic_alerts and alert_long_clean_event' not in source
    assert 'else if enable_dynamic_alerts and alert_long_early_event' not in source
    assert 'else if enable_dynamic_alerts and alert_long_armed_event' not in source
    assert 'else if enable_dynamic_alerts and long_arm_signal' not in source
    assert 'else if enable_dynamic_alerts and alert_long_watchlist_event' not in source
    assert 'next_seen_keys := emit_dynamic_alert_if_allowed(next_seen_keys, ready_active, long_ready_alert_key, long_ready_alert_name, compose_long_ready_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_trigger_level, 1, ltf_bull_share_context, ltf_volume_delta_context, ltf_price_only_context, signal_mode_text)' in source
    assert 'emit_priority_long_dynamic_alerts(string seen_keys, bool already_sent' in source
    assert 'ltf_price_only_context' in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and long_ready_signal, long_ready_alert_key, long_ready_alert_name, compose_long_ready_alert_detail(long_setup_source_display, long_strict_alert_suffix, long_environment_alert_suffix, long_micro_alert_suffix, long_score_detail_suffix), long_state.trigger, 1, ltf_bull_share, ltf_volume_delta, ltf_price_only, signal_mode_text)' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and long_invalidate_signal, long_invalidated_alert_key, long_invalidated_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and alert_long_entry_strict_event, long_entry_strict_alert_key, long_entry_strict_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and alert_long_entry_best_event, long_entry_best_alert_key, long_entry_best_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and alert_long_clean_event, long_clean_alert_key, long_clean_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and long_confirm_signal, long_confirmed_alert_key, long_confirmed_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and alert_long_early_event, long_early_alert_key, long_early_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and alert_long_armed_event, long_armed_plus_alert_key, long_armed_plus_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and long_arm_signal, long_armed_alert_key, long_armed_alert_name' not in source
    assert 'emit_dynamic_alert_if_allowed(dynamic_alert_seen_keys, enable_dynamic_alerts and alert_long_watchlist_event, long_watchlist_alert_key, long_watchlist_alert_name' not in source
    assert 'emit_priority_dynamic_alert_if_allowed(' not in source
    # Old detailed dashboard display patterns removed (Patch 5 compact dashboard rebuild)
    # prefer_level, quality_score_display, quality_env_display, etc. all replaced by compact dashboard
    assert 'dashboard_row(table tbl, int row, string name, string value, color bg, color txt) =>' in source
    assert 'dashboard_section_header(table tbl, int base_row, string title, color bg, color txt) =>' in source
    assert 'dashboard_section_row(table tbl, int base_row, int offset, string name, string value, color bg, color txt) =>' in source
    assert 'render_smc_dashboard_documented(table tbl) =>' not in source
    assert 'table tbl = _smc_dashboard' not in source
    assert 'int DB_ROW_TITLE = 0' not in source
    assert 'int DB_ROW_LIFECYCLE_HEADER = 1' not in source
    assert 'int DB_ROW_HARD_GATES_HEADER = 10' not in source
    assert 'int DB_ROW_QUALITY_HEADER = 19' not in source
    assert 'int DB_ROW_MODULES_HEADER = 28' not in source
    assert 'int DB_ROW_ENGINE_HEADER = 44' not in source
    assert 'int DB_LAST_ROW = 47' not in source
    assert "string DB_TITLE_LIFECYCLE = '[ Lifecycle ]'" not in source
    assert "string DB_TITLE_HARD_GATES = '[ Hard Gates ]'" not in source
    assert "string DB_TITLE_QUALITY = '[ Quality ]'" not in source
    assert "string DB_TITLE_MODULES = '[ Modules ]'" not in source
    assert "string DB_LABEL_TREND = 'Trend'" not in source
    assert "string DB_LABEL_READY_GATE = 'Ready Gate'" not in source
    assert "string DB_LABEL_LONG_DEBUG = 'Long Debug'" not in source
    assert "dashboard_header(_smc_dashboard, 0, 'SMC++ | ' + signal_mode_text + ' | ' + long_user_preset + ' | ' + performance_mode, _db_header_bg, _db_text)" in source
    assert 'if show_dashboard and barstate.islast' in source
    assert 'render_dashboard_lifecycle_section(_smc_dashboard, _db_header_bg, _db_text)' in source
    assert 'render_dashboard_hard_gates_section(_smc_dashboard, _db_header_bg, _db_text)' in source
    assert 'render_dashboard_quality_section(table tbl, color header_bg, color txt) =>' in source
    assert 'render_dashboard_modules_section(table tbl, color header_bg, color txt) =>' in source
    assert 'render_dashboard_engine_section(table tbl, color txt) =>' in source
    assert 'compute_dashboard_hard_gate_prep() =>' in source
    assert 'compute_dashboard_gate_quality_prep() =>' in source
    assert 'compute_dashboard_quality_filters_prep() =>' in source
    assert 'compute_dashboard_modules_structure_prep() =>' in source
    assert 'compute_dashboard_lifecycle_prep() =>' in source
    assert 'compute_dashboard_engine_debug_prep() =>' in source
    assert '[_mtf_bull_count, _db_trend_text, _db_trend_state, _db_htf_text, _db_htf_state, _db_setup_state, _db_exec_tier_text, _db_exec_tier_state, _db_setup_age, _db_setup_age_state, _db_pullback_state, _db_reclaim_state, _db_long_visual_state] = compute_dashboard_lifecycle_prep()' in source
    assert '[_db_ready_gate_state, _db_strict_gate_state, _db_debug_flags_state, _db_debug_flags_text, _db_long_debug_text, _db_long_debug_state] = compute_dashboard_engine_debug_prep()' in source
    assert 'render_dashboard_quality_section(_smc_dashboard, _db_header_bg, _db_text)' in source
    assert 'render_dashboard_modules_section(_smc_dashboard, _db_header_bg, _db_text)' in source
    assert 'render_dashboard_engine_section(_smc_dashboard, _db_text)' in source
    assert '[_db_session_text, _db_session_state, _db_market_text, _db_market_state, _db_vola_gate_text, _db_vola_gate_state, _db_micro_session_text, _db_micro_session_state, _db_micro_fresh_text, _db_micro_fresh_state, _db_volume_data_text, _db_volume_data_state] = compute_dashboard_hard_gate_prep()' in source
    assert '[_db_quality_env_text, _db_quality_env_state, _db_strict_quality_ok, _db_quality_strict_text, _db_quality_strict_state] = compute_dashboard_gate_quality_prep()' in source
    assert '[_db_close_strength_state, _db_ema_support_state, _db_adx_text, _db_adx_state, _db_relvol_text, _db_relvol_state, _db_vwap_text, _db_vwap_state, _db_context_quality_text, _db_context_quality_state, _db_quality_score_text, _db_quality_score_state, _db_quality_clean_text, _db_quality_clean_state] = compute_dashboard_quality_filters_prep()' in source
    assert '[_db_sd_confluence_text, _db_sd_confluence_state, _db_sd_direction_text, _db_sd_osc_text, _db_sd_osc_state, _db_vol_regime_text, _db_vol_regime_state, _db_vol_squeeze_text, _db_vol_squeeze_state, _db_vol_expand_text, _db_vol_expand_state, _db_stretch_state_text, _db_stretch_text, _db_stretch_state, _db_ddvi_text, _db_ddvi_state, _db_ltf_bias_text, _db_ltf_bias_state, _db_ltf_delta_text, _db_ltf_delta_state, _db_objects_text, _db_objects_state, _db_swing_trail_up_text, _db_swing_trail_dn_text, _db_swing_internal_up_text, _db_swing_internal_dn_text, _db_swing_text, _db_swing_state, _db_long_zones_text, _db_long_zones_state, _db_long_triggers_text, _db_long_triggers_state, _db_micro_profile_text, _db_micro_profile_state, _db_risk_plan_text, _db_risk_plan_state] = compute_dashboard_modules_structure_prep()' in source
    assert "dashboard_section_header(tbl, 19, '[ Quality ]', header_bg, txt)" in source
    assert "dashboard_section_row(tbl, 19, 1, 'Close Strength', close_state_text, status_bg(_db_close_strength_state), txt)" in source
    assert "dashboard_section_row(tbl, 19, 8, 'Quality Clean', _db_quality_clean_text, status_bg(_db_quality_clean_state), txt)" in source
    assert "dashboard_section_header(tbl, 28, '[ Modules ]', header_bg, txt)" in source
    assert "dashboard_section_row(tbl, 28, 1, 'SD Confluence', _db_sd_confluence_text, status_bg(_db_sd_confluence_state), txt)" in source
    assert "dashboard_section_row(tbl, 28, 8, 'LTF Bias', _db_ltf_bias_text, status_bg(_db_ltf_bias_state), txt)" in source
    assert "dashboard_section_row(tbl, 28, 15, 'Risk Plan', _db_risk_plan_text, status_bg(_db_risk_plan_state), txt)" in source
    assert 'render_dashboard_quality_section(_smc_dashboard, _db_header_bg, _db_text)' in source
    assert 'render_dashboard_modules_section(_smc_dashboard, _db_header_bg, _db_text)' in source
    assert 'render_dashboard_engine_section(_smc_dashboard, _db_text)' in source
    assert "string _db_session_text = not intraday_time_chart ? 'n/a' :" not in source
    assert "string _db_market_text = not use_index_gate and not use_sector_gate and not use_breadth_symbol_gate ? 'off' :" not in source
    assert "string _db_quality_strict_text = long_entry_strict_state ? 'Passed' :" not in source
    assert "_db_ltf_bias_text := not ltf_sampling_active ? 'n/a' : not ltf_price_ok ? 'n/a'" not in source
    assert "_db_ltf_delta_text := not ltf_sampling_active ? 'n/a' : ltf_price_only ? 'no-vol'" not in source
    assert "_db_ltf_bias_text := str.tostring(ltf_bull_share * 100.0, '#') + '%' + (ltf_price_only ? ' price-only' : '')" not in source
    assert "string _db_swing_text = 'S ' + (not na(trail_up) ? u.format_level(trail_up) : 'n/a') + ' / ' + (not na(trail_dn) ? u.format_level(trail_dn) : 'n/a') + ' | I ' + (not na(internal_trail_up) ? u.format_level(internal_trail_up) : 'n/a') + ' / ' + (not na(internal_trail_dn) ? u.format_level(internal_trail_dn) : 'n/a')" not in source
    assert "string _overhead = 'off'" in source
    assert 'if use_overhead_zone_filter_eff' in source
    assert "_overhead := 'clear'" in source
    assert 'if not na(headroom_to_overhead) and not na(planned_risk)' in source
    assert "_overhead := str.tostring(headroom_to_overhead / planned_risk, '#.##') + 'R'" in source
    assert "string _overhead = not use_overhead_zone_filter_eff ? 'off' : na(headroom_to_overhead) or na(planned_risk) ? 'clear' : str.tostring(headroom_to_overhead / planned_risk, '#.##') + 'R'" not in source
    assert 'int _db_long_visual_state = long_visual_state' in source
    assert "string _db_trend_text = db_trend_text(structure_display_trend)" in source
    assert 'int _db_trend_state = db_trend_state(structure_display_trend)' in source
    assert 'int _db_htf_state = -1' in source
    assert 'if _mtf_bull_count >= 2' in source
    assert '_db_htf_state := 5' in source
    assert 'else if _mtf_bull_count == 1' in source
    assert '_db_htf_state := 3' in source
    assert 'int _db_setup_state = 0' in source
    assert 'if long_entry_strict_state or long_entry_best_state' in source
    assert '_db_setup_state := 5' in source
    assert 'else if long_ready_state or long_state.confirmed' in source
    assert '_db_setup_state := 4' in source
    assert 'else if long_building_state' in source
    assert '_db_setup_state := 3' in source
    assert 'else if long_state.armed' in source
    assert '_db_setup_state := 2' in source
    assert 'else if long_zone_active' in source
    assert '_db_setup_state := 1' in source
    assert 'int _db_exec_tier_state = 0' in source
    assert '_db_exec_tier_state := 5' in source
    assert '_db_exec_tier_state := 4' in source
    assert '_db_exec_tier_state := 2' in source
    assert '_db_exec_tier_state := 1' in source
    assert 'int _db_setup_age_state = 0' in source
    assert 'if long_state.confirmed' in source
    assert '_db_setup_age_state := ready_is_fresh ? 5 : 2' in source
    assert 'else if long_state.armed' in source
    assert '_db_setup_age_state := confirm_is_fresh ? 4 : 2' in source
    assert 'int _db_pullback_state = 0' in source
    assert 'if in_bull_ob_zone and in_bull_fvg_zone' in source
    assert '_db_pullback_state := 5' in source
    assert 'else if in_bull_ob_zone or in_bull_fvg_zone' in source
    assert '_db_pullback_state := 4' in source
    assert 'int _db_reclaim_state = 0' in source
    assert 'if bull_reclaim_ob_strict or bull_reclaim_fvg_strict' in source
    assert '_db_reclaim_state := 5' in source
    assert 'else if bull_reclaim_swing_low_strict or bull_reclaim_internal_low_strict' in source
    assert '_db_reclaim_state := 4' in source
    assert 'else if reclaim_recent' in source
    assert '_db_reclaim_state := 2' in source
    assert 'int _db_session_state = -1' in source
    assert '_db_session_state := 0' in source
    assert 'else if session_structure_gate_ok' in source
    assert '_db_session_state := 5' in source
    assert 'int _db_market_state = -1' in source
    assert '_db_market_state := 0' in source
    assert 'else if market_symbols_missing and not block_on_missing_market_symbol' in source
    assert '_db_market_state := 2' in source
    assert 'else if market_regime_gate_ok' in source
    assert '_db_market_state := 5' in source
    assert "string _db_vola_gate_text = 'Blocked'" in source
    assert 'int _db_vola_gate_state = -1' in source
    assert 'if not use_vola_compression_gate' in source
    assert "_db_vola_gate_text := 'off'" in source
    assert 'else if vola_regime_gate_safe' in source
    assert "_db_vola_gate_text := 'Compression -> Expansion'" in source
    assert "_db_vola_gate_text := 'Compression context'" in source
    assert "_db_vola_gate_text := 'OK'" in source
    assert '_db_vola_gate_state := 0' in source
    assert '_db_vola_gate_state := 5' in source
    assert '_db_vola_gate_state := 3' in source
    assert 'int _db_htf_state = _mtf_bull_count >= 2 ? 5 : _mtf_bull_count == 1 ? 3 : -1' not in source
    assert 'int _db_setup_state = long_entry_strict_state ? 5 : long_entry_best_state ? 5 : long_ready_state ? 4 : long_state.confirmed ? 4 : long_building_state ? 3 : long_state.armed ? 2 : long_zone_active ? 1 : 0' not in source
    assert 'int _db_exec_tier_state = long_entry_strict_state ? 5 : long_entry_best_state ? 5 : long_ready_state ? 4 : long_state.confirmed ? 4 : long_state.armed ? 2 : long_zone_active ? 1 : 0' not in source
    assert 'int _db_setup_age_state = long_state.confirmed ? (ready_is_fresh ? 5 : 2) : long_state.armed ? (confirm_is_fresh ? 4 : 2) : 0' not in source
    assert 'int _db_pullback_state = in_bull_ob_zone and in_bull_fvg_zone ? 5 : in_bull_ob_zone or in_bull_fvg_zone ? 4 : 0' not in source
    assert 'int _db_reclaim_state = bull_reclaim_ob_strict or bull_reclaim_fvg_strict ? 5 : bull_reclaim_swing_low_strict or bull_reclaim_internal_low_strict ? 4 : reclaim_recent ? 2 : 0' not in source
    assert 'int _db_long_visual_state = long_visual_state == -1 ? -1 : long_visual_state' not in source
    assert 'int _db_session_state = not intraday_time_chart ? 0 : not use_trade_session_gate and not use_opening_range_gate ? 0 : session_structure_gate_ok ? 5 : -1' not in source
    assert 'int _db_market_state = not use_index_gate and not use_sector_gate and not use_breadth_symbol_gate ? 0 : market_symbols_missing and not block_on_missing_market_symbol ? 2 : market_regime_gate_ok ? 5 : -1' not in source
    assert 'int _db_vola_gate_state = not use_vola_compression_gate ? 0 : vola_regime_gate_safe ? (vola_expansion_now ? 5 : 3) : -1' not in source
    assert "_db_vola_gate_text := vola_expansion_now ? 'Compression -> Expansion' : vola_compression_recent ? 'Compression context' : 'OK'" not in source
    assert '_db_vola_gate_state := vola_expansion_now ? 5 : 3' not in source
    assert 'color _db_trend_bg = status_bg(_db_trend_state)' not in source
    assert 'color _db_htf_bg = status_bg(_db_htf_state)' not in source
    assert 'color _db_long_visual_bg = status_bg(_db_long_visual_state)' not in source
    assert 'int _db_ready_gate_state = db_ready_gate_state(long_ready_state, long_state.confirmed, lifecycle_ready_ok, setup_hard_gate_ok, trade_hard_gate_ok, environment_hard_gate_ok)' in source
    assert 'int _db_strict_gate_state = db_strict_gate_state(long_entry_strict_state, long_ready_state, strict_entry_ltf_ok, htf_alignment_ok, accel_strict_entry_gate_ok, sd_entry_strict_gate_ok, vol_entry_strict_context_ok_safe, stretch_entry_strict_context_ok, ddvi_entry_strict_ok_safe)' in source
    assert 'int _db_debug_flags_state = 0' in source
    assert 'string _db_debug_flags_text = compose_enabled_debug_modules_text(show_ob_debug, show_fvg_debug, show_long_engine_debug, long_engine_debug_mode_eff)' in source
    assert "string _db_long_debug_text = 'off'" in source
    assert 'int _db_long_debug_state = db_long_debug_state(show_long_engine_debug, long_visual_state, long_state.armed, long_state.confirmed, long_ready_state)' in source
    assert 'int _db_micro_session_state = -1' in source
    assert 'if not use_microstructure_profiles or not intraday_time_chart' in source
    assert '_db_micro_session_state := 0' in source
    assert 'else if micro_session_gate_ok' in source
    assert '_db_micro_session_state := 5' in source
    assert "string _db_micro_fresh_text = freshness_text + ' | ' + source_state_text" in source
    assert "if not use_microstructure_profiles" in source
    assert "_db_micro_fresh_text := 'off'" in source
    assert 'int _db_micro_fresh_state = -1' in source
    assert '_db_micro_fresh_state := 0' in source
    assert 'else if micro_freshness_gate_ok' in source
    assert '_db_micro_fresh_state := 5' in source
    assert 'int _db_volume_data_state = 5' in source
    assert '_db_volume_data_state := -1' in source
    assert '_db_volume_data_state := 2' in source
    assert 'int _db_quality_env_state = 2' in source
    assert '_db_quality_env_state := 5' in source
    assert '_db_quality_env_state := -1' in source
    assert 'bool _db_strict_quality_ok = false' in source
    assert 'if strict_entry_ltf_ok and htf_alignment_ok and accel_strict_entry_gate_ok and sd_entry_strict_gate_ok and vol_entry_strict_context_ok_safe and stretch_entry_strict_context_ok and ddvi_entry_strict_ok_safe' in source
    assert '_db_strict_quality_ok := true' in source
    assert 'int _db_quality_strict_state = -1' in source
    assert 'if long_entry_strict_state' in source
    assert '_db_quality_strict_state := 5' in source
    assert 'else if _db_strict_quality_ok' in source
    assert '_db_quality_strict_state := 4' in source
    assert 'int _db_micro_session_state = not use_microstructure_profiles or not intraday_time_chart ? 0 : micro_session_gate_ok ? 5 : -1' not in source
    assert "string _db_micro_fresh_text = not use_microstructure_profiles ? 'off' : freshness_text + ' | ' + source_state_text" not in source
    assert 'int _db_micro_fresh_state = not use_microstructure_profiles ? 0 : micro_freshness_gate_ok ? 5 : -1' not in source
    assert 'int _db_volume_data_state = not volume_current_bar_ok ? -1 : not volume_feed_quality_ok ? 2 : ltf_sampling_active and ltf_price_ok and not ltf_volume_ok ? 2 : 5' not in source
    assert 'int _db_quality_env_state = environment_hard_gate_ok ? 5 : not market_regime_gate_ok or not vola_regime_gate_safe ? -1 : 2' not in source
    assert 'bool _db_strict_quality_ok = strict_entry_ltf_ok and htf_alignment_ok and accel_strict_entry_gate_ok and sd_entry_strict_gate_ok and vol_entry_strict_context_ok_safe and stretch_entry_strict_context_ok and ddvi_entry_strict_ok_safe' not in source
    assert 'int _db_quality_strict_state = long_entry_strict_state ? 5 : _db_strict_quality_ok ? 4 : -1' not in source
    assert 'color _db_session_bg = status_bg(_db_session_state)' not in source
    assert 'int _db_close_strength_state = 0' in source
    assert 'int _db_ema_support_state = 0' in source
    assert "string _db_adx_text = 'off'" in source
    assert 'int _db_adx_state = 0' in source
    assert 'int _db_relvol_state = 0' in source
    assert 'int _db_vwap_state = 0' in source
    assert "string _db_context_quality_text = 'off'" in source
    assert 'int _db_context_quality_state = 0' in source
    assert 'int _db_quality_score_state = 2' in source
    assert "string _db_quality_clean_text = 'No'" in source
    assert 'int _db_quality_clean_state = 0' in source
    assert 'int _db_sd_confluence_state = 0' in source
    assert "string _db_sd_direction_text = 'flat'" in source
    assert 'int _db_sd_osc_state = 0' in source
    assert "string _db_vol_regime_text = 'off'" in source
    assert 'int _db_vol_regime_state = 0' in source
    assert 'int _db_vol_squeeze_state = 0' in source
    assert 'int _db_vol_expand_state = 0' in source
    assert "string _db_stretch_state_text = 'chasing'" in source
    assert 'int _db_stretch_state = 0' in source
    assert 'int _db_ddvi_state = 0' in source
    assert 'int _db_ltf_bias_state = 0' in source
    assert 'int _db_ltf_delta_state = 0' in source
    assert 'int _db_objects_state = 0' in source
    assert 'int _db_swing_state = 0' in source
    assert 'int _db_long_zones_state = 0' in source
    assert "string _db_long_triggers_text = 'n/a'" in source
    assert 'int _db_long_triggers_state = 0' in source
    assert 'int _db_micro_profile_state = 0' in source
    assert "string _db_risk_plan_text = 'n/a'" in source
    assert 'int _db_risk_plan_state = 0' in source
    assert 'color _db_quality_env_bg = status_bg(_db_quality_env_state)' not in source
    assert 'color _db_close_strength_bg = status_bg(_db_close_strength_state)' not in source
    assert 'color _db_ema_support_bg = status_bg(_db_ema_support_state)' not in source
    assert 'color _db_adx_bg = status_bg(_db_adx_state)' not in source
    assert 'color _db_sd_confluence_bg = status_bg(_db_sd_confluence_state)' not in source
    assert 'color _db_sd_osc_bg = status_bg(_db_sd_osc_state)' not in source
    assert 'color _db_vol_regime_bg = status_bg(_db_vol_regime_state)' not in source
    assert 'color _db_vol_squeeze_bg = status_bg(_db_vol_squeeze_state)' not in source
    assert 'color _db_vol_expand_bg = status_bg(_db_vol_expand_state)' not in source
    assert 'color _db_stretch_bg = status_bg(_db_stretch_state)' not in source
    assert 'color _db_ddvi_bg = status_bg(_db_ddvi_state)' not in source
    assert 'color _db_ltf_bias_bg = status_bg(_db_ltf_bias_state)' not in source
    assert 'color _db_ltf_delta_bg = status_bg(_db_ltf_delta_state)' not in source
    assert 'color _db_objects_bg = status_bg(_db_objects_state)' not in source
    assert 'color _db_swing_bg = status_bg(_db_swing_state)' not in source
    assert 'color _db_long_zones_bg = status_bg(_db_long_zones_state)' not in source
    assert 'color _db_long_triggers_bg = status_bg(_db_long_triggers_state)' not in source
    assert 'color _db_micro_profile_bg = status_bg(_db_micro_profile_state)' not in source
    assert 'color _db_risk_plan_bg = status_bg(_db_risk_plan_state)' not in source
    assert 'color _db_ready_gate_bg = status_bg(_db_ready_gate_state)' not in source
    assert 'color _db_debug_flags_bg = status_bg(_db_debug_flags_state)' not in source
    assert 'color _db_long_debug_bg = status_bg(_db_long_debug_state)' not in source
    assert "dashboard_section_row(tbl, 10, 7, 'Quality Env', _db_quality_env_text, status_bg(_db_quality_env_state), txt)" in source
    assert "dashboard_section_row(tbl, 19, 1, 'Close Strength', close_state_text, status_bg(_db_close_strength_state), txt)" in source
    assert "dashboard_section_row(tbl, 28, 1, 'SD Confluence', _db_sd_confluence_text, status_bg(_db_sd_confluence_state), txt)" in source
    assert "dashboard_section_row(tbl, 44, 2, 'Debug Flags', _db_debug_flags_text, status_bg(_db_debug_flags_state), txt)" in source
    assert "string trend_text = 'Neutral'" in source
    assert "string exec_tier_text = 'n/a'" in source
    assert "string setup_age_text = 'n/a'" in source
    assert 'int ready_gate_state = 2' in source
    assert 'int strict_gate_state = 2' in source
    assert 'int debug_state = 0' in source
    assert 'int _db_close_strength_state = not use_strong_close_filter ? 0 : bull_close_strong ? 5 : -1' not in source
    assert 'int _db_ema_support_state = not show_ema_support ? 0 : ema_support_ok ? 5 : -1' not in source
    assert "string _db_adx_text = not use_adx ? 'off' : not adx_data_ok ? 'n/a' : str.tostring(adx_value, '#.##') + ' | ' + adx_state_text" not in source
    assert 'int _db_adx_state = not use_adx or not adx_data_ok ? 0 : plus_di < minus_di ? -1 : adx_strong ? 5 : adx_value >= adx_trend_min ? 3 : 2' not in source
    assert 'int _db_relvol_state = not use_rel_volume ? 0 : not relvol_data_ok ? (allow_relvol_without_volume_data ? 2 : -1) : relvol_ok ? 5 : -1' not in source
    assert 'int _db_vwap_state = not use_vwap_filter ? 0 : not intraday_time_chart ? 0 : not vwap_session_active ? 0 : vwap_filter_ok ? 5 : -1' not in source
    assert "string _db_context_quality_text = not use_context_quality_score_eff ? 'off' : context_quality_gate_ok ? 'Supportive' : 'Weak'" not in source
    assert 'int _db_context_quality_state = not use_context_quality_score_eff ? 0 : context_quality_gate_ok ? 5 : 2' not in source
    assert 'int _db_quality_score_state = context_quality_gate_ok ? 5 : 2' not in source
    assert "string _db_quality_clean_text = long_quality_clean_tier ? 'Clean' : 'No'" not in source
    assert 'int _db_quality_clean_state = long_quality_clean_tier ? 5 : 0' not in source
    assert 'int _db_sd_confluence_state = not use_sd_confluence ? 0 : sd_support_both_recent ? 5 : sd_support_any_recent ? 4 : 0' not in source
    assert "string _db_sd_osc_text = str.tostring(sd_value, '#.##') + ' | ' + (sd_rising ? 'rising' : sd_falling ? 'falling' : 'flat')" not in source
    assert 'int _db_sd_osc_state = not use_sd_confluence or na(sd_value) ? 0 : sd_above_zero and sd_rising ? 5 : sd_rising ? 3 : sd_below_zero and sd_falling ? -1 : 0' not in source
    assert "string _db_vol_regime_text = not use_volatility_regime ? 'off' : vol_regime_trend_ok ? 'Bull stack' : 'Weak stack'" not in source
    assert 'int _db_vol_regime_state = not use_volatility_regime ? 0 : vol_regime_trend_ok ? 5 : -1' not in source
    assert 'int _db_vol_squeeze_state = not use_volatility_regime ? 0 : vol_squeeze_on ? 5 : vol_squeeze_release_recent ? 4 : vol_squeeze_recent ? 3 : 0' not in source
    assert 'int _db_vol_expand_state = not use_volatility_regime ? 0 : vol_momentum_expanding_long and vol_stack_spread_rising ? 5 : vol_momentum_expanding_long or vol_stack_spread_rising ? 3 : 0' not in source
    assert "string _db_stretch_text = str.tostring(distance_to_mean_z, '#.##') + 'z | ' + (in_lower_extreme ? 'lower extreme' : lower_extreme_recent ? 'recent extreme' : anti_chase_ok_entry_best ? 'anti-chase ok' : 'chasing')" not in source
    assert 'int _db_stretch_state = not use_stretch_context or na(distance_to_mean_z) ? 0 : (in_lower_extreme or lower_extreme_recent) and anti_chase_ok_entry_best ? 5 : anti_chase_ok_ready ? 3 : -1' not in source
    assert 'int _db_ddvi_state = not use_ddvi_context ? 0 : ddvi_bias_ok and ddvi_bull_divergence_any ? 5 : ddvi_bias_ok or ddvi_bull_divergence_any ? 4 : ddvi_lower_extreme_context ? 3 : 0' not in source
    assert 'int _db_ltf_bias_state = not show_dashboard_ltf_eff or not ltf_sampling_active or not ltf_price_ok ? 0 : ltf_bull_share >= ltf_bias_hint ? 5 : ltf_bull_share >= 0.50 ? 3 : -1' not in source
    assert 'int _db_ltf_delta_state = not show_dashboard_ltf_eff or not ltf_sampling_active ? 0 : ltf_price_only ? 2 : na(ltf_volume_delta) ? 0 : ltf_volume_delta >= 0 ? 5 : -1' not in source
    assert 'int _db_objects_state = array.size(ob_blocks_bull) > 0 and array.size(fvgs_bull) > 0 ? 5 : array.size(ob_blocks_bull) > 0 or array.size(fvgs_bull) > 0 ? 3 : 0' not in source
    assert 'int _db_swing_state = bullish_trend_safe ? 5 : bearish_trend_safe ? -1 : 0' not in source
    assert 'int _db_long_zones_state = long_zone_active ? 5 : 0' not in source
    assert "string _db_long_triggers_text = long_plan_active ? 'Trig ' + u.format_level(long_state.trigger) + ' | Inv ' + u.format_level(long_state.invalidation_level) : 'n/a'" not in source
    assert 'int _db_long_triggers_state = long_plan_active ? 5 : 0' not in source
    assert 'int _db_micro_profile_state = not use_microstructure_profiles ? 0 : str.length(micro_modifier_text) > 0 or micro_profile_text != \'Default\' ? 5 : 3' not in source
    assert "string _db_risk_plan_text = long_plan_active ? 'Entry ' + u.format_level(long_state.trigger) + ' | Stop ' + u.format_level(long_stop_level) + ' | T1 ' + u.format_level(long_target_1) + ' | T2 ' + u.format_level(long_target_2) : 'n/a'" not in source
    assert 'int _db_risk_plan_state = long_plan_active ? 5 : 0' not in source
    assert 'int _db_debug_flags_state = show_ob_debug or show_fvg_debug or show_long_engine_debug ? 5 : 0' not in source
    assert "string _db_long_debug_text = show_long_engine_debug ? long_debug_summary_text : 'off'" not in source
    assert "dir > 0 ? 'Bullish' : dir < 0 ? 'Bearish' : 'Neutral'" not in source
    assert "long_entry_strict_state ? 'Strict' : long_entry_best_state ? 'Best' : long_ready_state ? 'Ready' : long_state.confirmed ? 'Confirmed' : long_state.armed ? 'Armed' : long_zone_active ? 'Watchlist' : 'n/a'" not in source
    assert "long_state.confirmed and not na(long_state.confirm_bar_index) ? 'confirmed ' + str.tostring(long_confirm_age) : long_state.armed and not na(long_state.arm_bar_index) ? 'armed ' + str.tostring(long_setup_age) : 'n/a'" not in source
    assert 'int long_setup_age = 0' in source
    assert 'if long_state.armed and not na(long_state.arm_bar_index)' in source
    assert 'long_setup_age := bar_index - long_state.arm_bar_index' in source
    assert 'int long_confirm_age = 0' in source
    assert 'if long_state.confirmed and not na(long_state.confirm_bar_index)' in source
    assert 'long_confirm_age := bar_index - long_state.confirm_bar_index' in source
    assert 'int long_setup_age = long_state.armed and not na(long_state.arm_bar_index) ? bar_index - long_state.arm_bar_index : 0' not in source
    assert 'int long_confirm_age = long_state.confirmed and not na(long_state.confirm_bar_index) ? bar_index - long_state.confirm_bar_index : 0' not in source
    assert 'long_ready_state ? 5 : not long_setup_confirmed ? 2 : not lifecycle_ready_ok ? 2 : not setup_hard_gate_ok or not trade_hard_gate_ok or not environment_hard_gate_ok ? -1 : 2' not in source
    assert 'long_entry_strict_state ? 5 : not long_ready_state ? 2 : not strict_entry_ltf_ok or not htf_alignment_ok or not accel_strict_entry_gate_ok or not sd_entry_strict_gate_ok or not vol_entry_strict_context_ok_safe or not stretch_entry_strict_context_ok or not ddvi_entry_strict_ok_safe ? -1 : 2' not in source
    assert "not show_long_engine_debug ? 0 : long_visual_state == -1 ? -1 : long_setup_armed or long_setup_confirmed or long_ready_state ? 5 : 2" not in source
    assert "dashboard_section_header(tbl, 1, '[ Lifecycle ]', header_bg, txt)" in source
    assert "dashboard_section_row(tbl, 1, 1, 'Trend', _db_trend_text, status_bg(_db_trend_state), txt)" in source
    assert "dashboard_section_row(tbl, 1, 7, 'Long Visual', long_visual_text, status_bg(_db_long_visual_state), txt)" in source
    assert "dashboard_section_row(tbl, 10, 1, 'Session', _db_session_text, status_bg(_db_session_state), txt)" in source
    assert "dashboard_section_row(tbl, 10, 7, 'Quality Env', _db_quality_env_text, status_bg(_db_quality_env_state), txt)" in source
    assert "dashboard_section_row(tbl, 19, 1, 'Close Strength', close_state_text, status_bg(_db_close_strength_state), txt)" in source
    assert "dashboard_section_row(tbl, 19, 2, 'EMA Support', ema_state_text, status_bg(_db_ema_support_state), txt)" in source
    assert "dashboard_section_row(tbl, 19, 3, 'ADX', _db_adx_text, status_bg(_db_adx_state), txt)" in source
    assert "dashboard_section_row(tbl, 28, 1, 'SD Confluence', _db_sd_confluence_text, status_bg(_db_sd_confluence_state), txt)" in source
    assert "dashboard_section_row(tbl, 28, 5, 'Vol Expand', _db_vol_expand_text, status_bg(_db_vol_expand_state), txt)" in source
    assert "dashboard_section_row(tbl, 28, 15, 'Risk Plan', _db_risk_plan_text, status_bg(_db_risk_plan_state), txt)" in source
    assert "dashboard_section_row(tbl, 44, 0, 'Ready Gate', long_ready_blocker_text, status_bg(_db_ready_gate_state), txt)" in source
    assert "dashboard_section_row(tbl, 44, 2, 'Debug Flags', _db_debug_flags_text, status_bg(_db_debug_flags_state), txt)" in source
    assert "dashboard_section_row(tbl, 44, 3, 'Long Debug', _db_long_debug_text, status_bg(_db_long_debug_state), txt)" in source
    assert "dashboard_row(_smc_dashboard, 8, 'Long Visual', long_visual_text, status_bg(long_visual_state == -1 ? -1 : long_visual_state), _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, 20, 'Close Strength', close_state_text, status_bg(not use_strong_close_filter ? 0 : bull_close_strong ? 5 : -1), _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, 21, 'EMA Support', ema_state_text, status_bg(not show_ema_support ? 0 : ema_support_ok ? 5 : -1), _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, DB_ROW_HARD_GATES_HEADER + 1, DB_LABEL_SESSION, _db_session_text, status_bg(_db_session_state), _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, DB_ROW_QUALITY_HEADER + 3, DB_LABEL_ADX, _db_adx_text, status_bg(_db_adx_state), _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, DB_ROW_MODULES_HEADER + 15, DB_LABEL_RISK_PLAN, _db_risk_plan_text, status_bg(_db_risk_plan_state), _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, DB_ROW_LIFECYCLE_HEADER + 1, DB_LABEL_TREND, _db_trend_text, _db_trend_bg, _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, DB_ROW_ENGINE_HEADER + 2, DB_LABEL_DEBUG_FLAGS, _db_debug_flags_text, _db_debug_flags_bg, _db_text)" not in source
    assert "dashboard_header(_smc_dashboard, DB_ROW_LIFECYCLE_HEADER, DB_TITLE_LIFECYCLE, _db_header_bg, _db_text)" not in source
    assert "dashboard_header(_smc_dashboard, DB_ROW_LIFECYCLE_HEADER, '[ Lifecycle ]', _db_header_bg, _db_text)" not in source
    assert "dashboard_row(_smc_dashboard, DB_ROW_LIFECYCLE_HEADER + 1, DB_LABEL_TREND, db_trend_text(structure_display_trend), status_bg(db_trend_state(structure_display_trend)), _db_text)" not in source
    assert "string _score = ' | ctx=' + str.tostring(context_quality_score) + '/' + str.tostring(effective_min_context_quality_score)" in source
    assert "format_level(not na(active_bull_ob_break_level) ? active_bull_ob_break_level : last_bull_ob_break_level)" not in source
    assert "format_level(not na(active_bull_fvg_fill_level) ? active_bull_fvg_fill_level : last_bull_fvg_fill_level)" not in source
    assert "string quality_score_display = not quality_axis_active ? 'n/a' : str.format('Ctx {0}/{1}\\nMin {2}\\n{3}', context_quality_score, effective_context_quality_max_score, effective_min_context_quality_score, quality_score_ok ? 'OK' : 'Blocked')" not in source
    assert "string quality_env_display = not quality_axis_active ? 'n/a' : str.format('Trade {0}\\nEnv {1}', trade_hard_gate_ok ? 'OK' : not session_structure_gate_ok ? 'Session Block' : not microstructure_entry_gate_ok ? 'Micro Block' : not overhead_zone_ok ? 'Headroom Block' : 'Trade Blocked', environment_hard_gate_ok ? 'OK' : long_environment_focus_display)" not in source
    assert "string quality_strict_display = not quality_axis_active ? 'n/a' : str.format('{0}\\nZone {1}\\nSweep {2}\\nGuard {3}', quality_strict_ok ? 'Strict OK' : strict_flow_focus_display, strict_sequence_display, strict_sweep_display, strict_guard_display)" not in source
    assert "string long_strict_alert_suffix = strict_flow_active ? str.format(' | strict={0}', strict_flow_focus_display) : ''" not in source
    assert "string long_environment_alert_suffix = long_gate_features_active ? str.format(' | env={0}', long_environment_focus_display) : ''" not in source
    assert "string long_micro_alert_suffix = use_microstructure_profiles ? str.format(' | micro={0}', microstructure_focus_display) : ''" not in source
    assert "string overhead_text = not use_overhead_zone_filter_eff ? 'off' : na(headroom_to_overhead) or na(planned_risk) ? 'clear' : str.format('{0}R', headroom_to_overhead / planned_risk)" not in source
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
    assert 'alert_long_watchlist = false' in source
    assert 'if bullish_trend_safe and long_zone_active_safe and vol_watchlist_context_ok_safe and stretch_watchlist_context_ok_safe and ddvi_watchlist_ok_safe' in source
    assert 'alert_long_watchlist := true' in source
    assert 'alert_long_armed = false' in source
    assert 'if bullish_trend_safe and zone_recent and reclaim_recent and long_setup_in_progress' in source
    assert 'alert_long_armed := true' in source
    assert 'alert_long_early = false' in source
    assert 'if bullish_trend_safe and long_setup_in_progress and zone_recent and reclaim_recent and long_internal_structure_ok and bull_close_strong and ema_support_ok and accel_early_gate_ok and sd_early_gate_ok' in source
    assert 'alert_long_early := true' in source
    assert 'alert_long_clean = long_quality_clean_tier' in source
    assert 'alert_long_entry_best = long_entry_best_state' in source
    assert 'alert_long_entry_strict = false' in source
    assert 'if long_entry_strict_state' in source
    assert 'alert_long_entry_strict := true' in source
    assert 'alert_long_fail = false' in source
    assert 'if long_invalidate_signal' in source
    assert 'alert_long_fail := true' in source
    assert 'bool alert_long_early_event = false' in source
    assert 'if alert_long_early and long_state.setup_serial > 0 and last_long_early_alert_serial != long_state.setup_serial' in source
    assert 'alert_long_early_event := true' in source
    assert 'if alert_long_early_event' in source
    assert 'last_long_early_alert_serial := long_state.setup_serial' in source
    assert 'bool suppress_armed_plus_event = false' in source
    assert 'if alert_long_early' in source
    assert 'if long_arm_signal' in source
    assert 'suppress_armed_plus_event := true' in source
    assert 'bool alert_long_armed_event = false' in source
    assert 'if alert_long_armed and not suppress_armed_plus_event and long_state.setup_serial > 0 and last_long_armed_alert_serial != long_state.setup_serial' in source
    assert 'alert_long_armed_event := true' in source
    assert 'if alert_long_armed_event' in source
    assert 'last_long_armed_alert_serial := long_state.setup_serial' in source
    assert 'bool alert_long_clean_event = false' in source
    assert 'if alert_long_clean and long_state.setup_serial > 0 and last_long_clean_alert_serial != long_state.setup_serial' in source
    assert 'alert_long_clean_event := true' in source
    assert 'if alert_long_clean_event' in source
    assert 'last_long_clean_alert_serial := long_state.setup_serial' in source
    assert 'bool alert_long_entry_best_event = false' in source
    assert 'if alert_long_entry_best and long_state.setup_serial > 0 and last_long_entry_best_alert_serial != long_state.setup_serial' in source
    assert 'alert_long_entry_best_event := true' in source
    assert 'if alert_long_entry_best_event' in source
    assert 'last_long_entry_best_alert_serial := long_state.setup_serial' in source
    assert 'bool alert_long_entry_strict_event = false' in source
    assert 'if alert_long_entry_strict and long_state.setup_serial > 0 and last_long_entry_strict_alert_serial != long_state.setup_serial' in source
    assert 'alert_long_entry_strict_event := true' in source
    assert 'if alert_long_entry_strict_event' in source
    assert 'last_long_entry_strict_alert_serial := long_state.setup_serial' in source
    assert 'bool alert_long_early_event = alert_long_early and long_state.setup_serial > 0 and last_long_early_alert_serial != long_state.setup_serial' not in source
    assert 'bool suppress_armed_plus_event = alert_long_early or long_arm_signal' not in source
    assert 'if alert_long_early or long_arm_signal' not in source
    assert 'bool alert_long_armed_event = alert_long_armed and not suppress_armed_plus_event and long_state.setup_serial > 0 and last_long_armed_alert_serial != long_state.setup_serial' not in source
    assert 'bool alert_long_clean_event = alert_long_clean and long_state.setup_serial > 0 and last_long_clean_alert_serial != long_state.setup_serial' not in source
    assert 'bool alert_long_entry_best_event = alert_long_entry_best and long_state.setup_serial > 0 and last_long_entry_best_alert_serial != long_state.setup_serial' not in source
    assert 'bool alert_long_entry_strict_event = alert_long_entry_strict and long_state.setup_serial > 0 and last_long_entry_strict_alert_serial != long_state.setup_serial' not in source
    assert 'last_long_early_alert_serial := alert_long_early_event ? long_state.setup_serial : last_long_early_alert_serial' not in source
    assert 'last_long_armed_alert_serial := alert_long_armed_event ? long_state.setup_serial : last_long_armed_alert_serial' not in source
    assert 'last_long_clean_alert_serial := alert_long_clean_event ? long_state.setup_serial : last_long_clean_alert_serial' not in source
    assert 'last_long_entry_best_alert_serial := alert_long_entry_best_event ? long_state.setup_serial : last_long_entry_best_alert_serial' not in source
    assert 'last_long_entry_strict_alert_serial := alert_long_entry_strict_event ? long_state.setup_serial : last_long_entry_strict_alert_serial' not in source
    assert '[next_alert_long_early_event, next_last_long_early_alert_serial] = next_serial_event(alert_long_early, long_state.setup_serial, last_long_early_alert_serial)' not in source
    assert '[next_alert_long_armed_event, next_last_long_armed_alert_serial] = next_serial_event(alert_long_armed and not suppress_armed_plus_event, long_state.setup_serial, last_long_armed_alert_serial)' not in source
    assert '[next_alert_long_clean_event, next_last_long_clean_alert_serial] = next_serial_event(alert_long_clean, long_state.setup_serial, last_long_clean_alert_serial)' not in source
    assert '[next_alert_long_entry_best_event, next_last_long_entry_best_alert_serial] = next_serial_event(alert_long_entry_best, long_state.setup_serial, last_long_entry_best_alert_serial)' not in source
    assert '[next_alert_long_entry_strict_event, next_last_long_entry_strict_alert_serial] = next_serial_event(alert_long_entry_strict, long_state.setup_serial, last_long_entry_strict_alert_serial)' not in source
    assert 'alert_long_watchlist = bullish_trend_safe and long_zone_active_safe and vol_watchlist_context_ok_safe and stretch_watchlist_context_ok_safe and ddvi_watchlist_ok_safe' not in source
    assert 'alert_long_armed = bullish_trend_safe and zone_recent and reclaim_recent and long_setup_in_progress' not in source
    assert 'alert_long_early = bullish_trend_safe and long_setup_in_progress and zone_recent and reclaim_recent and long_internal_structure_ok and bull_close_strong and ema_support_ok and accel_early_gate_ok and sd_early_gate_ok' not in source
    assert 'alert_long_entry_strict = long_entry_strict_state' not in source
    assert 'alert_long_fail = long_invalidate_signal' not in source


def test_intrabar_ready_and_watchlist_events_are_debounced_and_latched() -> None:
    source = _read_smc_source()

    assert 'bool can_draw_reclaim_marker = false' in source
    assert 'if na(last_reclaim_marker_bar) or effective_reclaim_marker_gap <= 0 or bar_index - last_reclaim_marker_bar >= effective_reclaim_marker_gap' in source
    assert 'can_draw_reclaim_marker := true' in source
    assert 'bool can_draw_long_state_marker = false' in source
    assert 'if na(last_long_state_marker_bar) or effective_confirm_marker_gap <= 0 or bar_index - last_long_state_marker_bar >= effective_confirm_marker_gap' in source
    assert 'can_draw_long_state_marker := true' in source
    assert 'bool can_draw_long_ready_marker = false' in source
    assert 'if na(last_long_ready_marker_bar) or effective_ready_marker_gap <= 0 or bar_index - last_long_ready_marker_bar >= effective_ready_marker_gap' in source
    assert 'can_draw_long_ready_marker := true' in source
    assert 'bool can_draw_reclaim_marker = na(last_reclaim_marker_bar) or effective_reclaim_marker_gap <= 0 or bar_index - last_reclaim_marker_bar >= effective_reclaim_marker_gap' not in source
    assert 'bool can_draw_long_state_marker = na(last_long_state_marker_bar) or effective_confirm_marker_gap <= 0 or bar_index - last_long_state_marker_bar >= effective_confirm_marker_gap' not in source
    assert 'bool can_draw_long_ready_marker = na(last_long_ready_marker_bar) or effective_ready_marker_gap <= 0 or bar_index - last_long_ready_marker_bar >= effective_ready_marker_gap' not in source
    assert 'varip bool long_ready_fired_this_bar = false' in source
    assert 'long_ready_state_rt_prev := 0' in source
    assert 'if long_ready_state[1]' in source
    assert 'if long_ready_state' in source
    assert 'long_ready_state_rt_prev := long_ready_state[1] ? 1 : 0' not in source
    assert 'long_ready_state_rt_prev := long_ready_state ? 1 : 0' not in source
    assert 'bool long_ready_signal = false' in source
    assert 'if long_ready_state and long_ready_state_rt_prev == 0 and not long_ready_fired_this_bar' in source
    assert 'long_ready_signal := true' in source
    assert 'bool long_ready_signal = long_ready_state and long_ready_state_rt_prev == 0 and not long_ready_fired_this_bar' not in source
    assert 'if long_ready_signal' in source
    assert 'long_ready_fired_this_bar := true' in source
    assert 'varip bool long_watchlist_fired_this_bar = false' in source
    assert 'long_watchlist_rt_prev_active := 0' in source
    assert 'if alert_long_watchlist[1]' in source
    assert 'if alert_long_watchlist' in source
    assert 'long_watchlist_rt_prev_active := alert_long_watchlist[1] ? 1 : 0' not in source
    assert 'long_watchlist_rt_prev_active := alert_long_watchlist ? 1 : 0' not in source
    assert 'bool long_watchlist_started = false' in source
    assert 'if alert_long_watchlist and long_watchlist_rt_prev_active == 0 and not long_watchlist_fired_this_bar' in source
    assert 'long_watchlist_started := true' in source
    assert 'bool long_watchlist_started = alert_long_watchlist and long_watchlist_rt_prev_active == 0 and not long_watchlist_fired_this_bar' not in source
    assert 'long_watchlist_fired_this_bar := true' in source
    assert 'bool alert_long_watchlist_event = false' in source
    assert 'if long_watchlist_started and long_watchlist_serial > 0' in source
    assert 'alert_long_watchlist_event := true' in source
    assert 'bool alert_long_watchlist_event = long_watchlist_started and long_watchlist_serial > 0' not in source
    assert 'bool bull_ob_broken_event = false' in source
    assert 'if array.size(ob_broken_new_bull) > 0' in source
    assert 'bull_ob_broken_event := true' in source
    assert 'bool bull_ob_broken_event = array.size(ob_broken_new_bull) > 0' not in source
    assert 'varip bool alert_long_watchlist_event_latched = false' in source
    assert 'alert_long_watchlist_event_latched := update_latched_flag(alert_long_watchlist_event_latched, alert_long_watchlist_event, live_exec, barstate.isconfirmed)' in source
    assert 'alert_long_watchlist_event_latched := false' in source


def test_pre_arm_ob_selection_prefers_touch_anchor_then_recency_then_quality() -> None:
    source = _read_smc_source()

    assert 'scan_active_bull_ob() =>' in source
    assert 'bool _c_touch = not na(touched_bull_ob_id) and _c_id == touched_bull_ob_id' in source
    assert 'zone_candidate_preferred(bool candidate_touch_anchor, int candidate_recency, float candidate_quality, float candidate_overlap, int candidate_id, bool best_touch_anchor, int best_recency, float best_quality, float best_overlap, int best_id) =>' in source
    assert '_prefer := zone_candidate_preferred(_c_touch, _c_recency, _c_quality, _c_overlap, _c_id, _best_touch, _best_recency, _best_quality, _best_overlap, _best_id)' in source


def test_pre_arm_fvg_and_combined_active_zone_use_deterministic_priority() -> None:
    source = _read_smc_source()

    assert 'scan_active_bull_fvg() =>' in source
    assert 'bool _c_touch = not na(touched_bull_fvg_id) and _c_id == touched_bull_fvg_id' in source
    assert '_prefer := zone_candidate_preferred(_c_touch, _c_recency, _c_quality, _c_overlap, _c_id, _best_touch, _best_recency, _best_quality, _best_overlap, _best_id)' in source
    assert 'prefer_primary_zone(bool primary_touch_anchor, int primary_recency, float primary_quality, float primary_overlap, int primary_id, bool secondary_touch_anchor, int secondary_recency, float secondary_quality, float secondary_overlap, int secondary_id) =>' in source
    assert 'bool prefer_active_ob_zone = not na(active_bull_ob_id)' in source
    assert 'prefer_active_ob_zone := prefer_primary_zone(active_bull_ob_touch_anchor, active_bull_ob_recency, active_bull_ob_quality, best_bull_ob_overlap, active_bull_ob_id, active_bull_fvg_touch_anchor, active_bull_fvg_recency, active_bull_fvg_quality, best_bull_fvg_overlap, active_bull_fvg_id)' in source
    assert 'int active_long_zone_id = na' in source
    assert 'if not na(active_bull_ob_id) and (na(active_bull_fvg_id) or prefer_active_ob_zone)' in source
    assert 'active_long_zone_id := active_bull_ob_id' in source
    assert 'else if not na(active_bull_fvg_id)' in source
    assert 'active_long_zone_id := -active_bull_fvg_id' in source
    assert 'int active_long_zone_id = not na(active_bull_ob_id) and (na(active_bull_fvg_id) or prefer_active_ob_zone) ? active_bull_ob_id : not na(active_bull_fvg_id) ? -active_bull_fvg_id : na' not in source


def test_bear_pre_arm_selection_uses_same_deterministic_priority_without_touch_anchor() -> None:
    """Bear active-closest scanning removed (Patch 4), but blocker scanning must stay."""
    source = _read_smc_source()

    # Blocker scanning still present (long-only overhead zone filter) inside compute_overhead_context()
    assert '_bear_ob_lvl' in source
    assert '_bear_fvg_lvl' in source
    # Active-closest scanning loops removed
    assert 'int best_bear_ob_idx = na' not in source
    assert 'int best_bear_fvg_idx = na' not in source


def test_touched_bull_zone_lookups_use_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'OrderBlock touched_bull_ob_block = na' in source
    assert 'if touched_bull_ob_still_active' in source
    assert 'touched_bull_ob_block := get_by_id(ob_blocks_bull, touched_bull_ob_id)' in source
    assert 'FVG touched_bull_fvg_block = na' in source
    assert 'if touched_bull_fvg_still_active' in source
    assert 'touched_bull_fvg_block := get_by_id(fvgs_bull, touched_bull_fvg_id)' in source
    assert 'OrderBlock touched_bull_ob_block = touched_bull_ob_still_active ? get_by_id(ob_blocks_bull, touched_bull_ob_id) : na' not in source
    assert 'FVG touched_bull_fvg_block = touched_bull_fvg_still_active ? get_by_id(fvgs_bull, touched_bull_fvg_id) : na' not in source


def test_touched_bull_zone_quality_uses_explicit_block_logic() -> None:
    source = _read_smc_source()

    assert 'float touched_bull_ob_quality = 0.0' in source
    assert 'if not na(touched_bull_ob_block)' in source
    assert 'touched_bull_ob_quality := ob_quality_score(touched_bull_ob_block)' in source
    assert 'float touched_bull_fvg_quality = 0.0' in source
    assert 'if not na(touched_bull_fvg_block)' in source
    assert 'touched_bull_fvg_quality := fvg_quality_score(touched_bull_fvg_block, fvg_size_threshold)' in source
    assert 'float touched_bull_ob_quality = not na(touched_bull_ob_block) ? ob_quality_score(touched_bull_ob_block) : 0.0' not in source
    assert 'float touched_bull_fvg_quality = not na(touched_bull_fvg_block) ? fvg_quality_score(touched_bull_fvg_block, fvg_size_threshold) : 0.0' not in source


def test_locked_source_touch_count_selection_is_extracted() -> None:
    source = _read_smc_source()

    assert 'select_locked_source_touch_count(bool source_upgrade_now, bool prefer_ob_upgrade_now, int ob_candidate_id, int active_ob_touch_id, int active_ob_touch_count, int touched_ob_touch_count, int fvg_candidate_id, int active_fvg_touch_id, int active_fvg_touch_count, int touched_fvg_touch_count, int locked_source_touch_count) =>' in source
    assert 'int long_locked_source_touch_count_effective = select_locked_source_touch_count(long_source_upgrade_now, prefer_ob_upgrade, touched_bull_ob_id, active_ob_touch_id, active_ob_touch_count, touched_bull_ob_touch_count, touched_bull_fvg_id, active_fvg_touch_id, active_fvg_touch_count, touched_bull_fvg_touch_count, long_state.locked_source_touch_count)' in source


def test_scan_helpers_no_global_mutations_and_no_stale_scan_start_refs() -> None:
    """Guard against Pine v6 'Cannot modify global variable' and undeclared identifier regressions."""
    source = _read_smc_source()

    # scan helpers must NOT modify global var variables (Pine v6 forbids this)
    assert 'touched_bull_ob_top := _top' not in source or 'scan_active_bull_ob' not in source.split('touched_bull_ob_top := _top')[0].split('\n')[-5]
    # Simpler: the touched_* assignments must appear in main body, not inside the scan function
    ob_fn_body = source.split('scan_active_bull_ob() =>')[1].split('\n\n')[0]
    assert 'touched_bull_ob_top :=' not in ob_fn_body
    assert 'touched_bull_ob_bottom :=' not in ob_fn_body
    assert 'touched_bull_ob_id :=' not in ob_fn_body
    assert 'touched_bull_ob_bar_index :=' not in ob_fn_body

    fvg_fn_body = source.split('scan_active_bull_fvg() =>')[1].split('\n\n')[0]
    assert 'touched_bull_fvg_top :=' not in fvg_fn_body
    assert 'touched_bull_fvg_bottom :=' not in fvg_fn_body
    assert 'touched_bull_fvg_id :=' not in fvg_fn_body
    assert 'touched_bull_fvg_bar_index :=' not in fvg_fn_body

    # The touched_* updates must still happen in main body after the scan call
    assert 'touched_bull_ob_top := active_bull_ob_top' in source
    assert 'touched_bull_fvg_top := active_bull_fvg_top' in source

    # bull_ob_scan_start / bull_fvg_scan_start must NOT exist as standalone identifiers
    # (they were inlined into scan helpers; any remaining reference is a stale bug)
    import re
    # Must not be declared as a variable (was moved inside helper)
    assert re.search(r'(?:int|float)\s+bull_ob_scan_start\b', source) is None
    assert re.search(r'(?:int|float)\s+bull_fvg_scan_start\b', source) is None
    # Must not be referenced in for loops (was inlined)
    assert 'to bull_ob_scan_start' not in source
    assert 'to bull_fvg_scan_start' not in source

    # bear scan starts are still valid globals (used in bear blocker loops)
    assert 'int bear_ob_scan_start = math.max(0, array.size(ob_blocks_bear) - long_zone_scan_limit)' in source
    assert 'int bear_fvg_scan_start = math.max(0, array.size(fvgs_bear) - long_zone_scan_limit)' in source


def test_extracted_helpers_are_defined_before_first_call() -> None:
    """Pine Script requires functions to be defined before they are called.

    This test prevents regressions where a helper function definition is
    accidentally placed after its call site (which causes TradingView error
    'Could not find function or function reference').
    """
    source = _read_smc_source()

    # All extracted helper functions that must be defined before their call
    helpers = [
        'scan_live_bull_events',
        'compute_overhead_context',
        'compute_context_quality',
        'emit_long_engine_debug_logs',
        'compute_alert_text_suffixes',
        'compute_vol_regime',
        'compute_bull_reclaim_state',
        'scan_active_bull_ob',
        'scan_active_bull_fvg',
    ]

    for name in helpers:
        def_marker = f'{name}() =>'
        # Find first definition (function header)
        def_pos = source.find(def_marker)
        assert def_pos != -1, f'Function definition not found: {def_marker}'

        # Find first call site: `= name()` or `name()` not followed by `=>`
        call_pattern = re.compile(rf'(?<!=\s){re.escape(name)}\(\)')
        for m in call_pattern.finditer(source):
            # Skip the definition line itself
            if source[m.start():m.end() + 10].strip().startswith(name) and '=>' in source[m.start():source.index('\n', m.start())]:
                continue
            call_pos = m.start()
            assert def_pos < call_pos, (
                f'{name}() is called at offset {call_pos} but defined at offset {def_pos} — '
                f'definition must come first in Pine Script'
            )
            break  # only need to check the first non-definition occurrence


def test_extracted_helpers_reference_only_previously_declared_globals() -> None:
    """Pine Script requires globals to be declared before any function that
    references them.  A forward-referenced global causes TradingView error
    'Undeclared identifier'.

    For each extracted helper we list the critical globals it reads.  The test
    asserts that every listed global is declared (first occurrence) BEFORE the
    function definition line.
    """
    source = _read_smc_source()

    # Map: function_name -> list of global identifiers it reads
    helper_globals: dict[str, list[str]] = {
        'compute_overhead_context': [
            'long_plan_active',
            'long_state',
            'ob_threshold_atr',
            'stop_buffer_atr_mult',
            'ob_blocks_bear',
            'fvgs_bear',
            'bear_ob_scan_start',
            'bear_fvg_scan_start',
            'use_overhead_zone_filter_eff',
            'min_headroom_r',
        ],
        'compute_context_quality': [
            'mtf_trend_1',
            'mtf_trend_2',
            'mtf_trend_3',
            'use_ltf_for_strict_entry_eff',
            'use_rel_volume',
            'use_vwap_filter',
            'use_context_quality_score_eff',
            'min_context_quality_score',
        ],
        'emit_long_engine_debug_logs': [
            'long_setup_source_display',
            'long_invalidate_signal',
            'long_state',
            'long_arm_signal',
            'long_confirm_signal',
            'long_ready_signal',
            'long_source_upgrade_now',
            'long_source_upgrade_reason',
            'long_ready_blocker_text',
            'long_strict_blocker_text',
        ],
        'compute_alert_text_suffixes': [
            'headroom_to_overhead',
            'planned_risk',
            'context_quality_score',
            'effective_min_context_quality_score',
            'long_environment_focus_display',
            'use_overhead_zone_filter_eff',
        ],
        'scan_live_bull_events': [
            'last_bull_ob_break_level',
            'active_bull_ob_break_level',
            'last_bull_fvg_fill_level',
            'active_bull_fvg_fill_level',
            'ob_broken_new_bull',
            'filled_fvgs_new_bull',
            'ob_blocks_bull',
            'fvgs_bull',
            'long_zone_scan_limit',
        ],
        'compute_bull_reclaim_state': [
            'live_exec',
            'internal_trail_dn',
            'trail_dn',
            'long_state',
        ],
        'compute_vol_regime': [
            'vol_ma_len_1',
            'vol_ma_mode',
            'vol_bb_len',
            'vol_bb_mult',
            'vol_kc_len',
            'vol_kc_mult',
            'vol_squeeze_recent_bars',
            'vol_release_recent_bars',
            'vol_require_all_stack_slopes',
        ],
    }

    for func_name, globals_list in helper_globals.items():
        def_marker = f'{func_name}() =>'
        def_pos = source.find(def_marker)
        assert def_pos != -1, f'Function not found: {def_marker}'

        for gname in globals_list:
            # Find the first declaration/assignment of the global (skip comments)
            pattern = re.compile(
                rf'^[^/\n]*\b{re.escape(gname)}\b',
                re.MULTILINE,
            )
            m = pattern.search(source)
            assert m is not None, f'Global {gname} not found in source'
            global_pos = m.start()
            assert global_pos < def_pos, (
                f'Global "{gname}" (offset {global_pos}) must be declared before '
                f'{func_name}() (offset {def_pos}) to avoid "Undeclared identifier" error'
            )


