from __future__ import annotations

from typing import Any


from tests.smc_manifest_test_utils import (
    ROOT,
    extract_group_titles,
    extract_hidden_plot_labels,
    extract_input_bindings,
    load_manifest,
    read_text,
)


MANIFEST = load_manifest()
CORE_PATH = ROOT / 'SMC_Core_Engine.pine'
DASHBOARD_PATH = ROOT / 'SMC_Dashboard.pine'
STRATEGY_PATH = ROOT / 'SMC_Long_Strategy.pine'


def _binding_tuples(bindings: tuple[Any, ...]) -> tuple[tuple[str, str], ...]:
    return tuple((binding.label, binding.group) for binding in bindings)


def _consumer_group_titles(bindings: tuple[tuple[str, str], ...], group_titles: dict[str, str]) -> tuple[str, ...]:
    ordered_groups: list[str] = []
    for _, group in bindings:
        if not ordered_groups or ordered_groups[-1] != group:
            ordered_groups.append(group)
    return tuple(group_titles[group].split(' - ', 1)[1] for group in ordered_groups)


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


def test_engine_hidden_plot_order_matches_manifest() -> None:
    core_source = read_text(CORE_PATH)
    assert extract_hidden_plot_labels(core_source) == MANIFEST.ENGINE_BUS_LABELS


def test_dashboard_binding_order_and_groups_match_manifest() -> None:
    dashboard_source = read_text(DASHBOARD_PATH)
    assert extract_input_bindings(dashboard_source) == _binding_tuples(MANIFEST.DASHBOARD_BUS_BINDINGS)


def test_strategy_binding_order_and_groups_match_manifest() -> None:
    strategy_source = read_text(STRATEGY_PATH)
    assert extract_input_bindings(strategy_source) == _binding_tuples(MANIFEST.STRATEGY_BUS_BINDINGS)


def test_dashboard_group_titles_match_manifest() -> None:
    dashboard_source = read_text(DASHBOARD_PATH)
    group_titles = extract_group_titles(dashboard_source)
    assert _consumer_group_titles(_binding_tuples(MANIFEST.DASHBOARD_BUS_BINDINGS), group_titles) == MANIFEST.DASHBOARD_GROUP_TITLES


def test_strategy_group_titles_match_manifest() -> None:
    strategy_source = read_text(STRATEGY_PATH)
    group_titles = extract_group_titles(strategy_source)
    assert _consumer_group_titles(_binding_tuples(MANIFEST.STRATEGY_BUS_BINDINGS), group_titles) == MANIFEST.STRATEGY_GROUP_TITLES


def test_pro_only_contract_captures_diagnostic_surface() -> None:
    assert 'LtfDeltaState' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'SafeTrendState' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'MicroProfileCode' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ReadyBlockerCode' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'StrictBlockerCode' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'VolExpansionState' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'DdviContextState' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'StretchSupportMask' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LtfBiasHint' in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackD' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ReadyStrictPack' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'VolExpandRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'DdviRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LtfDeltaRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'SwingRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'MicroProfileRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ReadyGateRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'StrictGateRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackA' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackB' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'ModulePackC' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'QualityBoundsPack' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'LongTriggersRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'RiskPlanRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'MicroModifierMask' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'EventRiskRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
    assert 'DebugFlagsRow' not in MANIFEST.PRO_ONLY_BUS_CHANNELS
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
    assert 'ReadyStrictPack' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'LtfDeltaState' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SafeTrendState' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'MicroProfileCode' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ReadyBlockerCode' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'StrictBlockerCode' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolExpansionState' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'DdviContextState' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SessionGateRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'CloseStrengthRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'QualityScoreRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SdConfluenceRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SdOscRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolRegimeRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolSqueezeRow' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'VolExpandRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'DdviRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'LtfDeltaRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SwingRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'QualityBoundsPack' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'LongTriggersRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'EventRiskRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'MicroProfileRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'RiskPlanRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'DebugFlagsRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ReadyGateRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'StrictGateRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'MicroModifierMask' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'DebugStateRow' not in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ZoneObTop' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'SessionVwap' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'StretchSupportMask' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'LtfBiasHint' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ObjectsCountPack' in MANIFEST.DASHBOARD_BUS_CHANNELS
    assert 'ModulePackA' not in MANIFEST.ENGINE_BUS_CHANNELS


def test_c9_cut_partitions_the_pro_only_surface() -> None:
    assert MANIFEST.C9_REBUILD_BUS_CHANNELS == ()
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
        'ObjectsCountPack',
    )
    assert MANIFEST.C9_LEGACY_COMPAT_BUS_CHANNELS == ()
    assert MANIFEST.C9_STABLE_PRO_BUS_CHANNELS == (
        'MetaPack',
        'LtfDeltaState',
        'SafeTrendState',
        'MicroProfileCode',
        'StopLevel',
        'Target1',
        'Target2',
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
        'ReadyBlockerCode',
        'StrictBlockerCode',
        'VolExpansionState',
        'DdviContextState',
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