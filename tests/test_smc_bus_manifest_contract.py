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
    assert tuple(f'BUS {channel}' for channel in MANIFEST.LITE_BUS_CHANNELS) == MANIFEST.LITE_BUS_LABELS


def test_strategy_contract_matches_the_executable_core() -> None:
    assert MANIFEST.STRATEGY_BUS_CHANNELS == MANIFEST.EXECUTABLE_BUS_CHANNELS
    assert set(MANIFEST.STRATEGY_BUS_CHANNELS).issubset(set(MANIFEST.LITE_BUS_CHANNELS))
    assert tuple(f'BUS {channel}' for channel in MANIFEST.EXECUTABLE_BUS_CHANNELS) == MANIFEST.EXECUTABLE_BUS_LABELS


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
        'SchemaVersion',
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
        # Plan 1.4 / §2.5 H5 — Quickstart Preset contract: stable Pro-only,
        # not part of the C9 reduce/detail/rebuild/legacy partitions.
        'PresetClassCode',
        'PresetRvolMin',
        'PresetHtfBiasMin',
        'PresetFvgQualGate',
        'PresetVolRegimeDef',
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


def test_product_cut_payload_exports_governance_metadata() -> None:
    payload = MANIFEST.build_product_cut_manifest_payload()
    dashboard_target = payload['preflightScopes']['smcMainline'][1]
    strategy_target = payload['preflightScopes']['smcMainline'][2]

    assert payload['manifestVersion'] == 2
    assert payload['contracts']['lite'] == list(MANIFEST.LITE_BUS_LABELS)
    assert payload['contracts']['strategyBindings'] == list(MANIFEST.STRATEGY_BUS_LABELS)
    assert tuple(payload['preflightScopes'].keys()) == ('smcCoreDashboard', 'smcMainline', 'smcDecisionFirst')
    # Canonical unique TV script identities (no third-party substring collision).
    # See PREFLIGHT_*_TARGETS rationale comment in scripts/smc_bus_manifest.py.
    assert payload['preflightScopes']['smcCoreDashboard'][1]['scriptName'] == 'SMC Decision Board'
    assert payload['preflightScopes']['smcCoreDashboard'][1]['savedScriptName'] == 'SMC Long-Dip Dashboard v7'
    assert payload['preflightScopes']['smcMainline'][1]['scriptName'] == 'SMC Decision Board'
    assert payload['preflightScopes']['smcMainline'][1]['savedScriptName'] == 'SMC Long-Dip Dashboard v7'
    assert payload['preflightScopes']['smcMainline'][2]['scriptName'] == 'SMC Long-Dip Strategy v7'
    assert payload['preflightScopes']['smcMainline'][2]['savedScriptName'] == 'SMC Long-Dip Strategy v7'
    assert dashboard_target['bindingContractKey'] == 'dashboardBindings'
    assert dashboard_target['bindingContractName'] == 'dashboard companion BUS bindings'
    assert dashboard_target['bindingConsumerRole'] == 'dashboard_companion'
    assert dashboard_target['bindingContractLabels'] == list(MANIFEST.DASHBOARD_BUS_LABELS)
    assert dashboard_target['bindingLabelGroups'][0] == {
        'label': 'BUS SchemaVersion',
        'group': 'g_bus_lifecycle',
        'groupTitle': 'Lifecycle BUS',
        'tier': 'critical',
    }
    assert dashboard_target['bindingLabelGroups'][-1] == {
        'label': 'BUS PresetVolRegimeDef',
        'group': 'g_bus_preset',
        'groupTitle': 'Preset Contract',
        'tier': 'diagnostic',
    }
    assert strategy_target['bindingContractKey'] == 'strategyBindings'
    assert strategy_target['bindingContractName'] == 'execution wrapper BUS bindings'
    assert strategy_target['bindingConsumerRole'] == 'execution_wrapper'
    assert strategy_target['bindingContractLabels'] == list(MANIFEST.STRATEGY_BUS_LABELS)
    assert strategy_target['bindingLabelGroups'][0] == {
        'label': 'BUS Armed',
        'group': 'g_bus_entry',
        'groupTitle': 'Entry States',
        'tier': 'diagnostic',
    }
    assert strategy_target['bindingLabelGroups'][-1] == {
        'label': 'BUS Invalidation',
        'group': 'g_bus_plan',
        'groupTitle': 'Trade Plan',
        'tier': 'diagnostic',
    }
    assert payload['deprecatedFieldPolicy'] == MANIFEST.DEPRECATED_FIELD_POLICY
    assert payload['deprecatedFieldPolicy']['mode'] == 'compatibility_only'
    assert payload['deprecatedFieldPolicy']['preferredFieldVersion'] == 'v7.0a'
    assert payload['deprecatedFieldPolicy']['extensionAllowed'] is False
    assert payload['deprecatedFieldPolicy']['deprecatedGroups'] == []


def test_product_cut_payload_exports_validation_evidence_pack() -> None:
    payload = MANIFEST.build_product_cut_manifest_payload()
    evidence = payload['validationEvidence']

    assert evidence['captureMode'] == MANIFEST.VALIDATION_EVIDENCE_CAPTURE_MODE
    assert evidence['editorScreenshotsAllowed'] == MANIFEST.VALIDATION_EVIDENCE_EDITOR_SCREENSHOTS_ALLOWED
    assert evidence['editorScreenshotsAllowed'] is False
    assert [item['report_label'] for item in evidence['requiredCaptures']] == [
        capture.report_label
        for capture in MANIFEST.VALIDATION_EVIDENCE_CAPTURES
    ]
    assert [item['file'] for item in evidence['requiredCaptures']] == [
        capture.file
        for capture in MANIFEST.VALIDATION_EVIDENCE_CAPTURES
    ]


# — WP9: Surface sprawl curation tests —


def test_surface_definitions_pass_validation() -> None:
    errors = MANIFEST.validate_surface_definitions()
    assert errors == [], f"Surface definition validation errors: {errors}"


def test_all_role_values_are_from_allowed_sets() -> None:
    for surface in MANIFEST.SURFACE_DEFINITIONS:
        assert surface.surface_role in MANIFEST.SURFACE_ROLE_VALUES, \
            f"{surface.file}: surface_role '{surface.surface_role}' not in {MANIFEST.SURFACE_ROLE_VALUES}"
        assert surface.contract_tier in MANIFEST.CONTRACT_TIER_VALUES, \
            f"{surface.file}: contract_tier '{surface.contract_tier}' not in {MANIFEST.CONTRACT_TIER_VALUES}"
        assert surface.consumer_role in MANIFEST.CONSUMER_ROLE_VALUES, \
            f"{surface.file}: consumer_role '{surface.consumer_role}' not in {MANIFEST.CONSUMER_ROLE_VALUES}"


def test_no_duplicate_files_in_surface_definitions() -> None:
    files = [s.file for s in MANIFEST.SURFACE_DEFINITIONS]
    assert len(files) == len(set(files)), f"Duplicate files: {[f for f in files if files.count(f) > 1]}"


def test_mainline_hierarchy_has_exactly_one_lite_and_at_least_one_pro() -> None:
    assert len(MANIFEST.LITE_PRIMARY_FILES) == 1
    assert len(MANIFEST.PRO_PRIMARY_FILES) >= 1
    assert len(MANIFEST.MAINLINE_SURFACE_FILES) == 4


def test_every_pine_file_is_classified_or_explicitly_excluded() -> None:
    import pathlib
    all_pine_files = {p.name for p in pathlib.Path(ROOT).glob('*.pine')}
    governed_files = set(MANIFEST.ALL_SMC_PINE_FILES) | MANIFEST.NON_SMC_PINE_FILES
    unclassified = all_pine_files - governed_files
    assert not unclassified, f"Unclassified .pine files: {sorted(unclassified)}"


def test_non_smc_pine_files_are_disjoint_from_surface_definitions() -> None:
    smc_files = set(MANIFEST.ALL_SMC_PINE_FILES)
    overlap = smc_files & MANIFEST.NON_SMC_PINE_FILES
    assert not overlap, f"Files in both SMC definitions and non-SMC exclusions: {sorted(overlap)}"


def test_companion_surfaces_are_not_in_mainline() -> None:
    mainline = set(MANIFEST.MAINLINE_SURFACE_FILES)
    companions = set(MANIFEST.COMPANION_OPERATOR_ONLY_FILES)
    assert not mainline & companions, "Companion files must not appear as mainline"


def test_legacy_surfaces_are_not_validation_targets() -> None:
    for surface in MANIFEST.SURFACE_DEFINITIONS:
        if surface.surface_role == 'legacy':
            assert not surface.validation_target, \
                f"{surface.file}: legacy surfaces must not be validation targets"


# — WP10: Directional truth tests —

def test_mainline_pine_scripts_carry_explicit_directional_statement() -> None:
    """Every mainline Pine script must contain an explicit directional scope comment."""
    from tests.smc_manifest_test_utils import ROOT, read_text
    directional_markers = ('long-dip specialist', 'long-only', 'short-parity')
    for filename in MANIFEST.MAINLINE_SURFACE_FILES:
        source = read_text(ROOT / filename)
        head = source[:2000]
        found = any(marker in head.lower() for marker in directional_markers)
        assert found, (
            f"{filename}: mainline Pine script must carry an explicit directional "
            f"scope comment in the first 2000 characters"
        )


def test_product_cut_doc_contains_directional_truth_section() -> None:
    from tests.smc_manifest_test_utils import ROOT, read_text
    doc = read_text(ROOT / 'docs' / 'smc-lite-pro-product-cut.md')
    assert 'Directional Truth' in doc, "Product-cut doc must contain a Directional Truth section"
    assert 'Long-Dip' in doc or 'long-dip' in doc, "Product-cut doc must reference the long-dip specialization"


def test_strategy_guide_acknowledges_long_only_scope() -> None:
    from tests.smc_manifest_test_utils import ROOT, read_text
    doc = read_text(ROOT / 'docs' / 'TRADINGVIEW_STRATEGY_GUIDE.md')
    assert 'long-only' in doc.lower() or 'long only' in doc.lower(), \
        "Strategy guide must acknowledge long-only execution scope"

# — WP-A11: Dashboard Binding Simplification tests —


def test_dashboard_bindings_have_tier_classification() -> None:
    """Every dashboard binding must carry a tier ('critical' or 'diagnostic')."""
    for binding in MANIFEST.DASHBOARD_BUS_BINDINGS:
        assert binding.tier in ('critical', 'diagnostic'), \
            f"{binding.label}: tier must be 'critical' or 'diagnostic', got '{binding.tier}'"


def test_critical_bindings_are_at_most_20() -> None:
    """The critical binding set must stay at ≤20 to hit the WP-A11 onboarding target."""
    critical = MANIFEST.DASHBOARD_CRITICAL_BINDINGS
    assert len(critical) <= 20, f"Expected ≤20 critical bindings, got {len(critical)}"


def test_critical_bindings_cover_hero_trust_and_plan() -> None:
    """Critical bindings must include lifecycle, trade plan, and lean surface channels."""
    critical_labels = {b.label for b in MANIFEST.DASHBOARD_CRITICAL_BINDINGS}
    required = {
        'BUS StateCode', 'BUS QualityScore', 'BUS TrendPack', 'BUS MetaPack',
        'BUS StopLevel', 'BUS Target1', 'BUS Target2',
        'BUS LeanPackA', 'BUS LeanPackB',
    }
    missing = required - critical_labels
    assert not missing, f"Critical binding set is missing required channels: {missing}"


def test_diagnostic_bindings_complement_critical() -> None:
    """Critical + diagnostic bindings must equal the full set (no orphans)."""
    critical = set(b.label for b in MANIFEST.DASHBOARD_CRITICAL_BINDINGS)
    diagnostic = set(b.label for b in MANIFEST.DASHBOARD_DIAGNOSTIC_BINDINGS)
    all_labels = set(b.label for b in MANIFEST.DASHBOARD_BUS_BINDINGS)
    assert critical | diagnostic == all_labels
    assert critical & diagnostic == set(), "No binding should be both critical and diagnostic"
