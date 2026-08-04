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


def test_a_failed_publish_still_publishes_its_outputs(tmp_path: Path) -> None:
    """The partial-progress path, now reachable. REPLACES the test that pinned it shut.

    Until 2026-08-04 this file carried
    ``test_a_failed_publish_fails_the_step_and_publishes_no_outputs``, which
    recorded the opposite and said why: the behaviour contradicted the step's
    own comment, and making the path reachable "would change what a failed
    publish does to the live TradingView account, which is an operator
    decision, not a test fix". The operator took that decision on 2026-08-04
    and asked for the repair; this test documents the behaviour that replaced
    it, as that test's own failure message asked.

    One correction to the reasoning it was deferred on, measured rather than
    argued: nothing between the failing pipeline and the PR touches TradingView.
    ``npm run tv:publish-handlibs`` has already done whatever it did before it
    failed, and every later step is git and gh only -- checkout, add, commit,
    push, ``gh pr create``. What the repair changes is what happens in the
    REPOSITORY: a PR now carries the repins that already succeeded, instead of
    them being discarded with the runner.

    The cause: ``defaults: run: shell: bash`` makes Actions invoke the block as
    ``bash --noprofile --norc -eo pipefail``, so ``-e`` is on before line one,
    and the block's ``set -uo pipefail`` adds ``-u`` without clearing it. The
    failing pipeline ended the step before either output was written. ``set +e``
    is now the first line, and pin_registry.toml carries it in the set-plus-e
    allowlist with its bounding argument.
    """
    result = _publish(tmp_path, npm_exit=7, git_status=" M pine/skipp_smc_core.pine")

    assert result.outputs.get("rc") == "7", (
        "the step did not publish the publish's own exit code. Without it "
        "'Fail the run if a publish failed' reports 'exited ' with no number, "
        f"which is how this defect stayed invisible. Got: {result.outputs}"
    )
    assert result.outputs.get("changed") == "true", (
        "the step did not report the repins already made, so 'Open repin PR' "
        "skips and they are lost with the runner -- the exact failure the "
        f"step's comment promised to prevent. Got: {result.outputs}"
    )


def test_the_publish_step_does_not_fail_the_run_itself(tmp_path: Path) -> None:
    """Failing belongs to the dedicated final step, not to this one.

    A red step skips everything gated on its outputs -- including the step that
    opens the PR carrying the partial repins. The run still ends red, via
    ``Fail the run if a publish failed`` reading the rc published above.
    """
    result = _publish(tmp_path, npm_exit=7, git_status=" M pine/skipp_smc_core.pine")
    assert result.returncode == 0, (
        f"the publish step exited {result.returncode} on a failed publish. It "
        "must reach its output writes and let the final step end the run, or "
        "the partial-progress path is unreachable again.\n" + result.stderr
    )


def test_an_empty_rc_is_reported_as_its_own_failure() -> None:
    """A missing rc must not render as ``exited`` with no number.

    ``${rc:-1}`` already failed the run in that case -- the gate was never
    fail-open -- but the message named no cause, which is why a step that could
    not publish its outputs went unnoticed. An empty rc means the publish step
    died before its writes; that is a different fault from a non-zero rc.
    """
    for step in _steps():
        if step.get("name") == "Fail the run if a publish failed":
            run = str(step["run"])
            break
    else:
        raise AssertionError("no step named 'Fail the run if a publish failed'")

    assert '-z "${rc}"' in run, (
        "the final step no longer distinguishes an empty rc from a non-zero "
        "one, so a publish step that dies before writing its outputs reports "
        "'exited ' again."
    )


def test_rc_comes_from_the_publish_not_from_tee() -> None:
    """A LITERAL pin, and the reason it must be one is stated, not hidden.

    ``rc=${PIPESTATUS[0]}`` and ``rc=$?`` are indistinguishable for every input
    the executed tests above can produce: under ``pipefail`` a failing publish
    makes both 7. Measured 2026-08-04 with the real shell -- they diverge in
    exactly one shape, ``tee`` failing while the publish SUCCEEDS, where ``$?``
    reports tee's 1 and ``PIPESTATUS[0]`` reports the publish's 0.

    Driving that would mean making the hard-coded ``/tmp/handlib_publish.log``
    unwritable -- a path shared by every run on the box, so a crashed test
    leaves it broken for the next one -- or adding a log-path knob to
    production for the test's benefit. Both are worse than pinning the text and
    naming the limitation, so: this is the one assertion in this file a
    source-text change can satisfy without the behaviour holding.
    """
    for step in _steps():
        if step.get("name") == _PUBLISH_STEP:
            run = str(step["run"])
            break
    else:
        raise AssertionError(f"no step named {_PUBLISH_STEP!r}")

    assert "rc=${PIPESTATUS[0]}" in run, (
        "rc no longer comes from PIPESTATUS[0]. As `rc=$?` a failing `tee` "
        "(disk full, unwritable /tmp) would be reported as a failed publish "
        "while the publish actually succeeded."
    )
