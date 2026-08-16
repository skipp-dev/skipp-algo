"""What ``plan-2-8-weekly-digest.yml``'s resolve_alerts step decides, executed.

``has_alerts`` routes the weekly digest to one of two mutually exclusive
steps: open a drift-alert issue (``== 'True'``) or close the open ones
(``== 'False'``). The value is whatever a one-line python prints, with a
fallback for the case the digest never produced its alerts file.

Measured 2026-08-04 against a green unmutated baseline of the full suite:
turning the ``|| echo False`` fallback into ``|| echo True`` left all **24708
tests green** -- including the ~380 test files that name this workflow. An
unreadable alerts.json would then open a drift-alert issue every week on no
evidence at all.

Not a value-preserving mutation, so a whole-line source pin would also have
caught it. None existed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests._fast_gates_gate import evaluate_condition, step_conditions
from tests._workflow_step_shell import Stub, declares_bash_default, run_step

WORKFLOW = "plan-2-8-weekly-digest.yml"
STEP = "Resolve final has_alerts"
ALERTS = Path("artifacts/plan_2_8_digest/alerts.json")

OPEN_ISSUE = "Open drift-alert issue"
CLOSE_ISSUES = "Close drift-alert issues when alerts cleared"

_CONDITIONS = step_conditions(
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / WORKFLOW,
    job="weekly-digest",
)


def _resolve(tmp_path: Path, body: str | None):
    """``body=None`` means the digest never wrote its alerts file."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    if body is not None:
        target = tmp_path / ALERTS
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return run_step(WORKFLOW, STEP, tmp_path, env={},
                    stubs={"python": Stub(passthrough=sys.executable)})


def _routed(has_alerts: str) -> set[str]:
    outputs = {"resolve_alerts.has_alerts": has_alerts}
    return {name for name in (OPEN_ISSUE, CLOSE_ISSUES)
            if evaluate_condition(_CONDITIONS[name], outputs)}


def test_the_workflow_still_declares_the_shell_this_harness_runs() -> None:
    assert declares_bash_default(WORKFLOW)


def test_real_alerts_open_the_issue(tmp_path: Path) -> None:
    result = _resolve(tmp_path, json.dumps({"has_alerts": True}))
    assert result.outputs["has_alerts"] == "True", result.outputs
    assert _routed("True") == {OPEN_ISSUE}


def test_no_alerts_closes_the_open_issues(tmp_path: Path) -> None:
    """The control direction, and the reason the value is a python bool.

    The conditions compare against `'True'`/`'False'` -- python's repr, not
    shell's `true`/`false`. A lowercase value matches neither condition and
    the digest would silently route nowhere.
    """
    result = _resolve(tmp_path, json.dumps({"has_alerts": False}))
    assert result.outputs["has_alerts"] == "False", result.outputs
    assert _routed("False") == {CLOSE_ISSUES}


def test_a_missing_alerts_file_routes_nowhere(tmp_path: Path) -> None:
    """Revised 2026-08-15; the 2026-08-04 decision said "closes rather than
    opens".

    That decision's concern stands -- an `|| echo True` fallback would
    manufacture a drift issue every week on no evidence (measured then:
    24708 tests stayed green under that mutation). But its chosen direction
    conflated absence of evidence with evidence of absence: a HEALTHY digest
    writes alerts.json unconditionally, in both verdicts, so a missing file
    only ever means the instrument broke -- and the fallback then closed
    standing alarms on the strength of a measurement that never happened
    (the upstream digest/snooze steps are set +e fail-soft, so this path is
    reachable on any of their crashes). `unknown` dominates both concerns:
    it opens nothing (their worry) and closes nothing (this one).
    """
    result = _resolve(tmp_path, None)
    assert result.outputs["has_alerts"] == "unknown", result.outputs
    assert _routed("unknown") == set()


def test_a_corrupt_alerts_file_takes_the_same_fallback(tmp_path: Path) -> None:
    """Not the same case: the file exists, so the read fails rather than the open."""
    result = _resolve(tmp_path, "{not json")
    assert result.outputs["has_alerts"] == "unknown", result.outputs
    assert result.returncode == 0, "a corrupt digest must not fail the weekly run"


def test_the_verdict_reaches_the_run_log_too(tmp_path: Path) -> None:
    """The operator reads the run page, not the outputs blob."""
    assert "Final has_alerts=True" in _resolve(
        tmp_path, json.dumps({"has_alerts": True})
    ).stdout


def test_the_two_routes_are_mutually_exclusive(tmp_path: Path) -> None:
    """Both firing would open and close the same issue in one run; a broken
    measurement (None) routes NOWHERE -- revised 2026-08-15, see above.

    Directory names are index-based on purpose: the previous
    ``str(body)[:12]`` put a double quote into the work dir, which breaks the
    harness's generated python wrapper (bash syntax error) -- the old
    fallback then read as False, which ACCIDENTALLY satisfied the old
    "exactly one route" assertion, so the harness defect stayed invisible
    until unknown routed to zero. Measured 2026-08-15.
    """
    for index, (body, expected_routes) in enumerate(
        (
            (json.dumps({"has_alerts": True}), 1),
            (json.dumps({"has_alerts": False}), 1),
            (None, 0),
        )
    ):
        result = _resolve(tmp_path / f"case{index}", body)
        assert len(_routed(result.outputs["has_alerts"])) == expected_routes, result.outputs
