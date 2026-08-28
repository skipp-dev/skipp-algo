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


# --- Chart-Link completion (2026-08-28): the validation docs must speak the
# --- CURRENT panel group names, and the retired ones must never come back.

# The #4639 names these docs still carried 16 days after the rename — plus
# 'Operator Only', the pre-#4639 prefix whose revert was the #4646 incident.
RETIRED_GROUP_NAMES: tuple[str, ...] = (
    'Lifecycle BUS',
    'Diagnostic Support',
    'Diagnostic Rows',
    'Operator Only',
)

VALIDATION_DOC_PATHS: tuple[pathlib.Path, ...] = (
    CHECKLIST_PATH,
    RUNBOOK_DE_PATH,
    RUNBOOK_EN_PATH,
    SETUP_RUNBOOK_PATH,
)


def _ordered_dashboard_groups() -> list[tuple[str, int]]:
    """(panel title, channel count) in the panel's own group order, derived
    from the binding registry rather than restated."""
    ordered: list[tuple[str, int]] = []
    for binding in MANIFEST.DASHBOARD_BUS_BINDINGS:
        title = MANIFEST.DASHBOARD_GROUP_TITLES_BY_KEY[binding.group]
        if not ordered or ordered[-1][0] != title:
            ordered.append((title, 0))
        ordered[-1] = (title, ordered[-1][1] + 1)
    return ordered


def test_validation_docs_do_not_use_retired_group_names() -> None:
    checked = 0
    for path in VALIDATION_DOC_PATHS:
        text = read_text(path)
        for retired in RETIRED_GROUP_NAMES:
            assert retired not in text, (
                f'{path.name} still names the retired settings group '
                f'{retired!r} — the panel says '
                f'{tuple(MANIFEST.DASHBOARD_GROUP_TITLES)} since #4639'
            )
            checked += 1
    assert checked == len(VALIDATION_DOC_PATHS) * len(RETIRED_GROUP_NAMES)


def test_validation_docs_name_every_current_dashboard_group() -> None:
    assert len(MANIFEST.DASHBOARD_GROUP_TITLES) == 8
    for path in (CHECKLIST_PATH, RUNBOOK_DE_PATH, SETUP_RUNBOOK_PATH):
        for title in MANIFEST.DASHBOARD_GROUP_TITLES:
            assert_contains(path, title)


def test_setup_runbook_table_matches_the_binding_groups() -> None:
    """The 8-row table: panel order, per-group channel count, sum = 64."""
    groups = _ordered_dashboard_groups()
    assert [title for title, _ in groups] == list(MANIFEST.DASHBOARD_GROUP_TITLES)
    assert sum(count for _, count in groups) == len(MANIFEST.ENGINE_BUS_LABELS) == 64
    for position, (title, count) in enumerate(groups, 1):
        assert_contains(SETUP_RUNBOOK_PATH, f'| {position} | {title} | {count} |')


def test_docs_name_the_strategy_chart_link_groups() -> None:
    """The Strategy consumer's groups renamed with the 2026-08-28 completion."""
    for path, fragment in (
        (RUNBOOK_DE_PATH, '`3. Chart Link - Entry States` und `4. Chart Link - Trade Plan`'),
        (RUNBOOK_EN_PATH, '`3. Chart Link - Entry States` and `4. Chart Link - Trade Plan`'),
        (CHECKLIST_PATH, 'the two `Chart Link` groups'),
        (SETUP_RUNBOOK_PATH, 'two **Chart Link** source-binding groups'),
    ):
        assert_contains(path, fragment)
    for path in (RUNBOOK_DE_PATH, RUNBOOK_EN_PATH, CHECKLIST_PATH, SETUP_RUNBOOK_PATH):
        assert 'Expert Mapping' not in read_text(path), (
            f'{path.name} still says Expert Mapping — the Strategy groups are '
            'Chart Link groups since 2026-08-28 (Exit Signal keeps the old '
            'labels until its re-attestation, but these docs do not describe '
            'its groups)'
        )
