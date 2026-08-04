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


# --- the weekly verdict, executed rather than described ----------------------
#
# `weekly` maps the evaluator's exit code onto a status that later steps read.
# Measured 2026-08-04 with a value-preserving arm swap on the demotion flag: all
# 59 assertions across the 3 files that name this workflow stayed green.

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_WEEKLY_STEP = "Weekly k-of-n judgement (+ auto-demotion)"


def _weekly(tmp_path: Path, *, script_rc: int, apply_demotions: str = "true"):
    """Run the real step with the evaluator shadowed.

    Its exit-code contract is the thing later steps depend on, and it is
    supplied here so the step's mapping of it is what gets measured.
    """
    return run_step(
        "adr0023-magnitude-stage1-weekly.yml", _WEEKLY_STEP, tmp_path,
        env={"REAL_PYTHON": sys.executable, "APPLY": apply_demotions, "K": "3", "N": "5"},
        stubs={"python": Stub(script=f'case "$1" in -c) exec "$REAL_PYTHON" "$@" ;; esac\nexit {script_rc}')},
    )


def test_every_valid_verdict_keeps_its_own_name(tmp_path: Path) -> None:
    """Four distinct exit codes, four distinct statuses, none of them failures.

    0/2/3/4 are all valid weekly verdicts. Collapsing any two would hide a red
    flag behind a clean week or an empty ledger behind an applied demotion --
    and every one of them is green either way, so nothing else would notice.
    """
    for script_rc, expected in ((0, "clean"), (2, "red_flag"), (3, "empty_ledger"),
                                (4, "demotion_applied")):
        result = _weekly(tmp_path, script_rc=script_rc)
        assert result.returncode == 0, (
            f"rc={script_rc} is a valid verdict and must not fail the step: {result.stderr}"
        )
        assert result.outputs["status"] == expected, (
            f"rc={script_rc} must map to {expected!r}; got {result.outputs}"
        )


def test_a_usage_error_is_the_only_real_failure(tmp_path: Path) -> None:
    """rc=1 alone means the run itself is broken, not the data."""
    result = _weekly(tmp_path, script_rc=1)
    assert result.returncode != 0, "a config error must fail the step"
    assert result.outputs["status"] == "error"


def test_a_red_flag_announces_itself(tmp_path: Path) -> None:
    """An all-pass red flag is a suspected pipeline artifact.

    It is emitted on a green run, so the annotation is the only thing that
    distinguishes it from a genuinely clean week.
    """
    result = _weekly(tmp_path, script_rc=2)
    assert "::warning" in result.stdout and "red flag" in result.stdout, (
        f"a red flag must be visible on the run; got {result.stdout!r}"
    )


def test_demotions_are_applied_only_when_asked(tmp_path: Path) -> None:
    """Both directions. The flag is what turns a report into a mutation."""
    applied = _weekly(tmp_path, script_rc=0, apply_demotions="true")
    assert "--apply-demotions" in applied.calls[0], applied.calls

    dry = _weekly(tmp_path, script_rc=0, apply_demotions="false")
    assert "--apply-demotions" not in dry.calls[0], (
        f"apply=false must not pass the demotion flag; it ran: {dry.calls}"
    )
