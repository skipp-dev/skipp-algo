from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / 'SMC_Core_Engine.pine'


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

    expected_bus_labels = [
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
    ]

    hidden_bus_calls = re.findall(r"plot\([^\n]+display\s*=\s*display\.none\)", source)
    assert len(hidden_bus_calls) == len(expected_bus_labels)

    for label in expected_bus_labels:
        assert f"'{label}'" in source

    assert 'pack_bus_row(' in source
    assert 'pack_bus_four(' in source
    assert 'pack_bus_trend_set(' in source


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

    assert "plot(long_target_2, 'BUS Target2', display = display.none)" in source
    assert source.endswith('/////////////////////////////////////////////////////////////////////////////////')
    assert "plot(long_target_2, 'BUS Target2', display = display.none)\n\n/////////////////////////////////////////////////////////////////////////////////\n//#endregion                      IMPLEMENTATION\n/////////////////////////////////////////////////////////////////////////////////" in source
