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

from tests._workflow_step_shell import BASH, Stub, declares_bash_default, run_step, step_by_name

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


# ---------------------------------------------------------------------------
# 2026-10-01: the chained save never found the PR this step opens.
#
# tv-save-consumer-source waits for the refresh commit by looking for a PR
# whose branch starts with ``bot/library-refresh-<id of the REFRESH run>-``
# (the id its workflow_run event carries). Since the commit phase moved here on
# 2026-08-13, this step named the branch after its OWN run id -- the id of the
# PUBLISH run. Two different numbers, so the lookup matched nothing and the
# save read "No ... PR exists -- the refresh reported no post-publish changes"
# as a legitimate no-op, started on the pre-refresh tree and refused on
# "Library publish drift".
#
# Measured: 14 of 14 failed chained saves between 2026-09-24 and 2026-10-01
# carry exactly that notice; the last one (36919569655) started 26 s after
# PR #5597 was opened and 5 min before it merged. Each side had a test pinning
# its own text, and both were green: nothing ran the two against each other.
# The tests below do.
# ---------------------------------------------------------------------------

SAVE_WORKFLOW = "tv-save-consumer-source.yml"
AWAIT_STEP = "Await the refresh commit on main"
REFRESH_RUN = "36908068669"
PUBLISH_RUN = "36919569627"


def _branch_the_publish_step_creates(tmp_path: Path, env: dict[str, str]) -> str:
    """Run the publish step and read the branch name off its own git call."""
    tmp_path.mkdir(parents=True, exist_ok=True)
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
        "#!/bin/sh\n" f'{{ printf "%s " "$@"; printf "\\n"; }} >> "{calls}"\n' "exit 0\n",
    )
    result = run_step(WORKFLOW, STEP, tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    created = result.called_with("checkout", "-b")
    assert len(created) == 1, created
    return created[0].split()[2]


def _await_step_against(tmp_path: Path, pull_requests: list[dict], refresh_run: str):
    """Run the save's await step; ``gh pr list`` answers from ``pull_requests``.

    The step filters inside gh (``--jq``), so the stub hands that exact filter
    to the real jq over the sample payload -- the selection is executed, not
    assumed.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = tmp_path / "prs.json"
    payload.write_text(json.dumps(pull_requests), encoding="utf-8")
    gh = Stub(
        script=(
            'filter=""\n'
            'while [ "$#" -gt 0 ]; do\n'
            '  if [ "$1" = "--jq" ]; then filter="$2"; fi\n'
            "  shift\n"
            "done\n"
            f'exec jq -c "$filter" "{payload}"\n'
        )
    )
    return run_step(
        SAVE_WORKFLOW,
        AWAIT_STEP,
        tmp_path,
        env={
            "GH_TOKEN": "x",
            "REPO": "skipp-dev/skipp-algo",
            "REFRESH_RUN_ID": refresh_run,
            "AWAIT_TIMEOUT_SECONDS": "1",
        },
        stubs={"gh": gh},
    )


def test_the_chained_save_finds_the_pr_this_step_opens(tmp_path: Path) -> None:
    """Both halves executed against each other, with the real ids of the incident."""
    branch = _branch_the_publish_step_creates(
        tmp_path / "publish",
        {**_env(), "GITHUB_RUN_ID": PUBLISH_RUN, "REFRESH_SOURCE_RUN_ID": REFRESH_RUN},
    )

    result = _await_step_against(
        tmp_path / "save",
        [{"number": 5597, "headRefName": branch, "state": "MERGED", "mergeCommit": {"oid": "85b66551d"}}],
        REFRESH_RUN,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.outputs.get("sha") == "85b66551d", (
        f"the save did not resolve the refresh commit from branch {branch!r}: {result.stdout}"
    )
    assert "No bot/library-refresh-" not in result.stdout


def test_an_open_refresh_pr_makes_the_save_wait_instead_of_starting(tmp_path: Path) -> None:
    """The state the incident run met: PR open, merge five minutes away.

    With the timeout cut to one second the step must end in the loud
    "did not merge within" failure -- proof that it WAITED on this PR. Before
    the fix it exited 0 at once with the no-op notice.
    """
    branch = _branch_the_publish_step_creates(
        tmp_path / "publish",
        {**_env(), "GITHUB_RUN_ID": PUBLISH_RUN, "REFRESH_SOURCE_RUN_ID": REFRESH_RUN},
    )

    result = _await_step_against(
        tmp_path / "save",
        [{"number": 5597, "headRefName": branch, "state": "OPEN", "mergeCommit": None}],
        REFRESH_RUN,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "did not merge within" in result.stdout
    assert "sha" not in result.outputs


def test_a_refresh_pr_of_another_refresh_run_is_not_this_ones(tmp_path: Path) -> None:
    """Identity, not recency: the neighbour's PR must not satisfy the wait."""
    branch = _branch_the_publish_step_creates(
        tmp_path / "publish",
        {**_env(), "GITHUB_RUN_ID": PUBLISH_RUN, "REFRESH_SOURCE_RUN_ID": "36147883683"},
    )

    result = _await_step_against(
        tmp_path / "save",
        [{"number": 5525, "headRefName": branch, "state": "MERGED", "mergeCommit": {"oid": "5db4e72e5"}}],
        REFRESH_RUN,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "sha" not in result.outputs
    assert f"No bot/library-refresh-{REFRESH_RUN}-" in result.stdout


def test_both_sides_take_the_id_from_the_same_refresh_run() -> None:
    """The env bindings the harness cannot execute, pinned structurally.

    ``run_step`` feeds env values in by hand, so the executed tests above prove
    the shell on both sides agrees GIVEN the same id. That both steps are
    actually handed the id of the same run is an Actions-expression fact.
    """
    import yaml

    from tests._workflow_step_shell import WORKFLOWS

    publish_step = step_by_name(WORKFLOW, STEP)
    await_step = step_by_name(SAVE_WORKFLOW, AWAIT_STEP)
    publish_expr = publish_step["env"]["REFRESH_SOURCE_RUN_ID"]
    await_expr = await_step["env"]["REFRESH_RUN_ID"]
    assert "github.event.workflow_run.id" in publish_expr
    assert "inputs.source_run_id" in publish_expr, "a manual publish names its refresh run through source_run_id"
    assert "github.event.workflow_run.id" in await_expr

    # ... and that event is the completion of the same workflow on both sides.
    for workflow in (WORKFLOW, SAVE_WORKFLOW):
        doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
        triggers = doc.get("on") or doc.get(True)
        assert "smc-library-refresh" in triggers["workflow_run"]["workflows"], workflow


@pytest.mark.parametrize("source", ["", "main; rm -rf x", "12a"])
def test_a_publish_without_a_usable_refresh_run_keeps_the_plain_name(tmp_path: Path, source: str) -> None:
    """Manual dispatch without ``source_run_id`` (or with junk in it).

    The value arrives through ``env:`` and ends up in a branch name, so only
    digits are accepted; anything else falls back to the run's own id.
    """
    branch = _branch_the_publish_step_creates(
        tmp_path, {**_env(), "GITHUB_RUN_ID": PUBLISH_RUN, "REFRESH_SOURCE_RUN_ID": source}
    )
    assert branch == f"bot/library-refresh-{PUBLISH_RUN}-1"
