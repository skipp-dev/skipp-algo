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
