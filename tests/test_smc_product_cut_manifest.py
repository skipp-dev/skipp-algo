from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _load_json(path: str) -> dict:
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
    assert _load_json('automation/tradingview/preflight-decision-first.json') == {
        'productCutScope': 'smcDecisionFirst',
    }


def test_library_release_manifest_tracks_product_cut_roles() -> None:
    payload = _load_json('artifacts/tradingview/library_release_manifest.json')

    assert payload['productCut']['mainlineFiles'] == [
        'SMC_Core_Engine.pine',
        'SMC_Dashboard.pine',
        'SMC_Long_Strategy.pine',
    ]
    assert payload['productCut']['litePrimaryFiles'] == ['SMC_Core_Engine.pine']
    assert payload['productCut']['proPrimaryFiles'] == ['SMC_Dashboard.pine', 'SMC_Long_Strategy.pine']
    assert {
        item['file']: item['role']
        for item in payload['consumers']
    } == {
        'SMC_Core_Engine.pine': 'producer',
        'SMC_Dashboard.pine': 'dashboard_companion',
        'SMC_Long_Strategy.pine': 'execution_wrapper',
    }