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


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding = 'utf-8')


def test_dashboard_is_a_bus_only_consumer() -> None:
    source = _read(DASHBOARD_PATH)

    assert 'indicator("SMC Dashboard", "SMC Dash", overlay = true' in source
    assert source.count('input.source(') == 26
    assert 'BUS ZoneActive' in source
    assert 'BUS Armed' in source
    assert 'BUS Confirmed' in source
    assert 'BUS Ready' in source
    assert 'BUS EntryBest' in source
    assert 'BUS EntryStrict' in source
    assert 'BUS Trigger' in source
    assert 'BUS Invalidation' in source
    assert 'BUS QualityScore' in source
    assert 'BUS SourceKind' in source
    assert 'BUS StateCode' in source
    assert 'BUS TrendPack' in source
    assert 'BUS MetaPack' in source
    assert 'BUS HardGatesPackA' in source
    assert 'BUS HardGatesPackB' in source
    assert 'BUS QualityPackA' in source
    assert 'BUS QualityPackB' in source
    assert 'BUS QualityBoundsPack' in source
    assert 'BUS ModulePackA' in source
    assert 'BUS ModulePackB' in source
    assert 'BUS ModulePackC' in source
    assert 'BUS ModulePackD' in source
    assert 'BUS EnginePack' in source
    assert 'BUS StopLevel' in source
    assert 'BUS Target1' in source
    assert 'BUS Target2' in source
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
    assert len(hidden_bus_calls) == 26
    assert 'alertcondition(' not in source
    assert 'dashboard_header(' not in source


def test_legacy_core_duplicates_are_marked_deprecated() -> None:
    for path in LEGACY_CORE_PATHS:
        source = _read(path)
        assert 'DEPRECATED: legacy split prototype.' in source
        assert 'indicator("DEPRECATED SMC Core Prototype", "SMC Core OLD", overlay = true' in source