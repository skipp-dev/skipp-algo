from __future__ import annotations

import importlib.util
import pathlib
import re
import sys
from types import ModuleType


ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = ROOT / 'SMC_Core_Engine.pine'
DASHBOARD_PATH = ROOT / 'SMC_Dashboard.pine'
STRATEGY_PATH = ROOT / 'SMC_Long_Strategy.pine'
MANIFEST_PATH = ROOT / 'scripts' / 'smc_bus_manifest.py'
LEGACY_CORE_PATHS = [
    ROOT / 'SMC Core + Zones.pine',
    ROOT / 'SMC_Core_Zones.pine',
]


def _load_manifest() -> ModuleType:
    spec = importlib.util.spec_from_file_location('smc_bus_manifest', MANIFEST_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MANIFEST = _load_manifest()
EXPECTED_ENGINE_BUS_LABELS = list(MANIFEST.ENGINE_BUS_LABELS)
EXPECTED_DASHBOARD_BUS_LABELS = list(MANIFEST.DASHBOARD_BUS_LABELS)


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding = 'utf-8')


def test_dashboard_is_a_bus_only_consumer() -> None:
    source = _read(DASHBOARD_PATH)

    assert 'indicator("SMC Dashboard", "SMC Dash", overlay = true' in source
    assert source.count('input.source(') == len(EXPECTED_DASHBOARD_BUS_LABELS)
    for label in EXPECTED_DASHBOARD_BUS_LABELS:
        assert label in source
    assert 'BUS HardGatesPackA' not in source
    assert 'BUS HardGatesPackB' not in source
    assert 'BUS QualityPackA' not in source
    assert 'BUS QualityPackB' not in source
    assert 'BUS EnginePack' not in source
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
    assert len(bus_export_calls) == 5
    assert "plot(bus_trigger_level, 'BUS Trigger', display = display.none)" in source
    assert "plot(bus_invalidation_level, 'BUS Invalidation', display = display.none)" in source
    assert "plot(bus_stop_level, 'BUS StopLevel', display = display.none)" in source
    assert "plot(bus_target_1, 'BUS Target1', display = display.none)" in source
    assert "plot(bus_target_2, 'BUS Target2', display = display.none)" in source
    hidden_bus_calls = re.findall(r"plot\([^\n]+display\s*=\s*display\.none\)", source)
    assert len(hidden_bus_calls) == len(EXPECTED_ENGINE_BUS_LABELS)
    assert 'alertcondition(' not in source
    assert 'dashboard_header(' not in source


def test_legacy_core_duplicates_are_marked_deprecated() -> None:
    for path in LEGACY_CORE_PATHS:
        source = _read(path)
        assert 'DEPRECATED: legacy split prototype.' in source
        assert 'indicator("DEPRECATED SMC Core Prototype", "SMC Core OLD", overlay = true' in source