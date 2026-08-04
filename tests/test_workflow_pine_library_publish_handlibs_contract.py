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


# --- the publish step, executed rather than described ------------------------
#
# `Ordered publish + repin` decides `changed`, which gates the PR-opening step,
# and `rc`, which the summary reports. Measured 2026-08-04 with a
# value-preserving arm swap on `changed` (the `true`/`false` token multiset left
# unchanged, so any substring assertion is blind by construction): all 26 tests
# across the two files that name this workflow stayed green.

from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

_PUBLISH_STEP = "Ordered publish + repin"


def _publish(tmp_path: Path, *, npm_exit: int = 0, git_status: str = ""):
    """Run the real step with `npm` and `git` shadowed."""
    return run_step(
        "pine-library-publish-handlibs.yml",
        _PUBLISH_STEP,
        tmp_path,
        env={"TV_STORAGE_STATE": "{}"},
        stubs={"npm": Stub(exit_code=npm_exit), "git": Stub(stdout=git_status)},
    )


def test_a_repin_is_reported_as_changed(tmp_path: Path) -> None:
    """A publish that rewrote a .pine version must open the repin PR."""
    result = _publish(tmp_path, git_status=" M pine/skipp_smc_core.pine")
    assert result.returncode == 0, result.stderr
    assert result.outputs["changed"] == "true"
    assert result.outputs["rc"] == "0"


def test_an_idempotent_publish_opens_no_pr(tmp_path: Path) -> None:
    """Nothing rewritten means nothing to commit -- the control direction.

    Without it, `changed=true` hardcoded would satisfy the test above while
    opening an empty PR after every scheduled run.
    """
    result = _publish(tmp_path, git_status="")
    assert result.returncode == 0, result.stderr
    assert result.outputs["changed"] == "false"


def test_a_failed_publish_fails_the_step_and_publishes_no_outputs(tmp_path: Path) -> None:
    """What the step really does when the publish chain fails.

    Its own comment says otherwise::

        # A non-zero rc means a publish/verify failed mid-chain; still capture
        # any repins already made so the PR shows partial progress, but mark
        # the run failed at the end.

    That path cannot run. The workflow declares ``defaults: run: shell: bash``,
    so Actions executes the block as ``bash --noprofile --norc -eo pipefail``.
    The block's own ``set -uo pipefail`` adds ``-u``; it does NOT clear the
    ``-e`` the shell was started with. So the failing ``npm … | tee`` pipeline
    aborts the step immediately, and neither ``rc=`` nor ``changed=`` is ever
    written -- the step's ``rc`` output reaches the summary empty on exactly the
    runs it was added to describe.

    Measured 2026-08-04, not inferred. Pinned as-is rather than repaired: making
    the partial-progress path reachable would change what a failed publish does
    to the live TradingView account, which is an operator decision, not a test
    fix.
    """
    result = _publish(tmp_path, npm_exit=1, git_status=" M pine/skipp_smc_core.pine")
    assert result.returncode != 0, "a failed publish must fail the step"
    assert "rc" not in result.outputs and "changed" not in result.outputs, (
        "the step now publishes outputs on the failure path. If that was "
        "deliberate, this test documents the behaviour it replaced: update it "
        f"and say so in the PR body. Got: {result.outputs}"
    )
