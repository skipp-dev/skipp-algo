"""Structural pin-test for the F2 daily promotion-gate workflow YAML.

Guards against future edits accidentally breaking the §2.4 G2 rollback
flow. We do NOT execute the workflow; we just parse the YAML and assert
the invariants that matter:

  * Step ordering: gate -> append-history -> open-issue -> auto-revert
    -> annotate -> summary -> upload.
  * Conditional gates:
      - append-history fires only when status='ready' AND rc='0'
      - open-issue    fires only when status='ready' AND rc='2'
      - auto-revert   fires only when status='ready' AND rc='2'
      - annotate / summary / upload run on always() (with status guard
        for the artifact upload).
  * Permissions include issues:write so the GitHub-Issue-Ping rule can
    work.
  * Cron stays at 10:00 UTC daily.
  * Upload bundle includes both the revert journal and the contextual
    calibration archive directory.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "f2-promotion-gate-daily.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    wf = _load()
    return wf["jobs"]["promotion-gate"]["steps"]


def _step_by_name(name: str) -> dict:
    for s in _steps():
        if s.get("name", "").startswith(name):
            return s
    raise AssertionError(f"step starting with {name!r} not found")


def test_workflow_yaml_is_loadable() -> None:
    wf = _load()
    assert wf["name"] == "f2-promotion-gate-daily"


def test_workflow_runs_after_databento_producer_mon_fri() -> None:
    """14:30 UTC Mon-Fri — consumes the dual-arm artefact from
    smc-measurement-benchmark-rolling, which (Workflow-Audit HOCH-1,
    2026-06) now fires via workflow_run after the Databento producer
    (12:00/16:00 UTC Mon-Fri) succeeds, with a 16:30 UTC safety-net cron.
    Pre-#2447 this asserted '0 10 * * *' (10:00 UTC
    daily) which fired BEFORE the producer — always-skip pattern. The
    producer→consumer handoff invariant is now pinned in
    tests/test_workflow_databento_consumer_cron_ordering.py.
    """
    wf = _load()
    # PyYAML parses bare 'on:' as the boolean True under YAML 1.1.
    schedule = wf.get("on", wf.get(True))["schedule"]
    crons = [s["cron"] for s in schedule]
    assert "30 14 * * 1-5" in crons


def test_workflow_grants_issues_write() -> None:
    perms = _load()["permissions"]
    assert perms.get("issues") == "write"
    assert perms.get("contents") == "read"


def test_step_order_matches_rollback_flow_contract() -> None:
    """Order matters: append must come before issue+revert; revert
    must come AFTER issue (so the issue body — which says 'already
    demoted' — accurately reflects what the next step will do)."""
    names = [s.get("name", "") for s in _steps()]

    def idx_starts(prefix: str) -> int:
        for i, n in enumerate(names):
            if n.startswith(prefix):
                return i
        raise AssertionError(f"no step starts with {prefix!r}: {names}")

    i_gate     = idx_starts("Run F2 promotion-gate orchestrator")
    i_append   = idx_starts("Append rollback history")
    i_issue    = idx_starts("Open rollback Issue")
    i_revert   = idx_starts("Auto-revert contextual calibration")
    i_annotate = idx_starts("Annotate decision")
    i_summary  = idx_starts("Pipeline status summary")
    i_status   = idx_starts("Contextual arm status snapshot")
    i_runbook  = idx_starts("Operator runbook")
    i_cleanup  = idx_starts("Prune stale archive entries")
    i_upload   = idx_starts("Upload promotion-gate artifact")

    assert i_gate < i_append < i_issue < i_revert < i_annotate
    assert i_annotate < i_summary < i_status < i_runbook < i_cleanup < i_upload


def test_append_history_only_on_rc_zero() -> None:
    cond = _step_by_name("Append rollback history")["if"]
    assert "steps.locate.outputs.status == 'ready'" in cond
    assert "steps.gate.outputs.rc == '0'" in cond


def test_open_issue_only_on_rc_two() -> None:
    cond = _step_by_name("Open rollback Issue")["if"]
    assert "steps.locate.outputs.status == 'ready'" in cond
    assert "steps.gate.outputs.rc == '2'" in cond


def test_auto_revert_only_on_rc_two() -> None:
    step = _step_by_name("Auto-revert contextual calibration")
    cond = step["if"]
    assert "steps.locate.outputs.status == 'ready'" in cond
    assert "steps.gate.outputs.rc == '2'" in cond
    # Must tolerate failure so the gate's rc=2 stays the primary signal.
    run = step["run"]
    assert "set +e" in run
    # Bundle A 2026-05-28: revert failures MUST be surfaced as
    # ::error:: annotations (loud), but the step MUST still exit 0 so
    # the gate's own rc=2 stays the primary workflow signal. We assert
    # both invariants — the surfacing line AND the explicit exit 0.
    assert "revert_rc=$?" in run, (
        "Auto-revert step must capture revert exit code into $revert_rc "
        "so non-zero can be surfaced (see Bundle A hardening 2026-05-28)."
    )
    assert "::error title=f2-promotion-gate::auto-revert FAILED" in run, (
        "Auto-revert failures MUST emit an ::error:: annotation — "
        "silent revert-failures were the smoking gun in the "
        "2026-05-28 silent-skip post-mortem."
    )
    assert run.rstrip().endswith("exit 0"), (
        "Auto-revert step must end with explicit `exit 0` so the "
        "gate's rc=2 stays the primary signal; a bare `true` is too "
        "fragile (a later edit could append a failing command)."
    )


def test_stalled_gate_alert_surfaces_script_crash() -> None:
    """Bundle A 2026-05-28: f2_status_alert.py is a critical-path
    advisory. A non-zero exit (e.g. import / parse crash) used to be
    silently swallowed by ``|| true``. We now require:

      * Explicit rc capture (``alert_rc=$?``)
      * ``::error::`` annotation on non-zero
      * Final ``exit 0`` so the step's rc cannot mask the gate's rc.
    """
    step = _step_by_name("Stalled-gate streak alert")
    assert step.get("if") == "always()"
    run = step["run"]
    assert "set +e" in run
    assert "alert_rc=$?" in run, (
        "Stalled-gate alert step must capture script exit code so a "
        "crash (vs. a no-alert outcome) can be surfaced."
    )
    assert "::error title=f2-promotion-gate::f2_status_alert.py CRASHED" in run, (
        "A f2_status_alert.py crash MUST emit an ::error:: annotation — "
        "the script is the only signal we have for multi-day stalled "
        "promotion streaks. Silent crash = silent regression."
    )
    assert run.rstrip().endswith("exit 0"), (
        "Stalled-gate alert step must end with explicit `exit 0` so a "
        "tooling crash cannot mask the gate's primary rc."
    )
    # Guard against the regression: the pre-Bundle-A pattern was
    # `python ... > status_alert.json || true`. We must never go back.
    assert "> artifacts/ci/f2/status_alert.json || true" not in run, (
        "Reverted to pre-Bundle-A silent-swallow pattern — see "
        "tests/test_f2_workflow_yaml_contract.py rationale."
    )


def test_annotate_and_summary_run_on_always() -> None:
    annotate_cond = _step_by_name("Annotate decision")["if"]
    summary_cond  = _step_by_name("Pipeline status summary")["if"]
    status_cond   = _step_by_name("Contextual arm status snapshot")["if"]
    assert "always()" in annotate_cond
    assert "always()" in summary_cond
    assert "always()" in status_cond


def test_runbook_and_cleanup_run_on_always() -> None:
    runbook_cond = _step_by_name("Operator runbook")["if"]
    cleanup_cond = _step_by_name("Prune stale archive entries")["if"]
    assert "always()" in runbook_cond
    assert "always()" in cleanup_cond
    # Both must tolerate failure so the gate's rc stays the signal.
    for step_name in ("Operator runbook", "Prune stale archive entries"):
        run = _step_by_name(step_name)["run"]
        assert "set +e" in run
        assert run.rstrip().endswith("true")


def test_upload_bundle_carries_revert_artifacts() -> None:
    step = _step_by_name("Upload promotion-gate artifact")
    paths = step["with"]["path"]
    # `path:` is a multi-line string in upload-artifact@v4.
    assert "revert_journal.jsonl" in paths
    assert "promote_journal.jsonl" in paths
    assert "contextual_calibration.archive/**" in paths
    assert "rollback_history.json" in paths
    assert "history_summary.json" in paths
    assert "status_snapshot.json" in paths
    assert "runbook.json" in paths
    assert "cleanup_archives.json" in paths
    assert "cleanup_archives_journal.jsonl" in paths
    assert step["with"]["retention-days"] == 60
