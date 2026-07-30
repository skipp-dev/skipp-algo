from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from scripts.smc_context_bus_manifest import CONTEXT_BUS_CHANNELS


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
    lifecycle: str = 'active'
    deployment_mode: str = 'none'
    rollout_state: str = 'not_deployed'
    compile_expectation: str = 'required'
    bus_dependencies: tuple[str, ...] = ()
    archive_state: str = 'none'
    chart_instance_name: str | None = None
    known_missing_mp_fields: tuple[str, ...] = ()


@dataclass(frozen = True)
class PreflightTarget:
    file: str
    script_name: str
    check_inputs: bool
    add_to_chart: bool
    min_inputs: int | None = None
    saved_script_name: str | None = None
    binding_contract_key: str | None = None
    allow_fresh_draft_on_missing_existing: bool = False


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
    # Alert companion: restores the Suite's per-event selectable alertcondition()
    # slots (the Suite moved to alert() for the 64-plot budget, RE10140).
    'alert_companion',
)

LIFECYCLE_VALUES: tuple[str, ...] = (
    'active',
    'planned',
    'replacement_pending',
    'retirement_pending',
    'retired_tombstone',
    'archived',
)

DEPLOYMENT_MODE_VALUES: tuple[str, ...] = (
    'standard',
    'optional',
    'shadow',
    'none',
)

ROLLOUT_STATE_VALUES: tuple[str, ...] = (
    'deployed',
    'planned',
    'not_deployed',
)

COMPILE_EXPECTATION_VALUES: tuple[str, ...] = (
    'required',
    'deferred',
    'known_broken',
    'excluded',
)

BUS_DEPENDENCY_VALUES: tuple[str, ...] = (
    'engine_v2',
    'context_v3',
)

ARCHIVE_STATE_VALUES: tuple[str, ...] = (
    'none',
    'pending',
    'replace_in_place_pending',
    'archived',
)

PRODUCT_CUT_MANIFEST_VERSION = 3
PRODUCT_CUT_ARTIFACT_RELATIVE_PATH = 'artifacts/tradingview/smc_product_cut_manifest.json'
PRODUCT_CUT_SOURCE = 'scripts/smc_bus_manifest.py'
VALIDATION_EVIDENCE_CAPTURE_MODE = 'rendered_chart_only'
VALIDATION_EVIDENCE_EDITOR_SCREENSHOTS_ALLOWED = False

DEPRECATED_FIELD_POLICY: dict[str, Any] = {
    'mode': 'compatibility_only',
    'preferredFieldVersion': 'v8.0a',
    'extensionAllowed': False,
    'sunset_date': '2026-04-14',
    'sunset_action': 'removed',
    'deprecatedGroups': [],
}

KNOWN_MISSING_MP_FIELDS_BY_FILE: dict[str, tuple[str, ...]] = {
    'SMC_Imbalance_Context.pine': (
        'BEAR_FVG_ACTIVE',
        'BEAR_FVG_BOTTOM',
        'BEAR_FVG_COUNT',
        'BEAR_FVG_FULL_MITIGATION',
        'BEAR_FVG_MITIGATION_PCT',
        'BEAR_FVG_PARTIAL_MITIGATION',
        'BEAR_FVG_TOP',
        'BPR_ACTIVE',
        'BPR_BOTTOM',
        'BPR_TOP',
        'BULL_FVG_ACTIVE',
        'BULL_FVG_BOTTOM',
        'BULL_FVG_COUNT',
        'BULL_FVG_FULL_MITIGATION',
        'BULL_FVG_MITIGATION_PCT',
        'BULL_FVG_PARTIAL_MITIGATION',
        'BULL_FVG_TOP',
        'IMBALANCE_STATE',
        'LIQ_VOID_BEAR_ACTIVE',
        'LIQ_VOID_BOTTOM',
        'LIQ_VOID_BULL_ACTIVE',
        'LIQ_VOID_TOP',
    ),
    'SMC_Liquidity_Context.pine': (
        'ACTIVE_RESISTANCE_COUNT',
        'ACTIVE_SUPPORT_COUNT',
        'ACTIVE_ZONE_COUNT',
        'PRIMARY_RESISTANCE_LEVEL',
        'PRIMARY_RESISTANCE_STRENGTH',
        'PRIMARY_SUPPORT_LEVEL',
        'PRIMARY_SUPPORT_STRENGTH',
        'RESISTANCE_MITIGATION_PCT',
        'RESISTANCE_SWEEP_COUNT',
        'SUPPORT_MITIGATION_PCT',
        'SUPPORT_SWEEP_COUNT',
        'ZONE_CONTEXT_BIAS',
        'ZONE_LIQUIDITY_IMBALANCE',
    ),
    'SMC_Liquidity_Structure.pine': (
        'POOL_IMBALANCE',
        'POOL_MAGNET_DIRECTION',
        'POOL_QUALITY_SCORE',
        'RECENT_BEAR_SWEEP',
        'RECENT_BULL_SWEEP',
        'SWEEP_QUALITY_SCORE',
        'SWEEP_RECLAIM_ACTIVE',
        'SWEEP_TYPE',
    ),
    'SMC_Profile_Context.pine': (
        'PROFILE_AH_QUALITY',
        'PROFILE_AVG_SPREAD_BPS',
        'PROFILE_CLEAN_SCORE',
        'PROFILE_CONTEXT_SCORE',
        'PROFILE_MIDDAY_EFFICIENCY',
        'PROFILE_PM_QUALITY',
        'PROFILE_RTH_DOMINANCE_PCT',
        'PROFILE_SESSION_BIAS',
        'PROFILE_SPREAD_REGIME',
        'PROFILE_TICKER_GRADE',
        'PROFILE_VWAP_DISTANCE_PCT',
        'PROFILE_VWAP_POSITION',
        'PROFILE_WICKINESS',
    ),
    'SMC_Structure_Context.pine': (
        'ACTIVE_RESISTANCE',
        'ACTIVE_SUPPORT',
        'BOS_BEAR',
        'BOS_BULL',
        'CHOCH_BEAR',
        'CHOCH_BULL',
        'RESISTANCE_ACTIVE',
        'STRUCTURE_BEAR_ACTIVE',
        'STRUCTURE_BULL_ACTIVE',
        'STRUCTURE_STATE',
        'SUPPORT_ACTIVE',
    ),
}

SURFACE_DEFINITIONS: tuple[SurfaceDefinition, ...] = (
    SurfaceDefinition(
        file = 'SMC_Long_Dip_Suite.pine',
        script_name = 'SMC Long-Dip Suite',
        surface_role = 'lite_primary',
        contract_tier = 'lite_and_pro',
        consumer_role = 'producer',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        chart_instance_name = 'SMC Long-Dip Suite',
        validation_target = True,
        notes = (
            'Primary Focus View surface for the Lite rollout.',
            'Only active producer on the release mainline.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Long_Dip_Dashboard.pine',
        script_name = 'SMC Long-Dip Dashboard',
        surface_role = 'pro_primary',
        contract_tier = 'pro',
        consumer_role = 'dashboard_companion',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Decision Board',
        validation_target = True,
        notes = (
            'Primary linked decision companion surface.',
            'BUS bindings remain operator-only even though the dashboard is part of the main product cut.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Long_Dip_Strategy.pine',
        script_name = 'SMC Long-Dip Strategy',
        surface_role = 'pro_primary',
        contract_tier = 'execution',
        consumer_role = 'execution_wrapper',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Long-Dip Strategy',
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
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Event Overlay',
        validation_target = True,
        notes = (
            'Pro-only event-risk companion deployed in the private Simple Management layout.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Orderflow_Overlay.pine',
        script_name = 'SMC Orderflow Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'overlay_companion',
        lifecycle = 'retirement_pending',
        compile_expectation = 'required',
        archive_state = 'pending',
        notes = (
            'Static daily snapshot whose live-orderflow role moves to Railway/Databento.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Liquidity_Context.pine',
        script_name = 'SMC Liquidity Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'replacement_pending',
        compile_expectation = 'known_broken',
        archive_state = 'replace_in_place_pending',
        known_missing_mp_fields = KNOWN_MISSING_MP_FIELDS_BY_FILE['SMC_Liquidity_Context.pine'],
        notes = (
            'Snapshot-era source awaiting replacement by Context BUS v3.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_HTF_Confluence.pine',
        script_name = 'SMC HTF Confluence',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'active',
        deployment_mode = 'optional',
        rollout_state = 'not_deployed',
        compile_expectation = 'required',
        archive_state = 'none',
        notes = (
            'Confirmed live 15m/1h/4h companion pending private TradingView validation.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Imbalance_Context.pine',
        script_name = 'SMC Imbalance Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'replacement_pending',
        compile_expectation = 'known_broken',
        archive_state = 'replace_in_place_pending',
        known_missing_mp_fields = KNOWN_MISSING_MP_FIELDS_BY_FILE['SMC_Imbalance_Context.pine'],
        notes = (
            'Snapshot-era source awaiting replacement by Context BUS v3.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Structure_Context.pine',
        script_name = 'SMC Structure Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'replacement_pending',
        compile_expectation = 'known_broken',
        archive_state = 'replace_in_place_pending',
        known_missing_mp_fields = KNOWN_MISSING_MP_FIELDS_BY_FILE['SMC_Structure_Context.pine'],
        notes = (
            'Snapshot-era source awaiting replacement by Context BUS v3.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Session_Context.pine',
        script_name = 'SMC Session Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'active',
        deployment_mode = 'optional',
        rollout_state = 'not_deployed',
        compile_expectation = 'required',
        archive_state = 'none',
        notes = (
            'Confirmed IANA-timezone session companion pending private TradingView validation.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Profile_Context.pine',
        script_name = 'SMC Profile Context',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'replacement_pending',
        compile_expectation = 'known_broken',
        archive_state = 'replace_in_place_pending',
        known_missing_mp_fields = KNOWN_MISSING_MP_FIELDS_BY_FILE['SMC_Profile_Context.pine'],
        notes = (
            'Snapshot-era source awaiting replacement by the consolidated context architecture.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Liquidity_Structure.pine',
        script_name = 'SMC Liquidity Structure',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'replacement_pending',
        compile_expectation = 'known_broken',
        archive_state = 'replace_in_place_pending',
        known_missing_mp_fields = KNOWN_MISSING_MP_FIELDS_BY_FILE['SMC_Liquidity_Structure.pine'],
        notes = (
            'Snapshot-era source awaiting replacement by Context BUS v3.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Setup_Check.pine',
        script_name = 'SMC Setup Check',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'setup_utility',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Setup Check',
        notes = (
            'BUS connection validator — guides new users through initial setup.',
            'Reads 6 critical BUS channels and shows connection status with next-step instructions.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Long_Dip_Mobile.pine',
        script_name = 'SMC Long-Dip Mobile',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'mobile_companion',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Long-Dip Mobile',
        notes = (
            'Mobile-first dashboard — 4-row table, no overlays.',
            'Traffic light + levels + market context + quality score.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Confluence_Hub.pine',
        script_name = 'SMC Confluence Hub',
        surface_role = 'pro_primary',
        contract_tier = 'pro',
        consumer_role = 'confluence_hub',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Confluence Hub',
        notes = (
            'Multi-signal confluence aggregator (SMC BUS + trend + momentum + mean-reversion).',
            'Produces 0-100 confluence score with traffic-light overlay.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Regime_and_News.pine',
        script_name = 'SMC Regime & News',
        surface_role = 'internal',
        contract_tier = 'internal',
        consumer_role = 'bridge',
        lifecycle = 'retired_tombstone',
        compile_expectation = 'excluded',
        notes = (
            'Retired, network-inert compatibility notice; no live-overlay data ingress.',
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
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Breakout Overlay',
        notes = (
            'LonesomeTheBlue-style breakout/breakdown box renderer. Three-tier '
            'structure source: (1) imports smc_engine_private and runs the same '
            'order-block/structure detector as the engine, standalone; (2) '
            'optionally binds the SMC Core BUS (SchemaVersion/ZoneActive/Trigger/'
            'Invalidation, plus optional ZoneOb*/ZoneFvg*/StopLevel/Target1-2/'
            'QualityScore enrichments for real zone boxes, the real risk plan, '
            'and a quality filter) for the live gated setup; (3) local swing-'
            'pivot fallback. Does NOT import the micro-profiles snapshot (no '
            'per-bar structure there). Pure visual, no new detection.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Exit_Signal.pine',
        script_name = 'SMC Exit Signal',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'exit_companion',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Exit Signal',
        validation_target = True,
        notes = (
            'Beginner-facing exit companion: STOP / TP1 / TP2 / DEFENSIVE '
            'EXIT alerts driven by linked SMC Core BUS outputs. No '
            'library import — fully BUS-driven. Deployed as the sole '
            'actionable exit mode in the private Simple Management layout.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Hold_Manager.pine',
        script_name = 'SMC Hold Manager',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'exit_companion',
        lifecycle = 'planned',
        deployment_mode = 'standard',
        rollout_state = 'planned',
        bus_dependencies = ('engine_v2',),
        notes = (
            'Read-only hold-management overlay with Engine BUS v2 as its '
            'fail-closed primary plan, explicit manual fallback, '
            'ATR-Chandelier trail, BE-after-T1, optional Simple-Mode, '
            'time-stop, and confirmed-history state reconstruction.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Long_Dip_Alerts.pine',
        script_name = 'SMC Long-Dip Alerts',
        surface_role = 'companion_operator_only',
        contract_tier = 'lite_and_pro',
        consumer_role = 'alert_companion',
        deployment_mode = 'standard',
        rollout_state = 'deployed',
        bus_dependencies = ('engine_v2',),
        chart_instance_name = 'SMC Long-Dip Alerts',
        notes = (
            'Alert companion for the Suite. Restores the 16 lifecycle / structure '
            '/ trust / risk events as individually-selectable alertcondition() '
            'slots (the Suite moved to alert() for the 64-plot budget, RE10140). '
            'Product-state + zone from the BUS StateCode/Armed/ZoneActive inputs; '
            'structure recomputed via eng.detect_structure; trust via '
            'eng.resolve_trust_tier over mp.* consts; macro/earnings from mp.*.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Volume_Profile_Overlay.pine',
        script_name = 'SMC Volume Profile Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'overlay_companion',
        lifecycle = 'planned',
        deployment_mode = 'optional',
        rollout_state = 'planned',
        notes = (
            'Visible-Range Volume Profile companion: histogram + '
            'multi-POC + VAH/VAL. No library import — fully self-contained.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Context_Bus.pine',
        script_name = 'SMC Context Bus',
        surface_role = 'internal',
        contract_tier = 'internal',
        consumer_role = 'producer',
        lifecycle = 'active',
        deployment_mode = 'shadow',
        rollout_state = 'not_deployed',
        compile_expectation = 'required',
        notes = (
            'Context BUS v3 producer; schema 8001 exposes 60 direct domain '
            'channels with four TradingView plot slots reserved. Source exists '
            'locally but remains non-deployed until private compile, publish, '
            'binding and shadow evidence pass.',
        ),
    ),
    SurfaceDefinition(
        file = 'SMC_Context_Overlay.pine',
        script_name = 'SMC Context Overlay',
        surface_role = 'companion_operator_only',
        contract_tier = 'pro',
        consumer_role = 'context_companion',
        lifecycle = 'active',
        deployment_mode = 'shadow',
        rollout_state = 'not_deployed',
        compile_expectation = 'required',
        bus_dependencies = ('context_v3',),
        notes = (
            'Consolidated fail-closed Context BUS v3 consumer. Source exists '
            'locally but remains shadow-only and non-gating until private '
            'compile, all-source binding, performance and parity evidence pass.',
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
    - lifecycle, deployment, rollout, compile, BUS and archive values are valid
    - deployed chart instances and known-broken snapshot declarations are coherent
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
        if surface.lifecycle not in LIFECYCLE_VALUES:
            errors.append(f"{surface.file}: invalid lifecycle '{surface.lifecycle}'")
        if surface.deployment_mode not in DEPLOYMENT_MODE_VALUES:
            errors.append(f"{surface.file}: invalid deployment_mode '{surface.deployment_mode}'")
        if surface.rollout_state not in ROLLOUT_STATE_VALUES:
            errors.append(f"{surface.file}: invalid rollout_state '{surface.rollout_state}'")
        if surface.compile_expectation not in COMPILE_EXPECTATION_VALUES:
            errors.append(
                f"{surface.file}: invalid compile_expectation "
                f"'{surface.compile_expectation}'"
            )
        invalid_bus_dependencies = sorted(
            set(surface.bus_dependencies) - set(BUS_DEPENDENCY_VALUES)
        )
        if invalid_bus_dependencies:
            errors.append(
                f"{surface.file}: invalid bus_dependencies "
                f"{invalid_bus_dependencies}"
            )
        if len(surface.bus_dependencies) != len(set(surface.bus_dependencies)):
            errors.append(f"{surface.file}: duplicate bus_dependencies")
        if surface.archive_state not in ARCHIVE_STATE_VALUES:
            errors.append(f"{surface.file}: invalid archive_state '{surface.archive_state}'")
        if surface.rollout_state == 'deployed' and not surface.chart_instance_name:
            errors.append(f"{surface.file}: deployed surface requires chart_instance_name")
        if surface.rollout_state != 'deployed' and surface.chart_instance_name:
            errors.append(
                f"{surface.file}: non-deployed surface cannot declare chart_instance_name"
            )
        if (
            surface.compile_expectation == 'known_broken'
            and not surface.known_missing_mp_fields
        ):
            errors.append(
                f"{surface.file}: known_broken surface requires known_missing_mp_fields"
            )
        if (
            surface.compile_expectation != 'known_broken'
            and surface.known_missing_mp_fields
        ):
            errors.append(
                f"{surface.file}: known_missing_mp_fields requires known_broken compile expectation"
            )
        if len(surface.known_missing_mp_fields) != len(set(surface.known_missing_mp_fields)):
            errors.append(f"{surface.file}: duplicate known_missing_mp_fields")
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
    PreflightTarget('SMC_Long_Dip_Suite.pine', 'SMC Long-Dip Suite', False, False),
    PreflightTarget('SMC_Long_Dip_Dashboard.pine', 'SMC Long-Dip Dashboard', True, True, 58, 'SMC Long-Dip Dashboard', 'dashboardBindings'),
)

PREFLIGHT_MAINLINE_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget('SMC_Long_Dip_Suite.pine', 'SMC Long-Dip Suite', False, False),
    PreflightTarget('SMC_Long_Dip_Dashboard.pine', 'SMC Long-Dip Dashboard', True, True, 58, 'SMC Long-Dip Dashboard', 'dashboardBindings'),
    PreflightTarget('SMC_Long_Dip_Strategy.pine', 'SMC Long-Dip Strategy', True, True, 8, 'SMC Long-Dip Strategy', 'strategyBindings'),
)

PREFLIGHT_DECISION_FIRST_TARGETS: tuple[PreflightTarget, ...] = PREFLIGHT_MAINLINE_TARGETS

PREFLIGHT_HOLD_MANAGER_SHADOW_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget(
        'SMC_Long_Dip_Suite.pine',
        'SMC Long-Dip Suite',
        False,
        False,
    ),
    PreflightTarget(
        'SMC_Hold_Manager.pine',
        'SMC Hold Manager',
        True,
        True,
        13,
        'SMC Hold Manager R2.4 Validation',
        'holdManagerBindings',
    ),
)

PREFLIGHT_R1_COMPANION_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget(
        'SMC_Long_Dip_Suite.pine',
        'SMC Long-Dip Suite',
        False,
        False,
    ),
    PreflightTarget(
        'SMC_Event_Overlay.pine',
        'SMC Event Overlay',
        True,
        True,
        1,
        'SMC Event Overlay',
        'eventOverlayBindings',
        allow_fresh_draft_on_missing_existing = True,
    ),
    PreflightTarget(
        'SMC_Exit_Signal.pine',
        'SMC Exit Signal',
        True,
        True,
        9,
        'SMC Exit Signal',
        'exitSignalBindings',
        allow_fresh_draft_on_missing_existing = True,
    ),
)

PREFLIGHT_R4_CONTEXT_SHADOW_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget(
        'SMC_Context_Bus.pine',
        'SMC Context Bus',
        False,
        True,
        saved_script_name = 'SMC Context Bus',
        allow_fresh_draft_on_missing_existing = True,
    ),
    PreflightTarget(
        'SMC_Context_Overlay.pine',
        'SMC Context Overlay',
        True,
        True,
        60,
        'SMC Context Overlay',
        'contextOverlayBindings',
        allow_fresh_draft_on_missing_existing = True,
    ),
)

PREFLIGHT_R5_HTF_SESSION_TARGETS: tuple[PreflightTarget, ...] = (
    PreflightTarget(
        'SMC_HTF_Confluence.pine',
        'SMC HTF Confluence',
        False,
        True,
        saved_script_name = 'SMC HTF Confluence',
        allow_fresh_draft_on_missing_existing = True,
    ),
    PreflightTarget(
        'SMC_Session_Context.pine',
        'SMC Session Context',
        False,
        True,
        saved_script_name = 'SMC Session Context',
        allow_fresh_draft_on_missing_existing = True,
    ),
)

VALIDATION_EVIDENCE_CAPTURES: tuple[ValidationEvidenceCapture, ...] = (
    ValidationEvidenceCapture(
        key = 'core_first_run',
        file = 'SMC_Long_Dip_Suite.pine',
        script_name = 'SMC Long-Dip Suite',
        report_label = 'Core first-run',
        runbook_label_en = 'rendered Core first-run screen',
        runbook_label_de = 'gerenderter Core-First-Run-Screen',
        notes = (
            'Capture the chart-rendered Focus View first-run surface.',
        ),
    ),
    ValidationEvidenceCapture(
        key = 'dashboard_decision_brief',
        file = 'SMC_Long_Dip_Dashboard.pine',
        script_name = 'SMC Long-Dip Dashboard',
        report_label = 'Dashboard Decision Brief',
        runbook_label_en = 'rendered Dashboard screen in `Decision Brief`',
        runbook_label_de = 'gerenderter Dashboard-Screen in `Decision Brief`',
        notes = (
            'Capture the linked companion default brief surface.',
        ),
    ),
    ValidationEvidenceCapture(
        key = 'dashboard_audit_view',
        file = 'SMC_Long_Dip_Dashboard.pine',
        script_name = 'SMC Long-Dip Dashboard',
        report_label = 'Dashboard Audit View',
        runbook_label_en = 'rendered Dashboard screen in `Audit View`',
        runbook_label_de = 'gerenderter Dashboard-Screen in `Audit View`',
        notes = (
            'Capture the expert review surface separately from the Decision Brief.',
        ),
    ),
    ValidationEvidenceCapture(
        key = 'strategy_execution_plan',
        file = 'SMC_Long_Dip_Strategy.pine',
        script_name = 'SMC Long-Dip Strategy',
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
    payload['bus_dependencies'] = list(surface.bus_dependencies)
    payload['known_missing_mp_fields'] = list(surface.known_missing_mp_fields)
    payload['notes'] = list(surface.notes)
    if surface.chart_instance_name is None:
        payload.pop('chart_instance_name')
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
    if target.allow_fresh_draft_on_missing_existing:
        payload['allowFreshDraftOnMissingExisting'] = True
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


# Ordered to mirror the engine's BUS plot() order (channels 2..9). The set is the
# contract; the order is not semantic here (unlike ENGINE_BUS_CHANNELS, whose
# order mirrors the Pine plot block). Aligning it lets the Strategy declare its
# input.source rows in the same order TradingView lists the Suite's outputs in
# the dropdown, so the operator binds straight down without scrolling back up.
EXECUTABLE_BUS_CHANNELS: tuple[str, ...] = (
    'Armed',
    'Confirmed',
    'Ready',
    'EntryBest',
    'EntryStrict',
    'Trigger',
    'Invalidation',
    'QualityScore',
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


# Ordered so the settings panel walks the engine's BUS plot order 0..63 from top
# to bottom. TradingView renders a source study's outputs as ONE FLAT list in
# plot order and knows nothing about these groups, so a group whose plot range is
# out of sequence forces the operator to scroll back up in the dropdown. Every
# group therefore covers one contiguous range; 'Blocker Codes' was split out of
# 'Diagnostic Support', which previously held two disjoint ranges (14-16, 40-43).
DASHBOARD_GROUP_TITLES: tuple[str, ...] = (
    'Lifecycle BUS',        # plots 0-13
    'Diagnostic Support',   # plots 14-16
    'Trade Plan',           # plots 17-19
    'Diagnostic Rows',      # plots 20-39
    'Blocker Codes',        # plots 40-43
    'Detail Surface',       # plots 44-56
    'Lean Surface',         # plots 57-58
    'Preset Contract',      # plots 59-63
)

STRATEGY_GROUP_TITLES: tuple[str, ...] = (
    'Entry States',
    'Trade Plan',
)

DASHBOARD_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_bus_lifecycle': 'Lifecycle BUS',
    'g_bus_diag': 'Diagnostic Support',
    'g_bus_plan': 'Trade Plan',
    'g_bus_diag_rows': 'Diagnostic Rows',
    'g_bus_blockers': 'Blocker Codes',
    'g_bus_detail': 'Detail Surface',
    'g_bus_lean': 'Lean Surface',
    'g_bus_preset': 'Preset Contract',
}

STRATEGY_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_bus_entry': 'Entry States',
    'g_bus_plan': 'Trade Plan',
}

HOLD_MANAGER_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'gBus': 'Engine BUS v2 (Expert Mapping)',
}

EVENT_OVERLAY_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_ev': 'Event Overlay',
}

EXIT_SIGNAL_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_bus_state': 'Expert Mapping - Entry States',
    'g_bus_plan': 'Expert Mapping - Trade Plan',
}

CONTEXT_OVERLAY_GROUP_TITLES_BY_KEY: dict[str, str] = {
    'g_meta': 'Context BUS · Meta',
    'g_structure': 'Context BUS · Structure',
    'g_imbalance': 'Context BUS · Imbalance',
    'g_zone': 'Context BUS · Zones',
    'g_sweep': 'Context BUS · Sweeps',
    'g_pool': 'Context BUS · Pools',
    'g_session': 'Context BUS · Session',
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
    BusBinding('BUS LtfDeltaState', 'g_bus_diag', 'diagnostic'),
    BusBinding('BUS SafeTrendState', 'g_bus_diag', 'diagnostic'),
    BusBinding('BUS MicroProfileCode', 'g_bus_diag', 'diagnostic'),
    BusBinding('BUS StopLevel', 'g_bus_plan', 'critical'),
    BusBinding('BUS Target1', 'g_bus_plan', 'critical'),
    BusBinding('BUS Target2', 'g_bus_plan', 'critical'),
    BusBinding('BUS SessionGateRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS MarketGateRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS VolaGateRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS MicroSessionGateRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS MicroFreshRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS VolumeDataRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS QualityEnvRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS QualityStrictRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS CloseStrengthRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS EmaSupportRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS AdxRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS RelVolRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS VwapRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS ContextQualityRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS QualityCleanRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS QualityScoreRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS SdConfluenceRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS SdOscRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS VolRegimeRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS VolSqueezeRow', 'g_bus_diag_rows', 'diagnostic'),
    BusBinding('BUS ReadyBlockerCode', 'g_bus_blockers', 'diagnostic'),
    BusBinding('BUS StrictBlockerCode', 'g_bus_blockers', 'diagnostic'),
    BusBinding('BUS VolExpansionState', 'g_bus_blockers', 'diagnostic'),
    BusBinding('BUS DdviContextState', 'g_bus_blockers', 'diagnostic'),
    BusBinding('BUS ZoneObTop', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS ZoneObBottom', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS ZoneFvgTop', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS ZoneFvgBottom', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS SessionVwap', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS AdxValue', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS RelVolValue', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS StretchZ', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS StretchSupportMask', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS LtfBullShare', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS LtfBiasHint', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS LtfVolumeDelta', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS ObjectsCountPack', 'g_bus_detail', 'diagnostic'),
    BusBinding('BUS LeanPackA', 'g_bus_lean', 'critical'),
    BusBinding('BUS LeanPackB', 'g_bus_lean', 'critical'),
    BusBinding('BUS PresetClassCode', 'g_bus_preset', 'diagnostic'),
    BusBinding('BUS PresetRvolMin', 'g_bus_preset', 'diagnostic'),
    BusBinding('BUS PresetHtfBiasMin', 'g_bus_preset', 'diagnostic'),
    BusBinding('BUS PresetFvgQualGate', 'g_bus_preset', 'diagnostic'),
    BusBinding('BUS PresetVolRegimeDef', 'g_bus_preset', 'diagnostic'),
)

STRATEGY_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS Armed', 'g_bus_entry'),
    BusBinding('BUS Confirmed', 'g_bus_entry'),
    BusBinding('BUS Ready', 'g_bus_entry'),
    BusBinding('BUS EntryBest', 'g_bus_entry'),
    BusBinding('BUS EntryStrict', 'g_bus_entry'),
    BusBinding('BUS Trigger', 'g_bus_plan'),
    BusBinding('BUS Invalidation', 'g_bus_plan'),
    BusBinding('BUS QualityScore', 'g_bus_plan'),
)

HOLD_MANAGER_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS SchemaVersion', 'gBus', 'critical'),
    BusBinding('BUS ZoneActive', 'gBus', 'critical'),
    BusBinding('BUS Armed', 'gBus', 'critical'),
    BusBinding('BUS Confirmed', 'gBus', 'critical'),
    BusBinding('BUS Ready', 'gBus', 'critical'),
    BusBinding('BUS Trigger', 'gBus', 'critical'),
    BusBinding('BUS Invalidation', 'gBus', 'critical'),
    BusBinding('BUS QualityScore', 'gBus', 'critical'),
    BusBinding('BUS SourceKind', 'gBus', 'critical'),
    BusBinding('BUS StateCode', 'gBus', 'critical'),
    BusBinding('BUS StopLevel', 'gBus', 'critical'),
    BusBinding('BUS Target1', 'gBus', 'critical'),
    BusBinding('BUS Target2', 'gBus', 'critical'),
)

EVENT_OVERLAY_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS LeanPackA', 'g_ev', 'critical'),
)

EXIT_SIGNAL_BUS_BINDINGS: tuple[BusBinding, ...] = (
    BusBinding('BUS SchemaVersion', 'g_bus_state', 'critical'),
    BusBinding('BUS Armed', 'g_bus_state', 'critical'),
    BusBinding('BUS Confirmed', 'g_bus_state', 'critical'),
    BusBinding('BUS Ready', 'g_bus_state', 'critical'),
    BusBinding('BUS Trigger', 'g_bus_plan', 'critical'),
    BusBinding('BUS Invalidation', 'g_bus_plan', 'critical'),
    BusBinding('BUS StopLevel', 'g_bus_plan', 'critical'),
    BusBinding('BUS Target1', 'g_bus_plan', 'critical'),
    BusBinding('BUS Target2', 'g_bus_plan', 'critical'),
)

_CONTEXT_GROUP_KEYS: dict[str, str] = {
    'meta': 'g_meta',
    'aggregate': 'g_meta',
    'structure': 'g_structure',
    'imbalance': 'g_imbalance',
    'zone': 'g_zone',
    'sweep': 'g_sweep',
    'pool': 'g_pool',
    'session': 'g_session',
}

CONTEXT_OVERLAY_BUS_BINDINGS: tuple[BusBinding, ...] = tuple(
    BusBinding(
        channel.label,
        _CONTEXT_GROUP_KEYS[channel.group],
        'critical' if channel.required else 'diagnostic',
    )
    for channel in CONTEXT_BUS_CHANNELS
)


DASHBOARD_BUS_LABELS: tuple[str, ...] = tuple(binding.label for binding in DASHBOARD_BUS_BINDINGS)
STRATEGY_BUS_LABELS: tuple[str, ...] = tuple(binding.label for binding in STRATEGY_BUS_BINDINGS)
HOLD_MANAGER_BUS_LABELS: tuple[str, ...] = tuple(
    binding.label for binding in HOLD_MANAGER_BUS_BINDINGS
)
EVENT_OVERLAY_BUS_LABELS: tuple[str, ...] = tuple(
    binding.label for binding in EVENT_OVERLAY_BUS_BINDINGS
)
EXIT_SIGNAL_BUS_LABELS: tuple[str, ...] = tuple(
    binding.label for binding in EXIT_SIGNAL_BUS_BINDINGS
)

DASHBOARD_CRITICAL_BINDINGS: tuple[BusBinding, ...] = tuple(
    b for b in DASHBOARD_BUS_BINDINGS if b.tier == 'critical'
)
DASHBOARD_DIAGNOSTIC_BINDINGS: tuple[BusBinding, ...] = tuple(
    b for b in DASHBOARD_BUS_BINDINGS if b.tier == 'diagnostic'
)

DASHBOARD_BUS_CHANNELS: tuple[str, ...] = tuple(label.removeprefix('BUS ') for label in DASHBOARD_BUS_LABELS)
STRATEGY_BUS_CHANNELS: tuple[str, ...] = tuple(label.removeprefix('BUS ') for label in STRATEGY_BUS_LABELS)
HOLD_MANAGER_BUS_CHANNELS: tuple[str, ...] = tuple(
    label.removeprefix('BUS ') for label in HOLD_MANAGER_BUS_LABELS
)

BINDING_CONTRACT_BINDINGS: dict[str, tuple[BusBinding, ...]] = {
    'dashboardBindings': DASHBOARD_BUS_BINDINGS,
    'strategyBindings': STRATEGY_BUS_BINDINGS,
    'holdManagerBindings': HOLD_MANAGER_BUS_BINDINGS,
    'eventOverlayBindings': EVENT_OVERLAY_BUS_BINDINGS,
    'exitSignalBindings': EXIT_SIGNAL_BUS_BINDINGS,
    'contextOverlayBindings': CONTEXT_OVERLAY_BUS_BINDINGS,
}

BINDING_CONTRACT_NAMES: dict[str, str] = {
    'dashboardBindings': 'dashboard companion BUS bindings',
    'strategyBindings': 'execution wrapper BUS bindings',
    'holdManagerBindings': 'Hold Manager BUS bindings',
    'eventOverlayBindings': 'Event Overlay BUS bindings',
    'exitSignalBindings': 'Exit Signal BUS bindings',
    'contextOverlayBindings': 'Context Overlay schema-8001 bindings',
}

BINDING_CONTRACT_CONSUMER_ROLES: dict[str, str] = {
    'dashboardBindings': 'dashboard_companion',
    'strategyBindings': 'execution_wrapper',
    'holdManagerBindings': 'exit_companion',
    'eventOverlayBindings': 'overlay_companion',
    'exitSignalBindings': 'exit_companion',
    'contextOverlayBindings': 'context_companion',
}

BINDING_CONTRACT_GROUP_TITLES: dict[str, dict[str, str]] = {
    'dashboardBindings': DASHBOARD_GROUP_TITLES_BY_KEY,
    'strategyBindings': STRATEGY_GROUP_TITLES_BY_KEY,
    'holdManagerBindings': HOLD_MANAGER_GROUP_TITLES_BY_KEY,
    'eventOverlayBindings': EVENT_OVERLAY_GROUP_TITLES_BY_KEY,
    'exitSignalBindings': EXIT_SIGNAL_GROUP_TITLES_BY_KEY,
    'contextOverlayBindings': CONTEXT_OVERLAY_GROUP_TITLES_BY_KEY,
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
            'holdManagerBindings': list(HOLD_MANAGER_BUS_LABELS),
            'eventOverlayBindings': list(EVENT_OVERLAY_BUS_LABELS),
            'exitSignalBindings': list(EXIT_SIGNAL_BUS_LABELS),
            'contextOverlayBindings': [
                binding.label for binding in CONTEXT_OVERLAY_BUS_BINDINGS
            ],
        },
        'preflightScopes': {
            'smcCoreDashboard': [_preflight_target_payload(target) for target in PREFLIGHT_CORE_DASHBOARD_TARGETS],
            'smcMainline': [_preflight_target_payload(target) for target in PREFLIGHT_MAINLINE_TARGETS],
            'smcDecisionFirst': [_preflight_target_payload(target) for target in PREFLIGHT_DECISION_FIRST_TARGETS],
            'smcHoldManagerShadow': [_preflight_target_payload(target) for target in PREFLIGHT_HOLD_MANAGER_SHADOW_TARGETS],
            'smcR1Companions': [_preflight_target_payload(target) for target in PREFLIGHT_R1_COMPANION_TARGETS],
            'smcR4ContextShadow': [_preflight_target_payload(target) for target in PREFLIGHT_R4_CONTEXT_SHADOW_TARGETS],
            'smcR5HtfSession': [_preflight_target_payload(target) for target in PREFLIGHT_R5_HTF_SESSION_TARGETS],
        },
        'validationEvidence': {
            'captureMode': VALIDATION_EVIDENCE_CAPTURE_MODE,
            'editorScreenshotsAllowed': VALIDATION_EVIDENCE_EDITOR_SCREENSHOTS_ALLOWED,
            'requiredCaptures': [_validation_evidence_capture_payload(capture) for capture in VALIDATION_EVIDENCE_CAPTURES],
        },
        'deprecatedFieldPolicy': dict(DEPRECATED_FIELD_POLICY),
    }
