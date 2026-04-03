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
    'HardGatesPackA',
    'HardGatesPackB',
    'EventRiskRow',
    'QualityPackA',
    'QualityPackB',
    'QualityBoundsPack',
    'ModulePackA',
    'ModulePackB',
    'ModulePackC',
    'ModulePackD',
    'EnginePack',
    'StopLevel',
    'Target1',
    'Target2',
    'LeanPackA',
    'LeanPackB',
)

ENGINE_BUS_LABELS: tuple[str, ...] = tuple(f'BUS {channel}' for channel in ENGINE_BUS_CHANNELS)


DASHBOARD_GROUP_TITLES: tuple[str, ...] = (
    'Lifecycle',
    'Diagnostic Packs',
    'Trade Plan',
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
    BusBinding('BUS HardGatesPackA', 'g_bus_diag'),
    BusBinding('BUS HardGatesPackB', 'g_bus_diag'),
    BusBinding('BUS EventRiskRow', 'g_bus_diag'),
    BusBinding('BUS QualityPackA', 'g_bus_diag'),
    BusBinding('BUS QualityPackB', 'g_bus_diag'),
    BusBinding('BUS QualityBoundsPack', 'g_bus_diag'),
    BusBinding('BUS ModulePackA', 'g_bus_diag'),
    BusBinding('BUS ModulePackB', 'g_bus_diag'),
    BusBinding('BUS ModulePackC', 'g_bus_diag'),
    BusBinding('BUS ModulePackD', 'g_bus_diag'),
    BusBinding('BUS EnginePack', 'g_bus_diag'),
    BusBinding('BUS StopLevel', 'g_bus_plan'),
    BusBinding('BUS Target1', 'g_bus_plan'),
    BusBinding('BUS Target2', 'g_bus_plan'),
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