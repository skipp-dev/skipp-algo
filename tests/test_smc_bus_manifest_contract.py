from __future__ import annotations


from tests.smc_manifest_test_utils import load_manifest


MANIFEST = load_manifest()


def test_lite_contract_stays_a_stable_engine_subset() -> None:
    assert MANIFEST.LITE_BUS_CHANNELS == (
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
    assert set(MANIFEST.LITE_BUS_CHANNELS).issubset(set(MANIFEST.ENGINE_BUS_CHANNELS))
    assert MANIFEST.LITE_BUS_LABELS == tuple(f'BUS {channel}' for channel in MANIFEST.LITE_BUS_CHANNELS)


def test_strategy_contract_matches_the_executable_core() -> None:
    assert MANIFEST.STRATEGY_BUS_CHANNELS == MANIFEST.EXECUTABLE_BUS_CHANNELS
    assert set(MANIFEST.STRATEGY_BUS_CHANNELS).issubset(set(MANIFEST.LITE_BUS_CHANNELS))
    assert MANIFEST.EXECUTABLE_BUS_LABELS == tuple(f'BUS {channel}' for channel in MANIFEST.EXECUTABLE_BUS_CHANNELS)


def test_pro_only_contract_captures_diagnostic_surface() -> None:
    assert 'SdConfluenceRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'VolSqueezeRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'VolExpandRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'DdviRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'StretchSupportMask' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LtfBiasHint' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackA' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackB' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LongTriggersRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ReadyGateRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'SessionGateRow' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ZoneObTop' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'StopLevel' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'Target1' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'Target2' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'HardGatesPackA' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'QualityPackA' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'EnginePack' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LeanPackA' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LeanPackB' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert len(MANIFEST.LITE_BUS_CHANNELS) + len(MANIFEST.PRO_ONLY_BUS_CHANNELS) == len(MANIFEST.ENGINE_BUS_CHANNELS)
    assert MANIFEST.PRO_BUS_CHANNELS == MANIFEST.ENGINE_BUS_CHANNELS


def test_dashboard_contract_moves_to_named_rows_and_detail_channels() -> None:
    assert set(MANIFEST.DASHBOARD_BUS_CHANNELS).issubset(set(MANIFEST.ENGINE_BUS_CHANNELS))
    assert 'HardGatesPackA' not in MANIFEST.ENGINE_BUS_CHANNELS
    assert 'HardGatesPackB' not in MANIFEST.ENGINE_BUS_CHANNELS
    assert 'QualityPackA' not in MANIFEST.ENGINE_BUS_CHANNELS
    assert 'QualityPackB' not in MANIFEST.ENGINE_BUS_CHANNELS
    assert 'ModulePackB' not in MANIFEST.ENGINE_BUS_CHANNELS
    assert 'ModulePackD' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'EnginePack' not in MANIFEST.ENGINE_BUS_CHANNELS
    assert 'SessionGateRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'CloseStrengthRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'QualityScoreRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SdConfluenceRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SdOscRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolRegimeRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolSqueezeRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolExpandRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'DdviRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'LongTriggersRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'RiskPlanRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'DebugFlagsRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ReadyGateRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ZoneObTop' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SessionVwap' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'StretchSupportMask' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'LtfBiasHint' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ModulePackA' not in MANIFEST.ENGINE_BUS_CHANNELS


def test_c9_cut_partitions_the_pro_only_surface() -> None:
    assert MANIFEST.C9_REBUILD_BUS_CHANNELS == (
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
    assert MANIFEST.C9_REDUCE_BUS_CHANNELS == (
        'CloseStrengthRow',
        'EmaSupportRow',
        'AdxRow',
        'RelVolRow',
        'VwapRow',
        'ContextQualityRow',
        'QualityCleanRow',
        'QualityScoreRow',
    )
    assert MANIFEST.C9_DETAIL_BUS_CHANNELS == (
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
    assert MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS == ()
    assert MANIFEST.C9_STABLE_PRO_BUS_CHANNELS == (
        'MetaPack',
        'EventRiskRow',
        'QualityBoundsPack',
        'ModulePackC',
        'StopLevel',
        'Target1',
        'Target2',
    )

    c9_partition = (
        set(MANIFEST.C9_REBUILD_BUS_CHANNELS)
        | set(MANIFEST.C9_REDUCE_BUS_CHANNELS)
        | set(MANIFEST.C9_DETAIL_BUS_CHANNELS)
        | set(MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS)
        | set(MANIFEST.C9_STABLE_PRO_BUS_CHANNELS)
    )
    assert c9_partition == set(MANIFEST.PRO_ONLY_BUS_CHANNELS)
    assert set(MANIFEST.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_REDUCE_BUS_CHANNELS))
    assert set(MANIFEST.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_DETAIL_BUS_CHANNELS))
    assert set(MANIFEST.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS))
    assert set(MANIFEST.C9_REBUILD_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_STABLE_PRO_BUS_CHANNELS))
    assert set(MANIFEST.C9_REDUCE_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_DETAIL_BUS_CHANNELS))
    assert set(MANIFEST.C9_REDUCE_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS))
    assert set(MANIFEST.C9_REDUCE_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_STABLE_PRO_BUS_CHANNELS))
    assert set(MANIFEST.C9_DETAIL_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS))
    assert set(MANIFEST.C9_DETAIL_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_STABLE_PRO_BUS_CHANNELS))
    assert set(MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS).isdisjoint(set(MANIFEST.C9_STABLE_PRO_BUS_CHANNELS))
