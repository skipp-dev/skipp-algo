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
