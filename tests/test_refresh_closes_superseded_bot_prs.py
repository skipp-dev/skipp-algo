"""The refresh must close the bot PRs it supersedes -- executed, not read.

Branch names carry the run id (``bot/library-refresh-<run>-<attempt>``), so
every refresh opens a NEW PR and, until 2026-08-04, nothing ever closed an old
one. That was invisible while auto-merge cleared each PR in seconds; the moment
the R1 guard blocked the merge they piled up at export cadence.

Both halves are exercised for real: the shell loop runs against stubbed
executables and its calls are inspected, and the jq selection is extracted from
the workflow and run through jq against sample API payloads. A substring test
over the YAML could not tell "closes the siblings" from "closes everything" --
and closing everything would take out the PR this run just opened.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests._workflow_step_shell import BASH, declares_bash_default, run_step, step_by_name

# 2026-08-13: Der Schritt gehoert zur Commit-Phase und ist mit ihr nach
# smc-library-publish gezogen; der Refresh committet nicht mehr.
WORKFLOW = "smc-library-publish.yml"
STEP = "Commit and push changes"
CURRENT_BRANCH = "bot/library-refresh-999-1"


def _write_stub(bin_dir: Path, name: str, body: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text(body, encoding="utf-8")
    stub.chmod(0o755)


def _env() -> dict[str, str]:
    return {
        "GITHUB_RUN_ID": "999",
        "GITHUB_RUN_ATTEMPT": "1",
        "REFRESH_DATE": "2026-08-04",
        "GH_TOKEN": "x",
        "GITHUB_TOKEN": "x",
        "R1_ATTESTATION_NOTICE": "",
        "R1_HOLD_NOTICE": "",
        "HOME": "/tmp",
        "RUN_NUMBER": "1099",
    }


def test_workflow_still_declares_the_bash_default_this_harness_assumes() -> None:
    assert declares_bash_default(WORKFLOW), (
        f"{WORKFLOW} no longer declares `defaults: run: shell: bash`; "
        f"{BASH} is then the wrong shell contract for this test"
    )


def test_the_step_closes_every_superseded_sibling_and_not_its_own_pr(tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"

    # `git diff --cached --quiet` must report staged content, or the step exits
    # early with "No post-publish changes to commit" and never reaches the
    # cleanup. Every other git call succeeds.
    _write_stub(
        bin_dir,
        "git",
        "#!/bin/sh\n"
        f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{calls}"\n'
        'case "$*" in *"--cached --quiet"*) exit 1 ;; esac\n'
        "exit 0\n",
    )
    # gh emulates the API: two older refresh PRs are open. The jq selection runs
    # inside gh, so this stub returns what a correct filter would yield; the
    # filter itself is executed separately below.
    _write_stub(
        bin_dir,
        "gh",
        "#!/bin/sh\n"
        f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{calls}"\n'
        'case "$1$2" in prlist) printf "4405\\n4429\\n" ;; esac\n'
        "exit 0\n",
    )

    result = run_step(WORKFLOW, STEP, tmp_path, env=_env())

    assert result.returncode == 0, result.stderr
    closed = result.called_with("pr", "close")
    assert len(closed) == 2, f"expected both siblings closed, got: {closed}"
    # The argument after `close` is the target. Asserting on the whole line
    # would pass on the branch name inside the --comment text, which every
    # close carries -- a tautology rather than a check.
    targets = {call.split()[2] for call in closed}
    assert targets == {"4405", "4429"}, targets
    for call in closed:
        assert "--delete-branch" in call
    # Which PRs are eligible is decided by the jq selection, executed
    # separately below; that is where "not its own PR" is actually proven.
    # And the cleanup runs AFTER the PR exists, never instead of creating it.
    assert result.called_with("pr", "create")


def test_a_failing_close_is_reported_but_does_not_fail_the_refresh(tmp_path: Path) -> None:
    """The refresh has already landed in a PR; losing cleanup must not lose it."""
    calls = tmp_path / "calls"
    calls.write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    _write_stub(
        bin_dir,
        "git",
        "#!/bin/sh\n"
        f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{calls}"\n'
        'case "$*" in *"--cached --quiet"*) exit 1 ;; esac\n'
        "exit 0\n",
    )
    _write_stub(
        bin_dir,
        "gh",
        "#!/bin/sh\n"
        f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{calls}"\n'
        'case "$1$2" in prlist) printf "4405\\n" ;; prclose) exit 1 ;; esac\n'
        "exit 0\n",
    )

    result = run_step(WORKFLOW, STEP, tmp_path, env=_env())

    assert result.returncode == 0, result.stderr
    assert "could not close superseded refresh PR #4405" in result.stdout


def _jq_filter() -> str:
    """The selection the step hands to `gh --jq`, taken from the step itself."""
    run = str(step_by_name(WORKFLOW, STEP)["run"])
    marker = "--jq "
    start = run.index(marker) + len(marker)
    expr = run[start:].split("\n", 1)[0].strip()
    # The step embeds it as a shell double-quoted string with escaped quotes.
    assert expr.startswith('"') and expr.endswith('\\'), expr
    expr = expr.rstrip("\\").strip().strip('"')
    return expr.replace('\\"', '"').replace("${BRANCH}", CURRENT_BRANCH)


@pytest.mark.parametrize(
    ("head_ref", "selected"),
    [
        ("bot/library-refresh-111-1", True),
        ("bot/library-refresh-222-2", True),
        (CURRENT_BRANCH, False),  # the PR this run just opened
        ("fix/some-human-branch", False),
        ("bot/other-automation-1", False),  # a different bot, not ours to close
        ("dependabot/pip/pip-all-767e150241", False),
        ("main", False),
    ],
)
def test_the_selection_picks_only_superseded_refresh_branches(head_ref: str, selected: bool) -> None:
    payload = json.dumps([{"number": 4242, "headRefName": head_ref}])

    out = subprocess.run(
        ["jq", "-r", _jq_filter()],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    assert bool(out) is selected, f"{head_ref!r} -> {out!r}"
    if selected:
        assert out == "4242"
