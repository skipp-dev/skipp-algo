"""What ``credential-health-check.yml``'s probe step decides, executed.

The step exits 0 on purpose so the annotation and issue-filing steps run, and
publishes the verdict as ``overall`` instead. Its own comment states the rule
this file pins: *"a missing report file maps to error"*.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
turning the missing-report branch's ``overall=error`` into ``overall=ok`` left
all **24708 tests green**. A probe that dies before writing its report would
then report healthy credentials, "Fail the job on error" would never fire, and
the workflow whose entire purpose is to surface credential problems loudly
would go quiet -- with a green tick.

Not a value-preserving mutation, so a whole-line source pin would also have
caught it. None existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import Stub, declares_bash_default, run_step

WORKFLOW = "credential-health-check.yml"
STEP = "Run credential health probes"
REPORT = "artifacts/ci/credential_health.json"

ANNOTATE = "Surface probe results as annotations"
ISSUE = "Open / update cron-failure issue on warn or error"
SLACK = "Notify operator via Slack on warn or error (Composio, opt-in)"
FAIL_JOB = "Fail the job on error"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="probe",
)

# Dispatches on argv: the probe script itself is faked (it would reach real
# vendors), while the `python -c` that parses the report is the genuine
# computation under test and runs for real.
_PYTHON = Stub(script='''
case "$1" in
  scripts/credential_health_check.py)
     if [ -n "${REPORT_BODY:-}" ]; then
       mkdir -p artifacts/ci
       printf '%s' "$REPORT_BODY" > artifacts/ci/credential_health.json
     fi
     exit "${PROBE_RC:-0}" ;;
  -c) exec "$REAL_PYTHON" "$@" ;;
esac
exit 0
''')


def _probe(tmp_path: Path, *, severity: str | None, rc: int = 0):
    """Run the step. ``severity=None`` means the probe wrote no report at all."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    env = {"REAL_PYTHON": sys.executable, "PROBE_RC": str(rc)}
    if severity is not None:
        env["REPORT_BODY"] = json.dumps({"overall_severity": severity, "checks": []})
    # Every `${{ secrets.* }}` / `${{ vars.* }}` the step's `env:` block reads
    # is resolved by Actions before the shell starts; none reaches this block.
    return run_step(WORKFLOW, STEP, tmp_path, env=env, stubs={"python": _PYTHON})


def _fired(overall: str, rc: str) -> set[str]:
    outputs = {"probe.overall": overall, "probe.rc": rc}
    return {name for name in (ANNOTATE, ISSUE, SLACK, FAIL_JOB)
            if evaluate_condition(_CONDITIONS[name], outputs)}


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_healthy_credentials_report_ok_and_nothing_fires(tmp_path: Path) -> None:
    result = _probe(tmp_path, severity="ok")
    assert result.outputs["overall"] == "ok", result.outputs
    assert result.outputs["rc"] == "0"
    assert _fired("ok", "0") == {ANNOTATE}, "a healthy probe annotates and nothing else"


def test_a_warn_opens_the_issue_but_does_not_fail_the_job(tmp_path: Path) -> None:
    result = _probe(tmp_path, severity="warn")
    assert result.outputs["overall"] == "warn"
    fired = _fired("warn", "0")
    assert ISSUE in fired and SLACK in fired
    assert FAIL_JOB not in fired, "warn is not error; failing the job on it pages nobody twice"


def test_an_error_fails_the_job(tmp_path: Path) -> None:
    result = _probe(tmp_path, severity="error")
    assert result.outputs["overall"] == "error"
    assert FAIL_JOB in _fired("error", "0")


def test_a_probe_that_wrote_no_report_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """The assertion this whole file exists for.

    A crash before the report is written is the one case where the probe has
    nothing to say, and the block's comment says it must be read as `error`.
    Read as `ok` it is indistinguishable in the outputs from a clean run.
    """
    result = _probe(tmp_path, severity=None, rc=2)
    assert result.outputs["overall"] == "error", result.outputs
    assert result.outputs["rc"] == "2", "the real exit code must survive, not a constant"
    assert FAIL_JOB in _fired("error", "2")


def test_the_step_itself_always_exits_zero(tmp_path: Path) -> None:
    """Deliberate: the annotation and issue steps must still run after a failure.

    They are gated on `always() && …`, but a step that exits non-zero without
    `continue-on-error` fails the job before the verdict is ever published.
    """
    assert _probe(tmp_path, severity=None, rc=2).returncode == 0
    assert _probe(tmp_path / "b", severity="error", rc=1).returncode == 0


def test_the_retired_newsapi_probe_stays_skipped(tmp_path: Path) -> None:
    """2026-07-08: NewsAPI.ai was retired; probing it reports a false alarm.

    Read off the recorded invocation rather than the source, because the flag
    has to survive line continuations to actually reach the command line.
    """
    call = _probe(tmp_path, severity="ok").called_with("credential_health_check.py")
    assert call, "the probe never ran"
    assert "--skip-newsapi" in call[0], call[0]
    assert f"--output {REPORT}" in call[0], call[0]
