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


def _publish(tmp_path: Path, *, npm_exit: int = 0, git_status: str = "", tee_exit: int = 0):
    """Run the real step with `npm`, `git` and `tee` shadowed.

    ``tee`` is stubbed even in the happy path on purpose. The step writes to a
    HARD-CODED ``/tmp/handlib_publish.log`` shared by every process on the box,
    so letting the real one run would have these tests leave a file behind on
    each developer machine and runner they touch.
    """
    return run_step(
        "pine-library-publish-handlibs.yml",
        _PUBLISH_STEP,
        tmp_path,
        env={"TV_STORAGE_STATE": "{}"},
        stubs={
            "npm": Stub(exit_code=npm_exit),
            "git": Stub(stdout=git_status),
            "tee": Stub(exit_code=tee_exit),
        },
    )


def _hold(tmp_path: Path, *, git_status: str = "", hold_exit: int = 0):
    """Run the real R1-hold step with `git` and `python3` shadowed.

    Since 2026-08-14 this step, not the publish step, decides `changed` —
    measured on the POST-hold tree, after the attested companions were
    restored. `python3` is stubbed because the real hold module would operate
    on the actual repository checkout; its behaviour has its own executed
    suite (tests/test_hold_r1_attested_sources.py). What this file exercises
    is the step's own shell: the fail-closed propagation and the porcelain
    branch.
    """
    return run_step(
        "pine-library-publish-handlibs.yml",
        "Hold R1-attested sources at their attested content",
        tmp_path,
        env={},
        stubs={
            "python3": Stub(exit_code=hold_exit),
            "git": Stub(stdout=git_status),
        },
    )


def _final(tmp_path: Path, *, rc: str, log_rc: str):
    """Run the real `Fail the run if a publish failed` step over given outputs.

    The step takes both statuses through ``env:`` rather than expanding them
    into the block, so they arrive here as environment variables -- the same
    way Actions delivers them. An empty string is a real state (the publish
    step died before its writes), not an absent one.
    """
    return run_step(
        "pine-library-publish-handlibs.yml",
        "Fail the run if a publish failed",
        tmp_path,
        env={"RC": rc, "LOG_RC": log_rc},
    )


def test_a_repin_is_reported_as_changed(tmp_path: Path) -> None:
    """A publish that rewrote a .pine version must open the repin PR.

    MIGRATED 2026-08-14: `changed` moved from the publish step into the
    R1-hold step, measured on the POST-hold tree — the pre-hold measurement
    counted diffs the hold takes back, so a run whose only edit was an
    attested companion opened an empty PR. Same property, new address; the
    publish half keeps its own `rc` contract below.
    """
    result = _hold(tmp_path, git_status=" M SMC_Long_Dip_Suite.pine")
    assert result.returncode == 0, result.stderr
    assert result.outputs["changed"] == "true"


def test_a_verified_publish_still_reports_its_rc(tmp_path: Path) -> None:
    """The publish step's surviving output contract after the migration."""
    result = _publish(tmp_path, git_status=" M pine/skipp_smc_core.pine")
    assert result.returncode == 0, result.stderr
    assert result.outputs["rc"] == "0"
    assert "changed" not in result.outputs, (
        "the publish step grew a changed= write back; two computations are "
        "two truths, and this one is measured before the hold"
    )


def test_an_idempotent_publish_opens_no_pr(tmp_path: Path) -> None:
    """Nothing rewritten means nothing to commit -- the control direction.

    Without it, `changed=true` hardcoded would satisfy the test above while
    opening an empty PR after every scheduled run. Runs against the hold step
    since the migration (see test_a_repin_is_reported_as_changed).
    """
    result = _hold(tmp_path, git_status="")
    assert result.returncode == 0, result.stderr
    assert result.outputs["changed"] == "false"


def test_a_failed_hold_publishes_no_verdict(tmp_path: Path) -> None:
    """Fail closed: a hold that could not run must not decide anything.

    The step runs under the workflow's `-e` default with `set -euo pipefail`
    re-asserted, so a failing hold module ends the step before the porcelain
    branch — no `changed` output, the job fails, and `Open repin PR` (gated
    on `changed == 'true'`, no always()) never runs. The alternative — a PR
    carrying a de-attested companion — is the #4284/#4371 class from the
    refresh path.
    """
    result = _hold(tmp_path, git_status=" M SMC_Long_Dip_Suite.pine", hold_exit=1)
    assert result.returncode != 0, (
        "the step swallowed the hold module's failure; a repin PR could now "
        "carry a modified attested companion"
    )
    assert "changed" not in result.outputs, (
        f"a failed hold still published a verdict: {result.outputs}"
    )


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
    # The repins-already-made half of the partial-progress promise moved with
    # the changed= migration: the hold step runs unconditionally after this
    # one and reports the post-hold tree (test_a_repin_is_reported_as_changed).
    hold = _hold(tmp_path, git_status=" M pine/skipp_smc_core.pine")
    assert hold.outputs.get("changed") == "true", (
        "the hold step did not report the repins the failed publish already "
        "made, so 'Open repin PR' skips and they are lost with the runner -- "
        f"the exact failure the partial-progress path exists for. Got: {hold.outputs}"
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


def test_an_empty_rc_ends_the_run_with_a_named_cause(tmp_path: Path) -> None:
    """A missing rc must not render as ``exited`` with no number.

    ``${rc:-1}`` already failed the run in that case -- the gate was never
    fail-open -- but the message named no cause, which is why a step that could
    not publish its outputs went unnoticed. An empty rc means the publish step
    died before its writes; that is a different fault from a non-zero rc.

    Executed, not matched. Until 2026-08-04 this asserted only that the string
    ``-z "${rc}"`` appeared; a review measured that deleting the ``exit 1`` from
    that branch -- leaving the text -- kept the whole file green. The test
    claimed to pin the reporting and would have survived its removal.
    """
    result = _final(tmp_path, rc="", log_rc="")
    assert result.returncode != 0, (
        "an empty rc finished the run GREEN. The publish step only fails to "
        f"write its outputs when it died before reaching them.\n{result.stdout}"
    )
    assert "produced no rc at all" in result.stdout, (
        "the run failed without naming the cause, which is the 'exited ' with "
        f"no number this branch exists to replace. Got: {result.stdout!r}"
    )


def test_the_final_step_is_actually_wired_to_the_publish_outputs() -> None:
    """The seam the executed tests CANNOT see, and it is stated rather than hidden.

    :func:`_final` puts RC/LOG_RC into the environment itself, because that is
    how Actions delivers an ``env:`` binding -- which means it would keep
    passing if the workflow stopped binding them at all. Measured 2026-08-04:
    renaming ``RC:`` to ``RC_UNUSED:`` left all 18 tests green. The failure
    would be fail-CLOSED (an unbound rc reads empty and every run ends red),
    but a workflow that fails every run for an invisible reason is its own
    outage, so the wiring is pinned here.

    Structural, not a substring sweep: the binding is read out of the step's
    parsed ``env`` mapping, so indentation and comment churn cannot break it
    and a renamed key is a named failure.
    """
    for step in _steps():
        if step.get("name") == "Fail the run if a publish failed":
            break
    else:
        raise AssertionError("no step named 'Fail the run if a publish failed'")

    env = step.get("env") or {}
    assert env.get("RC") == "${{ steps.publish.outputs.rc }}", (
        "the final step no longer receives the publish's rc. Unbound it reads "
        f"empty, so EVERY run ends red on 'produced no rc at all'. Got: {env}"
    )
    assert env.get("LOG_RC") == "${{ steps.publish.outputs.log_rc }}", (
        f"the final step no longer receives the log pipeline's status. Got: {env}"
    )

    run = str(step["run"])
    for name in ("RC", "LOG_RC"):
        assert f"${{{name}:-}}" in run, (
            f"{name} is bound in env: but the block does not read it, so the "
            "binding is decoration. A step that ignores the status it was "
            "handed cannot fail the run for it."
        )


def test_a_clean_publish_ends_the_run_green(tmp_path: Path) -> None:
    """The control direction: without it, `exit 1` unconditionally passes above."""
    result = _final(tmp_path, rc="0", log_rc="0")
    assert result.returncode == 0, (
        f"a successful publish failed the run.\n{result.stdout}\n{result.stderr}"
    )


def test_a_failed_log_pipeline_ends_the_run(tmp_path: Path) -> None:
    """`tee` dying is a real failure, and turning -e off is what made it silent.

    With -e on, a `tee` that could not write ended the step and the run went
    red. With -e off -- required for the partial-progress path -- the step now
    survives it, so the status has to be carried to the end explicitly.
    Otherwise the run finishes GREEN with no publish log, `Upload publish log`
    only warns (``if-no-files-found: warn``), and every error message in this
    workflow points at an artifact that was never written.
    """
    result = _final(tmp_path, rc="0", log_rc="3")
    assert result.returncode != 0, (
        "the publish log pipeline failed and the run still finished green -- "
        f"a run whose own evidence was never written.\n{result.stdout}"
    )


def _open_pr(tmp_path: Path, *, publish_rc: str):
    """Run the real `Open repin PR` step with git and gh shadowed."""
    return run_step(
        "pine-library-publish-handlibs.yml",
        "Open repin PR",
        tmp_path,
        env={
            "GH_TOKEN": "x",
            "PUBLISH_RC": publish_rc,
            "GITHUB_RUN_ID": "999",
            "GITHUB_REPOSITORY": "owner/repo",
        },
        stubs={"git": Stub(), "gh": Stub()},
    )


def test_a_partial_repin_pr_says_so(tmp_path: Path) -> None:
    """The PR opened on the FAILURE path must not claim the chain completed.

    Making the partial-progress path reachable also made this step run on red
    runs for the first time. Its body was written when only a fully successful
    run could reach it and states that the helper "published the changed
    hand-authored SMC++ libraries ... and repinned their consumers" -- which,
    on a chain that broke mid-way, tells the human reviewing the pin diff the
    opposite of what happened.
    """
    created = _open_pr(tmp_path, publish_rc="7").called_with("pr", "create")
    assert created, "no PR was opened on the partial-progress path"
    body = " ".join(created)
    assert "PARTIAL" in body, (
        f"the PR opened after a FAILED publish does not say it is partial: {body}"
    )
    assert "7" in body, f"the PR does not report the exit code it was opened for: {body}"


def test_a_complete_repin_pr_does_not_cry_partial(tmp_path: Path) -> None:
    """The control direction: a clean run must not be labelled partial.

    Without it, hardcoding the PARTIAL wording would satisfy the test above
    while marking every successful weekly run as a failure.
    """
    body = " ".join(_open_pr(tmp_path, publish_rc="0").called_with("pr", "create"))
    assert body, "no PR was opened on the success path"
    assert "PARTIAL" not in body, f"a successful publish was announced as partial: {body}"


def test_rc_comes_from_the_publish_not_from_tee(tmp_path: Path) -> None:
    """The one shape where ``PIPESTATUS[0]`` and ``$?`` disagree, driven.

    Under ``pipefail`` a failing publish makes both 7, so the executed tests
    above cannot tell the two apart. They diverge in exactly one case: ``tee``
    failing while the publish SUCCEEDS, where ``$?`` reports tee's status and
    ``PIPESTATUS[0]`` reports the publish's 0.

    Until 2026-08-04 this was a literal text pin whose docstring claimed that
    case could only be reached by making the shared ``/tmp/handlib_publish.log``
    unwritable or by adding a log-path knob to production. That was wrong, and
    a review measured it: ``run_step`` shadows executables BY NAME and ``tee``
    is an executable, so the divergence is a one-line stub. The limitation was
    never real -- only unexamined.
    """
    result = _publish(tmp_path, npm_exit=0, tee_exit=1, git_status=" M pine/skipp_smc_core.pine")

    assert result.outputs.get("rc") == "0", (
        "a failing `tee` was reported as a failed publish. rc must come from "
        "PIPESTATUS[0]; as `rc=$?` an unwritable /tmp turns a successful "
        f"publish chain into a phantom publish failure. Got: {result.outputs}"
    )
    assert result.outputs.get("log_rc") == "1", (
        "the failing log pipeline was not published, so nothing downstream can "
        "fail the run for it and it finishes green without its evidence. Got: "
        f"{result.outputs}"
    )
