from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SMC_PATH = ROOT / 'SMC_Long_Dip_Suite.pine'
SUITE_PATH = SMC_PATH
ENGINE_PATH = ROOT / "SMC++" / "smc_engine_private.pine"
LIFECYCLE_PATH = ROOT / "SMC++" / "smc_lifecycle_private.pine"
RESOLVERS_PATH = ROOT / "SMC++" / "smc_context_resolvers.pine"
UTILS_PATH = ROOT / "SMC++" / "smc_utils.pine"
PROFILE_ENGINE_PATH = ROOT / "SMC++" / "smc_profile_engine.pine"
OBSERVABILITY_PATH = ROOT / "SMC++" / "smc_observability_private.pine"
DRAW_PATH = ROOT / "SMC++" / "smc_draw.pine"
DASHBOARD_PATH = ROOT / "SMC_Long_Dip_Dashboard.pine"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _body(path: pathlib.Path, function_name: str) -> str:
    source = _read(path)
    start = source.find(f"{function_name}(")
    assert start != -1, f"{function_name} not found in {path.name}"
    body_start = source.index("\n", start) + 1
    lines: list[str] = []
    for line in source[body_start:].splitlines():
        if not line.strip() or line.startswith("    "):
            lines.append(line)
        else:
            break
    return "\n".join(lines)


def _assert_order(source: str, *markers: str) -> None:
    positions = [source.find(marker) for marker in markers]
    assert all(position >= 0 for position in positions), dict(zip(markers, positions, strict=True))
    assert positions == sorted(positions), dict(zip(markers, positions, strict=True))


def test_label_new_never_puts_font_family_in_the_tooltip_slot() -> None:
    source = _read(DRAW_PATH)
    calls = re.findall(r"(?:label|box)\.new\([^\n]*\)", source)
    font_calls = [call for call in calls if "text_font_family" in call]
    assert len(calls) >= 4
    assert font_calls
    assert all(
        not re.search(r"text_align\s*,\s*[\w.]*text_font_family", call)
        for call in font_calls
    )


def test_refactored_helpers_preserve_dependency_order() -> None:
    source = _read(SUITE_PATH)
    _assert_order(
        source,
        "compute_long_overhead_context(",
        "[long_planned_stop_level, planned_risk, headroom_to_overhead, overhead_zone_ok] = compute_long_overhead_context(",
    )
    _assert_order(source, "scan_live_bull_events() =>", "] = scan_live_bull_events()")
    _assert_order(source, "compute_context_quality() =>", "] = compute_context_quality()")


def test_atr_helper_uses_deterministic_warmup_accumulator() -> None:
    body = _body(UTILS_PATH, "smc_lib_atr")
    assert "float atr_value = ta.atr(length)" in body
    assert "float tr_cum = ta.cum(ta.tr(true))" in body
    assert "if bar_index < length" in body
    assert "atr_value := tr_cum / (bar_index + 1)" in body
    assert "u.smc_lib_atr(" in _read(SUITE_PATH)


def test_strict_ltf_fallback_is_limited_to_missing_or_unverifiable_ltf() -> None:
    source = _read(SUITE_PATH)
    for marker in (
        "allow_strict_entry_without_ltf = input.bool(false",
        "bool ltf_needed = (show_dashboard and show_dashboard_ltf_eff) or use_ltf_for_strict_entry_eff",
        "bool strict_ltf_available = ltf_sampling_active and ltf_volume_ok",
        "bool strict_ltf_unavailable = use_ltf_for_strict_entry_eff and not strict_ltf_available",
        "bool strict_ltf_unverifiable = use_ltf_for_strict_entry_eff and not barstate.isrealtime and not strict_ltf_available",
        "else if allow_strict_entry_without_ltf and (strict_ltf_unavailable or strict_ltf_unverifiable)",
    ):
        assert marker in source
    assert "ltf_needed_for_messages" not in source


def test_relvol_fallback_stays_split_from_strict_volume_scoring() -> None:
    source = _read(SUITE_PATH)
    assert "bool relvol_data_ok = volume_current_bar_ok" in source
    assert "bool relvol_ok = true" in source
    assert "relvol_ok := allow_relvol_without_volume_data" in source
    assert "bool relvol_score_ok = true" in source
    assert "if relvol_data_ok and not na(rel_volume)" in source
    assert "bool _relvol_unavail = false" in source
    assert "if use_rel_volume and not relvol_data_ok and allow_relvol_without_volume_data" in source


def test_ob_profile_freezes_when_volume_quality_is_weak() -> None:
    source = _read(SUITE_PATH)
    assert "bool use_ob_profile_effective = use_ob_profile and volume_feed_quality_ok" in source
    assert "bool collect_ob_profile_current_bar = use_ob_profile_effective and volume_current_bar_ok" in source
    assert "capture_profile = collect_ob_profile_current_bar" in source
    assert "update_profile_current_bar = collect_ob_profile_current_bar" in source


def test_session_quality_gate_texts_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    for marker in (
        "float session_vwap = (intraday_time_chart) ? (session_vwap_raw) : (float(na))",
        "bool vwap_session_active = intraday_time_chart and not na(time(timeframe.period, vwap_session))",
        "bool session_gate_ok = true",
        "session_gate_ok := trade_entry_session_active",
        "bool opening_range_gate_ok = true",
        "opening_range_gate_ok := close > opening_range_high",
        "opening_range_gate_ok := close > opening_range_mid",
        "micro_session_gate_ok := micro_rth_gate_ok and micro_midday_gate_ok and micro_premarket_gate_ok and micro_afterhours_gate_ok",
        "vwap_filter_ok := not na(session_vwap) and close >= session_vwap",
    ):
        assert marker in source


def test_micro_modifier_and_ltf_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    for modifier in ("Stop-Hunt", "Clean Reclaim", "Fast Decay", "RTH Only", "Midday Dead"):
        assert modifier in source
    assert "if ltf_auto_select" in source
    assert "effective_ltf_timeframe := auto_selected_ltf" in source
    assert "int ltf_ratio = (effective_ltf_tf_sec > 0)" in source
    assert "bool ltf_ratio_ok = not na(ltf_ratio)" in source
    assert "if enable_ltf_sampling and ltf_timeframe_valid and ltf_needed and ltf_ratio_ok and ltf_sample_count_ok" in source


def test_adx_quality_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    assert "bool adx_data_ok = not na(adx_value) and not na(plus_di) and not na(minus_di)" in source
    assert "bool adx_strong = true" in source
    assert "if adx_data_ok and adx_value >= adx_strong_min and plus_di >= minus_di" in source
    assert "adx_strong := true" in source


def test_accel_context_and_gate_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    for marker in (
        "bool accel_below_zero = not na(accel_value)",
        "bool accel_rising = not na(accel_value) and accel_value > accel_value[1]",
        "if accel_close_safe_only and not barstate.isconfirmed",
        "bool accel_ready_gate_ok = true",
        "accel_ready_gate_ok := (not na(accel_value_safe)",
        "bool accel_strict_entry_gate_ok = true",
    ):
        assert marker in source


def test_sd_context_and_gate_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    for marker in (
        "bool sd_above_zero = not na(sd_value) and sd_value > 0",
        "bool sd_bullish_divergence_event = false",
        "bool sd_support_any_recent = sd_bullish_divergence_recent or sd_higher_lows_recent",
        "bool sd_ready_gate_ok = true",
        "bool sd_entry_strict_context_ok = sd_support_any_recent",
        "if sd_require_both_for_entry_strict",
    ):
        assert marker in source


def test_effective_live_break_overrides_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    assert "bool effective_use_live_confirm_break = use_live_confirm_break" in source
    assert "bool effective_use_live_invalidation_break = use_live_invalidation_break" in source
    assert "if micro_stop_hunt_force_close_confirm" in source
    assert "effective_use_live_confirm_break := false" in source
    assert "if micro_stop_hunt_disable_live_invalid" in source
    assert "effective_use_live_invalidation_break := false" in source


def test_volatility_context_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    body = _body(SUITE_PATH, "compute_vol_regime")
    for marker in (
        "bool _stack_order = false",
        "bool _stack_slopes = false",
        "bool _spread_rising = false",
        "bool _mom_expanding = false",
        "bool _squeeze = false",
        "bool _released = false",
        "bool _trend_ok = false",
    ):
        assert marker in body
    assert "bool vol_ready_context_ok = true" in source
    assert "bool vol_entry_strict_context_ok_safe = resolve_close_safe_bool_gated(vol_entry_strict_context_ok)" in source


def test_stretch_context_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    assert "float stretch_lower_threshold = (not na(stretch_mean)" in source
    assert "bool in_lower_extreme = not na(stretch_lower_threshold) and low <= stretch_lower_threshold" in source
    assert "bool stretch_ready_context_ok = true" in source
    assert "stretch_ready_context_ok := stretch_ready_context_ok and (in_lower_extreme or lower_extreme_recent)" in source
    assert "stretch_entry_strict_context_ok := stretch_entry_best_context_ok and anti_chase_ok_entry_strict" in source


def test_ddvi_context_derivations_use_explicit_block_logic() -> None:
    body = _body(SUITE_PATH, "compute_ddvi_context")
    for marker in (
        "bool bias_bull = use_context and not na(value) and value > 0",
        "bool bias_rising = use_context and not na(value) and not na(value[1]) and value > value[1]",
        "bool lower_extreme_context = lower_extreme_now or lower_extreme_recent or recover_from_lower_extreme",
        "bool entry_strict_ok = not use_context or (entry_best_ok and bias_ok and not lower_extreme_now)",
        "if close_safe_only and not barstate.isconfirmed and bar_index > 0",
    ):
        assert marker in body


def test_ddvi_and_market_safe_fallbacks_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    assert "bool vola_compression_now = not na(atr_baseline)" in source
    assert "bool market_symbols_missing = (use_index_gate and index_missing)" in source
    assert "if index_missing" in source
    assert "index_gate_effective_ok := not block_on_missing_market_symbol" in source
    assert "bool market_regime_gate_ok = resolve_close_safe_bool_gated(market_regime_gate_ok_raw)" in source
    assert "bool vola_regime_gate_safe = resolve_close_safe_bool_gated(vola_regime_gate_ok)" in source


def test_signal_and_long_state_contract_are_declared_for_safe_refactors() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "type LongLifecycleState" in suite
    assert "method clear(LongLifecycleState this) =>" in suite
    assert "method arm(LongLifecycleState this" in suite
    assert "method confirm(LongLifecycleState this" in suite
    assert "method invalidate(LongLifecycleState this" in suite
    assert "validate_long_state(long_state, show_long_engine_debug_eff)" in suite
    assert "eng.resolve_long_visual_state(" in suite
    assert "resolve_long_state_code(" in engine


def test_long_source_numeric_abi_matches_engine_and_suite() -> None:
    pattern = re.compile(r"^int (LONG_SOURCE_[A-Z_]+) = (\d+)$", re.MULTILINE)
    suite_values = dict(pattern.findall(_read(SUITE_PATH)))
    engine_values = dict(pattern.findall(_read(ENGINE_PATH)))
    expected = {
        "LONG_SOURCE_NONE": "0",
        "LONG_SOURCE_OB": "1",
        "LONG_SOURCE_FVG": "2",
        "LONG_SOURCE_SWING_LOW": "3",
        "LONG_SOURCE_INTERNAL_LOW": "4",
    }
    assert suite_values == expected
    assert engine_values == expected


def test_backing_zone_identity_and_touch_count_persist_after_arm() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "select_long_arm_backing_zone_touch_count(" in engine
    assert "export resolve_long_arm_transition_payload(" in engine
    assert "eng.resolve_long_arm_transition_payload(" in suite
    assert "long_state.arm(bar_index" in suite


def test_invalidation_path_records_specific_reason_and_clears_setup_state() -> None:
    suite = _read(SUITE_PATH)
    body = _body(ENGINE_PATH, "resolve_long_invalidation_reason")
    for helper in (
        "compose_long_source_invalidated_text",
        "compose_long_backing_zone_lost_text",
        "compose_long_setup_expired_text",
        "compose_long_confirm_expired_text",
    ):
        assert helper in body
    assert "eng.resolve_long_invalidation_reason(" in suite
    assert "long_state.invalidate(long_invalidation_reason, long_state.invalidation_level)" in suite


def test_ob_confirmed_profiles_are_rebuilt_from_copied_ltf_data() -> None:
    engine = _read(ENGINE_PATH)
    assert engine.count("bear_ob_confirmed.create_profile()") >= 2
    assert engine.count("bull_ob_confirmed.create_profile()") >= 2


def test_udt_render_and_draw_helpers_guard_na_before_field_access() -> None:
    engine = _read(ENGINE_PATH)
    assert "import preuss_steffen/smc_draw/3 as d" in engine
    assert "method delete(OrderBlock this) =>" in engine
    assert "if not na(this.plot_box)" in engine
    assert "method hide(FVG this) =>" in engine
    assert "if not na(this.plot_fill_target_label)" in engine


def test_indicator_resource_caps_match_runtime_history_behavior() -> None:
    suite = _read(SUITE_PATH)
    assert 'indicator("SMC Long-Dip Suite", overlay = true, max_bars_back = 500, max_lines_count = 300, max_boxes_count = 300, max_labels_count = 300)' in suite
    assert "long_marker_history_limit" not in suite
    assert "eng.draw_overlay_line_tail(" in suite


def test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods() -> None:
    engine = _read(ENGINE_PATH)
    assert "blocks.values().draw(config" in engine
    assert "export method draw(FVG[] fvgs, FVGConfig config" in engine
    assert ".clear_filled(" in engine


def test_fvg_hide_and_orderblock_reset_are_cleanup_consistent() -> None:
    engine = _read(ENGINE_PATH)
    assert "method hide(FVG this) =>" in engine
    assert "this.plot_fill_target_label.hide()" in engine
    assert "method reset_tracking(OrderBlock this) =>" in engine
    assert "this.ltf_volume.clear()" in engine
    assert "this.awaiting_confirmation := false" in engine


def test_invalidated_alert_has_single_preset_definition_without_failed_alias() -> None:
    suite = _read(SUITE_PATH)
    assert suite.count("SMC: Zone Invalidated |") == 1
    assert "if enable_dynamic_alerts and long_invalidated_now and barstate.isconfirmed" in suite
    assert "SMC: Zone Failed" not in suite


def test_confirmed_only_touch_state_updates_are_gated_by_state_update_bar_ok() -> None:
    suite = _read(SUITE_PATH)
    assert "bool state_update_bar_ok = barstate.isconfirmed or signal_mode == ct.SignalMode.AGGRESSIVE_LIVE" in suite
    assert suite.count("if state_update_bar_ok") >= 8


def test_signal_mode_derivations_use_explicit_block_logic() -> None:
    suite = _read(SUITE_PATH)
    assert "bool live_exec = signal_mode == ct.SignalMode.AGGRESSIVE_LIVE and barstate.isrealtime" in suite
    assert "signal_mode != ct.SignalMode.AGGRESSIVE_LIVE and not barstate.isconfirmed" in suite
    assert "(signal_mode == ct.SignalMode.AGGRESSIVE_LIVE or barstate.isconfirmed) and alert_now" in suite


def test_visible_range_derivations_use_explicit_block_logic() -> None:
    source = _read(SUITE_PATH)
    assert "visible_left_time" in source
    assert "visible_right_time" in source
    assert "render_visible_only" in source


def test_structure_signal_derivations_use_explicit_block_logic() -> None:
    suite = _read(SUITE_PATH)
    assert "bool bullish_structure_break = bull_bos_alert or bull_choch_alert" in suite
    assert "bool bearish_structure_break = bear_bos_alert or bear_choch_alert" in suite
    assert "int structure_display_trend = (not na(structure_break_since)) ? (trend) : (0)" in suite
    assert "bool bull_bos_sig = resolve_confirmed_signal(bull_bos_alert)" in suite


def test_htf_fvg_confirmation_gate_uses_explicit_block_logic() -> None:
    runtime = _read(SUITE_PATH) + _read(ENGINE_PATH)
    assert "htf_fvg_confirmed" not in runtime
    assert "show_htf_fvg" not in runtime
    assert "request.security_lower_tf" in _read(SUITE_PATH)


def test_active_backing_zones_are_protected_from_cleanup_rotation() -> None:
    suite = _read(SUITE_PATH)
    assert "int _ob_backing_zone_id = (long_state.backing_zone_kind == LONG_SOURCE_OB)" in suite
    assert "int _fvg_backing_zone_id = (long_state.backing_zone_kind == LONG_SOURCE_FVG)" in suite
    assert "protected_bull_id = _ob_backing_zone_id" in suite
    assert "eng.fvgs_objects(active_break_mode, fvg_fill_target_ratio, fvg_size_threshold, enable_fvg_engine, fvg_keep_filled_max, object_gc_cycle_eff, _fvg_backing_zone_id)" in suite


def test_quality_score_api_replaces_legacy_probability_naming() -> None:
    engine = _read(ENGINE_PATH)
    assert "float quality_score" in engine
    assert "show_quality_score" in engine
    assert "probability_score" not in engine


def test_armed_stage_can_be_optionally_tightened() -> None:
    suite = _read(SUITE_PATH)
    body = _body(LIFECYCLE_PATH, "compute_long_arm_prequality_ok")
    assert "if tighten_armed_stage_eff" in body
    assert "bullish_trend_safe and micro_session_gate_ok" in body
    assert "ll.compute_long_arm_prequality_ok(" in suite


def test_user_presets_and_performance_modes_drive_effective_runtime_layers() -> None:
    suite = _read(SUITE_PATH)
    for marker in (
        "performance_mode_light",
        "performance_mode_pro",
        "performance_mode_debug",
        "object_gc_cycle_eff",
        "max_ltf_ratio_eff",
        "use_ltf_for_strict_entry_eff",
        "quickstart_preset",
    ):
        assert marker in suite


def test_breadth_gate_supports_multiple_modes() -> None:
    source = _read(SUITE_PATH)
    assert "breadth_gate_mode" in source
    assert "u.external_breadth_gate(" in source
    assert "breadth_gate_effective_ok" in source


def test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard() -> None:
    suite = _read(SUITE_PATH)
    observability = _read(OBSERVABILITY_PATH)
    assert "show_long_engine_debug" in suite
    assert "obv.emit_long_engine_debug_logs(" in suite
    assert "export emit_long_engine_debug_logs(" in observability
    assert "compose_long_debug_summary_text(" in observability


def test_prepare_order_block_confirmation_runs_each_calc_without_shadowing_state() -> None:
    engine = _read(ENGINE_PATH)
    body = _body(ENGINE_PATH, "prepare_order_block_confirmation")
    assert "if should_prepare" in body
    assert "block.create_profile()" in body
    assert "block.align_to_profile(align_break_price = true)" in body
    assert "[ob_size_min, ob_size_max]" in body
    assert "prepare_order_block_confirmation(" in engine


def test_clean_tier_is_renamed_as_a_quality_diagnostic() -> None:
    suite = _read(SUITE_PATH)
    lifecycle = _read(LIFECYCLE_PATH)
    assert "export resolve_long_clean_tier(" in lifecycle
    assert "bool long_quality_clean_tier = ll.resolve_long_clean_tier(" in suite
    assert "bool long_clean_tier" not in suite


def test_cleanup_protection_does_not_mask_genuine_break_migration() -> None:
    engine = _read(ENGINE_PATH)
    suite = _read(SUITE_PATH)
    assert "update_broken(int mode, OrderBlock[] tracking_blocks" in engine
    assert "protected_bull_id = _ob_backing_zone_id" in suite
    assert "ll.resolve_long_source_runtime_state(" in suite


def test_source_lock_decouples_setup_source_from_live_active_ranking() -> None:
    suite = _read(SUITE_PATH)
    lifecycle = _read(LIFECYCLE_PATH)
    assert "export resolve_long_source_runtime_state(" in lifecycle
    assert "prev_locked_source_kind = long_state.locked_source_kind" in suite
    assert "ll.resolve_long_source_runtime_state(" in suite
    assert "long_state.locked_source_id" in suite


def test_locked_source_drives_touch_history_and_strict_sweep() -> None:
    suite = _read(SUITE_PATH)
    assert "long_locked_source_touch_now" in suite
    assert "long_locked_source_last_touch_bar_index_effective" in suite
    assert "long_locked_ob_real_sweep" in suite
    assert "long_locked_fvg_real_sweep" in suite


def test_source_upgrade_is_explicit_and_quality_gated() -> None:
    suite = _read(SUITE_PATH)
    body = _body(ENGINE_PATH, "compute_long_source_upgrade_state")
    assert "allow_armed_source_upgrade" in suite
    assert "min_source_upgrade_quality_gain" in suite
    assert "touched_bull_ob_quality >= long_locked_source_quality + min_source_upgrade_quality_gain" in body
    assert "touched_bull_fvg_quality >= long_locked_source_quality + min_source_upgrade_quality_gain" in body
    assert "eng.compute_long_source_upgrade_state(" in suite


def test_script_text_is_english_only_for_known_long_lifecycle_regressions() -> None:
    runtime = _read(SUITE_PATH) + _read(ENGINE_PATH)
    assert "source invalidated" in runtime
    assert "backing zone lost" in runtime
    assert "Quelle gebrochen" not in runtime
    assert "Quelle verloren" not in runtime


def test_source_upgrade_requires_different_candidate_than_locked_source() -> None:
    body = _body(ENGINE_PATH, "compute_long_source_upgrade_state")
    assert "prev_locked_source_kind != LONG_SOURCE_OB or prev_locked_source_id != touched_bull_ob_id" in body
    assert "prev_locked_source_kind != LONG_SOURCE_FVG or prev_locked_source_id != touched_bull_fvg_id" in body


def test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain() -> None:
    body = _body(ENGINE_PATH, "compute_long_source_upgrade_state")
    assert "bool helper_ob_source_upgrade_ok = false" in body
    assert "bool helper_fvg_source_upgrade_ok = false" in body
    assert "if allow_armed_source_upgrade and long_setup_armed and not long_setup_confirmed" in body
    assert "helper_long_source_upgrade_now = helper_ob_source_upgrade_ok or helper_fvg_source_upgrade_ok" in body


def test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks() -> None:
    source = _read(SUITE_PATH)
    _assert_order(
        source,
        "eng.stage_locked_source_transition(",
        "bool long_locked_ob_alive_now",
        "bool long_locked_fvg_alive_now",
        "bool long_source_broken",
    )


def test_arm_and_confirm_transitions_route_through_long_state_methods() -> None:
    suite = _read(SUITE_PATH)
    assert "long_state.arm(" in suite
    assert "long_state.confirm(bar_index)" in suite
    assert "long_state.invalidate(" in suite


def test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "entry_origin_source" in suite
    assert "locked_source_kind" in suite
    assert "eng.compose_long_setup_source_display(long_state.entry_origin_source, long_validation_source)" in suite
    assert "export compose_long_setup_source_display(" in engine


def test_display_and_status_text_are_extracted_into_helpers() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "export describe_long_freshness(" in engine
    assert "export describe_long_source_state(" in engine
    assert "eng.describe_long_freshness(" in suite
    assert "eng.describe_long_source_state(" in suite


def test_confirm_and_ready_gate_logic_is_extracted_into_helpers() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    lifecycle = _read(LIFECYCLE_PATH)
    assert "export select_effective_long_touch_count(" in engine
    assert "eng.select_effective_long_touch_count(" in suite
    assert "export compute_long_confirm_transition_state(" in lifecycle
    assert "ll.compute_long_confirm_transition_state(" in suite
    assert "export resolve_long_ready_projection_state(" in lifecycle
    assert "ll.resolve_long_ready_projection_state(" in suite


def test_setup_text_and_visual_state_are_extracted_into_helpers() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "resolve_long_state_code(" in engine
    assert "export resolve_long_visual_state(" in engine
    assert "eng.resolve_long_visual_state(" in suite
    assert "export resolve_core_product_state(" in engine
    assert "eng.resolve_core_product_state(long_visual_state)" in suite


def test_profile_and_track_obs_use_defensive_semantic_helpers() -> None:
    engine = _read(ENGINE_PATH)
    profile = _read(PROFILE_ENGINE_PATH)
    for marker in (
        "normalize_profile_resolution(",
        "normalize_profile_vah_pc(",
        "normalize_profile_val_pc(",
        "profile_data_ready(",
        "is_impulse_candle_now(",
        "is_indecision_candle_now(",
    ):
        assert marker in profile
    assert "pe.is_impulse_candle_now(" in engine
    assert "pe.profile_features_enabled(" in engine


def test_track_obs_lifecycle_steps_are_split_into_small_helpers() -> None:
    engine = _read(ENGINE_PATH)
    for marker in (
        "method capture_profile_bar(OrderBlock this",
        "handle_pending_tracking_reset(",
        "prepare_order_block_confirmation(",
        "update_soft_confirmation(",
        "update_broken(",
    ):
        assert marker in engine


def test_watchlist_alert_level_follows_active_zone_preference() -> None:
    suite = _read(SUITE_PATH)
    assert "compute_long_dynamic_alert_gates(" not in suite
    assert "emit_priority_long_dynamic_alerts(" not in suite
    assert "if enable_dynamic_alerts and alert_product_state" in suite
    assert "alert_product_state = eng.resolve_core_product_state(long_visual_state)" in suite


def test_detect_pivot_resets_trend_concordant_before_optional_filter() -> None:
    body = _body(ENGINE_PATH, "detect_pivot")
    assert "var trend_concordant = true" in body
    assert "trend_concordant := true" in body
    assert "if filter_insignificant_internal_breaks" in body
    _assert_order(body, "trend_concordant := true", "if filter_insignificant_internal_breaks")


def test_visual_text_dashboard_and_colors_are_extracted_into_helpers() -> None:
    engine = _read(ENGINE_PATH)
    dashboard = _read(DASHBOARD_PATH)
    assert "export resolve_core_product_state(" in engine
    assert "dashboard_product_state_text(" in dashboard
    for state in ("WAIT", "BLOCKED", "PREPARE LONG", "READY LONG", "ENTER LONG"):
        assert state in engine
        assert state in dashboard


def test_dashboard_long_zone_summary_uses_shared_zone_text_helper() -> None:
    suite = _read(SUITE_PATH)
    dashboard = _read(DASHBOARD_PATH)
    for channel in ("ZoneObTop", "ZoneObBottom", "ZoneFvgTop", "ZoneFvgBottom"):
        assert f"'BUS {channel}'" in suite
        assert f'"BUS {channel}"' in dashboard


def test_arm_setup_resolution_is_extracted_into_helpers() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "export resolve_long_arm_source_state(" in engine
    assert "eng.resolve_long_arm_source_state(" in suite
    assert "export resolve_long_arm_transition_payload(" in engine
    assert "eng.resolve_long_arm_transition_payload(" in suite


def test_long_alert_helpers_cover_close_safe_events_and_message_composition() -> None:
    suite = _read(SUITE_PATH)
    resolvers = _read(RESOLVERS_PATH)
    assert "compose_long_invalidated_alert_detail(" in resolvers
    assert "compose_long_ready_alert_detail(" in resolvers
    assert "compose_long_confirmed_alert_detail(" in resolvers
    assert "compose_long_watchlist_alert_detail(" in resolvers
    assert "compose_long_invalidated_alert_detail(" not in suite
    assert suite.count("alert(") >= 16


def test_intrabar_ready_and_watchlist_events_are_debounced_and_latched() -> None:
    suite = _read(SUITE_PATH)
    body = _body(OBSERVABILITY_PATH, "resolve_long_ready_signal_state")
    assert "if current_bar_is_new" in body
    assert "helper_ready_fired_this_bar := false" in body
    assert "if long_ready_state and helper_ready_state_rt_prev == 0 and not helper_ready_fired_this_bar" in body
    assert "obv.resolve_long_ready_signal_state(" in suite
    assert "long_ready_state_rt_prev := long_ready_state_rt_prev_next" in suite


def test_pre_arm_ob_selection_prefers_touch_anchor_then_recency_then_quality() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "scan_active_bull_ob() =>" in suite
    assert "export zone_candidate_preferred(" in engine
    assert "_prefer := eng.zone_candidate_preferred(" in suite


def test_pre_arm_fvg_and_combined_active_zone_use_deterministic_priority() -> None:
    suite = _read(SUITE_PATH)
    assert "scan_active_bull_fvg() =>" in suite
    assert suite.count("_prefer := eng.zone_candidate_preferred(") >= 2
    assert "eng.prefer_primary_zone(" in suite


def test_bear_pre_arm_selection_uses_same_deterministic_priority_without_touch_anchor() -> None:
    suite = _read(SUITE_PATH)
    assert "int bear_ob_scan_start = math.max(0, array.size(ob_blocks_bear) - long_zone_scan_limit)" in suite
    assert "int bear_fvg_scan_start = math.max(0, array.size(fvgs_bear) - long_zone_scan_limit)" in suite
    assert "for i = array.size(ob_blocks_bear_param) - 1 to bear_ob_scan_start" in suite
    assert "for i = array.size(fvgs_bear_param) - 1 to bear_fvg_scan_start" in suite


def test_touched_bull_zone_lookups_use_explicit_block_logic() -> None:
    suite = _read(SUITE_PATH)
    assert "eng.OrderBlock touched_bull_ob_block = na" in suite
    assert "touched_bull_ob_block := ob_blocks_bull.get_by_id(touched_bull_ob_id)" in suite
    assert "eng.FVG touched_bull_fvg_block = na" in suite
    assert "touched_bull_fvg_block := fvgs_bull.get_by_id(touched_bull_fvg_id)" in suite


def test_touched_bull_zone_quality_uses_explicit_block_logic() -> None:
    suite = _read(SUITE_PATH)
    assert "float touched_bull_ob_quality = (not na(touched_bull_ob_block))" in suite
    assert "eng.ob_quality_score(touched_bull_ob_block)" in suite
    assert "float touched_bull_fvg_quality = (not na(touched_bull_fvg_block))" in suite
    assert "eng.fvg_quality_score(touched_bull_fvg_block, fvg_size_threshold)" in suite


def test_locked_source_touch_count_selection_is_extracted() -> None:
    suite = _read(SUITE_PATH)
    engine = _read(ENGINE_PATH)
    assert "export select_locked_source_touch_count(" in engine
    assert "eng.select_locked_source_touch_count(" in suite


def test_scan_helpers_no_global_mutations_and_no_stale_scan_start_refs() -> None:
    suite = _read(SUITE_PATH)
    for function_name in ("scan_active_bull_ob", "scan_active_bull_fvg"):
        body = _body(SUITE_PATH, function_name)
        assert ":=" not in "\n".join(
            line for line in body.splitlines() if line.startswith("    ") and not line.startswith("        ")
        )
    assert "scan_start_ref" not in suite


def test_extracted_helpers_are_defined_before_first_call() -> None:
    suite = _read(SUITE_PATH)
    for definition, call in (
        ("compute_long_overhead_context(", "] = compute_long_overhead_context("),
        ("compute_ddvi_context(", "] = compute_ddvi_context("),
        ("scan_live_bull_events() =>", "] = scan_live_bull_events()"),
        ("compute_context_quality() =>", "] = compute_context_quality()"),
    ):
        _assert_order(suite, definition, call)


def test_extracted_helpers_reference_only_previously_declared_globals() -> None:
    suite = _read(SUITE_PATH)
    for function_name in ("compute_long_overhead_context", "compute_ddvi_context"):
        definition = suite.find(f"{function_name}(")
        assert definition >= 0
        body = _body(SUITE_PATH, function_name)
        assert body.strip()
    assert suite.find("compute_long_overhead_context(") < suite.find("var g_mode")


def test_overhead_membership_is_decided_by_the_far_edge() -> None:
    """A bear zone is overhead while any part of it sits above the entry.

    The scan previously answered two questions with one number: "is this zone
    overhead at all?" and "how far is the entry from the reaction it produces?".
    Both used the reaction level (OB ``break_price`` -- POC-aligned when
    profiles are on -- resp. FVG ``fill_target_level``), so a zone whose
    reaction level sat below the entry dropped out of the scan entirely.

    Membership is now decided by the far edge (``left_top.price``); the reaction
    level stays the distance reference, which is the deliberate design recorded
    in #4200.
    """
    overhead_body = _body(SUITE_PATH, "compute_long_overhead_context")

    assert "resolve_ob_overhead_level(" in overhead_body
    assert "resolve_fvg_overhead_level(" in overhead_body
    assert "resolve_ob_alert_level(" not in overhead_body
    assert "resolve_fvg_alert_level(" not in overhead_body

    ob_body = _body(SUITE_PATH, "resolve_ob_overhead_level")
    fvg_body = _body(SUITE_PATH, "resolve_fvg_overhead_level")

    for body in (ob_body, fvg_body):
        assert "left_top.price" in body

    # The reaction level remains the distance reference on both arms.
    assert "break_price" in ob_body
    assert "fill_target_level" in fvg_body


def test_overhead_distance_is_clamped_at_the_entry() -> None:
    """An entry inside a still-live zone must report zero headroom, not none.

    ``long_trigger`` is frozen at arm time and derived from wicks
    (``math.max(high, ta.highest(high, long_confirm_lookback)[1])``), while a
    zone only counts as consumed once price CLOSES through its reaction level in
    the default CONFIRMED_ONLY mode. The two can disagree, so the distance is
    clamped at the scan reference instead of letting the zone vanish.
    """
    for function_name in ("resolve_ob_overhead_level", "resolve_fvg_overhead_level"):
        body = _body(SUITE_PATH, function_name)
        assert "scan_ref" in body
        assert "level := scan_ref" in body


def test_shared_alert_level_resolvers_stay_untouched_for_the_alert_paths() -> None:
    """The overhead split must not change the bull alert levels.

    ``resolve_ob_alert_level`` / ``resolve_fvg_alert_level`` also serve the
    alert and zone-scan paths, where the reaction level is the correct and
    only reference.
    """
    suite = _read(SUITE_PATH)
    assert "break_price" in _body(SUITE_PATH, "resolve_ob_alert_level")
    assert "fill_target_level" in _body(SUITE_PATH, "resolve_fvg_alert_level")
    assert suite.count("resolve_ob_alert_level(") >= 4
    assert suite.count("resolve_fvg_alert_level(") >= 4
