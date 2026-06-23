"""Contract pin: ``run-open-prep-daily.yml`` (Bundle D-2 from issue #2422).

This workflow is the daily producer that grows the FI labeled-sample
corpus. Its schedule, mutation surface, and bot-PR push pattern have
non-obvious requirements (notably: the push must use GH_PAT so the
spawned PR triggers required checks — observed regression in PR #103,
run 24894798260).
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "run-open-prep-daily.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    return data.get("on") or data.get(True)


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: mutating-on-cron" in head, (
        "first-line live-window marker required by F-V6-F2.1; this workflow "
        "mutates git on cron and must declare it"
    )


def test_cron_is_weekday_13_utc() -> None:
    """13:00 UTC weekdays — 30 min before RTH open (EDT) / 90 min (EST)."""
    on_block = _on(_load())
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["0 13 * * 1-5"], (
        f"open-prep cron drifted to {crons}; must be ``0 13 * * 1-5`` so the "
        "downstream outcome-backfill has a fresh outcomes_<date>.json to label"
    )


def test_concurrency_does_not_cancel_in_progress() -> None:
    """Cron mutators must never cancel themselves mid-write."""
    concurrency = _load()["concurrency"]
    assert concurrency["group"] == "run-open-prep-daily"
    assert concurrency["cancel-in-progress"] is False, (
        "cron mutators must NOT cancel-in-progress (partial git push corrupts state)"
    )


def test_permissions_allow_pr_creation() -> None:
    perms = _load()["permissions"]
    assert perms.get("contents") == "write", (
        "needs contents:write to push the bot/* branch"
    )
    assert perms.get("pull-requests") == "write", (
        "needs pull-requests:write to open the auto-merge PR"
    )


def test_jobs_select_runner_then_run() -> None:
    jobs = _load()["jobs"]
    assert list(jobs.keys()) == ["select-runner", "run"], (
        "job topology drifted; expected select-runner -> run"
    )
    assert jobs["run"]["needs"] == "select-runner", (
        "``run`` must depend on ``select-runner`` resolution"
    )
    assert jobs["run"]["timeout-minutes"] == 35
    assert jobs["select-runner"]["timeout-minutes"] == 5


def _job_checkout_step(job_name: str) -> dict:
    jobs = _load()["jobs"]
    steps = jobs[job_name]["steps"]
    for step in steps:
        uses = step.get("uses") or ""
        if isinstance(uses, str) and uses.startswith("actions/checkout@"):
            return step
    raise AssertionError(f"missing actions/checkout step in jobs.{job_name}")


def test_checkout_uses_gh_pat_for_bot_pr_trigger() -> None:
    """GH_PAT regression guard: PR #103 / run 24894798260 stuck in BLOCKED."""
    checkout = _job_checkout_step("run")
    with_block = checkout.get("with")
    assert isinstance(with_block, dict), "jobs.run checkout must define a with: block"

    token = with_block.get("token")
    assert isinstance(token, str) and "secrets.GH_PAT != ''" in token, (
        "jobs.run checkout token must use GH_PAT-or-default expression so bot PRs "
        "trigger required checks (avoid fast-gates stuck as expected/BLOCKED)"
    )

    assert with_block.get("persist-credentials") is False, (
        "run job checkout must disable persisted credentials; push auth must be explicit"
    )

    run_scripts = "\n".join(
        str(step.get("run", "")) for step in _load()["jobs"]["run"]["steps"]
    )
    assert "git remote set-url origin \"https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git\"" in run_scripts, (
        "run job must set tokenized remote URL explicitly before git push"
    )


def test_run_step_invokes_open_prep_module() -> None:
    steps = _load()["jobs"]["run"]["steps"]
    runs = " ".join(s.get("run", "") for s in steps)
    assert "open_prep.run_open_prep" in runs, (
        "entrypoint script renamed; downstream FI corpus growth will silently halt"
    )
    assert "--pre-open-only" in runs, "pre-open mode flag dropped"


def test_run_step_uploads_outcomes_artifact_always() -> None:
    upload_steps = [
        s for s in _load()["jobs"]["run"]["steps"]
        if "actions/upload-artifact" in (s.get("uses") or "")
    ]
    assert len(upload_steps) == 1
    step = upload_steps[0]
    assert step["if"] == "always()", (
        "outcome upload must run on failure too (partial outcomes are useful for triage)"
    )
    assert "artifacts/open_prep/outcomes/" in step["with"]["path"]


def _snapshot_publish_step() -> dict:
    for step in _load()["jobs"]["run"]["steps"]:
        if "bot/live-open-prep-snapshot" in str(step.get("run", "")):
            return step
    raise AssertionError(
        "missing the open-prep snapshot publish step (bot/live-open-prep-snapshot)"
    )


def test_publishes_open_prep_snapshot_to_bot_branch() -> None:
    """The realtime-signals producer consumes latest_open_prep_run.json from a
    stable git path; this step keeps bot/live-open-prep-snapshot fresh."""
    step = _snapshot_publish_step()
    run = str(step["run"])

    assert "artifacts/open_prep/latest/latest_open_prep_run.json" in run, (
        "snapshot publish must push the stable latest_open_prep_run.json path"
    )
    assert (
        "git push --force-with-lease=refs/remotes/origin/bot/live-open-prep-snapshot "
        "origin \"HEAD:refs/heads/bot/live-open-prep-snapshot\"" in run
    ), "snapshot publish must force-with-lease the dedicated bot snapshot branch"
    assert "if git push --force-with-lease" in run, (
        "must use the positive `if git push` form (see test_workflow_auth_pattern)"
    )
    assert "git fetch origin \"+refs/heads/bot/live-open-prep-snapshot" in run, (
        "must fetch the snapshot tip first so --force-with-lease has a real lease"
    )
    assert "git checkout --detach" in run, (
        "snapshot commit must be isolated on a detached HEAD so the outcomes "
        "auto-merge PR diff stays free of the gitignored snapshot file"
    )


def test_snapshot_publish_uses_gh_pat_token() -> None:
    step = _snapshot_publish_step()
    token = str((step.get("env") or {}).get("GH_TOKEN", ""))
    assert "secrets.GH_PAT != ''" in token, (
        "snapshot publish push must use GH_PAT-or-default so the force-push "
        "is authorized against the protected repository"
    )
