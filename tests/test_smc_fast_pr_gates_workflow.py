from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github/workflows/smc-fast-pr-gates.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow_doc() -> dict:
    data = yaml.safe_load(_read(WORKFLOW_PATH))
    assert isinstance(data, dict)
    return data


def _fast_gate_steps() -> list[dict]:
    jobs = _workflow_doc()["jobs"]
    fast_gates = jobs["fast-gates"]
    steps = fast_gates["steps"]
    assert isinstance(steps, list)
    return steps


def _step(name: str) -> dict:
    for step in _fast_gate_steps():
        if isinstance(step, dict) and step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


def test_fast_pr_gates_workflow_runs_terminal_coverage_subset() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Run terminal coverage subset' in workflow_text
    assert '--cov=streamlit_terminal' in workflow_text
    assert '--cov=streamlit_terminal_alerts' in workflow_text
    assert '--cov=terminal_export' in workflow_text
    assert '--cov=terminal_notifications' in workflow_text
    assert 'tests/test_streamlit_terminal_import.py' in workflow_text
    assert 'tests/test_terminal_notifications.py' in workflow_text
    assert 'tests/test_terminal_export_dispatch.py' in workflow_text
    assert 'tests/test_streamlit_terminal_pure_functions.py' in workflow_text
    assert 'artifacts/ci/terminal_coverage.txt' in workflow_text
    assert 'artifacts/ci/terminal_coverage.xml' in workflow_text


def test_fast_pr_gates_workflow_uploads_terminal_coverage_artifacts() -> None:
    workflow_text = _read(WORKFLOW_PATH)

    assert '- name: Upload fast gate report' in workflow_text
    assert 'artifacts/ci/smc_fast_health_report.json' in workflow_text
    assert 'artifacts/ci/terminal_coverage.txt' in workflow_text
    assert 'artifacts/ci/terminal_coverage.xml' in workflow_text


# ---------------------------------------------------------------------------
# WP-R15 — CI summary normalization
# ---------------------------------------------------------------------------


def test_fast_pr_gates_workflow_has_normalized_summary_step() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert '- name: Render fast gate summary' in workflow_text
    assert 'render_ci_gate_summary.py' in workflow_text
    assert '--enforcement hard' in workflow_text


# ---------------------------------------------------------------------------
# WP-R19 — CI cancel churn
# ---------------------------------------------------------------------------


def test_fast_pr_gates_cancel_in_progress_only_for_prs() -> None:
    workflow_text = _read(WORKFLOW_PATH)
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow_text


def test_fast_pr_gates_verify_both_live_overlay_dashboards() -> None:
    step = _step("Verify live overlay dashboard is up to date")
    run = step.get("run") or ""

    assert "python scripts/update_overlay_dashboard.py" in run
    assert "services/live_overlay_daemon/infra/grafana/dashboard.json" in run
    assert (
        "services/live_overlay_daemon/infra/grafana/dashboard-signals-experiments.json"
        in run
    )
    assert run.count("--check") == 2
