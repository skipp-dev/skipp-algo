"""Contract pin: ``pine-library-publish-handlibs`` workflow.

Pins the schedule + dispatch triggers, the mutating-on-cron posture, the
fail-fast-without-auth guard, the idempotent ordered-publish entrypoint, and the
PR-not-push-to-main safety model. Also satisfies ``test_workflow_orphan_inventory``
by referencing the workflow stem ``pine-library-publish-handlibs``.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "pine-library-publish-handlibs.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _load()["jobs"]["publish"]["steps"]


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_mutating_on_cron() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[1]
    assert "live-window: mutating-on-cron" in head


def test_has_dispatch_and_weekly_schedule() -> None:
    on_block = _load().get("on") or _load().get(True)
    assert "workflow_dispatch" in on_block
    crons = [e["cron"] for e in on_block["schedule"]]
    assert crons == ["0 4 * * 0"], crons


def test_permissions_allow_pr_creation() -> None:
    perms = _load()["permissions"]
    assert perms.get("contents") == "write"
    assert perms.get("pull-requests") == "write"


def test_fails_fast_without_tv_auth() -> None:
    """Publishing must not silently no-op: a missing TV_STORAGE_STATE aborts."""
    step = next(s for s in _steps() if "storage state" in s.get("name", "").lower())
    assert 'if [ -z "${TV_STORAGE_STATE_SECRET:-}" ]; then' in step["run"]
    assert "exit 1" in step["run"]


def test_runs_the_ordered_helper() -> None:
    body = " ".join(s.get("run", "") for s in _steps())
    assert "npm run tv:publish-handlibs" in body


def test_opens_pr_and_never_pushes_to_main() -> None:
    """Repins are captured in a per-run branch + PR for review, never pushed to
    main — the safety model for a scheduled live-TV publish."""
    body = "\n".join(s.get("run", "") for s in _steps())
    assert "bot/handlib-repin-${GITHUB_RUN_ID}" in body
    assert "gh pr create" in body
    # No force-push anywhere (a per-run branch never needs it).
    assert "--force" not in body


def test_non_zero_publish_fails_the_run() -> None:
    body = "\n".join(s.get("run", "") for s in _steps())
    assert 'if [ "${rc:-1}" != "0" ]; then' in body
