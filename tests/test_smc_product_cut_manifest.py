from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding = 'utf-8'))


def test_checked_in_product_cut_artifact_matches_python_manifest() -> None:
    from scripts.smc_bus_manifest import build_product_cut_manifest_payload

    assert _load_json('artifacts/tradingview/smc_product_cut_manifest.json') == build_product_cut_manifest_payload()


def test_dashboard_is_explicitly_classified_in_main_product_cut() -> None:
    from scripts.smc_bus_manifest import SURFACE_DEFINITIONS_BY_FILE

    dashboard = SURFACE_DEFINITIONS_BY_FILE['SMC_Long_Dip_Dashboard.pine']

    assert dashboard.surface_role == 'pro_primary'
    assert dashboard.consumer_role == 'dashboard_companion'
    assert dashboard.validation_target is True


def test_product_cut_manifest_exports_surface_governance_schema_v3() -> None:
    payload = _load_json('artifacts/tradingview/smc_product_cut_manifest.json')
    surfaces = {
        item['file']: item
        for item in payload['surfaceRoles']
    }

    assert payload['manifestVersion'] == 3
    assert surfaces['SMC_Long_Dip_Dashboard.pine']['rollout_state'] == 'deployed'
    assert surfaces['SMC_Hold_Manager.pine']['lifecycle'] == 'planned'
    assert surfaces['SMC_Hold_Manager.pine']['bus_dependencies'] == ['engine_v2']
    assert surfaces['SMC_HTF_Confluence.pine']['compile_expectation'] == 'known_broken'
    assert len(surfaces['SMC_HTF_Confluence.pine']['known_missing_mp_fields']) == 12
    assert surfaces['SMC_Context_Overlay.pine']['bus_dependencies'] == ['context_v3']
    assert 'SMC++.pine' not in surfaces
    assert 'SMC_Core_Zones.pine' not in surfaces
    assert 'SMC Core + Zones.pine' not in surfaces


def test_preflight_configs_use_canonical_product_cut_scopes() -> None:
    assert _load_json('automation/tradingview/preflight-core-dashboard.json') == {
        'productCutScope': 'smcCoreDashboard',
    }
    assert _load_json('automation/tradingview/preflight-smc-mainline.json') == {
        'productCutScope': 'smcMainline',
    }
    assert _load_json('automation/tradingview/preflight-smc-mainline-open-only.json') == {
        'targets': [
            {
                'file': 'SMC_Long_Dip_Suite.pine',
                'scriptName': 'SMC Long-Dip Suite',
                'checkInputs': False,
                'addToChart': False,
            },
            {
                'file': 'SMC_Long_Dip_Dashboard.pine',
                'scriptName': 'SMC Long-Dip Dashboard',
                'savedScriptName': 'SMC Long-Dip Dashboard',
                'checkInputs': False,
                'addToChart': False,
            },
            {
                'file': 'SMC_Long_Dip_Strategy.pine',
                'scriptName': 'SMC Long-Dip Strategy',
                'savedScriptName': 'SMC Long-Dip Strategy',
                'checkInputs': False,
                'addToChart': False,
            },
        ],
    }
    assert _load_json('automation/tradingview/preflight-decision-first.json') == {
        'productCutScope': 'smcDecisionFirst',
    }
    assert _load_json(
        'automation/tradingview/preflight-hold-manager-shadow.json'
    ) == {
        'productCutScope': 'smcHoldManagerShadow',
    }
    assert _load_json('automation/tradingview/preflight-r1-companions.json') == {
        'productCutScope': 'smcR1Companions',
    }


def test_product_cut_manifest_exports_validation_evidence_policy() -> None:
    from scripts.smc_bus_manifest import VALIDATION_EVIDENCE_CAPTURES

    evidence = _load_json('artifacts/tradingview/smc_product_cut_manifest.json')['validationEvidence']

    assert evidence['captureMode'] == 'rendered_chart_only'
    assert evidence['editorScreenshotsAllowed'] is False
    assert [item['report_label'] for item in evidence['requiredCaptures']] == [
        capture.report_label
        for capture in VALIDATION_EVIDENCE_CAPTURES
    ]


def test_checked_in_product_cut_artifact_exports_binding_contract_metadata() -> None:
    payload = _load_json('artifacts/tradingview/smc_product_cut_manifest.json')
    dashboard_target = payload['preflightScopes']['smcMainline'][1]
    strategy_target = payload['preflightScopes']['smcMainline'][2]
    hold_target = payload['preflightScopes']['smcHoldManagerShadow'][1]
    event_target = payload['preflightScopes']['smcR1Companions'][1]
    exit_target = payload['preflightScopes']['smcR1Companions'][2]

    assert dashboard_target['bindingContractKey'] == 'dashboardBindings'
    assert dashboard_target['bindingContractName'] == 'dashboard companion BUS bindings'
    assert dashboard_target['bindingConsumerRole'] == 'dashboard_companion'
    assert dashboard_target['bindingLabelGroups'][0]['groupTitle'] == 'Lifecycle BUS'
    assert dashboard_target['bindingLabelGroups'][-1]['groupTitle'] == 'Preset Contract'
    assert strategy_target['bindingContractKey'] == 'strategyBindings'
    assert strategy_target['bindingContractName'] == 'execution wrapper BUS bindings'
    assert strategy_target['bindingConsumerRole'] == 'execution_wrapper'
    assert strategy_target['bindingLabelGroups'][0]['groupTitle'] == 'Entry States'
    assert strategy_target['bindingLabelGroups'][-1]['groupTitle'] == 'Trade Plan'
    assert hold_target['bindingContractKey'] == 'holdManagerBindings'
    assert hold_target['bindingContractName'] == 'Hold Manager BUS bindings'
    assert hold_target['bindingConsumerRole'] == 'exit_companion'
    assert len(hold_target['bindingContractLabels']) == 13
    assert {
        group['groupTitle'] for group in hold_target['bindingLabelGroups']
    } == {'Engine BUS v2 (Expert Mapping)'}
    assert event_target['bindingContractKey'] == 'eventOverlayBindings'
    assert event_target['bindingContractLabels'] == ['BUS LeanPackA']
    assert exit_target['bindingContractKey'] == 'exitSignalBindings'
    assert len(exit_target['bindingContractLabels']) == 9


def test_library_release_manifest_tracks_product_cut_roles() -> None:
    payload = _load_json('artifacts/tradingview/library_release_manifest.json')
    product_cut = _load_json('artifacts/tradingview/smc_product_cut_manifest.json')

    assert payload['manifestVersion'] == 2
    assert payload['library']['productivityGate']['publishReady'] is True
    assert payload['library']['productivityGate']['blockingReasons'] == []
    assert payload['library']['productivityGate']['fixtureInputDetected'] is False
    # 2026-07-23: the enriched pipeline is restored (#3896 revert landed and the
    # data path is fixed end-to-end), so v162 carries REAL event risk from the
    # builder — not the static-control-plane defaults the old assertions pinned.
    # placeholderSymbols is non-empty (CCC) but non-blocking, because that only
    # blocks when paired with fixture input (generator: fixture_input AND
    # placeholder_symbols), and fixtureInputDetected is False here.
    assert payload['library']['productivityGate']['defaultEventRiskDetected'] is False
    assert payload['library']['productivityGate']['eventRiskSource'] == 'smc_event_risk_builder'
    assert payload['library']['productivityGate']['placeholderSymbols'] == ['CCC']
    assert payload['productCut']['mainlineFiles'] == product_cut['mainlineSurfaceFiles']
    assert payload['productCut']['manifestVersion'] == 3
    assert payload['productCut']['litePrimaryFiles'] == product_cut['litePrimaryFiles']
    assert payload['productCut']['proPrimaryFiles'] == product_cut['proPrimaryFiles']
    assert payload['productCut']['companionOperatorOnlyFiles'] == product_cut['companionOperatorOnlyFiles']
    assert payload['productCut']['internalFiles'] == product_cut['internalFiles']
    assert payload['productCut']['legacyFiles'] == product_cut['legacyFiles']
    assert payload['productCut']['contracts']['lite'] == product_cut['contracts']['lite']
    assert set(payload['productCut']['preflightScopes'].keys()) == {
        'smcCoreDashboard',
        'smcMainline',
        'smcDecisionFirst',
        'smcHoldManagerShadow',
        'smcR1Companions',
    }
    assert payload['productCut']['preflightScopes']['smcCoreDashboard'][1]['savedScriptName'] == 'SMC Long-Dip Dashboard'
    assert payload['productCut']['preflightScopes']['smcMainline'][1]['savedScriptName'] == 'SMC Long-Dip Dashboard'
    assert payload['productCut']['preflightScopes']['smcMainline'][2]['savedScriptName'] == 'SMC Long-Dip Strategy'
    assert payload['productCut']['preflightScopes']['smcMainline'][1]['bindingContractKey'] == 'dashboardBindings'
    assert payload['productCut']['preflightScopes']['smcMainline'][2]['bindingContractKey'] == 'strategyBindings'
    assert payload['productCut']['preflightScopes']['smcHoldManagerShadow'][1]['bindingContractKey'] == 'holdManagerBindings'
    assert payload['productCut']['deprecatedFieldPolicy']['mode'] == 'compatibility_only'
    assert payload['productCut']['deprecatedFieldPolicy']['extensionAllowed'] is False
    assert {
        item['file']: item['role']
        for item in payload['consumers']
    } == {
        'SMC_Long_Dip_Suite.pine': 'producer',
        'SMC_Long_Dip_Dashboard.pine': 'dashboard_companion',
        'SMC_Long_Dip_Strategy.pine': 'execution_wrapper',
    }
