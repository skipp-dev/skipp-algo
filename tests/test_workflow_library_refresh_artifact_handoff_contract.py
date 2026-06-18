"""Q6 regression guard: smc-library-refresh.yml must reject a stale Databento
fallback artifact on automated (non-dispatch) runs.

Root-cause from Q6 (2026-06-17 audit): if smc-databento-production-export-sharded
hasn't published today's bundle yet and the workflow falls back to the latest
historical bundle, the generated Pine library would contain dated signal
parameters — a silent correctness regression with no visible error marker.

The ``reject_stale_export_fallback`` step must:
  1. Only fire when event_name != 'workflow_dispatch' AND today's artifact is
     missing AND the fallback artifact IS present.
  2. Emit an ``::error::`` annotation (enforced by shell ``exit 1``).
  3. Not be soft-failed (no ``continue-on-error: true``).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_WF = Path(".github/workflows/smc-library-refresh.yml")


def _load() -> dict:
    return yaml.safe_load(_WF.read_text(encoding="utf-8"))


def _refresh_job(wf: dict) -> dict:
    return wf["jobs"]["refresh"]


def _find_step(job: dict, step_id: str) -> dict | None:
    return next((s for s in job.get("steps", []) if s.get("id") == step_id), None)


# ---------------------------------------------------------------------------
# Step existence + structure
# ---------------------------------------------------------------------------


def test_reject_stale_fallback_step_exists() -> None:
    """The step reject_stale_export_fallback must be present in the refresh job."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, (
        "Step id='reject_stale_export_fallback' missing from smc-library-refresh.yml "
        "refresh job — Q6 guard not present."
    )


def test_reject_stale_fallback_has_exit_1() -> None:
    """The guard step must hard-fail (exit 1) so the run is marked failure, not skipped."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, "Step not found (see test_reject_stale_fallback_step_exists)"
    run_block: str = step.get("run", "")
    assert "exit 1" in run_block, (
        "reject_stale_export_fallback must call 'exit 1' to hard-fail the workflow. "
        "A missing exit 1 means automated runs silently accept stale producer data."
    )


def test_reject_stale_fallback_not_soft_failed() -> None:
    """The guard step must NOT have continue-on-error: true — it must block the workflow."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, "Step not found"
    assert step.get("continue-on-error", False) is not True, (
        "reject_stale_export_fallback has continue-on-error: true — the guard is "
        "silently bypassed on stale-artifact runs."
    )


# ---------------------------------------------------------------------------
# Condition correctness (3-clause AND guard)
# ---------------------------------------------------------------------------


def test_reject_stale_fallback_requires_non_dispatch_event() -> None:
    """Guard must only fire on automated (non-dispatch) runs."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, "Step not found"
    condition: str = str(step.get("if", ""))
    assert "workflow_dispatch" in condition, (
        "reject_stale_export_fallback.if must exclude workflow_dispatch events so "
        "operators can manually accept a fallback artifact."
    )
    # Must be a negative check: operators are ALLOWED on dispatch, BLOCKED on schedule.
    assert re.search(
        r"github\.event_name\s*!=\s*['\"]workflow_dispatch['\"]",
        condition,
    ), (
        "Condition must use github.event_name != 'workflow_dispatch' (not ==) to allow "
        "manual override on dispatch runs."
    )


def test_reject_stale_fallback_requires_today_artifact_missing() -> None:
    """Guard fires only when today's artifact was NOT found."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, "Step not found"
    condition: str = str(step.get("if", ""))
    assert "restore_export_bundle_today" in condition, (
        "Condition must reference restore_export_bundle_today step output."
    )
    assert re.search(
        r"found_artifact.*!=\s*['\"]true['\"]|found_artifact.*==\s*['\"]false[\"']",
        condition,
    ), (
        "Condition must assert that today's artifact was NOT found "
        "(found_artifact != 'true' or found_artifact == 'false')."
    )


def test_reject_stale_fallback_requires_fallback_artifact_present() -> None:
    """Guard fires only when the fallback artifact IS present — otherwise there is nothing to reject."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, "Step not found"
    condition: str = str(step.get("if", ""))
    assert "restore_export_bundle_fallback" in condition, (
        "Condition must reference restore_export_bundle_fallback step output."
    )
    assert re.search(r"found_artifact.*==\s*['\"]true['\"]|", condition) or re.search(
        r"found_artifact.*==\s*['\"]true[\"']", condition
    ), (
        "Condition must assert that the FALLBACK artifact was found "
        "(found_artifact == 'true') — rejecting only when a stale artifact was "
        "actually resolved."
    )


# ---------------------------------------------------------------------------
# Ordering: today-restore → fallback-restore → reject → generate
# ---------------------------------------------------------------------------


def _step_index(job: dict, step_id: str) -> int:
    for i, step in enumerate(job.get("steps", [])):
        if step.get("id") == step_id:
            return i
    return -1


def test_reject_step_comes_after_both_restore_steps() -> None:
    """reject_stale_export_fallback must follow both restore steps."""
    job = _refresh_job(_load())
    today_idx = _step_index(job, "restore_export_bundle_today")
    fallback_idx = _step_index(job, "restore_export_bundle_fallback")
    reject_idx = _step_index(job, "reject_stale_export_fallback")
    assert today_idx != -1, "restore_export_bundle_today step not found"
    assert fallback_idx != -1, "restore_export_bundle_fallback step not found"
    assert reject_idx != -1, "reject_stale_export_fallback step not found"
    assert reject_idx > today_idx, "reject step must come after restore_export_bundle_today"
    assert reject_idx > fallback_idx, "reject step must come after restore_export_bundle_fallback"
