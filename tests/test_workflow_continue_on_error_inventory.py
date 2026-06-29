"""Semantic inventory pin for ``continue-on-error: true`` in workflows.

Background
==========

Audit `docs/audits/smc-system-review-2026-04-24.md` (M-2) flagged
``continue-on-error: true`` as a silent-degradation surface and we agreed
to keep an explicit per-step allowlist. The original implementation pinned
1-based line numbers, which forced a rebaseline on every unrelated comment
or env edit (12+ rebaselines for ``smc-library-refresh.yml`` alone). This
revision anchors on **semantic identifiers** (``job_id`` plus the step's
``id``/``name``) so churn in comments and surrounding steps no longer
trips the guard.

Failure semantics are unchanged: adding or removing a CoE-true step still
requires updating ``_ALLOWED`` below with a short rationale in the PR
description.
"""

from __future__ import annotations

import pytest

from tests._workflow_yaml import (
    WORKFLOWS_DIR,
    has_continue_on_error_true,
    iter_steps,
    iter_workflow_files,
    load_workflow,
    step_anchor,
)

# workflow filename → { job_id → { semantic step anchor, ... } }
#
# A semantic anchor is the value returned by ``step_anchor()`` —
# ``id:<step-id>`` when the step declares an ``id:`` (preferred), otherwise
# ``name:<step-name>``. Adding/removing entries here MUST be paired with a
# CHANGELOG entry justifying the silent-fail tolerance.
_ALLOWED: dict[str, dict[str, set[str]]] = {
    # smc-live-newsapi-refresh.yml entry removed (Workflow-Audit MITTEL-11,
    # 2026-06): the bot-branch publish step is internally fail-loud
    # (F-V5-F1) and the step-level continue-on-error neutralised that —
    # a permanently failing push stayed green forever.
    # Library refresh: best-effort hops for advisory probes, release reference
    # refresh, TradingView post-release raw+normalization, alerts,
    # breaking-change notify, end-of-run heartbeat, and observability history.
    "smc-library-refresh.yml": {
        "refresh": {
            "id:gates",
            "id:pre_release_refresh",
            "id:tv_post_release_raw",
            "id:tv_post_release",
            "id:alerts",
            "id:notify_breaking",
            "id:notify_end",
            # 2026-06-17 (W3, R4b audit): cumulative best-effort failure
            # summary + cross-run trend. Observability-only steps that must
            # never flip the job conclusion of a best-effort pipeline.
            "id:dl_best_effort_history",
            "id:best_effort_summary",
            "id:ul_best_effort_history",
        },
    },
    # Deeper integration gates: 2 advisory probes (measurement export + E2E smoke).
    "smc-deeper-integration-gates.yml": {
        "deeper-gates": {
            "id:deeper_export",
            "id:e2e_smoke",
        },
    },
    # Weekly digest: 3 best-effort prior-artifact downloads (cold-start safe).
    "plan-2-8-weekly-digest.yml": {
        "weekly-digest": {
            "id:dl_digest_archive",
            "id:dl_manifest",
            "id:dl_status_ledger",
        },
    },
    # Release gates: advisory TradingView post-release validation.
    "smc-release-gates.yml": {
        "release-gates": {"id:tv_validation"},
    },
    # ADR0023 magnitude shadow: ledger-metrics step is summary-only reporting
    # (GITHUB_STEP_SUMMARY + ::notice). It must never cause the shadow
    # workflow to fail — the shadow is a daily measure-only cron, not a gate.
    "adr0023-magnitude-shadow-daily.yml": {
        "magnitude-shadow": {"id:ledger_metrics"},
    },
    # C13 daily-cron: 9 best-effort steps so partial failures still upload
    # artefacts and the issue-opener can report which step failed.
    "c13-daily-cron.yml": {
        "daily-pipeline": {
            "id:backfill",
            "id:backfill_progress",
            "id:drift_input",
            "id:backtest_ref",
            "id:slippage_sample",
            "id:drift",
            "id:families",
            "id:emit_public",
            "id:corpus",
        },
    },
}


def _scan_inventory() -> dict[str, dict[str, set[str]]]:
    """Return observed CoE-true inventory: workflow → job_id → set(anchors)."""
    observed: dict[str, dict[str, set[str]]] = {}
    for wf in iter_workflow_files():
        data = load_workflow(wf)
        for job_id, step in iter_steps(data):
            if has_continue_on_error_true(step):
                observed.setdefault(wf.name, {}).setdefault(job_id, set()).add(
                    step_anchor(step)
                )
    return observed


def test_workflows_directory_exists() -> None:
    files = iter_workflow_files()
    assert len(files) >= 5, f"unexpectedly few workflow files: {len(files)}"


def test_continue_on_error_inventory_matches_allowed() -> None:
    observed = _scan_inventory()

    extra_files = sorted(set(observed) - set(_ALLOWED))
    missing_files = sorted(set(_ALLOWED) - set(observed))
    assert not extra_files, (
        f"NEW workflow(s) introduced continue-on-error: true: {extra_files}. "
        "Update _ALLOWED with rationale, or remove the silent-fail."
    )
    assert not missing_files, (
        f"Workflow(s) no longer carry continue-on-error: {missing_files}. "
        "Remove the entry from _ALLOWED."
    )

    diffs: list[str] = []
    for wf_name, allowed_jobs in _ALLOWED.items():
        seen_jobs = observed[wf_name]
        for job_id, allowed_anchors in allowed_jobs.items():
            seen_anchors = seen_jobs.get(job_id, set())
            added = seen_anchors - allowed_anchors
            removed = allowed_anchors - seen_anchors
            if added or removed:
                diffs.append(
                    f"  {wf_name}::{job_id}: added={sorted(added)} "
                    f"removed={sorted(removed)}"
                )
        extra_jobs = sorted(set(seen_jobs) - set(allowed_jobs))
        for job_id in extra_jobs:
            diffs.append(
                f"  {wf_name}::{job_id}: NEW job has CoE-true steps "
                f"{sorted(seen_jobs[job_id])}"
            )
    assert not diffs, (
        "continue-on-error inventory drift:\n" + "\n".join(diffs)
        + "\nUpdate _ALLOWED with rationale, or revert the workflow change."
    )


def test_continue_on_error_count_pin() -> None:
    expected = sum(len(anchors) for jobs in _ALLOWED.values() for anchors in jobs.values())
    actual = sum(len(anchors) for jobs in _scan_inventory().values() for anchors in jobs.values())
    assert actual == expected, (
        f"continue-on-error total drift: expected {expected}, observed {actual}. "
        "See per-file test for details."
    )


@pytest.mark.parametrize("name,jobs", sorted(_ALLOWED.items()))
def test_each_allowed_workflow_file_exists(name: str, jobs: dict[str, set[str]]) -> None:
    assert (WORKFLOWS_DIR / name).is_file(), f"allowlist references missing workflow: {name}"
    assert jobs, f"empty allowlist for {name} — remove the key entirely"
    for job_id, anchors in jobs.items():
        assert anchors, f"empty anchor set for {name}::{job_id}"
