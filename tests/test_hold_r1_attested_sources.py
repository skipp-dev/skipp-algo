"""Tests for scripts/hold_r1_attested_sources.py.

Every test below RUNS the hold against a real git working tree rather than
reading its source: the whole point of the script is what the tree looks like
afterwards, and a substring test cannot tell "restored the file" from "printed
that it would".
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "hold_r1_attested_sources.py"

_spec = importlib.util.spec_from_file_location("hold_r1_attested_sources", _SCRIPT)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True, env=env)
    return root


def test_modified_attested_source_is_restored_to_committed_content(tmp_path: Path) -> None:
    attested = "SMC_Event_Overlay.pine"
    other = "SMC_Long_Dip_Suite.pine"
    root = _repo(
        tmp_path,
        {
            attested: "import preuss_steffen/smc_micro_profiles_generated/183 as mp\n",
            other: "import preuss_steffen/smc_micro_profiles_generated/183 as mp\n",
        },
    )
    # What a refresh does: bump the pin everywhere.
    for name in (attested, other):
        (root / name).write_text(
            "import preuss_steffen/smc_micro_profiles_generated/186 as mp\n",
            encoding="utf-8",
        )

    held = mod.hold([attested], cwd=root)

    assert held == [attested]
    # The attested companion is back at the version the evidence describes...
    assert "/183 as mp" in (root / attested).read_text(encoding="utf-8")
    # ...and every other consumer keeps the bump. Holding must not be a revert
    # of the refresh.
    assert "/186 as mp" in (root / other).read_text(encoding="utf-8")


def test_untouched_attested_source_is_left_alone(tmp_path: Path) -> None:
    attested = "SMC_Event_Overlay.pine"
    root = _repo(tmp_path, {attested: "unchanged\n", "other.pine": "a\n"})
    (root / "other.pine").write_text("b\n", encoding="utf-8")

    assert mod.hold([attested], cwd=root) == []
    assert (root / "other.pine").read_text(encoding="utf-8") == "b\n"


def test_empty_roster_is_refused_rather_than_diffing_the_whole_tree(tmp_path: Path) -> None:
    """The pathspec trap, pinned.

    ``git diff --name-only HEAD --`` with no paths drops the pathspec and
    reports every modified file in the tree. Holding on that answer would
    restore the entire refresh, silently undoing the run it is meant to keep.
    """
    root = _repo(tmp_path, {"a.pine": "a\n"})
    (root / "a.pine").write_text("changed\n", encoding="utf-8")

    with pytest.raises(ValueError):
        mod.modified_attested([], cwd=root)

    # And the file it would have clobbered is untouched.
    assert (root / "a.pine").read_text(encoding="utf-8") == "changed\n"


def test_roster_is_derived_from_the_live_rollout_contract() -> None:
    """No second hand-maintained list of attested paths."""
    paths = mod.attested_paths()

    assert paths, "the live contract must yield at least one attested source"
    assert "SMC_Event_Overlay.pine" in paths
    for path in paths:
        assert (_REPO / path).exists(), f"{path} is attested but not in the tree"


def test_notice_names_every_held_path_and_says_the_pin_is_deliberate() -> None:
    notice = mod.render_notice(["SMC_Event_Overlay.pine", "SMC_Exit_Signal.pine"])

    assert "SMC_Event_Overlay.pine" in notice
    assert "SMC_Exit_Signal.pine" in notice
    # A reviewer must be able to tell a deliberate lag from a stale pin.
    assert "deliberate" in notice.lower()
    assert "re-attestation" in notice.lower()


def _run_main(tmp_path: Path, root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, str]:
    """Run main() end to end and return (exit code, $GITHUB_OUTPUT content)."""
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")
    # The roster comes from the real contract; the tree under test is the temp
    # repo, which is exactly how the workflow calls it (repo checkout == cwd).
    monkeypatch.setattr(mod, "attested_paths", lambda *a, **k: ["SMC_Event_Overlay.pine"])
    code = mod.main(["--repo", str(root), "--github-output", str(output)])
    return code, output.read_text(encoding="utf-8")


def test_main_writes_held_paths_and_a_notice_when_it_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attested = "SMC_Event_Overlay.pine"
    root = _repo(tmp_path, {attested: "old\n"})
    (root / attested).write_text("new\n", encoding="utf-8")

    code, outputs = _run_main(tmp_path, root, monkeypatch)

    assert code == 0
    assert '"SMC_Event_Overlay.pine"' in outputs
    assert "R1-attested sources held" in outputs
    # And the tree really was restored -- the outputs are a claim, this is the fact.
    assert (root / attested).read_text(encoding="utf-8") == "old\n"


def test_main_emits_an_empty_notice_when_nothing_needed_holding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No hold must not decorate the PR body with an empty claim."""
    root = _repo(tmp_path, {"SMC_Event_Overlay.pine": "old\n"})

    code, outputs = _run_main(tmp_path, root, monkeypatch)

    assert code == 0
    assert "held=[]" in outputs
    assert "R1-attested sources held" not in outputs


def test_main_fails_closed_on_an_empty_roster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty roster is UNKNOWN, never an all-clear."""
    root = _repo(tmp_path, {"SMC_Event_Overlay.pine": "old\n"})
    (root / "SMC_Event_Overlay.pine").write_text("new\n", encoding="utf-8")
    monkeypatch.setattr(mod, "attested_paths", lambda *a, **k: [])
    output = tmp_path / "gh_output"
    output.write_text("", encoding="utf-8")

    code = mod.main(["--repo", str(root), "--github-output", str(output)])

    assert code == 1
    # Nothing held, nothing claimed, and the tree untouched.
    assert output.read_text(encoding="utf-8") == ""
    assert (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8") == "new\n"
