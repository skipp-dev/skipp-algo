from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / 'SMC_Core_Engine.pine'
DASHBOARD_PATH = ROOT / 'SMC_Dashboard.pine'
STRATEGY_PATH = ROOT / 'SMC_Long_Strategy.pine'
LEGACY_CORE_PATHS = [
    ROOT / 'SMC Core + Zones.pine',
    ROOT / 'SMC_Core_Zones.pine',
]
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


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding = 'utf-8')


def test_dashboard_is_a_bus_only_consumer() -> None:
    source = _read(DASHBOARD_PATH)

    assert 'indicator("SMC Dashboard", "SMC Dash", overlay = true' in source
    assert source.count('input.source(') == len(EXPECTED_BUS_LABELS)
    for label in EXPECTED_BUS_LABELS:
        assert label in source
    assert 'n/a - not on bus' not in source

    assert 'import preuss_steffen/' not in source
    assert 'detect_structure' not in source
    assert 'track_obs' not in source
    assert 'OrderBlock' not in source
    assert 'request.security' not in source


def test_strategy_is_a_bus_only_consumer() -> None:
    source = _read(STRATEGY_PATH)

    assert 'strategy("SMC Long Strategy", overlay = true' in source
    assert source.count('input.source(') == 8
    assert 'strategy.entry("L", strategy.long, stop = src_trigger)' in source
    assert 'var float active_invalidation = na' in source
    assert 'if strategy.position_size > 0 and strategy.position_size[1] <= 0' in source
    assert 'strategy.exit("L Exit", "L", stop = exit_stop, limit = exit_limit)' in source

    assert 'import preuss_steffen/' not in source
    assert 'detect_structure' not in source
    assert 'track_obs' not in source
    assert 'OrderBlock' not in source
    assert 'request.security' not in source


def test_core_remains_the_only_active_producer() -> None:
    source = _read(CORE_PATH)

    assert 'indicator("SMC Core Engine", "SMC Core", overlay = true' in source
    bus_export_calls = re.findall(r"plot\(bus_[^\n]+display\s*=\s*display\.none\)", source)
    assert len(bus_export_calls) == 0
    hidden_bus_calls = re.findall(r"plot\([^\n]+display\s*=\s*display\.none\)", source)
    assert len(hidden_bus_calls) == len(EXPECTED_BUS_LABELS)
    assert 'alertcondition(' not in source
    assert 'dashboard_header(' not in source


def test_legacy_core_duplicates_are_marked_deprecated() -> None:
    for path in LEGACY_CORE_PATHS:
        source = _read(path)
        assert 'DEPRECATED: legacy split prototype.' in source
        assert 'indicator("DEPRECATED SMC Core Prototype", "SMC Core OLD", overlay = true' in source