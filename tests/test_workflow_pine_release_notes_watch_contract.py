"""pine-release-notes-watch.yml — executed contract of the announcement bridge.

The decision steps RUN here (via ``tests/_workflow_step_shell.py``) instead of
being string-matched: a substring test cannot tell "arms auto-merge" from
"never arms it", and this workflow's whole value is what it does on a delta.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests._workflow_step_shell import Stub, declares_bash_default, run_step

_WORKFLOW = "pine-release-notes-watch.yml"
_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / ".github" / "workflows" / _WORKFLOW


def _doc() -> dict:
    return yaml.safe_load(_PATH.read_text(encoding="utf-8"))


def _on(doc: dict) -> dict:
    return doc.get("on") or doc.get(True)


# -- static contract --------------------------------------------------------
def test_triggers_are_cron_and_dispatch_only() -> None:
    on = _on(_doc())
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert [entry["cron"] for entry in on["schedule"]] == ["30 5 * * 1"]


def test_runner_uses_the_hosted_selector_and_bash_default() -> None:
    job = _doc()["jobs"]["watch"]
    assert job["runs-on"] == "${{ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}"
    assert declares_bash_default(_WORKFLOW)


def test_job_permissions_are_minimal() -> None:
    assert _doc()["jobs"]["watch"]["permissions"] == {
        "contents": "read",
        "issues": "write",
    }


def test_freshness_monitor_carries_the_weekly_budget_row() -> None:
    # A weekly cron that silently stops running is exactly the failure class
    # workflow-freshness-monitor.yml exists for (post-mortem #2415).
    monitor = (_ROOT / ".github" / "workflows" / "workflow-freshness-monitor.yml").read_text(
        encoding="utf-8"
    )
    assert f"{_WORKFLOW}=192" in monitor


def test_pr_and_issue_steps_gate_on_the_detect_outputs() -> None:
    doc = _doc()
    steps = {s.get("name"): s for s in doc["jobs"]["watch"]["steps"] if isinstance(s, dict)}
    assert steps["Open snapshot PR"]["if"] == "steps.watch.outputs.changed == 'true'"
    issue_if = " ".join(str(steps["File affected-surface issue"]["if"]).split())
    assert issue_if == (
        "steps.watch.outputs.changed == 'true' && steps.watch.outputs.affected_files != '0'"
    )


# -- executed steps ---------------------------------------------------------
_ENV = {
    "GITHUB_RUN_ID": "424242",
    "GITHUB_REPOSITORY": "skipp-dev/skipp-algo",
}


def test_detect_step_forwards_the_script_outputs(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "Detect release-notes delta",
        tmp_path,
        env=_ENV,
        stubs={
            "python": Stub(
                stdout="changed=true\nnew_entries=2\nchanged_entries=1\naffected_files=3"
            ),
        },
    )
    assert result.returncode == 0
    assert result.outputs == {
        "changed": "true",
        "new_entries": "2",
        "changed_entries": "1",
        "affected_files": "3",
    }
    assert result.called_with("scripts/pine_release_notes_watch.py", "--update", "--report")


def test_detect_step_fails_the_job_when_the_watcher_fails(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "Detect release-notes delta",
        tmp_path,
        env=_ENV,
        stubs={"python": Stub(exit_code=1)},
    )
    assert result.returncode != 0, "a fetch/extraction failure must be a RED run"


def test_snapshot_pr_commits_pushes_creates_and_arms_automerge(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "Open snapshot PR",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "tok", "NEW_ENTRIES": "2", "CHANGED_ENTRIES": "0"},
        stubs={"git": Stub(), "gh": Stub()},
    )
    assert result.returncode == 0
    assert result.called_with("add", "pine/tv_release_notes_snapshot.md")
    assert result.called_with("push")
    assert result.called_with("pr create", "--base main")
    assert result.called_with("pr merge", "--auto", "--squash")


def test_snapshot_pr_without_token_warns_and_creates_nothing(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "Open snapshot PR",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "", "NEW_ENTRIES": "2", "CHANGED_ENTRIES": "0"},
        stubs={"git": Stub(), "gh": Stub()},
    )
    assert result.returncode == 0
    assert not result.calls
    assert "GH_PAT not configured" in result.stdout


def test_pr_creation_failure_is_red_but_automerge_failure_is_soft(tmp_path: Path) -> None:
    creation_fails = run_step(
        _WORKFLOW,
        "Open snapshot PR",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "tok", "NEW_ENTRIES": "1", "CHANGED_ENTRIES": "0"},
        stubs={
            "git": Stub(),
            "gh": Stub(script='case "$1 $2" in "pr create") exit 1;; esac\nexit 0'),
        },
    )
    assert creation_fails.returncode != 0, "green without the PR would drop the observation"

    arming_fails = run_step(
        _WORKFLOW,
        "Open snapshot PR",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "tok", "NEW_ENTRIES": "1", "CHANGED_ENTRIES": "0"},
        stubs={
            "git": Stub(),
            "gh": Stub(script='case "$1 $2" in "pr merge") exit 1;; esac\nexit 0'),
        },
    )
    assert arming_fails.returncode == 0
    assert "auto-merge could not be armed" in arming_fails.stdout


def test_issue_step_comments_on_the_existing_open_issue(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "File affected-surface issue",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "tok", "GH_REPO": "skipp-dev/skipp-algo"},
        stubs={
            "gh": Stub(
                script=(
                    'case "$1" in\n'
                    "  repo) echo true;;\n"
                    "  issue) if [ \"$2\" = list ]; then echo 77; fi;;\n"
                    "esac\nexit 0"
                )
            ),
        },
    )
    assert result.returncode == 0
    assert result.called_with("issue comment", "77")
    assert not result.called_with("issue create")


def test_issue_step_creates_labeled_issue_when_none_open(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "File affected-surface issue",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "tok", "GH_REPO": "skipp-dev/skipp-algo"},
        stubs={
            "gh": Stub(script='case "$1" in repo) echo true;; esac\nexit 0'),
        },
    )
    assert result.returncode == 0
    assert result.called_with("issue create", "--label automated")
    assert not result.called_with("issue comment")


def test_issue_step_degrades_softly_when_issues_disabled(tmp_path: Path) -> None:
    result = run_step(
        _WORKFLOW,
        "File affected-surface issue",
        tmp_path,
        env={**_ENV, "GH_TOKEN": "tok", "GH_REPO": "skipp-dev/skipp-algo"},
        stubs={"gh": Stub(script='case "$1" in repo) echo false;; esac\nexit 0')},
    )
    assert result.returncode == 0
    assert not result.called_with("issue create")
    assert not result.called_with("issue comment")
