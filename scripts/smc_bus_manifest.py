from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen = True)
class BusBinding:
    label: str
    group: str
    tier: str = 'diagnostic'  # 'critical' | 'diagnostic'


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
    saved_script_name: str | None = None
    binding_contract_key: str | None = None


@dataclass(frozen = True)
class ValidationEvidenceCapture:
    key: str
    file: str
    script_name: str
    report_label: str
    runbook_label_en: str
    runbook_label_de: str
    notes: tuple[str, ...] = ()


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
    'setup_utility',
    'confluence_hub',
    'mobile_companion',
    'bridge',
    'legacy_monolith',
    'legacy_split',
    # Companion exits / hold-management surfaces (added with v3 phase 1
    # classification of SMC_Exit_Signal.pine + SMC_Hold_Manager.pine).
    'exit_companion',
)

PRODUCT_CUT_MANIFEST_VERSION = 2
PRODUCT_CUT_ARTIFACT_RELATIVE_PATH = 'artifacts/tradingview/smc_product_cut_manifest.json'
PRODUCT_CUT_SOURCE = 'scripts/smc_bus_manifest.py'
VALIDATION_EVIDENCE_CAPTURE_MODE = 'rendered_chart_only'
VALIDATION_EVIDENCE_EDITOR_SCREENSHOTS_ALLOWED = False

DEPRECATED_FIELD_POLICY: dict[str, Any] = {
    'mode': 'compatibility_only',
    'preferredFieldVersion': 'v5.5c',
    'extensionAllowed': False,
    'sunset_date': '2026-04-14',
    'sunset_action': 'removed',
    'deprecatedGroups': [],
}

SURFACE_DEFINITIONS: tuple[SurfaceDefinition, ...] = (
    SurfaceDefinition(
        file = 'SMC_Core_Engine.pine',
        script_name = 'SMC Core',
        surface_role = 'lite_primary',
        contract_tier = 'lite_and_pro',
        consumer_role = 'producer',
        validation_target = True,
        notes = (
            'Primary Focus View surface for the Lite rollout.',
            'Only active producer on the release mainline.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Dashboard.pine',
        script_name = 'SMC Decision Board',
        surface_role = 'pro_primary',
        contract_tier = 'pro',
        consumer_role = 'dashboard_companion',
        validation_target = True,
        notes = (
            'Primary linked decision companion surface.',
            'BUS bindings remain operator-only even though the dashboard is part of the main product cut.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Long_Strategy.pine',
        script_name = 'SMC Execution',
        surface_role = 'pro_primary',
        contract_tier = 'execution',
        consumer_role = 'execution_wrapper',
        validation_target = True,
        notes = (
            'Primary execution surface on the frozen 8-channel executable contract.',
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
        file = 'SMC_Setup_Check.pine',
        script_name = 'SMC Setup Check',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'setup_utility',
        notes = (
            'BUS connection validator — guides new users through initial setup.',
            'Reads 6 critical BUS channels and shows connection status with next-step instructions.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Mobile_Dashboard.pine',
        script_name = 'SMC Mobile',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'mobile_companion',
        notes = (
            'Mobile-first dashboard — 4-row table, no overlays.',
            'Traffic light + levels + market context + quality score.',
        ),
    ),
    SurfaceDefinition(
        file = 'SkippALGO_Confluence.pine',
        script_name = 'SkippALGO Confluence',
        surface_role = 'pro_primary',
        contract_tier = 'pro',
        consumer_role = 'confluence_hub',
        notes = (
            'Multi-signal confluence aggregator (SMC BUS + trend + momentum + mean-reversion).',
            'Produces 0-100 confluence score with traffic-light overlay.',
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
    # New companion surfaces shipped 2026-04-30 (commit 68e1aac0):
    # BE-after-T1 + Simple-Mode + Trade-Mgmt rows feature bundle.
    # Classified here so the manifest contract pin
    # ``test_every_pine_file_is_classified_or_explicitly_excluded`` no
    # longer flags them as unclassified drift.
    # Discovered via SMC review v3 phase 1.
    SurfaceDefinition(
        file = 'SMC_Breakout_Overlay.pine',
        script_name = 'SMC Breakout Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'overlay_companion',
        notes = (
            'LonesomeTheBlue-style breakout/breakdown box renderer over '
            'mp.BOS_* / mp.CHoCH_* signals. Pure visual, no new detection.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Exit_Signal.pine',
        script_name = 'SMC Exit Signal',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'exit_companion',
        notes = (
            'Beginner-facing exit companion: STOP / TP1 / TP2 / DEFENSIVE '
            'EXIT alerts driven by linked SMC Core BUS outputs. No '
            'library import — fully BUS-driven.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Hold_Manager.pine',
        script_name = 'SMC Hold-Manager v1',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'exit_companion',
        notes = (
            'Read-only hold-management overlay with ATR-Chandelier trail, '
            'BE-after-T1, optional Simple-Mode, and time-stop. Imports '
            'skippALGO/smc_micro_profiles_generated (separate namespace '
            'from preuss_steffen — not auto-pinned by library refresh).',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_VRVP_Overlay.pine',
        script_name = 'SMC VRVP Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'overlay_companion',
        notes = (
            'Visible-Range Volume Profile companion: histogram + '
            'multi-POC + VAH/VAL. No library import — fully self-contained.',
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

# Non-SMC Pine files that are explicitly outside the SMC product-cut governance.
# These are personal/historical tools, not part of the SMC mainline, companion, or
# legacy hierarchy.  Keeping them enumerated here prevents unclassified drift.
NON_SMC_PINE_FILES: frozenset[str] = frozenset({
    'BFI-Reversal.pine',
    'Breakout_Finder_Intelligent.pine',
    'BTC 3m EV Scalper BALANCED (Harmonized).pine',
    'CHOCH-Base_Indikator.pine',
    'CHOCH-Base_Strategy.pine',
    'CHOCH-Indicator.pine',
    'CHOCH-Strategy.pine',
    'CHoCH.pine',
    'QuickALGO.pine',
    'REV-BUY.pine',
    'REV-Ladder-CHoCH.pine',
    'REV-Ladder.pine',
    # NOTE: SMC_Breakout_Overlay / SMC_Exit_Signal / SMC_Hold_Manager /
    # SMC_VRVP_Overlay used to live in this fallback list as
    # "tracked but unclassified" markers. They have since been promoted into
    # SURFACE_DEFINITIONS (companion_operator_only / overlay_companion +
    # exit_companion) so they MUST be removed here — leaving them in both
    # lists trips test_non_smc_pine_files_are_disjoint_from_surface_definitions.
    'USI_Lines.pine',
    'USI_Strategy.pine',
    'USI-CHOCH.pine',
    'USI-Flip.pine',
    'USI-REV-BUY.pine',
    'USI.pine',
    'Volume_Weighted_Trend_SkippAlgo.pine',
    'VWAP_Long_Reclaim_Indicator.pine',
    'VWAP_Long_Reclaim_Strategy.pine',
    'VWAP_Reclaim_Indicator.pine',
    'VWAP_Reclaim_Strategy.pine',
    'test_div.pine',
})


def validate_surface_definitions() -> list[str]:
    """Return a list of validation errors for SURFACE_DEFINITIONS.

    Checks:
    - surface_role values are from SURFACE_ROLE_VALUES
    - contract_tier values are from CONTRACT_TIER_VALUES
    - consumer_role values are from CONSUMER_ROLE_VALUES
    - No duplicate files
    - Mainline hierarchy: exactly 1 lite_primary, at least 1 pro_primary
    """
    errors: list[str] = []
    seen_files: set[str] = set()

    for surface in SURFACE_DEFINITIONS:
        if surface.surface_role not in SURFACE_ROLE_VALUES:
            errors.append(f"{surface.file}: invalid surface_role '{surface.surface_role}'")
        if surface.contract_tier not in CONTRACT_TIER_VALUES:
            errors.append(f"{surface.file}: invalid contract_tier '{surface.contract_tier}'")
        if surface.consumer_role not in CONSUMER_ROLE_VALUES:
            errors.append(f"{surface.file}: invalid consumer_role '{surface.consumer_role}'")
        if surface.file in seen_files:
            errors.append(f"{surface.file}: duplicate entry")
        seen_files.add(surface.file)

    lite_primary_count = sum(1 for s in SURFACE_DEFINITIONS if s.surface_role == 'lite_primary')
    pro_primary_count = sum(1 for s in SURFACE_DEFINITIONS if s.surface_role == 'pro_primary')
    if lite_primary_count != 1:
        errors.append(f"expected exactly 1 lite_primary, got {lite_primary_count}")
    if pro_primary_count < 1:
        errors.append(f"expected at least 1 pro_primary, got {pro_primary_count}")

    return errors

# Canonical TradingView script identity per docs/SMC_PRODUCT_IDENTITY.md.
# Names MUST be unique enough to never appear as a substring of any third-party
# script title in TradingView's user library. Rationale: 2026-04-22 collision
# where the previous bare name 'SMC Execution' substring-matched the public
# 'SMC Execution Engine (Free) by @abdallacrypto v1.3' script during the
# settings-dialog identity check, causing the preflight to read the wrong
# script's input bindings.
PREFLIGHT_CORE_DASHBOARD_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget('SMC_Core_Engine.pine', 'SMC Core', False, False),
    PreflightTarget('SMC_Dashboard.pine', 'SMC Long-Dip Dashboard v7', True, True, 58, 'SMC Long-Dip Dashboard v7', 'dashboardBindings'),
)

PREFLIGHT_MAINLINE_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget('SMC_Core_Engine.pine', 'SMC Core', False, False),
    PreflightTarget('SMC_Dashboard.pine', 'SMC Long-Dip Dashboard v7', True, True, 58, 'SMC Long-Dip Dashboard v7', 'dashboardBindings'),
    PreflightTarget('SMC_Long_Strategy.pine', 'SMC Long-Dip Strategy v7', True, True, 8, 'SMC Long-Dip Strategy v7', 'strategyBindings'),
)

PREFLIGHT_DECISION_FIRST_TARGETS: tuple[PreflightTarget, ...] = PREFLIGHT_MAINLINE_TARGETS

VALIDATION_EVIDENCE_CAPTURES: tuple[ValidationEvidenceCapture, ...] = (
    ValidationEvidenceCapture(
        key = 'core_first_run',
        file = 'SMC_Core_Engine.pine',
        script_name = 'SMC Core',
        report_label = 'Core first-run',
        runbook_label_en = 'rendered Core first-run screen',
        runbook_label_de = 'gerenderter Core-First-Run-Screen',
        notes = (
            'Capture the chart-rendered Focus View first-run surface.',
        ),
    ),
    ValidationEvidenceCapture(
        key = 'dashboard_decision_brief',
        file = 'SMC_Dashboard.pine',
        script_name = 'SMC Decision Board',
        report_label = 'Dashboard Decision Brief',
        runbook_label_en = 'rendered Dashboard screen in `Decision Brief`',
        runbook_label_de = 'gerenderter Dashboard-Screen in `Decision Brief`',
        notes = (
            'Capture the linked companion default brief surface.',
        ),
    ),
    ValidationEvidenceCapture(
        key = 'dashboard_audit_view',
        file = 'SMC_Dashboard.pine',
        script_name = 'SMC Decision Board',
        report_label = 'Dashboard Audit View',
        runbook_label_en = 'rendered Dashboard screen in `Audit View`',
        runbook_label_de = 'gerenderter Dashboard-Screen in `Audit View`',
        notes = (
            'Capture the expert review surface separately from the Decision Brief.',
        ),
    ),
    ValidationEvidenceCapture(
        key = 'strategy_execution_plan',
        file = 'SMC_Long_Strategy.pine',
        script_name = 'SMC Execution',
        report_label = 'Strategy execution',
        runbook_label_en = 'rendered Strategy screen with `Execution Trigger`, `Execution Invalidation`, and `Execution Take Profit` when a plan is active',
        runbook_label_de = 'gerenderter Strategy-Screen mit `Execution Trigger`, `Execution Invalidation` und `Execution Take Profit`, wenn ein Plan aktiv ist',
        notes = (
            'Capture the rendered execution plan, not the Pine editor state.',
        ),
    ),
)


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
    if target.saved_script_name:
        payload['savedScriptName'] = target.saved_script_name
    if target.binding_contract_key:
        payload['bindingContractKey'] = target.binding_contract_key
        payload['bindingContractName'] = BINDING_CONTRACT_NAMES[target.binding_contract_key]
        payload['bindingConsumerRole'] = BINDING_CONTRACT_CONSUMER_ROLES[target.binding_contract_key]
        payload['bindingContractLabels'] = [binding.label for binding in BINDING_CONTRACT_BINDINGS[target.binding_contract_key]]
        payload['bindingLabelGroups'] = _binding_label_group_payload(target.binding_contract_key)
    return payload


def _validation_evidence_capture_payload(capture: ValidationEvidenceCapture) -> dict[str, Any]:
    payload = asdict(capture)
    payload['notes'] = list(capture.notes)
    return payload


ENGINE_BUS_CHANNELS: tuple[str, ...] = (
    'SchemaVersion',
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
    # Plan 1.4 / §2.5 H5 — Quickstart Preset contract. Engine publishes the
    # effective preset floors so the Hero / Dashboard can detect CUSTOM (class
    # code 0) vs. a curated profile and surface why a floor was raised.
    'PresetClassCode',
    'PresetRvolMin',
    'PresetHtfBiasMin',
    'PresetFvgQualGate',
    'PresetVolRegimeDef',
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
    'Lifecycle BUS',
    'Diagnostic Rows',
    'Diagnostic Support',
    'Trade Plan',
    'Detail Surface',
    'Lean Surface',
    'Preset Contract',
)

STRATEGY_GROUP_TITLES: tuple[str, ...] = (
    'Entry States',
    'Trade Plan',
)

DASHBOARD_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_bus_lifecycle': 'Lifecycle BUS',
    'g_bus_diag_rows': 'Diagnostic Rows',
    'g_bus_diag': 'Diagnostic Support',
    'g_bus_plan': 'Trade Plan',
    'g_bus_detail': 'Detail Surface',
    'g_bus_lean': 'Lean Surface',
    'g_bus_preset': 'Preset Contract',
}

STRATEGY_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_bus_entry': 'Entry States',
    'g_bus_plan': 'Trade Plan',
}


DASHBOARD_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS SchemaVersion', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS ZoneActive', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS Armed', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS Confirmed', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS Ready', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS EntryBest', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS EntryStrict', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS Trigger', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS Invalidation', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS QualityScore', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS SourceKind', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS StateCode', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS TrendPack', 'g_bus_lifecycle', 'critical'),
    BusBinding('BUS MetaPack', 'g_bus_lifecycle', 'critical'),
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
    BusBinding('BUS StopLevel', 'g_bus_plan', 'critical'),
    BusBinding('BUS Target1', 'g_bus_plan', 'critical'),
    BusBinding('BUS Target2', 'g_bus_plan', 'critical'),
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
    BusBinding('BUS LeanPackA', 'g_bus_lean', 'critical'),
    BusBinding('BUS LeanPackB', 'g_bus_lean', 'critical'),
    # Plan 1.4 / §2.5 H5 — Quickstart Preset contract bindings. Order mirrors
    # the engine plot order; the Hero reads PresetClassCode to detect CUSTOM.
    BusBinding('BUS PresetClassCode', 'g_bus_preset'),
    BusBinding('BUS PresetRvolMin', 'g_bus_preset'),
    BusBinding('BUS PresetHtfBiasMin', 'g_bus_preset'),
    BusBinding('BUS PresetFvgQualGate', 'g_bus_preset'),
    BusBinding('BUS PresetVolRegimeDef', 'g_bus_preset'),
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

DASHBOARD_CRITICAL_BINDINGS: tuple[BusBinding, ...] = tuple(
    b for b in DASHBOARD_BUS_BINDINGS if b.tier == 'critical'
)
DASHBOARD_DIAGNOSTIC_BINDINGS: tuple[BusBinding, ...] = tuple(
    b for b in DASHBOARD_BUS_BINDINGS if b.tier == 'diagnostic'
)

DASHBOARD_BUS_CHANNELS: tuple[str, ...] = tuple(label.removeprefix('BUS ') for label in DASHBOARD_BUS_LABELS)
STRATEGY_BUS_CHANNELS: tuple[str, ...] = tuple(label.removeprefix('BUS ') for label in STRATEGY_BUS_LABELS)

BINDING_CONTRACT_BINDINGS: dict[str, tuple[BusBinding, ...]] = {
    'dashboardBindings': DASHBOARD_BUS_BINDINGS,
    'strategyBindings': STRATEGY_BUS_BINDINGS,
}

BINDING_CONTRACT_NAMES: dict[str, str] = {
    'dashboardBindings': 'dashboard companion BUS bindings',
    'strategyBindings': 'execution wrapper BUS bindings',
}

BINDING_CONTRACT_CONSUMER_ROLES: dict[str, str] = {
    'dashboardBindings': 'dashboard_companion',
    'strategyBindings': 'execution_wrapper',
}

BINDING_CONTRACT_GROUP_TITLES: dict[str, dict[str, str]] = {
    'dashboardBindings': DASHBOARD_GROUP_TITLES_BY_KEY,
    'strategyBindings': STRATEGY_GROUP_TITLES_BY_KEY,
}


def _binding_label_group_payload(binding_contract_key: str) -> list[dict[str, str]]:
    bindings = BINDING_CONTRACT_BINDINGS[binding_contract_key]
    group_titles = BINDING_CONTRACT_GROUP_TITLES[binding_contract_key]
    return [
        {
            'label': binding.label,
            'group': binding.group,
            'groupTitle': group_titles[binding.group],
            'tier': binding.tier,
        }
        for binding in bindings
    ]


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
        'validationEvidence': {
            'captureMode': VALIDATION_EVIDENCE_CAPTURE_MODE,
            'editorScreenshotsAllowed': VALIDATION_EVIDENCE_EDITOR_SCREENSHOTS_ALLOWED,
            'requiredCaptures': [_validation_evidence_capture_payload(capture) for capture in VALIDATION_EVIDENCE_CAPTURES],
        },
        'deprecatedFieldPolicy': dict(DEPRECATED_FIELD_POLICY),
    }
