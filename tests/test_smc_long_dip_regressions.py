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
    assert "long_setup_backing_zone_touch_count := arm_backing_zone_kind == 'OB' and arm_backing_zone_id == active_ob_touch_id ? active_ob_touch_count : arm_backing_zone_kind == 'FVG' and -arm_backing_zone_id == active_fvg_touch_id ? active_fvg_touch_count : 0" in source
    assert "if long_setup_backing_zone_kind == 'OB' and long_setup_backing_zone_id == active_ob_touch_id" in source
    assert "else if long_setup_backing_zone_kind == 'FVG' and -long_setup_backing_zone_id == active_fvg_touch_id" in source


def test_invalidation_path_records_specific_reason_and_clears_setup_state() -> None:
    source = _read_smc_source()

    assert "long_last_invalid_source := str.format('{0} source changed', long_setup_source)" in source
    assert "long_last_invalid_source := str.format('{0} backing zone lost', long_setup_source)" in source
    assert "long_last_invalid_source := str.format('{0} setup expired', long_setup_source)" in source
    assert "long_last_invalid_source := str.format('{0} confirm expired', long_setup_source)" in source
    assert 'long_invalidate_signal := long_setup_armed or long_setup_confirmed' in source
    assert "long_setup_source := 'None'" in source
    assert "long_setup_backing_zone_kind := 'None'" in source
    assert 'long_setup_backing_zone_id := na' in source


def test_ob_profile_ownership_transfer_paths_remain_present() -> None:
    source = _read_smc_source()

    assert source.count('bear_ob_confirmed.profile := bull_ob.profile') >= 1
    assert source.count('bull_ob_confirmed.profile := bear_ob.profile') >= 1


def test_invalidated_alert_has_single_preset_definition_without_failed_alias() -> None:
    source = _read_smc_source()

    preset_defs = re.findall(r"alertcondition\(long_invalidate_alert_event, 'Long Invalidated', 'SMC\+\+: Invalidated\. Setup failed\.'\)", source)
    assert len(preset_defs) == 1, 'Expected exactly one Long Invalidated preset definition'
    assert "alertcondition(long_invalidate_alert_event, 'Long Dip Failed'" not in source


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
    assert 'long_setup_backing_zone_kind == \'FVG\' ? -long_setup_backing_zone_id : na' in source
    assert 'tracking_blocks_bull.remove_insignificant(min_block_size, max_block_size, discarded_blocks_bull, protected_bull_id)' in source
    assert 'buffer_bull.clear_filled(buffer_bull_filled, buffer_bull_filled_new, filled_max_keep, buffer_bull_discarded, protected_bull_id)' in source
    assert 'buffer_bull.remove_insignificant(size_threshold, buffer_bull_discarded, protected_bull_id)' in source
    assert 'bool is_protected = not na(protected_id) and block.id == protected_id' in source
    assert 'bool is_protected = not na(protected_id) and fvg.id == protected_id' in source


def test_quality_scores_replace_dead_probability_display() -> None:
    source = _read_smc_source()

    assert 'ob_quality_score(OrderBlock block) =>' in source
    assert 'fvg_quality_score(FVG fvg, float size_threshold = 0.0) =>' in source
    assert "str.format(' (Q {0,number,percent})', ob_quality)" in source
    assert "str.format('(Q {0,number,percent})', fvg_quality)" in source


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
    assert 'long_source_lost := (long_setup_armed or long_setup_confirmed) and long_source_tracked and not long_source_alive' in source
