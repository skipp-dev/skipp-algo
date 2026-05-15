from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/smc-release-gates.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_gates_workflow_runs_tradingview_post_release_validation() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Set up Node' in workflow_text
    assert 'npm ci' in workflow_text
    assert 'npx playwright install --with-deps chromium' in workflow_text
    assert '- name: Write TradingView storage state' in workflow_text
    assert 'TV_STORAGE_STATE_SECRET: ${{ secrets.TV_STORAGE_STATE }}' in workflow_text
    assert '- name: Run TradingView post-release validation' in workflow_text
    assert 'tv_post_release_validation.json' in workflow_text
    assert 'python scripts/verify_tradingview_post_release.py' in workflow_text
    assert 'artifacts/ci/smc_tradingview_post_release_report.json' in workflow_text


def test_release_gates_workflow_checks_release_reference_manifest_drift() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Verify refreshed release reference manifests are unchanged' in workflow_text
    assert 'smc_release_reference_manifest.diff' in workflow_text
    assert 'git --no-pager diff -- "${manifests[@]}"' in workflow_text
    assert 'Release reference manifest drift detected after refresh. Commit refreshed manifests before publishing.' in workflow_text


# ---------------------------------------------------------------------------
# F-09 — Release gate classification step
# ---------------------------------------------------------------------------


def test_release_gates_workflow_has_classification_step() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert '- name: Classify release gate results (F-09)' in workflow_text
    assert 'ci_structural_pass' in workflow_text
    assert 'operational_release_pass' in workflow_text
    assert 'soft_gates_for_review' in workflow_text


# ---------------------------------------------------------------------------
# WP-R12 — CI summary normalization
# ---------------------------------------------------------------------------


def test_release_gates_workflow_has_normalized_summary_step() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert '- name: Render release gate summary' in workflow_text
    assert 'render_ci_gate_summary.py' in workflow_text
    assert '--enforcement hard' in workflow_text


# ---------------------------------------------------------------------------
# WP-R14 — TV-Publish advisory classification
# ---------------------------------------------------------------------------


def test_tv_validation_step_has_continue_on_error() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert 'id: tv_validation' in workflow_text
    assert 'continue-on-error: true' in workflow_text


def test_tv_validation_has_classification_step() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert '- name: Classify TV validation failure (WP-R14)' in workflow_text
    assert 'classify_tv_gate_failure' in workflow_text
    assert 'external_tv_drift' in workflow_text
    assert "steps.tv_validation.outcome == 'failure'" in workflow_text


# ---------------------------------------------------------------------------
# WP-R20 — Artifact attestation
# ---------------------------------------------------------------------------


def test_release_gates_has_attestation_step() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert '- name: Attest release gate report (WP-R20)' in workflow_text
    # Accept both the floating tag and its SHA-pinned equivalent.
    _ATTEST_V2_SHA = "e8998f949152b193b063cb0ec769d69d929409be"
    assert (
        'actions/attest-build-provenance@v2' in workflow_text
        or f'actions/attest-build-provenance@{_ATTEST_V2_SHA}' in workflow_text
    ), "must reference actions/attest-build-provenance@v2 (or its SHA-pinned equivalent)"
    assert 'smc_release_gates_report.json' in workflow_text


def test_release_gates_has_attestation_permissions() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert 'id-token: write' in workflow_text
    assert 'attestations: write' in workflow_text
