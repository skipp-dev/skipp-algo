"""Pin-test for the feature-importance-daily workflow.

E4-3 (Q3): the workflow must surface ranking-drift signals as a workflow
warning (analog to weight-drift-gate). This locks the parsing tokens
emitted by ``open_prep.feature_importance_report`` and the GitHub
Actions output names so a refactor on either side breaks loudly.
"""
from __future__ import annotations

from pathlib import Path

import open_prep.feature_importance_report as fr

WF = Path(".github/workflows/feature-importance-daily.yml")


def _workflow_text() -> str:
    return WF.read_text(encoding="utf-8")


def test_workflow_parses_drift_status_token() -> None:
    text = _workflow_text()
    # The script writes "drift_status=…" — the workflow must parse it.
    assert "drift_status=" in text
    assert "drift_max_delta=" in text


def test_workflow_emits_warning_on_drift() -> None:
    text = _workflow_text()
    assert "Alert on ranking drift" in text
    assert "steps.fi.outputs.drift_status == 'warn'" in text
    assert "::warning" in text


def test_workflow_writes_step_summary() -> None:
    text = _workflow_text()
    assert "GITHUB_STEP_SUMMARY" in text
    assert "ranking_drift" in text


def test_workflow_prefers_gpu_labeled_runner() -> None:
    text = _workflow_text()
    assert "SMC_PRIORITY_CRON_GPU_SELF_HOSTED_LABEL" in text
    assert "priority-gpu" not in text  # variable-driven, not hard-coded


def test_workflow_forces_gpu_backend_on_self_hosted() -> None:
    text = _workflow_text()
    assert "requirements-gpu.txt" in text
    assert "OPEN_PREP_FI_BACKEND=gpu" in text
    assert "OPEN_PREP_FI_BACKEND=cpu" in text


def test_workflow_uploads_generated_report_artifact() -> None:
    text = WF.read_text(encoding="utf-8").replace("\\", "/")
    assert f"{fr.FI_REPORT_DIR.as_posix()}/latest.json" in text
    assert "artifacts/open_prep/outcomes/feature_importance/latest.json" not in text


# --- the report's status, executed rather than described ---------------------
#
# `fi` publishes fi_status and drift_status; the annotation step and the G1
# countdown read them. Measured 2026-08-04 with a value-preserving arm swap
# (status insufficient_labels <-> no_data): all 159 assertions across the 5
# files that name this workflow stayed green.
#
# The step's own comment says what is at stake: "only a real status=ok may be
# annotated ok, or the G1 countdown (>=5 days status=ok) reads as met while the
# report never left insufficient_labels." Nothing tested that.

from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_FI_STEP = "Run feature-importance report"


def _fi(tmp_path: Path, *, log: str, rc: int = 0):
    """Run the real step with the report script shadowed.

    The script's contract is its stdout plus an exit code; both are supplied
    here, so what gets measured is the step's classification of them.
    """
    return run_step(
        "feature-importance-daily.yml", _FI_STEP, tmp_path,
        env={"LOOKBACK": "30", "SMC_PYTHON_BIN": "fi-stub", "FI_LOG": log},
        stubs={"fi-stub": Stub(script=f'printf \'%s\\n\' "$FI_LOG"\nexit {rc}')},
    )


def test_a_clean_report_is_ok(tmp_path: Path) -> None:
    result = _fi(tmp_path, log="rows=120 drift_status=stable drift_max_delta=3")
    assert result.returncode == 0, result.stderr
    assert result.outputs["fi_status"] == "ok"


def test_insufficient_labels_is_never_annotated_ok(tmp_path: Path) -> None:
    """The G1 countdown reads fi_status. Reporting ok here fakes a gate.

    Exit code 0 alone is not evidence of a usable report: the script is
    fail-soft and exits 0 for both no_data and insufficient_labels.
    """
    result = _fi(tmp_path, log="status=insufficient_labels rows=4", rc=0)
    assert result.outputs["fi_status"] == "insufficient_labels", (
        f"a fail-soft status must be reported as itself; got {result.outputs}"
    )


def test_no_data_is_reported_as_itself(tmp_path: Path) -> None:
    result = _fi(tmp_path, log="status=no_data", rc=0)
    assert result.outputs["fi_status"] == "no_data"


def test_a_real_failure_is_an_error_and_fails_the_step(tmp_path: Path) -> None:
    """rc != 0 without a fail-soft token is a genuine break, not a quiet day."""
    result = _fi(tmp_path, log="Traceback (most recent call last):", rc=2)
    assert result.returncode == 2, (
        f"a real failure must propagate the exit code; got {result.returncode}"
    )
    assert result.outputs["fi_status"] == "error"


def test_a_fail_soft_status_outranks_a_nonzero_exit(tmp_path: Path) -> None:
    """Order matters, and only execution shows which way.

    The fail-soft branches are checked BEFORE rc, so a script that reports
    insufficient_labels and still exits non-zero keeps the job green under its
    own name. Reversing the two would turn every thin-data day red.
    """
    result = _fi(tmp_path, log="status=insufficient_labels", rc=1)
    assert result.returncode == 0, "a fail-soft day must not fail the job"
    assert result.outputs["fi_status"] == "insufficient_labels"


def test_the_drift_tokens_come_from_the_report(tmp_path: Path) -> None:
    result = _fi(tmp_path, log="status=ok drift_status=degraded drift_max_delta=17")
    assert result.outputs["drift_status"] == "degraded"
    assert result.outputs["drift_max_delta"] == "17"


def test_absent_drift_tokens_read_as_unknown_not_as_healthy(tmp_path: Path) -> None:
    """A report that said nothing about drift must not be recorded as stable."""
    result = _fi(tmp_path, log="rows=120")
    assert result.outputs["drift_status"] == "unknown", (
        f"missing drift telemetry must not read as a verdict; got {result.outputs}"
    )
    assert result.outputs["drift_max_delta"] == "0"
