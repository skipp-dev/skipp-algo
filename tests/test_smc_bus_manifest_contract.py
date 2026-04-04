from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType


ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / 'scripts' / 'smc_bus_manifest.py'


def _load_manifest() -> ModuleType:
    spec = importlib.util.spec_from_file_location('smc_bus_manifest', MANIFEST_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_lite_contract_stays_a_stable_engine_subset() -> None:
    manifest = _load_manifest()

    assert manifest.LITE_BUS_CHANNELS == (
        'ZoneActive',
        'Armed',
        'Confirmed',
        'Ready',
        'EntryBest',
        'EntryStrict',
        'Trigger',
        'Invalidation',
        'QualityScore',
        'SourceKind',
        'StateCode',
        'TrendPack',
        'LeanPackA',
        'LeanPackB',
    )
    assert set(manifest.LITE_BUS_CHANNELS).issubset(set(manifest.ENGINE_BUS_CHANNELS))
    assert manifest.LITE_BUS_LABELS == tuple(f'BUS {channel}' for channel in manifest.LITE_BUS_CHANNELS)


def test_strategy_contract_matches_the_executable_core() -> None:
    manifest = _load_manifest()

    assert manifest.STRATEGY_BUS_CHANNELS == manifest.EXECUTABLE_BUS_CHANNELS
    assert set(manifest.STRATEGY_BUS_CHANNELS).issubset(set(manifest.LITE_BUS_CHANNELS))
    assert manifest.EXECUTABLE_BUS_LABELS == tuple(f'BUS {channel}' for channel in manifest.EXECUTABLE_BUS_CHANNELS)


def test_pro_only_contract_captures_diagnostic_surface() -> None:
    manifest = _load_manifest()

    assert 'SdConfluenceRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'VolSqueezeRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'VolExpandRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'DdviRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'StretchSupportMask' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'LtfBiasHint' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackA' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackB' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'LongTriggersRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'ReadyGateRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'SessionGateRow' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'ZoneObTop' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'StopLevel' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'Target1' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'Target2' in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'HardGatesPackA' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'QualityPackA' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'EnginePack' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'LeanPackA' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert 'LeanPackB' not in manifest.PRO_ONLY_BUS_CHANNELS
    assert len(manifest.LITE_BUS_CHANNELS) + len(manifest.PRO_ONLY_BUS_CHANNELS) == len(manifest.ENGINE_BUS_CHANNELS)
    assert manifest.PRO_BUS_CHANNELS == manifest.ENGINE_BUS_CHANNELS


def test_dashboard_contract_moves_to_named_rows_and_detail_channels() -> None:
    manifest = _load_manifest()

    assert set(manifest.DASHBOARD_BUS_CHANNELS).issubset(set(manifest.ENGINE_BUS_CHANNELS))
    assert 'HardGatesPackA' not in manifest.ENGINE_BUS_CHANNELS
    assert 'HardGatesPackB' not in manifest.ENGINE_BUS_CHANNELS
    assert 'QualityPackA' not in manifest.ENGINE_BUS_CHANNELS
    assert 'QualityPackB' not in manifest.ENGINE_BUS_CHANNELS
    assert 'ModulePackB' not in manifest.ENGINE_BUS_CHANNELS
    assert 'ModulePackD' not in manifest.DASHBOARD_BUS_CHANNELS
    assert 'EnginePack' not in manifest.ENGINE_BUS_CHANNELS
    assert 'SessionGateRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'CloseStrengthRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'QualityScoreRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'SdConfluenceRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'SdOscRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'VolRegimeRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'VolSqueezeRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'VolExpandRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'DdviRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'LongTriggersRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'RiskPlanRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'DebugFlagsRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'ReadyGateRow' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'ZoneObTop' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'SessionVwap' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'StretchSupportMask' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'LtfBiasHint' in manifest.DASHBOARD_BUS_CHANNELS
    assert 'ModulePackA' not in manifest.ENGINE_BUS_CHANNELS


def test_c9_cut_partitions_the_pro_only_surface() -> None:
    manifest = _load_manifest()

    assert manifest.C9_REBUILD_BUS_CHANNELS == (
        'SessionGateRow',
        'MarketGateRow',
        'VolaGateRow',
        'MicroSessionGateRow',
        'MicroFreshRow',
        'VolumeDataRow',
        'QualityEnvRow',
        'QualityStrictRow',
        'SdConfluenceRow',
        'SdOscRow',
        'VolRegimeRow',
        'VolSqueezeRow',
        'VolExpandRow',
        'DdviRow',
        'LongTriggersRow',
        'RiskPlanRow',
        'DebugFlagsRow',
        'ReadyGateRow',
        'StrictGateRow',
        'DebugStateRow',
        'MicroModifierMask',
    )
    assert manifest.C9_REDUCE_BUS_CHANNELS == (
        'CloseStrengthRow',
        'EmaSupportRow',
        'AdxRow',
        'RelVolRow',
        'VwapRow',
        'ContextQualityRow',
        'QualityCleanRow',
        'QualityScoreRow',
    )
    assert manifest.C9_DETAIL_BUS_CHANNELS == (
        'ZoneObTop',
        'ZoneObBottom',
        'ZoneFvgTop',
        'ZoneFvgBottom',
        'SessionVwap',
        'AdxValue',
        'RelVolValue',
        'StretchZ',
        'StretchSupportMask',
        'LtfBullShare',
        'LtfBiasHint',
        'LtfVolumeDelta',
    )
    assert manifest.C9_LEGACY_COMPAT_BUS_CHANNELS == ()
    assert manifest.C9_STABLE_PRO_BUS_CHANNELS == (
        'MetaPack',
        'EventRiskRow',
        'QualityBoundsPack',
        'ModulePackC',
        'StopLevel',
        'Target1',
        'Target2',
    )

    c9_partition = (
        set(manifest.C9_REBUILD_BUS_CHANNELS)
        | set(manifest.C9_REDUCE_BUS_CHANNELS)
        | set(manifest.C9_DETAIL_BUS_CHANNELS)
        | set(manifest.C9_LEGACY_COMPAT_BUS_CHANNELS)
        | set(manifest.C9_STABLE_PRO_BUS_CHANNELS)
    )
    assert c9_partition == set(manifest.PRO_ONLY_BUS_CHANNELS)
    assert set(manifest.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(manifest.C9_REDUCE_BUS_CHANNELS))
    assert set(manifest.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(manifest.C9_DETAIL_BUS_CHANNELS))
    assert set(manifest.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(manifest.C9_LEGACY_COMPAT_BUS_CHANNELS))
    assert set(manifest.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(manifest.C9_STABLE_PRO_BUS_CHANNELS))
    assert set(manifest.C9_REDUCE_BUS_CHANNELS).isdisjoint(set(manifest.C9_DETAIL_BUS_CHANNELS))
    assert set(manifest.C9_REDUCE_BUS_CHANNELS).isdisjoint(set(manifest.C9_LEGACY_COMPAT_BUS_CHANNELS))
    assert set(manifest.C9_REDUCE_BUS_CHANNELS).isdisjoint(set(manifest.C9_STABLE_PRO_BUS_CHANNELS))
    assert set(manifest.C9_DETAIL_BUS_CHANNELS).isdisjoint(set(manifest.C9_LEGACY_COMPAT_BUS_CHANNELS))
    assert set(manifest.C9_DETAIL_BUS_CHANNELS).isdisjoint(set(manifest.C9_STABLE_PRO_BUS_CHANNELS))
    assert set(manifest.C9_LEGACY_COMPAT_BUS_CHANNELS).isdisjoint(set(manifest.C9_STABLE_PRO_BUS_CHANNELS))
