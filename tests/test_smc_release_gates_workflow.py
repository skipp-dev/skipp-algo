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