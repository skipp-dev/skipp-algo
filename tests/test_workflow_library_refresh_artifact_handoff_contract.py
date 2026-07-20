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


def test_reject_stale_fallback_requires_semantic_fallback_mode() -> None:
    """Guard fires only when the semantic restore selected a fallback day."""
    job = _refresh_job(_load())
    step = _find_step(job, "reject_stale_export_fallback")
    assert step is not None, "Step not found"
    condition: str = str(step.get("if", ""))
    assert "steps.restore_export_bundle.outputs.artifact_mode" in condition
    assert re.search(r"artifact_mode\s*==\s*['\"]fallback['\"]", condition)


# ---------------------------------------------------------------------------
# Ordering: today-restore → fallback-restore → reject → generate
# ---------------------------------------------------------------------------


def _step_index(job: dict, step_id: str) -> int:
    for i, step in enumerate(job.get("steps", [])):
        if step.get("id") == step_id:
            return i
    return -1


def test_reject_step_comes_after_semantic_restore_step() -> None:
    """reject_stale_export_fallback must follow the semantic restore."""
    job = _refresh_job(_load())
    restore_idx = _step_index(job, "restore_export_bundle")
    reject_idx = _step_index(job, "reject_stale_export_fallback")
    assert restore_idx != -1, "restore_export_bundle step not found"
    assert reject_idx != -1, "reject_stale_export_fallback step not found"
    assert reject_idx > restore_idx, "reject step must come after restore_export_bundle"
