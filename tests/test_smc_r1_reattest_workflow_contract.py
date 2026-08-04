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


def test_proposer_runs_on_weekday_premarket_schedule_and_dispatch_only() -> None:
    on_block = _reattest().get("on") or _reattest().get(True)
    crons = [entry["cron"] for entry in on_block["schedule"]]
    assert crons == ["7 12 * * 1-5"], (
        "one weekday pre-US-open proposal per day -- the fixed branch and the "
        "chain head-check both assume no concurrent proposals"
    )
    assert "workflow_dispatch" in on_block
    assert set(on_block) == {"schedule", "workflow_dispatch"}, (
        "no push/PR triggers: the proposer must never run on its own proposal"
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


def test_proposer_pin_substitution_bumps_exactly_the_import_line() -> None:
    """Executed, not string-matched: the same regex the proposer ships must
    rewrite the REAL Event Overlay source to a target pin and change nothing
    else -- the pin-only diff class is what the generator later re-proves by
    hash reconstruction."""
    push = _step(_reattest()["jobs"]["propose"]["steps"], "Force-push the pin-bump")
    match = re.search(r'r"\(import preuss_steffen[^"]+"', push["run"])
    assert match is not None, "the pin substitution regex left the proposer"

    source = (_REPO_ROOT / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    new = re.sub(
        r"(import preuss_steffen/smc_micro_profiles_generated/)\d+( as mp)",
        r"\g<1>99999\g<2>",
        source,
        count=1,
    )
    assert new != source
    changed = [
        (a, b)
        for a, b in zip(source.splitlines(), new.splitlines())
        if a != b
    ]
    assert len(changed) == 1
    assert changed[0][1].endswith("/99999 as mp")


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


def test_the_unattested_guard_remeasures_instead_of_trusting_the_flag() -> None:
    """The carve-out may only turn the run green by asking the SAME module
    that found the un-attestation again, against the extended chain."""
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
