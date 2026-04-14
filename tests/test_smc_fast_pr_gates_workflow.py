from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/smc-fast-pr-gates.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fast_pr_gates_workflow_runs_terminal_coverage_subset() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Run terminal coverage subset' in workflow_text
    assert '--cov=streamlit_terminal' in workflow_text
    assert '--cov=streamlit_terminal_alerts' in workflow_text
    assert 'tests/test_streamlit_terminal_import.py' in workflow_text
    assert 'tests/test_streamlit_terminal_pure_functions.py' in workflow_text
    assert 'artifacts/ci/terminal_coverage.txt' in workflow_text
    assert 'artifacts/ci/terminal_coverage.xml' in workflow_text


def test_fast_pr_gates_workflow_uploads_terminal_coverage_artifacts() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Upload fast gate report' in workflow_text
    assert 'artifacts/ci/smc_fast_health_report.json' in workflow_text
    assert 'artifacts/ci/terminal_coverage.txt' in workflow_text
    assert 'artifacts/ci/terminal_coverage.xml' in workflow_text
