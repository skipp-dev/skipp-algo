"""Contract pin: ``adr0023-magnitude-stage1-weekly`` workflow (ADR-0023 §4.4/§4.5).

Pins the Monday cron, the mutating-on-cron live-window marker (the workflow
commits the stage policy back on auto-demotion), the permissions, the weekly
evaluator entrypoint + policy path, the fail-soft exit-code contract
(0/2/3/4 are verdicts, only 1 fails), and the artifact upload guard — so
silent drift of the Stage-1 weekly k-of-n scheduler is caught at
validate-time. This file also satisfies ``test_workflow_orphan_inventory``
by referencing the workflow stem ``adr0023-magnitude-stage1-weekly``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = (
    _REPO_ROOT / ".github" / "workflows" / "adr0023-magnitude-stage1-weekly.yml"
)


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "first-line live-window marker required by F-V6-F2.1 — "
        "mutating-on-cron because the workflow commits the stage policy back "
        "on auto-demotion"
    )


def test_schedule_is_monday_0630_utc() -> None:
    data = _load()
    # PyYAML parses bare ``on`` as boolean True — accept both keys.
    on_block = data.get("on") or data.get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["30 6 * * 1"], crons


def test_workflow_dispatch_exposes_k_n_and_demotion_toggle() -> None:
    data = _load()
    on_block = data.get("on") or data.get(True)
    inputs = on_block["workflow_dispatch"]["inputs"]
    assert inputs["k"]["default"] == "3"
    assert inputs["n"]["default"] == "4"
    assert "apply_demotions" in inputs


def test_permissions_allow_policy_commit_back() -> None:
    data = _load()
    assert data["permissions"] == {"contents": "write", "actions": "read"}


def test_job_invokes_weekly_evaluator_with_policy() -> None:
    data = _load()
    job = data["jobs"]["stage1-weekly"]
    assert job["timeout-minutes"] == 15
    steps_run = " ".join(step.get("run", "") for step in job["steps"])
    assert "scripts/eval_magnitude_shadow_weekly.py" in steps_run
    assert "artifacts/governance/magnitude_resolution_shadow.jsonl" in steps_run
    assert "governance/magnitude_stage_policy.json" in steps_run


def test_fail_soft_treats_2_3_and_4_as_valid_verdicts() -> None:
    data = _load()
    job = data["jobs"]["stage1-weekly"]
    weekly_step = next(
        step for step in job["steps"] if step.get("id") == "weekly"
    )
    run = weekly_step["run"]
    # Exit codes 0/2/3/4 are valid weekly verdicts; only other codes fail.
    assert 'case "$rc" in' in run
    assert "red_flag" in run
    assert "empty_ledger" in run
    assert "demotion_applied" in run


def test_commit_back_guarded_on_demotion_status() -> None:
    data = _load()
    job = data["jobs"]["stage1-weekly"]
    commit_step = next(
        step
        for step in job["steps"]
        if "magnitude_stage_policy.json" in (step.get("run") or "")
        and "git push" in (step.get("run") or "")
    )
    assert commit_step["if"] == "steps.weekly.outputs.status == 'demotion_applied'"


def test_demotions_restricted_to_main_ref() -> None:
    # A workflow_dispatch on a feature branch must never apply demotions:
    # the commit-back step pushes HEAD:main, so a branch run would mutate
    # main's policy from unreviewed code (Copilot review, PR #2700).
    data = _load()
    job = data["jobs"]["stage1-weekly"]
    weekly_step = next(step for step in job["steps"] if step.get("id") == "weekly")
    apply_expr = weekly_step["env"]["APPLY"]
    assert "github.ref == 'refs/heads/main'" in apply_expr, apply_expr


def test_unpersisted_demotion_fails_the_job() -> None:
    # Both unpersisted-demotion paths (rebase conflict, exhausted push
    # retries) must fail the job loudly — a green run with a local-only
    # demotion would leave Stage-2 arming silently active (PR #2700 review).
    data = _load()
    job = data["jobs"]["stage1-weekly"]
    commit_step = next(
        step
        for step in job["steps"]
        if "magnitude_stage_policy.json" in (step.get("run") or "")
        and "git push" in (step.get("run") or "")
    )
    run = commit_step["run"]
    assert run.count("DEMOTION NOT PERSISTED") == 2, run
    # The old rebase-conflict branch downgraded to a warning + exit 0;
    # only the benign policy-unchanged notice may skip.
    assert "skipping commit-back this run" not in run


def test_upload_artifact_is_fail_soft() -> None:
    data = _load()
    upload_steps = [
        step
        for step in data["jobs"]["stage1-weekly"]["steps"]
        if "actions/upload-artifact" in (step.get("uses") or "")
    ]
    assert len(upload_steps) == 1
    assert upload_steps[0]["if"] == "always()"
    cfg = upload_steps[0]["with"]
    assert cfg["if-no-files-found"] == "ignore"
    assert cfg["retention-days"] == 30
