from __future__ import annotations

import re

from tests.smc_manifest_test_utils import ROOT

RESOLVERS_PATH = ROOT / 'SMC++' / 'smc_context_resolvers.pine'
CORE_ENGINE_PATH = ROOT / 'SMC_Core_Engine.pine'


def _read_resolvers_source() -> str:
    return RESOLVERS_PATH.read_text(encoding='utf-8')


def _read_core_source() -> str:
    return CORE_ENGINE_PATH.read_text(encoding='utf-8')


def _normalize_ws(text: str) -> str:
    return ' '.join(text.strip().split())


def _extract_export_signatures(source: str) -> list[str]:
    signatures: list[str] = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith('export '):
            continue
        assert stripped.endswith('=>'), f'Export line must end with =>: {stripped}'
        signatures.append(_normalize_ws(stripped[:-2]))
    return signatures


def _extract_signature_name_and_params(signature: str) -> tuple[str, str]:
    match = re.match(r'^export\s+([A-Za-z_][A-Za-z0-9_]*)\((.*)\)$', signature)
    assert match is not None, f'Cannot parse export signature: {signature}'
    return match.group(1), match.group(2).strip()


EXPECTED_EXPORT_SIGNATURES = [
    'export f_parse_ticker_heat(string heat_map, string ticker)',
    'export resolve_core_provider_state(string provider_status, int provider_count, string stale_providers)',
    'export resolve_core_bias_text(string signal_bias_alignment)',
    'export compose_why_now_text(string product_state, string long_setup_source_display, string signal_freshness, string signal_warnings, string long_ready_blocker_text, string long_strict_blocker_text, float long_trigger)',
    'export compose_main_risk_text(string product_state, string event_risk_state, string long_ready_blocker_text, string long_strict_blocker_text, string long_last_invalid_source, string signal_warnings, string provider_status, bool has_earnings_tomorrow)',
    'export compose_trade_threshold_text(string trust_tier, int signal_quality_score)',
    'export resolve_core_hero_color(string product_state, color bull_hero, color bull_hero_ready, color bear_hero)',
    'export compose_core_hero_text(string product_state, string bias_text, string trade_threshold_text, string trust_tier, string trust_suffix, string provider_state, string why_now, string main_risk, string market_regime, bool regime_blocks, bool regime_dims, string asof_display, float vix_level, string market_event, string tone_text, bool yield_inverted, string sector_leading, bool breaking_news, int high_impact_count, bool ticker_in_universe)',
    'export resolve_core_alert_action_name(string event_name)',
    'export pack_bus_row(int row_state, int reason_code)',
    'export pack_bus_four(float value1, float value2, float value3, float value4)',
    'export pack_bus_counts(int primary_count, int secondary_count)',
    'export normalize_bus_trend(int dir)',
    'export pack_bus_trend_set(int trend_now, int trend_htf_1, int trend_htf_2, int trend_htf_3)',
    'export pack_bus_meta(int freshness_code, int source_state_code, int reclaim_code, int zone_code)',
    'export resolve_bus_stretch_support_mask(bool use_stretch_context, bool in_lower_extreme, bool lower_extreme_recent, bool anti_chase_ok_ready, bool anti_chase_ok_entry_best)',
    'export resolve_bus_freshness_code(bool long_setup_armed, bool long_setup_confirmed, bool ready_is_fresh, bool confirm_is_fresh)',
    'export resolve_bus_source_state_code(bool long_source_tracked, bool long_source_alive, bool long_source_broken)',
    'export resolve_bus_zone_code(bool long_zone_active, bool in_bull_ob_zone, bool in_bull_fvg_zone)',
    'export resolve_bus_zone_row(bool long_zone_active, bool in_bull_ob_zone, bool in_bull_fvg_zone)',
    'export resolve_bus_reclaim_code(bool reclaim_recent, bool bull_reclaim_internal_low_strict, bool bull_reclaim_swing_low_strict, bool bull_reclaim_fvg_strict, bool bull_reclaim_ob_strict)',
    'export resolve_bus_reclaim_row(bool reclaim_recent, bool bull_reclaim_internal_low_strict, bool bull_reclaim_swing_low_strict, bool bull_reclaim_fvg_strict, bool bull_reclaim_ob_strict)',
    'export resolve_bus_session_row(bool intraday_time_chart, bool use_trade_session_gate, bool use_opening_range_gate, bool session_structure_gate_ok, bool session_gate_ok)',
    'export resolve_bus_market_row(bool use_index_gate, bool use_sector_gate, bool use_breadth_symbol_gate, bool market_symbols_missing, bool block_on_missing_market_symbol, bool market_regime_gate_ok, bool index_gate_effective_ok, bool sector_gate_effective_ok, bool market_valuation_caution)',
    'export resolve_bus_vola_row(bool use_vola_compression_gate, bool vola_regime_gate_safe, bool vola_expansion_now, bool vola_compression_recent)',
    'export resolve_bus_micro_session_row(bool use_microstructure_profiles, bool intraday_time_chart, bool micro_session_gate_ok, bool micro_rth_gate_ok, bool micro_midday_gate_ok, bool micro_premarket_gate_ok)',
    'export resolve_bus_micro_fresh_row(bool use_microstructure_profiles, bool micro_freshness_gate_ok)',
    'export resolve_bus_volume_data_row(bool volume_current_bar_ok, bool volume_feed_quality_ok, bool ltf_sampling_active, bool ltf_price_ok, bool ltf_volume_ok, bool ltf_price_only)',
    'export resolve_bus_quality_env_row(bool environment_hard_gate_ok, bool market_regime_gate_ok, bool vola_regime_gate_safe)',
    'export resolve_bus_quality_strict_row(bool long_entry_strict_state, bool strict_entry_ltf_ok, bool htf_alignment_ok, bool accel_strict_entry_gate_ok, bool sd_entry_strict_gate_ok, bool vol_entry_strict_context_ok_safe, bool stretch_entry_strict_context_ok, bool ddvi_entry_strict_ok_safe)',
    'export resolve_bus_close_strength_row(bool use_strong_close_filter, bool bull_close_strong)',
    'export resolve_bus_ema_support_row(bool show_ema_support, bool ema_support_ok)',
    'export resolve_bus_adx_row(bool use_adx, bool adx_data_ok, float plus_di, float minus_di, bool adx_strong, float adx_value, float adx_trend_min)',
    'export resolve_bus_relvol_row(bool use_rel_volume, bool relvol_data_ok, bool allow_relvol_without_volume_data, bool relvol_ok)',
    'export resolve_bus_vwap_row(bool use_vwap_filter, bool intraday_time_chart, bool vwap_session_active, bool vwap_filter_ok)',
    'export resolve_bus_context_quality_row(bool use_context_quality_score_eff, bool context_quality_gate_ok)',
    'export resolve_bus_quality_score_row(int signal_quality_score)',
    'export resolve_bus_quality_clean_row(bool long_quality_clean_tier)',
    'export resolve_bus_sd_confluence_row(bool use_sd_confluence, bool sd_support_both_recent, bool sd_bullish_divergence_recent, bool sd_higher_lows_recent, bool sd_support_any_recent)',
    'export resolve_bus_sd_osc_row(bool use_sd_confluence, float sd_value, bool sd_above_zero, bool sd_rising, bool sd_below_zero, bool sd_falling)',
    'export resolve_bus_vol_regime_row(bool use_volatility_regime, bool vol_regime_trend_ok)',
    'export resolve_bus_vol_squeeze_row(bool use_volatility_regime, bool vol_squeeze_on, bool vol_squeeze_release_recent, bool vol_squeeze_recent)',
    'export resolve_bus_vol_expansion_state(bool use_volatility_regime, bool vol_momentum_expanding_long, bool vol_stack_spread_rising)',
    'export resolve_bus_stretch_row(bool use_stretch_context, float distance_to_mean_z, bool in_lower_extreme, bool lower_extreme_recent, bool anti_chase_ok_entry_best, bool anti_chase_ok_ready)',
    'export resolve_bus_ddvi_context_state(bool use_ddvi_context, bool ddvi_bias_ok, bool ddvi_bull_divergence_any, bool ddvi_lower_extreme_context)',
    'export resolve_bus_ltf_bias_row(bool show_dashboard_ltf_eff, bool ltf_sampling_active, bool ltf_price_ok, bool ltf_price_only, float ltf_bull_share, float ltf_bias_hint)',
    'export resolve_bus_ltf_delta_state(bool show_dashboard_ltf_eff, bool ltf_sampling_active, bool ltf_price_only, float ltf_volume_delta)',
    'export resolve_bus_objects_row(int ob_count, int fvg_count)',
    'export resolve_bus_safe_trend_state(bool bullish_trend_safe, bool bearish_trend_safe)',
    'export resolve_bus_micro_profile_code(bool use_microstructure_profiles, string micro_profile_text, string micro_modifier_text)',
    'export resolve_bus_signal_quality_row(int sq_score, string sq_tier)',
    'export resolve_bus_signal_freshness_row(string sq_freshness, string sq_bias)',
    'export resolve_bus_event_risk_light_row(string erl_window, string erl_level, bool erl_market_blocked, bool erl_symbol_blocked)',
    'export resolve_bus_struct_light_row(int trend_strength, bool fresh, string last_event)',
    'export resolve_bus_ob_light_row(string ob_side, bool ob_fresh, string ob_mitig)',
    'export resolve_bus_fvg_light_row(string fvg_side, bool fvg_fresh, bool fvg_invalidated)',
    'export resolve_bus_ensemble_transport_state(float ensemble_quality_score, string ensemble_quality_tier)',
    'export resolve_bus_library_vol_reason_code(string volatility_regime, string volatility_model_source)',
    'export resolve_bus_ensemble_vol_transport_row(float ensemble_quality_score, string ensemble_quality_tier, string volatility_regime, string volatility_model_source)',
    'export resolve_bus_trend_pack(int structure_display_trend, int mtf_trend_1, int mtf_trend_2, int mtf_trend_3)',
    'export resolve_bus_meta_pack(bool long_setup_armed, bool long_setup_confirmed, bool ready_is_fresh, bool confirm_is_fresh, bool long_source_tracked, bool long_source_alive, bool long_source_broken, bool reclaim_recent, bool bull_reclaim_internal_low_strict, bool bull_reclaim_swing_low_strict, bool bull_reclaim_fvg_strict, bool bull_reclaim_ob_strict, bool long_zone_active, bool in_bull_ob_zone, bool in_bull_fvg_zone)',
    'export resolve_bus_lean_pack_a(int signal_quality_score, string signal_quality_tier, string signal_freshness, string signal_bias_alignment, string event_window_state, string event_risk_level, bool market_event_blocked, bool symbol_event_blocked, int structure_trend_strength, bool structure_fresh, string structure_last_event)',
    'export resolve_bus_lean_pack_b(string ob_side, bool ob_fresh, string ob_mitigation_state, string fvg_side, bool fvg_fresh, bool fvg_invalidated, int session_context_score, bool in_killzone, float ensemble_quality_score, string ensemble_quality_tier, string volatility_regime, string volatility_model_source)',
    'export compose_long_invalidated_alert_detail(string long_last_invalid_source, string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_entry_strict_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_entry_best_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_ready_alert_detail(string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_confirmed_alert_detail(string long_setup_source_display, string long_strict_alert_suffix, string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_clean_alert_detail(string long_environment_alert_suffix, string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_early_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_armed_plus_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_armed_alert_detail(string long_setup_source_display, string long_micro_alert_suffix, string long_score_detail_suffix)',
    'export compose_long_watchlist_alert_detail(string long_micro_alert_suffix, string long_score_detail_suffix)',
]

EXPECTED_IMPORTS = [
    'import preuss_steffen/smc_utils/1 as u',
    'import preuss_steffen/smc_bus_private/1 as bp',
]


# ── Header and imports ─────────────────────────────────────────────────────


def test_context_resolvers_file_exists_and_declares_library_header() -> None:
    assert RESOLVERS_PATH.exists(), 'SMC++/smc_context_resolvers.pine must exist'
    source = _read_resolvers_source()
    assert 'library("smc_context_resolvers", overlay = false)' in source


def test_context_resolvers_imports_required_dependencies() -> None:
    source = _read_resolvers_source()
    for expected_import in EXPECTED_IMPORTS:
        assert expected_import in source


# ── Export surface completeness ────────────────────────────────────────────


def test_context_resolvers_exports_exact_surface() -> None:
    source = _read_resolvers_source()
    export_signatures = _extract_export_signatures(source)

    normalized_actual = [_normalize_ws(sig) for sig in export_signatures]
    normalized_expected = [_normalize_ws(sig) for sig in EXPECTED_EXPORT_SIGNATURES]

    assert len(normalized_actual) == len(normalized_expected), (
        f'Expected {len(normalized_expected)} exports, found {len(normalized_actual)}'
    )

    assert set(normalized_actual) == set(normalized_expected), (
        'Export surface mismatch between expected and actual signatures'
    )


def test_context_resolvers_export_names_are_unique() -> None:
    source = _read_resolvers_source()
    export_signatures = _extract_export_signatures(source)
    names = [_extract_signature_name_and_params(sig)[0] for sig in export_signatures]

    assert len(names) == len(set(names)), 'Duplicate export function names detected'


# ── Signature strictness ───────────────────────────────────────────────────


def test_context_resolvers_signatures_preserve_parameter_names_and_counts() -> None:
    source = _read_resolvers_source()
    export_signatures = _extract_export_signatures(source)

    actual_by_name: dict[str, tuple[str, int]] = {}
    for sig in export_signatures:
        name, params = _extract_signature_name_and_params(sig)
        param_count = 0 if params == '' else len([p for p in params.split(',') if p.strip()])
        actual_by_name[name] = (_normalize_ws(params), param_count)

    for expected_sig in EXPECTED_EXPORT_SIGNATURES:
        name, params = _extract_signature_name_and_params(_normalize_ws(expected_sig))
        expected_count = 0 if params == '' else len([p for p in params.split(',') if p.strip()])

        assert name in actual_by_name, f'Missing export: {name}'
        actual_params, actual_count = actual_by_name[name]

        assert actual_count == expected_count, (
            f'Parameter count drift in {name}: expected {expected_count}, got {actual_count}'
        )
        assert actual_params == _normalize_ws(params), (
            f'Parameter name/order/type drift in {name}: expected "{params}", got "{actual_params}"'
        )


# ── Family grouping checks ────────────────────────────────────────────────


def test_context_resolvers_export_family_distribution_is_stable() -> None:
    source = _read_resolvers_source()
    names = [_extract_signature_name_and_params(sig)[0] for sig in _extract_export_signatures(source)]

    core_narrative_names = {
        'compose_why_now_text',
        'compose_main_risk_text',
        'compose_trade_threshold_text',
    }

    core_names = [
        n
        for n in names
        if n.startswith('resolve_core_')
        or n.startswith('compose_core_')
        or n.startswith('f_parse_')
        or n in core_narrative_names
    ]
    bus_names = [n for n in names if n.startswith('resolve_bus_') or n.startswith('pack_bus_') or n == 'normalize_bus_trend']
    alert_detail_names = [n for n in names if n.startswith('compose_long_') and n.endswith('_alert_detail')]

    assert len(core_names) == 9
    assert len(bus_names) == 54
    assert len(alert_detail_names) == 10


# ── Core import and alias usage ───────────────────────────────────────────


def test_core_engine_imports_context_resolvers_as_cr() -> None:
    source = _read_core_source()
    assert 'import preuss_steffen/smc_context_resolvers/1 as cr' in source


def test_core_engine_uses_cr_alias_calls() -> None:
    source = _read_core_source()
    cr_calls = re.findall(r'\bcr\.([A-Za-z_][A-Za-z0-9_]*)\(', source)

    assert len(cr_calls) >= 50, f'Expected heavy cr alias usage, found only {len(cr_calls)} calls'

    required_calls = [
        'resolve_core_provider_state',
        'resolve_core_bias_text',
        'compose_core_hero_text',
        'pack_bus_counts',
        'resolve_bus_meta_pack',
        'resolve_bus_lean_pack_a',
        'resolve_bus_lean_pack_b',
        'resolve_bus_quality_score_row',
        'resolve_bus_micro_profile_code',
        'compose_long_invalidated_alert_detail',
        'compose_long_watchlist_alert_detail',
    ]
    for fn in required_calls:
        assert fn in cr_calls, f'Core Engine is missing expected cr.{fn}(...) usage'
