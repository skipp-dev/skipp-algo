from __future__ import annotations

import pathlib

from tests.smc_manifest_test_utils import ROOT, load_manifest, read_text

CHECKLIST_PATH = ROOT / 'docs' / 'tradingview-validation-checklist.md'
RUNBOOK_DE_PATH = ROOT / 'docs' / 'tradingview-manual-validation-runbook.md'
RUNBOOK_EN_PATH = ROOT / 'docs' / 'tradingview-manual-validation-runbook_EN.md'
REPORT_TEMPLATE_DE_PATH = ROOT / 'docs' / 'tradingview-manual-validation-report-template.md'
REPORT_TEMPLATE_EN_PATH = ROOT / 'docs' / 'tradingview-manual-validation-report-template_EN.md'
AUDIT_PATH = ROOT / 'docs' / 'smc-bus-v2-audit.md'
ROADMAP_PATH = ROOT / 'docs' / 'smc-bus-roadmap.md'
RUNTIME_BUDGET_PATH = ROOT / 'docs' / 'RUNTIME_BUDGET.md'
PRODUCT_CUT_PATH = ROOT / 'docs' / 'smc-lite-pro-product-cut.md'

MANIFEST = load_manifest()
ENGINE_COUNT = len(MANIFEST.ENGINE_BUS_LABELS)
DASHBOARD_COUNT = len(MANIFEST.DASHBOARD_BUS_LABELS)
STRATEGY_COUNT = len(MANIFEST.STRATEGY_BUS_LABELS)


def assert_contains(path: pathlib.Path, fragment: str) -> None:
    text = read_text(path)
    assert fragment in text, f'{path.name} must contain: {fragment}'


def test_tradingview_validation_checklist_matches_manifest_counts() -> None:
    assert_contains(CHECKLIST_PATH, f'- Producer hidden series: `{ENGINE_COUNT}`')
    assert_contains(CHECKLIST_PATH, f'- Dashboard bindings: `{DASHBOARD_COUNT}`')
    assert_contains(CHECKLIST_PATH, f'- Strategy bindings: `{STRATEGY_COUNT}`')
    assert_contains(CHECKLIST_PATH, f'The dashboard expects all `{DASHBOARD_COUNT}` bindings')
    assert_contains(CHECKLIST_PATH, f'The strategy expects only the {STRATEGY_COUNT} bindings declared')
    assert_contains(CHECKLIST_PATH, f'bind all {DASHBOARD_COUNT} sources to the core plots.')


def test_manual_validation_runbooks_match_manifest_counts() -> None:
    assert_contains(RUNBOOK_DE_PATH, f'Dashboard hinzufügen und alle {DASHBOARD_COUNT} `source`-Bindings auf den Core legen.')
    assert_contains(RUNBOOK_DE_PATH, f'Strategy hinzufügen und alle {STRATEGY_COUNT} `source`-Bindings auf den Core legen.')
    assert_contains(RUNBOOK_DE_PATH, f'Alle {DASHBOARD_COUNT} Dashboard-Bindings')
    assert_contains(RUNBOOK_DE_PATH, f'Alle {DASHBOARD_COUNT} Serien sind auswählbar.')

    assert_contains(RUNBOOK_EN_PATH, f'Add the dashboard and bind all {DASHBOARD_COUNT} `source` inputs to the core.')
    assert_contains(RUNBOOK_EN_PATH, f'Add the strategy and bind all {STRATEGY_COUNT} `source` inputs to the core.')
    assert_contains(RUNBOOK_EN_PATH, f'All {DASHBOARD_COUNT} dashboard bindings listed')
    assert_contains(RUNBOOK_EN_PATH, f'All {DASHBOARD_COUNT} series are selectable.')


def test_manual_validation_evidence_pack_matches_manifest() -> None:
    for capture in MANIFEST.VALIDATION_EVIDENCE_CAPTURES:
        assert_contains(REPORT_TEMPLATE_DE_PATH, f'- {capture.report_label}:')
        assert_contains(REPORT_TEMPLATE_EN_PATH, f'- {capture.report_label}:')
        assert_contains(RUNBOOK_DE_PATH, f'- {capture.runbook_label_de}')
        assert_contains(RUNBOOK_EN_PATH, f'- {capture.runbook_label_en}')

    assert_contains(RUNBOOK_DE_PATH, 'Die kanonische Product-Surface-Evidence liegt im `validationEvidence`-Block des Artifacts `artifacts/tradingview/smc_product_cut_manifest.json`.')
    assert_contains(RUNBOOK_EN_PATH, 'The canonical product-surface evidence pack lives in the `validationEvidence` block of `artifacts/tradingview/smc_product_cut_manifest.json`.')
    assert_contains(RUNBOOK_DE_PATH, 'Nur gerenderte Chart-Screenshots erfassen, keine Pine-Editor-Screenshots.')
    assert_contains(RUNBOOK_EN_PATH, 'Capture rendered chart screenshots, not Pine editor screenshots.')
    assert_contains(REPORT_TEMPLATE_DE_PATH, 'Editor-Screenshots ausgeschlossen: ja/nein')
    assert_contains(REPORT_TEMPLATE_EN_PATH, 'Editor screenshots excluded: yes/no')


def test_core_bus_docs_match_manifest_counts() -> None:
    assert_contains(AUDIT_PATH, f'The current contract is a {ENGINE_COUNT}-channel hidden plot bus.')
    assert_contains(AUDIT_PATH, f'- The producer exports {ENGINE_COUNT} hidden plots')
    assert_contains(AUDIT_PATH, f'- The dashboard binds {DASHBOARD_COUNT} `input.source()` channels')
    assert_contains(AUDIT_PATH, f'- The strategy binds {STRATEGY_COUNT} `input.source()` channels')

    assert_contains(ROADMAP_PATH, f'the active dashboard now binds the full {ENGINE_COUNT}-channel producer contract directly')
    assert_contains(RUNTIME_BUDGET_PATH, f'The active BUS export surface now consumes {ENGINE_COUNT} hidden plots')
    assert_contains(RUNTIME_BUDGET_PATH, f'The active dashboard now reads all {DASHBOARD_COUNT} producer channels')
    assert_contains(PRODUCT_CUT_PATH, f'den vollen {ENGINE_COUNT}-Kanal-BUS-Contract')
    assert_contains(PRODUCT_CUT_PATH, f'Das aktive Dashboard nutzt derzeit den kompletten {ENGINE_COUNT}-Kanal-Producer-Vertrag.')


SETUP_RUNBOOK_PATH = ROOT / 'docs' / 'smc-mainline-setup-runbook.md'


def test_mainline_setup_runbook_matches_manifest_counts() -> None:
    assert_contains(SETUP_RUNBOOK_PATH, f'all {DASHBOARD_COUNT} `input.source(...)` channels **top-to-bottom**')
    assert_contains(SETUP_RUNBOOK_PATH, f'all {STRATEGY_COUNT} `input.source(...)` channels **top-to-bottom**')
    assert_contains(SETUP_RUNBOOK_PATH, f'fewer than {DASHBOARD_COUNT}')
    assert_contains(SETUP_RUNBOOK_PATH, f'fewer than {STRATEGY_COUNT}')


def test_mainline_setup_runbook_references_canonical_sources() -> None:
    assert_contains(SETUP_RUNBOOK_PATH, 'smc_bus_manifest.py')
    assert_contains(SETUP_RUNBOOK_PATH, 'smc_product_cut_manifest.json')
    assert_contains(SETUP_RUNBOOK_PATH, 'npm run tv:preflight:smc-mainline')
