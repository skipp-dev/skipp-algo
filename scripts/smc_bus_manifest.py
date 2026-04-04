from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen = True)
class BusBinding:
    label: str
    group: str


ACTIVE_VALIDATION_PINE_FILES: tuple[str, ...] = (
    'SMC_Core_Engine.pine',
    'SMC_Dashboard.pine',
    'SMC_Long_Strategy.pine',
)


ENGINE_BUS_CHANNELS: tuple[str, ...] = (
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
    'MetaPack',
    'EventRiskRow',
    'QualityBoundsPack',
    'ModulePackC',
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
    'CloseStrengthRow',
    'EmaSupportRow',
    'AdxRow',
    'RelVolRow',
    'VwapRow',
    'ContextQualityRow',
    'QualityCleanRow',
    'QualityScoreRow',
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
    'LeanPackA',
    'LeanPackB',
)

ENGINE_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in ENGINE_BUS_CHANNELS)


EXECUTABLE_BUS_CHANNELS: tuple[str, ...] = (
    'Armed',
    'Confirmed',
    'Ready',
    'EntryBest',
    'EntryStrict',
    'QualityScore',
    'Trigger',
    'Invalidation',
)

LITE_SURFACE_BUS_CHANNELS: tuple[str, ...] = (
    'ZoneActive',
    'SourceKind',
    'StateCode',
    'TrendPack',
    'LeanPackA',
    'LeanPackB',
)

LITE_BUS_CHANNELS: tuple[str, ...] = (
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

PRO_BUS_CHANNELS: tuple[str, ...] = ENGINE_BUS_CHANNELS
PRO_ONLY_BUS_CHANNELS: tuple[str, ...] = tuple(
    channel for channel in ENGINE_BUS_CHANNELS if channel not in LITE_BUS_CHANNELS
)

C9_REBUILD_BUS_CHANNELS: tuple[str, ...] = (
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

C9_REDUCE_BUS_CHANNELS: tuple[str, ...] = (
    'CloseStrengthRow',
    'EmaSupportRow',
    'AdxRow',
    'RelVolRow',
    'VwapRow',
    'ContextQualityRow',
    'QualityCleanRow',
    'QualityScoreRow',
)

C9_DETAIL_BUS_CHANNELS: tuple[str, ...] = (
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

C9_LEGACY_COMPAT_BUS_CHANNELS: tuple[str, ...] = ()

C9_STABLE_PRO_BUS_CHANNELS: tuple[str, ...] = tuple(
    channel
    for channel in PRO_ONLY_BUS_CHANNELS
    if channel not in C9_REBUILD_BUS_CHANNELS
    and channel not in C9_REDUCE_BUS_CHANNELS
    and channel not in C9_DETAIL_BUS_CHANNELS
    and channel not in C9_LEGACY_COMPAT_BUS_CHANNELS
)

EXECUTABLE_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in EXECUTABLE_BUS_CHANNELS)
LITE_SURFACE_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in LITE_SURFACE_BUS_CHANNELS)
LITE_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in LITE_BUS_CHANNELS)
PRO_BUS_LABELS: tuple[str, ...] = ENGINE_BUS_LABELS
PRO_ONLY_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in PRO_ONLY_BUS_CHANNELS)
C9_REBUILD_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in C9_REBUILD_BUS_CHANNELS)
C9_REDUCE_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in C9_REDUCE_BUS_CHANNELS)
C9_DETAIL_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in C9_DETAIL_BUS_CHANNELS)
C9_LEGACY_COMPAT_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in C9_LEGACY_COMPAT_BUS_CHANNELS)
C9_STABLE_PRO_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in C9_STABLE_PRO_BUS_CHANNELS)


DASHBOARD_GROUP_TITLES: tuple[str, ...] = (
    'Lifecycle',
    'Diagnostic Rows',
    'Diagnostic Packs',
    'Trade Plan',
    'Detail Surface',
    'Lean Surface',
)

STRATEGY_GROUP_TITLES: tuple[str, ...] = (
    'Entry States',
    'Trade Plan',
)


DASHBOARD_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS ZoneActive', 'g_bus_lifecycle'),
    BusBinding('BUS Armed', 'g_bus_lifecycle'),
    BusBinding('BUS Confirmed', 'g_bus_lifecycle'),
    BusBinding('BUS Ready', 'g_bus_lifecycle'),
    BusBinding('BUS EntryBest', 'g_bus_lifecycle'),
    BusBinding('BUS EntryStrict', 'g_bus_lifecycle'),
    BusBinding('BUS Trigger', 'g_bus_lifecycle'),
    BusBinding('BUS Invalidation', 'g_bus_lifecycle'),
    BusBinding('BUS QualityScore', 'g_bus_lifecycle'),
    BusBinding('BUS SourceKind', 'g_bus_lifecycle'),
    BusBinding('BUS StateCode', 'g_bus_lifecycle'),
    BusBinding('BUS TrendPack', 'g_bus_lifecycle'),
    BusBinding('BUS MetaPack', 'g_bus_lifecycle'),
    BusBinding('BUS SessionGateRow', 'g_bus_diag_rows'),
    BusBinding('BUS MarketGateRow', 'g_bus_diag_rows'),
    BusBinding('BUS VolaGateRow', 'g_bus_diag_rows'),
    BusBinding('BUS MicroSessionGateRow', 'g_bus_diag_rows'),
    BusBinding('BUS MicroFreshRow', 'g_bus_diag_rows'),
    BusBinding('BUS VolumeDataRow', 'g_bus_diag_rows'),
    BusBinding('BUS QualityEnvRow', 'g_bus_diag_rows'),
    BusBinding('BUS QualityStrictRow', 'g_bus_diag_rows'),
    BusBinding('BUS CloseStrengthRow', 'g_bus_diag_rows'),
    BusBinding('BUS EmaSupportRow', 'g_bus_diag_rows'),
    BusBinding('BUS AdxRow', 'g_bus_diag_rows'),
    BusBinding('BUS RelVolRow', 'g_bus_diag_rows'),
    BusBinding('BUS VwapRow', 'g_bus_diag_rows'),
    BusBinding('BUS ContextQualityRow', 'g_bus_diag_rows'),
    BusBinding('BUS QualityCleanRow', 'g_bus_diag_rows'),
    BusBinding('BUS QualityScoreRow', 'g_bus_diag_rows'),
    BusBinding('BUS SdConfluenceRow', 'g_bus_diag_rows'),
    BusBinding('BUS SdOscRow', 'g_bus_diag_rows'),
    BusBinding('BUS VolRegimeRow', 'g_bus_diag_rows'),
    BusBinding('BUS VolSqueezeRow', 'g_bus_diag_rows'),
    BusBinding('BUS VolExpandRow', 'g_bus_diag_rows'),
    BusBinding('BUS DdviRow', 'g_bus_diag_rows'),
    BusBinding('BUS EventRiskRow', 'g_bus_diag'),
    BusBinding('BUS QualityBoundsPack', 'g_bus_diag'),
    BusBinding('BUS ModulePackC', 'g_bus_diag'),
    BusBinding('BUS LongTriggersRow', 'g_bus_diag_rows'),
    BusBinding('BUS RiskPlanRow', 'g_bus_diag_rows'),
    BusBinding('BUS DebugFlagsRow', 'g_bus_diag_rows'),
    BusBinding('BUS ReadyGateRow', 'g_bus_diag_rows'),
    BusBinding('BUS StrictGateRow', 'g_bus_diag_rows'),
    BusBinding('BUS DebugStateRow', 'g_bus_diag_rows'),
    BusBinding('BUS MicroModifierMask', 'g_bus_diag_rows'),
    BusBinding('BUS StopLevel', 'g_bus_plan'),
    BusBinding('BUS Target1', 'g_bus_plan'),
    BusBinding('BUS Target2', 'g_bus_plan'),
    BusBinding('BUS ZoneObTop', 'g_bus_detail'),
    BusBinding('BUS ZoneObBottom', 'g_bus_detail'),
    BusBinding('BUS ZoneFvgTop', 'g_bus_detail'),
    BusBinding('BUS ZoneFvgBottom', 'g_bus_detail'),
    BusBinding('BUS SessionVwap', 'g_bus_detail'),
    BusBinding('BUS AdxValue', 'g_bus_detail'),
    BusBinding('BUS RelVolValue', 'g_bus_detail'),
    BusBinding('BUS StretchZ', 'g_bus_detail'),
    BusBinding('BUS StretchSupportMask', 'g_bus_detail'),
    BusBinding('BUS LtfBullShare', 'g_bus_detail'),
    BusBinding('BUS LtfBiasHint', 'g_bus_detail'),
    BusBinding('BUS LtfVolumeDelta', 'g_bus_detail'),
    BusBinding('BUS LeanPackA', 'g_bus_lean'),
    BusBinding('BUS LeanPackB', 'g_bus_lean'),
)

STRATEGY_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS Armed', 'g_bus_entry'),
    BusBinding('BUS Confirmed', 'g_bus_entry'),
    BusBinding('BUS Ready', 'g_bus_entry'),
    BusBinding('BUS EntryBest', 'g_bus_entry'),
    BusBinding('BUS EntryStrict', 'g_bus_entry'),
    BusBinding('BUS QualityScore', 'g_bus_entry'),
    BusBinding('BUS Trigger', 'g_bus_plan'),
    BusBinding('BUS Invalidation', 'g_bus_plan'),
)


DASHBOARD_BUS_LABELS: tuple[str, ...] = tuple(binding.label for binding in DASHBOARD_BUS_BINDINGS)
STRATEGY_BUS_LABELS: tuple[str, ...] = tuple(binding.label for binding in STRATEGY_BUS_BINDINGS)

DASHBOARD_BUS_CHANNELS: tuple[str, ...] = tuple(label.removeprefix('BUS ') for label in DASHBOARD_BUS_LABELS)
STRATEGY_BUS_CHANNELS: tuple[str, ...] = tuple(label.removeprefix('BUS ') for label in STRATEGY_BUS_LABELS)