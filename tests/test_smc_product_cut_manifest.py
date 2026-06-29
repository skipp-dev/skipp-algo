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

    dashboard = SURFACE_DEFINITIONS_BY_FILE['SMC_Dashboard.pine']

    assert dashboard.surface_role == 'pro_primary'
    assert dashboard.consumer_role == 'dashboard_companion'
    assert dashboard.validation_target is True


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
                'file': 'SMC_Core_Engine.pine',
                'scriptName': 'SMC Core',
                'checkInputs': False,
                'addToChart': False,
            },
            {
                'file': 'SMC_Dashboard.pine',
                'scriptName': 'SMC Decision Board',
                'savedScriptName': 'SMC Long-Dip Dashboard v7',
                'checkInputs': False,
                'addToChart': False,
            },
            {
                'file': 'SMC_Long_Strategy.pine',
                'scriptName': 'SMC Long-Dip Strategy v7',
                'savedScriptName': 'SMC Long-Dip Strategy v7',
                'checkInputs': False,
                'addToChart': False,
            },
        ],
    }
    assert _load_json('automation/tradingview/preflight-decision-first.json') == {
        'productCutScope': 'smcDecisionFirst',
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


def test_library_release_manifest_tracks_product_cut_roles() -> None:
    payload = _load_json('artifacts/tradingview/library_release_manifest.json')

    assert payload['manifestVersion'] == 2
    assert payload['library']['productivityGate']['publishReady'] is True
    assert payload['library']['productivityGate']['blockingReasons'] == []
    assert payload['library']['productivityGate']['fixtureInputDetected'] is False
    assert payload['library']['productivityGate']['defaultEventRiskDetected'] is False
    assert payload['library']['productivityGate']['placeholderSymbols'] == []
    assert payload['productCut']['mainlineFiles'] == [
        'SMC_Core_Engine.pine',
        'SMC_Dashboard.pine',
        'SMC_Long_Strategy.pine',
    ]
    assert payload['productCut']['manifestVersion'] == 2
    assert payload['productCut']['litePrimaryFiles'] == ['SMC_Core_Engine.pine']
    assert payload['productCut']['proPrimaryFiles'] == ['SMC_Dashboard.pine', 'SMC_Long_Strategy.pine']
    assert payload['productCut']['contracts']['lite'] == [
        'BUS ZoneActive',
        'BUS Armed',
        'BUS Confirmed',
        'BUS Ready',
        'BUS EntryBest',
        'BUS EntryStrict',
        'BUS Trigger',
        'BUS Invalidation',
        'BUS QualityScore',
        'BUS SourceKind',
        'BUS StateCode',
        'BUS TrendPack',
        'BUS LeanPackA',
        'BUS LeanPackB',
    ]
    assert set(payload['productCut']['preflightScopes'].keys()) == {'smcCoreDashboard', 'smcMainline', 'smcDecisionFirst'}
    assert payload['productCut']['preflightScopes']['smcCoreDashboard'][1]['savedScriptName'] == 'SMC Long-Dip Dashboard v7'
    assert payload['productCut']['preflightScopes']['smcMainline'][1]['savedScriptName'] == 'SMC Long-Dip Dashboard v7'
    assert payload['productCut']['preflightScopes']['smcMainline'][2]['savedScriptName'] == 'SMC Long-Dip Strategy v7'
    assert payload['productCut']['preflightScopes']['smcMainline'][1]['bindingContractKey'] == 'dashboardBindings'
    assert payload['productCut']['preflightScopes']['smcMainline'][2]['bindingContractKey'] == 'strategyBindings'
    assert payload['productCut']['deprecatedFieldPolicy']['mode'] == 'compatibility_only'
    assert payload['productCut']['deprecatedFieldPolicy']['extensionAllowed'] is False
    assert {
        item['file']: item['role']
        for item in payload['consumers']
    } == {
        'SMC_Core_Engine.pine': 'producer',
        'SMC_Dashboard.pine': 'dashboard_companion',
        'SMC_Long_Strategy.pine': 'execution_wrapper',
    }
