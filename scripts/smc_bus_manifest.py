from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen = True)
class BusBinding:
    label: str
    group: str


@dataclass(frozen = True)
class SurfaceDefinition:
    file: str
    script_name: str
    surface_role: str
    contract_tier: str
    consumer_role: str
    validation_target: bool = False
    notes: tuple[str, ...] = ()


@dataclass(frozen = True)
class PreflightTarget:
    file: str
    script_name: str
    check_inputs: bool
    add_to_chart: bool
    min_inputs: int | None = None


SURFACE_ROLE_VALUES: tuple[str, ...] = (
    'lite_primary',
    'pro_primary',
    'companion_operator_only',
    'internal',
    'legacy',
)

CONTRACT_TIER_VALUES: tuple[str, ...] = (
    'lite_and_pro',
    'pro',
    'execution',
    'internal',
    'legacy',
)

CONSUMER_ROLE_VALUES: tuple[str, ...] = (
    'producer',
    'dashboard_companion',
    'execution_wrapper',
    'overlay_companion',
    'context_companion',
    'bridge',
    'legacy_monolith',
    'legacy_split',
)

PRODUCT_CUT_MANIFEST_VERSION = 1
PRODUCT_CUT_ARTIFACT_RELATIVE_PATH = 'artifacts/tradingview/smc_product_cut_manifest.json'
PRODUCT_CUT_SOURCE = 'scripts/smc_bus_manifest.py'

SURFACE_DEFINITIONS: tuple[SurfaceDefinition, ...] = (
    SurfaceDefinition(
        file = 'SMC_Core_Engine.pine',
        script_name = 'SMC Core Engine',
        surface_role = 'lite_primary',
        contract_tier = 'lite_and_pro',
        consumer_role = 'producer',
        validation_target = True,
        notes = (
            'Primary operator surface for the Lite rollout.',
            'Only active producer on the release mainline.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Dashboard.pine',
        script_name = 'SMC Dashboard',
        surface_role = 'pro_primary',
        contract_tier = 'pro',
        consumer_role = 'dashboard_companion',
        validation_target = True,
        notes = (
            'Primary Pro diagnostics surface.',
            'BUS bindings remain operator-only even though the dashboard is part of the main product cut.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Long_Strategy.pine',
        script_name = 'SMC Long Strategy',
        surface_role = 'pro_primary',
        contract_tier = 'execution',
        consumer_role = 'execution_wrapper',
        validation_target = True,
        notes = (
            'Primary execution wrapper on the frozen 8-channel executable contract.',
            'Visible setup controls are product surface; BUS bindings remain operator-only.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Event_Overlay.pine',
        script_name = 'SMC Event Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'overlay_companion',
        notes = (
            'Pro-only event-risk companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Orderflow_Overlay.pine',
        script_name = 'SMC Orderflow Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'overlay_companion',
        notes = (
            'Pro-only orderflow companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Liquidity_Context.pine',
        script_name = 'SMC Liquidity Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only liquidity context companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_HTF_Confluence.pine',
        script_name = 'SMC HTF Confluence',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only HTF context companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Imbalance_Context.pine',
        script_name = 'SMC Imbalance Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only imbalance context companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Structure_Context.pine',
        script_name = 'SMC Structure Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only structure context companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Session_Context.pine',
        script_name = 'SMC Session Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only session context companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Profile_Context.pine',
        script_name = 'SMC Profile Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only profile context companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Liquidity_Structure.pine',
        script_name = 'SMC Liquidity Structure',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        notes = (
            'Pro-only liquidity-structure companion.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_TV_Bridge.pine',
        script_name = 'SMC TV Bridge',
        surface_role = 'internal',
        contract_tier = 'internal',
        consumer_role = 'bridge',
        notes = (
            'Internal bridge helper outside the user-facing Lite/Pro rollout.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC++.pine',
        script_name = 'SMC++',
        surface_role = 'legacy',
        contract_tier = 'legacy',
        consumer_role = 'legacy_monolith',
        notes = (
            'Historical monolith kept for reference, not for the active product cut.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Core_Zones.pine',
        script_name = 'SMC Core OLD',
        surface_role = 'legacy',
        contract_tier = 'legacy',
        consumer_role = 'legacy_split',
        notes = (
            'Deprecated split prototype.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC Core + Zones.pine',
        script_name = 'SMC Core OLD',
        surface_role = 'legacy',
        contract_tier = 'legacy',
        consumer_role = 'legacy_split',
        notes = (
            'Deprecated split prototype.',
        ),
    ),
)

SURFACE_DEFINITIONS_BY_FILE: dict[str, SurfaceDefinition] = {
    surface.file: surface
    for surface in SURFACE_DEFINITIONS
}

ALL_SMC_PINE_FILES: tuple[str, ...] = tuple(surface.file for surface in SURFACE_DEFINITIONS)
MAINLINE_SURFACE_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.surface_role in ('lite_primary', 'pro_primary')
)
ACTIVE_VALIDATION_PINE_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.validation_target
)
LITE_PRIMARY_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.surface_role == 'lite_primary'
)
PRO_PRIMARY_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.surface_role == 'pro_primary'
)
COMPANION_OPERATOR_ONLY_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.surface_role == 'companion_operator_only'
)
INTERNAL_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.surface_role == 'internal'
)
LEGACY_FILES: tuple[str, ...] = tuple(
    surface.file
    for surface in SURFACE_DEFINITIONS
    if surface.surface_role == 'legacy'
)

PREFLIGHT_CORE_DASHBOARD_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget('SMC_Core_Engine.pine', 'SMC Core Engine', False, False),
    PreflightTarget('SMC_Dashboard.pine', 'SMC Dashboard', True, True, 58),
)

PREFLIGHT_MAINLINE_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget('SMC_Core_Engine.pine', 'SMC Core Engine', False, False),
    PreflightTarget('SMC_Dashboard.pine', 'SMC Dashboard', True, True, 58),
    PreflightTarget('SMC_Long_Strategy.pine', 'SMC Long Strategy', True, True, 8),
)

PREFLIGHT_DECISION_FIRST_TARGETS: tuple[PreflightTarget, ...] = PREFLIGHT_MAINLINE_TARGETS


def _surface_payload(surface: SurfaceDefinition) -> dict[str, Any]:
    payload = asdict(surface)
    payload['notes'] = list(surface.notes)
    return payload


def _preflight_target_payload(target: PreflightTarget) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'file': target.file,
        'scriptName': target.script_name,
        'checkInputs': target.check_inputs,
        'addToChart': target.add_to_chart,
    }
    if target.min_inputs is not None:
        payload['minInputs'] = target.min_inputs
    return payload


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
    'ReadyBlockerCode',
    'StrictBlockerCode',
    'VolExpansionState',
    'DdviContextState',
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

C9_REBUILD_BUS_CHANNELS: tuple[str, ...] = ()

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
    'ObjectsCountPack',
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
    'Diagnostic Support',
    'Trade Plan',
    'Detail Surface',
    'Lean Surface',
)

STRATEGY_GROUP_TITLES: tuple[str, ...] = (
    'Operator Bindings - Entry States',
    'Operator Bindings - Trade Plan',
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
    BusBinding('BUS LtfDeltaState', 'g_bus_diag'),
    BusBinding('BUS SafeTrendState', 'g_bus_diag'),
    BusBinding('BUS MicroProfileCode', 'g_bus_diag'),
    BusBinding('BUS ReadyBlockerCode', 'g_bus_diag'),
    BusBinding('BUS StrictBlockerCode', 'g_bus_diag'),
    BusBinding('BUS VolExpansionState', 'g_bus_diag'),
    BusBinding('BUS DdviContextState', 'g_bus_diag'),
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
    BusBinding('BUS ObjectsCountPack', 'g_bus_detail'),
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


def build_product_cut_manifest_payload() -> dict[str, Any]:
    return {
        'manifestVersion': PRODUCT_CUT_MANIFEST_VERSION,
        'source': PRODUCT_CUT_SOURCE,
        'artifactPath': PRODUCT_CUT_ARTIFACT_RELATIVE_PATH,
        'surfaceRoles': [_surface_payload(surface) for surface in SURFACE_DEFINITIONS],
        'surfaceRoleCounts': {
            'lite_primary': len(LITE_PRIMARY_FILES),
            'pro_primary': len(PRO_PRIMARY_FILES),
            'companion_operator_only': len(COMPANION_OPERATOR_ONLY_FILES),
            'internal': len(INTERNAL_FILES),
            'legacy': len(LEGACY_FILES),
        },
        'mainlineSurfaceFiles': list(MAINLINE_SURFACE_FILES),
        'activeValidationFiles': list(ACTIVE_VALIDATION_PINE_FILES),
        'litePrimaryFiles': list(LITE_PRIMARY_FILES),
        'proPrimaryFiles': list(PRO_PRIMARY_FILES),
        'companionOperatorOnlyFiles': list(COMPANION_OPERATOR_ONLY_FILES),
        'internalFiles': list(INTERNAL_FILES),
        'legacyFiles': list(LEGACY_FILES),
        'contracts': {
            'engine': list(ENGINE_BUS_LABELS),
            'executable': list(EXECUTABLE_BUS_LABELS),
            'liteSurface': list(LITE_SURFACE_BUS_LABELS),
            'lite': list(LITE_BUS_LABELS),
            'proOnly': list(PRO_ONLY_BUS_LABELS),
            'dashboardBindings': list(DASHBOARD_BUS_LABELS),
            'strategyBindings': list(STRATEGY_BUS_LABELS),
        },
        'preflightScopes': {
            'smcCoreDashboard': [_preflight_target_payload(target) for target in PREFLIGHT_CORE_DASHBOARD_TARGETS],
            'smcMainline': [_preflight_target_payload(target) for target in PREFLIGHT_MAINLINE_TARGETS],
            'smcDecisionFirst': [_preflight_target_payload(target) for target in PREFLIGHT_DECISION_FIRST_TARGETS],
        },
    }