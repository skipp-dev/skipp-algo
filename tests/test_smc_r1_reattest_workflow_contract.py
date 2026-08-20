"""Contracts for the automated R1 re-attestation chain (workflow half).

The proposer (``smc-r1-reattest.yml``) bumps the Event Overlay pin on a FIXED
branch and dispatches ``tv-save-consumer-source`` there; the save workflow's
reattest path measures, generates evidence, self-checks the chain and commits.
These tests pin the wiring that makes the chain safe rather than merely
present -- and where a rule is enforced by a shell fragment, the fragment is
EXECUTED against both arms instead of being string-matched (the
string-match-only workflow tests of this repo have been measured vacuous
twice, 2026-08-04).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REATTEST = _REPO_ROOT / ".github" / "workflows" / "smc-r1-reattest.yml"
_SAVE = _REPO_ROOT / ".github" / "workflows" / "tv-save-consumer-source.yml"


def _reattest() -> dict:
    return yaml.safe_load(_REATTEST.read_text(encoding="utf-8"))


def _save() -> dict:
    return yaml.safe_load(_SAVE.read_text(encoding="utf-8"))


def _save_steps() -> list[dict]:
    return _save()["jobs"]["save"]["steps"]


def _step(steps: list[dict], name_prefix: str) -> dict:
    return next(s for s in steps if str(s.get("name", "")).startswith(name_prefix))


# ------------------------------------------------------------- the proposer


def test_proposer_runs_on_schedule_dispatch_and_save_success_only() -> None:
    """The cron is the floor; the save-chain completion is the cadence.

    Until 2026-08-14 the cron was the only automatic trigger, and since
    refreshes land 12:57-17:55Z a 12:07Z-only proposer always re-attested
    YESTERDAY's final published version -- Event Overlay (whose imports are
    exclusively event-risk fields) structurally ran ~1 trading day behind its
    fourteen neighbours. The workflow_run trigger closes that; the guards that
    keep it from looping live in the job condition and are pinned below.
    """
    on_block = _reattest().get("on") or _reattest().get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["7 12 * * 1-5"], (
        "the weekday pre-US-open floor -- self-healing when an event-driven "
        "run was displaced or the chain was down"
    )
    assert "workflow_dispatch" in on_block
    assert set(on_block) == {"schedule", "workflow_dispatch", "workflow_run"}, (
        "no push/PR triggers: the proposer must never run on its own proposal "
        "(that property now lives in the job condition's head_branch filter, "
        "pinned by test_proposer_event_trigger_cannot_loop_or_fire_on_failure)"
    )
    assert on_block["workflow_run"]["workflows"] == ["tv-save-consumer-source"], (
        "the event trigger must watch exactly the save chain whose success "
        "means the published library may have moved"
    )
    assert on_block["workflow_run"]["types"] == ["completed"]


def test_proposer_event_trigger_cannot_loop_or_fire_on_failure() -> None:
    """workflow_run fires on cancelled/failure too, and the measuring save IS
    a tv-save-consumer-source run on bot/r1-reattest.

    Without the conclusion guard the proposer would fire on the routinely
    cancelled completions of the saturated queue (2026-08-13: 44 cancelled in
    one day) and race a TradingView state nobody verified. Without the
    head_branch guard every proposal's own measuring save would re-trigger the
    proposer -- an infinite loop throttled only by the session queue.
    """
    # Asserted as ONE normalized expression, not three substrings: the
    # 2026-08-15 review showed an `&&`→`||` swap keeps every substring while
    # letting a cancelled main run — or a successful bot-branch run — propose.
    # YAML `>-` folding preserves the more-indented continuation line as a
    # literal newline inside the string, hence the whitespace normalization.
    condition = " ".join(str(_reattest()["jobs"]["propose"]["if"]).split())
    assert condition == (
        "github.event_name != 'workflow_run' "
        "|| (github.event.workflow_run.conclusion == 'success' "
        "&& github.event.workflow_run.head_branch == 'main')"
    ), (
        "the event-trigger guard changed shape. It must let cron/dispatch "
        "pass untouched, refuse any non-success save-chain completion (the "
        "2026-08-13 queue produced 44 cancelled completions in one day), and "
        "refuse non-main head branches (the measuring save completes on "
        f"bot/r1-reattest and would re-trigger the proposer). Got: {condition}"
    )


def test_proposer_serialises_itself_and_never_cancels_a_running_proposal() -> None:
    concurrency = _reattest()["concurrency"]
    assert concurrency["group"] == "smc-r1-reattest"
    assert concurrency["cancel-in-progress"] is False


def test_proposer_pushes_the_fixed_branch_and_dispatches_reattest_on_it() -> None:
    steps = _reattest()["jobs"]["propose"]["steps"]
    push = _step(steps, "Force-push the pin-bump proposal branch")
    dispatch = _step(steps, "Dispatch the measuring save")

    assert "git push -f" in push["run"]
    assert "bot/r1-reattest" in push["run"]
    # PAT, not github.token: a github.token push triggers no workflows, so the
    # proposal PR would never get its fast-gates run.
    assert push["env"]["GH_TOKEN"] == "${{ secrets.GH_PAT }}"
    assert 'test -n "${GH_TOKEN}"' in push["run"]

    assert "tv-save-consumer-source.yml" in dispatch["run"]
    assert "--ref bot/r1-reattest" in dispatch["run"]
    assert "-f reattest=true" in dispatch["run"]
    assert dispatch["env"]["GH_TOKEN"] == "${{ secrets.GH_PAT }}"


def _pin_substitution_fragment() -> str:
    """The proposer's pin-rewrite command, sliced out of the step verbatim.

    Re-implementing the regex here is what made the earlier version of this
    test vacuous: on 2026-08-05, the first day the proposer had real work to
    do, the shipped command died with ``NameError: name 'TARGET' is not
    defined`` (run 31007122044) because an inner single quote closed the
    ``python3 -c '...'`` shell string -- a defect no string match and no
    re-implementation of the regex can see. Run what ships.
    """
    push = _step(_reattest()["jobs"]["propose"]["steps"], "Force-push the pin-bump")
    run = push["run"]
    # Sliced by its neighbours, not by the quoting form, so a revert to any
    # other spelling of the command is still EXECUTED (and still fails here)
    # instead of merely failing to be located.
    start = run.index('TARGET="${TARGET}"')
    end = run.index("git config user.email")
    return "set -euo pipefail\n" + run[start:end]


def test_proposer_pin_substitution_bumps_exactly_the_import_line(
    tmp_path: Path,
) -> None:
    """EXECUTED, not string-matched: the command the proposer actually ships
    must rewrite the REAL Event Overlay source to the target pin and change
    nothing else -- the pin-only diff class is what the generator later
    re-proves by hash reconstruction."""
    source = (_REPO_ROOT / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    (tmp_path / "SMC_Event_Overlay.pine").write_text(source, encoding="utf-8")

    done = subprocess.run(
        ["/bin/bash", "-c", _pin_substitution_fragment()],
        cwd=tmp_path,
        env={"PATH": os.environ["PATH"], "TARGET": "99999"},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr

    new = (tmp_path / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    changed = [
        (a, b) for a, b in zip(source.splitlines(), new.splitlines()) if a != b
    ]
    assert len(changed) == 1
    assert changed[0][1].endswith("/99999 as mp")


def test_proposer_pin_substitution_refuses_a_target_it_cannot_apply() -> None:
    """The fragment is fail-closed in both arms: no import line to bump means
    a non-zero exit, never a silent no-op commit of an unchanged pin."""
    empty = subprocess.run(
        ["/bin/bash", "-c", _pin_substitution_fragment()],
        cwd=_REPO_ROOT / "tests",  # no SMC_Event_Overlay.pine here
        env={"PATH": os.environ["PATH"], "TARGET": "99999"},
        capture_output=True,
        text=True,
    )
    assert empty.returncode != 0


def test_proposer_refuses_to_downgrade_an_ahead_pin() -> None:
    decide = _step(_reattest()["jobs"]["propose"]["steps"], "Decide whether")
    assert "refusing to propose a downgrade" in decide["run"]
    assert 'exit 1' in decide["run"]


# ------------------------------------------------------ the save-side chain


def test_save_declares_the_reattest_input_off_by_default() -> None:
    on_block = _save().get("on") or _save().get(True)
    reattest = on_block["workflow_dispatch"]["inputs"]["reattest"]
    assert reattest["default"] is False
    assert reattest["type"] == "boolean"


def test_reattest_steps_chain_conclusion_by_conclusion() -> None:
    """The entry step gates on the input; every later step gates on its
    predecessor's conclusion -- severing any link leaves the rest skipped,
    never running against a half-measured state."""
    steps = _save_steps()
    preserve = _step(steps, "Preserve the write-pass report")
    reverify = _step(steps, "Independent verify-only pass")
    attest = _step(steps, "Generate the supersession evidence")
    commit = _step(steps, "Commit the evidence to the proposal branch")

    assert "github.event.inputs.reattest == 'true'" in preserve["if"]
    assert "steps.save.conclusion" in preserve["if"]
    assert "steps.preserve_report.conclusion == 'success'" in reverify["if"]
    assert "steps.reverify.conclusion == 'success'" in attest["if"]
    assert "steps.attest.conclusion == 'success'" in commit["if"]

    assert preserve.get("id") == "preserve_report"
    assert reverify.get("id") == "reverify"
    assert attest.get("id") == "attest"
    assert commit.get("id") == "attest_commit"


def test_the_branch_guard_fragment_actually_refuses_foreign_branches(
    tmp_path: Path,
) -> None:
    """Executed in both arms. The preserve step's shell must exit 1 on any
    branch that is not bot/r1-reattest* and move the report on the right one."""
    preserve = _step(_save_steps(), "Preserve the write-pass report")
    script = preserve["run"]

    report_dir = tmp_path / "artifacts" / "monitoring"
    report_dir.mkdir(parents=True)

    def _run(branch: str) -> subprocess.CompletedProcess:
        (report_dir / "tradingview_consumer_bindings.json").write_text(
            "{}", encoding="utf-8"
        )
        runner_temp = tmp_path / "runner-temp"
        runner_temp.mkdir(exist_ok=True)
        return subprocess.run(
            ["/bin/bash", "-c", script],
            cwd=tmp_path,
            env={
                "PATH": "/usr/bin:/bin",
                "GITHUB_REF_NAME": branch,
                "RUNNER_TEMP": str(runner_temp),
            },
            capture_output=True,
            text=True,
        )

    foreign = _run("main")
    assert foreign.returncode == 1
    assert "only valid on a bot/r1-reattest" in foreign.stdout + foreign.stderr

    proposal = _run("bot/r1-reattest")
    assert proposal.returncode == 0
    assert (tmp_path / "runner-temp" / "report-write.json").is_file()


def test_the_verify_pass_is_read_only_and_the_attest_step_runs_both_tools() -> None:
    steps = _save_steps()
    reverify = _step(steps, "Independent verify-only pass")
    attest = _step(steps, "Generate the supersession evidence")

    assert "--verify-only" in reverify["run"]
    assert reverify["env"]["TV_CONSUMER_MAPPING_JSON"] == "[]"

    assert "scripts.smc_r1_generate_attestation" in attest["run"]
    for flag in ("--write-report", "--verify-report", "--run-id"):
        assert flag in attest["run"]
    # Contract regeneration must be a FRESH interpreter after the generator:
    # the contract module resolves the chain head at import time.
    generator_pos = attest["run"].index("scripts.smc_r1_generate_attestation")
    contract_pos = attest["run"].index("scripts.smc_r1_rollout_contract")
    assert contract_pos > generator_pos


def test_the_evidence_commit_is_seeded_scoped_and_arms_auto_merge() -> None:
    commit = _step(_save_steps(), "Commit the evidence to the proposal branch")
    run = commit["run"]

    assert commit["env"]["GH_TOKEN"] == "${{ secrets.GH_PAT }}"
    assert 'test -n "${GH_TOKEN}"' in run
    # ADR-0024 5: seed from the remote tip before committing.
    assert "git fetch" in run
    # Only the three chain files -- never a bare `git add artifacts/`
    # (the suite writes into the repo tree; a broad add would ship debris).
    assert '"${EVIDENCE_PATH}"' in run
    assert "artifacts/governance/smc_r1_evidence_chain.json" in run
    assert "artifacts/governance/smc_r1_live_rollout_contract.json" in run
    assert not re.search(r"git add [^\n]*artifacts/governance/?\s*$", run, re.M)
    assert "gh pr create" in run
    assert "--squash --auto" in run


_GH_STUB = """#!/bin/sh
printf '%s\\n' "$*" >> "${GH_LOG}"
case "$*" in
  "pr create"*)
    if [ "${STUB_PR_EXISTS}" = "1" ]; then
      echo 'a pull request for branch "bot/r1-reattest" into branch "main" already exists' >&2
      exit 1
    fi
    ;;
  "pr list"*)
    # `--jq '.[0].number // empty'` is applied by gh itself, so the stub emits
    # what the real binary would already have reduced it to.
    [ "${STUB_NO_OPEN_PR}" = "1" ] || echo 4906
    ;;
  *"--json autoMergeRequest"*) echo "${STUB_ARMED}" ;;
esac
exit 0
"""

_GIT_STUB = "#!/bin/sh\nexit 0\n"

_SUBJECT = "--subject chore(governance): automated R1 re-attestation to /283 (#4906)"


def _run_evidence_commit_step(
    tmp_path: Path,
    *,
    pr_exists: bool,
    armed: bool,
    open_pr: bool = True,
) -> tuple[subprocess.CompletedProcess, list[str], Path]:
    """Execute the evidence-commit step against stubbed `gh`/`git`.

    Returns the process result, the `gh` argv lines it produced in order, and
    the runner temp dir (which holds the message files the step wrote).
    """
    stub_dir = tmp_path / "stub"
    stub_dir.mkdir(exist_ok=True)
    for name, body in (("gh", _GH_STUB), ("git", _GIT_STUB)):
        path = stub_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)

    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    evidence = tmp_path / "smc_r1_live_rollout_evidence_2026-08-20T010429Z.json"
    # The release the chain is attesting IN THIS CYCLE.
    evidence.write_text(json.dumps({"libraryReleaseVersion": 283}), encoding="utf-8")
    gh_log = tmp_path / "gh.log"
    gh_log.write_text("", encoding="utf-8")

    run = _step(_save_steps(), "Commit the evidence to the proposal branch")["run"]
    result = subprocess.run(
        ["/bin/bash", "-c", run],
        cwd=tmp_path,
        env={
            "PATH": f"{stub_dir}:/usr/bin:/bin",
            "GH_TOKEN": "stub-token",
            "GITHUB_REPOSITORY": "skipp-dev/skipp-algo",
            "GITHUB_REF_NAME": "bot/r1-reattest",
            "GITHUB_RUN_ID": "32289119773",
            "RUNNER_TEMP": str(runner_temp),
            "EVIDENCE_PATH": str(evidence),
            "GH_LOG": str(gh_log),
            "STUB_PR_EXISTS": "1" if pr_exists else "0",
            "STUB_ARMED": "true" if armed else "false",
            "STUB_NO_OPEN_PR": "0" if open_pr else "1",
        },
        capture_output=True,
        text=True,
    )
    calls = [line for line in gh_log.read_text(encoding="utf-8").splitlines() if line]
    return result, calls, runner_temp


def test_the_merge_message_names_the_release_this_cycle_actually_carries(
    tmp_path: Path,
) -> None:
    """Executed in both arms.

    The proposal branch is FIXED, and a cycle force-pushes a new release onto a
    PR an earlier cycle already opened. This repo squashes with
    ``squash_merge_commit_title=PR_TITLE`` / ``...message=PR_BODY`` (measured
    2026-08-20), so GitHub composes the merge commit from the PR's own fields
    when auto-merge fires -- and #4894 landed on main as "re-attestation to
    /282" over a tree carrying /283 with a different evidence file, because
    ``gh pr create`` answered "already exists" and nobody repointed those
    fields. A governance chain whose main-line history names the wrong release
    is worse than no history.
    """
    result, calls, runner_temp = _run_evidence_commit_step(
        tmp_path, pr_exists=True, armed=True
    )
    assert result.returncode == 0, result.stdout + result.stderr

    edits = [c for c in calls if c.startswith("pr edit")]
    assert edits, f"a stale open PR was not repointed: {calls}"
    assert "/283" in edits[0]

    assert any("--disable-auto" in c for c in calls), (
        f"auto-merge armed by an earlier cycle was never disarmed: {calls}"
    )

    arm = [c for c in calls if "--squash --auto" in c]
    assert len(arm) == 1, f"expected exactly one re-arm, got {arm}"
    # Headline derived from the evidence file THIS run wrote, and it keeps the
    # PR back-reference the PR_TITLE default would have supplied.
    assert _SUBJECT in arm[0]
    assert "/282" not in arm[0]
    # Disarm must precede the re-arm, or the stale message survives.
    assert calls.index(next(c for c in calls if "--disable-auto" in c)) < calls.index(
        arm[0]
    )

    # The body must name THIS cycle's evidence and run, not a predecessor's.
    body = (runner_temp / "reattest-merge-body.md").read_text(encoding="utf-8")
    assert "smc_r1_live_rollout_evidence_2026-08-20T010429Z.json" in body
    assert "32289119773" in body
    assert "Co-authored-by: github-actions[bot]" in body


def test_a_first_cycle_pr_is_armed_without_a_pointless_disarm(
    tmp_path: Path,
) -> None:
    """The repoint path is for a PR an earlier cycle left behind. On the normal
    path (create succeeds, nothing armed) the step must not edit or disarm."""
    result, calls, _ = _run_evidence_commit_step(
        tmp_path, pr_exists=False, armed=False
    )
    assert result.returncode == 0, result.stdout + result.stderr

    assert not [c for c in calls if c.startswith("pr edit")], calls
    assert not [c for c in calls if "--disable-auto" in c], calls
    arm = [c for c in calls if "--squash --auto" in c]
    assert len(arm) == 1, f"expected exactly one arming, got {arm}"
    assert _SUBJECT in arm[0]


def test_the_pr_number_comes_from_the_open_pr_not_the_branch_selector(
    tmp_path: Path,
) -> None:
    """`gh pr <cmd> <branch>` on a FIXED branch answers with a CLOSED/MERGED PR
    when no open one exists -- measured 2026-08-20, `gh pr view bot/r1-reattest`
    returned #4894 (MERGED) after that PR had landed. Reading the back-reference
    that way turns a loud failure into a merge commit citing a foreign PR, so
    the step must resolve the OPEN PR explicitly and refuse when there is none.
    """
    result, calls, _ = _run_evidence_commit_step(
        tmp_path, pr_exists=True, armed=False, open_pr=False
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "no OPEN proposal PR" in result.stdout + result.stderr
    # Nothing may be armed once the back-reference is unknown.
    assert not [c for c in calls if "--squash --auto" in c], calls
    # And the resolution must go through the open-PR listing, not `pr view`.
    assert any(c.startswith("pr list") and "--state open" in c for c in calls), calls


def test_the_unattested_guard_remeasures_instead_of_trusting_the_flag() -> None:
    """The carve-out may only exit 0 by asking the SAME module that found the
    un-attestation again, against the extended chain."""
    guard = _step(_save_steps(), "Fail the run when an R1-attested")
    run = guard["run"]

    assert guard["env"]["REATTEST_COMMITTED"] == (
        "${{ steps.attest_commit.conclusion }}"
    )
    assert "scripts.check_tv_unattested_sources" in run
    # exit 0 only inside the emptiness branch of the re-measurement, and the
    # non-empty answer stays a hard failure even after a committed
    # re-attestation.
    assert 'if [ -z "${remaining}" ] || [ "${remaining}" = "[]" ]' in run
    assert "re-attestation committed but sources remain un-attested" in run
    assert run.rstrip().endswith("exit 1")


def test_the_unattested_guard_survives_the_save_failure_it_reports_on() -> None:
    """The guard's own trigger is what makes the save step fail.

    A step whose ``if`` names no status function is ANDed with an implicit
    ``success()``, so it is skipped the moment any earlier step failed. This
    guard fires on a NON-EMPTY un-attested list -- and that same list is what
    ``scripts/tv_batch_consumer_rollout.ts`` fails the save on. Its condition
    was therefore true only in runs where it could no longer execute.

    Measured 2026-08-06 over the last 20 tv-save-consumer-source runs: the
    step appeared 12 times and was ``skipped`` all 12, never once executed.
    The re-measurement it exists for -- "re-attestation committed but sources
    remain un-attested" -- had never run, so a re-attestation that committed
    without resolving the un-attestation would have merged unremarked (the
    chain reached exactly that step for the first time in run 31106318082).
    """
    guard = _step(_save_steps(), "Fail the run when an R1-attested")
    condition = str(guard["if"])

    assert re.search(r"!\s*cancelled\(\)", condition), (
        "without a status function this guard is suppressed by the very save "
        f"failure it reports on (condition: {condition!r})"
    )
    # Not always(): a cancelled run measured nothing worth reporting on.
    assert "always()" not in condition
    # Still gated on there being something to re-measure: a run with nothing
    # un-attested must not pay for this step.
    assert "steps.attestation.outputs.unattested" in condition


# ---- the proposal must be rebuilt at MEASURE time, not at proposal time ----
#
# Measured 2026-08-06: the proposer built bot/r1-reattest at 19:31Z on 08-05
# from a manifest that said 190. By the time a tv-save run reached the front of
# the one-slot TradingView queue, TradingView listed 192, and the rollout tool
# refused every save -- "the manifest says ... 190, but TradingView lists 192".
# The library moves several times a day; a snapshot branch ages out before it
# is ever measured.


def _rebuild_step() -> dict:
    return _step(_save_steps(), "Rebuild the proposal on current main")


def _rebuild_fragment() -> str:
    """The rebuild step's shell, verbatim and complete -- push included.

    Executed rather than string-matched, and executed WHOLE: the first
    production run of this step (31086697823) died on its very first git
    command, because the checkout leaves `origin` without credentials while
    only the push carried a token URL. A fragment sliced before the push
    hides exactly that class, so the tests point both directions at a real
    local repository through the same override the step reads.
    """
    return _rebuild_step()["run"]


def _origin_with(tmp_path: Path, *, pin: int, published: int) -> Path:
    """A real origin whose main carries `pin` in the source and `published` in
    the manifest, plus a STALE proposal clone to run the fragment in."""
    origin = tmp_path / "origin"
    origin.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=origin, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=origin, check=True)
    source = re.sub(
        r"(import preuss_steffen/smc_micro_profiles_generated/)\d+( as mp)",
        rf"\g<1>{pin}\g<2>",
        (_REPO_ROOT / "SMC_Event_Overlay.pine").read_text(encoding="utf-8"),
        count=1,
    )
    (origin / "SMC_Event_Overlay.pine").write_text(source, encoding="utf-8")
    manifest_dir = origin / "artifacts" / "tradingview"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "library_release_manifest.json").write_text(
        json.dumps({"library": {"publishedVersion": published}}), encoding="utf-8"
    )
    subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
    subprocess.run(["git", "commit", "-qm", "main"], cwd=origin, check=True)

    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=work, check=True)
    # The snapshot the proposer left behind: an older pin AND an older
    # manifest -- exactly the shape that made the rollout tool refuse.
    stale = (work / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    (work / "SMC_Event_Overlay.pine").write_text(
        stale.replace(f"/{pin} as mp", "/183 as mp"), encoding="utf-8"
    )
    (work / "artifacts" / "tradingview" / "library_release_manifest.json").write_text(
        json.dumps({"library": {"publishedVersion": 190}}), encoding="utf-8"
    )
    subprocess.run(["git", "commit", "-qam", "stale proposal"], cwd=work, check=True)
    return work


def _run_rebuild(work: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    outputs = tmp_path / "gh-output"
    outputs.write_text("", encoding="utf-8")
    return subprocess.run(
        ["/bin/bash", "-c", _rebuild_fragment()],
        cwd=work,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "GITHUB_REF_NAME": "bot/r1-reattest",
            "GITHUB_OUTPUT": str(outputs),
            "GITHUB_REPOSITORY": "skipp-dev/skipp-algo",
            "GH_TOKEN": "test-token",
            "REATTEST_REMOTE": str(tmp_path / "origin"),
        },
        capture_output=True,
        text=True,
    )


def test_the_reattest_run_rebuilds_its_proposal_from_current_main(
    tmp_path: Path,
) -> None:
    """The measuring run must carry the manifest and the pin that are current
    WHEN IT RUNS, not the ones that were current when the proposal was made."""
    work = _origin_with(tmp_path, pin=183, published=192)

    done = _run_rebuild(work, tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    manifest = json.loads(
        (
            work / "artifacts" / "tradingview" / "library_release_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["library"]["publishedVersion"] == 192, "the stale manifest survived"
    source = (work / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    assert "smc_micro_profiles_generated/192 as mp" in source
    # The rebuilt proposal really reached the remote: the later evidence
    # commit fast-forwards onto this, so a push that silently failed would
    # strand the whole chain.
    pushed = subprocess.run(
        ["git", "show", "bot/r1-reattest:SMC_Event_Overlay.pine"],
        cwd=tmp_path / "origin",
        capture_output=True,
        text=True,
    )
    assert pushed.returncode == 0, pushed.stderr
    assert "smc_micro_profiles_generated/192 as mp" in pushed.stdout


def test_the_rebuild_no_ops_when_main_already_carries_the_published_pin(
    tmp_path: Path,
) -> None:
    work = _origin_with(tmp_path, pin=192, published=192)
    outputs = tmp_path / "gh-output"

    done = _run_rebuild(work, tmp_path)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "skip=true" in outputs.read_text(encoding="utf-8")


def test_the_rebuild_refuses_a_pin_ahead_of_the_manifest(tmp_path: Path) -> None:
    """Never a downgrade: a pin ahead of the manifest is the drift gate's
    business, not a reason to move the pin backwards."""
    work = _origin_with(tmp_path, pin=200, published=192)

    done = _run_rebuild(work, tmp_path)

    assert done.returncode == 1
    assert "AHEAD" in done.stdout + done.stderr


def test_the_rebuild_runs_before_anything_is_measured() -> None:
    names = [str(step.get("name", "")) for step in _save_steps()]
    rebuild = next(
        i for i, n in enumerate(names) if n.startswith("Rebuild the proposal")
    )
    save = next(
        i for i, n in enumerate(names) if n.startswith("Save or read-only verify")
    )
    assert rebuild < save, "the rebuild must precede the write pass"
    assert "reattest" in str(_rebuild_step().get("if", "")), "reattest-only"
    assert "-f" in _rebuild_step()["run"], "the fixed proposal branch is force-pushed"


def test_the_rebuild_authenticates_both_directions_the_same_way() -> None:
    """`persist-credentials: false` leaves `origin` credential-less.

    Run 31086697823 died on `git fetch origin main` while the push beside it
    carried a token URL -- the fetch and the push must go through the same
    authenticated remote, and neither may address the bare `origin`.
    """
    run = _rebuild_step()["run"]
    assert 'git fetch --depth=1 "${remote_url}" main' in run
    assert 'git push -f "${remote_url}"' in run
    assert "x-access-token:${GH_TOKEN}@github.com" in run, "no default token URL"
    # Executable lines only: the step's own comment names the broken form.
    executable = "\n".join(
        line for line in run.splitlines() if not line.lstrip().startswith("#")
    )
    for direction in ("git fetch origin", "git push origin"):
        assert direction not in executable, f"{direction} has no credentials here"
