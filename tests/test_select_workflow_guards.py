"""The gate must run every guard that reads a workflow the PR changed.

Three times on 2026-08-01 a green PR changed a workflow and broke a guard that
reads it but is not on the fast-gates list. Each repair added one more file to
the roster, which closes the instance and not the class.

The regression cases below are the point of this module. They are not examples:
each one is a workflow that actually shipped a break, paired with the guard that
would have caught it and was not consulted. A selector that misses any of them
is the selector that let that day happen.

Measured before believed, twice:

* a roster rule ("every workflow guard must be gated") is a gate rebuild -- 571
  test files read a workflow, 484 are unlisted;
* a first draft of this selector matched workflow names only, and caught ONE of
  the three. That is why enumeration is a separate rule rather than a nicety.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.select_workflow_guards import ROOT, select_guards

# (changed workflow, guard that reads it, what shipped past it)
_REGRESSIONS = [
    pytest.param(
        "smc-r4-context-readback.yml",
        "tests/test_workflow_python_bin_resolved.py",
        id="4285-python-bin-never-set",
    ),
    pytest.param(
        "smc-r4-context-readback.yml",
        "tests/test_workflow_live_window_posture.py",
        id="4291-posture-marker-outside-vocabulary",
    ),
    pytest.param(
        "smc-library-refresh.yml",
        "tests/test_workflow_databento_handoff_concurrency.py",
        id="4302-two-concurrency-pins-disagreeing",
    ),
]


@pytest.mark.parametrize("workflow,guard", _REGRESSIONS)
def test_the_guard_that_was_missed_is_selected(workflow: str, guard: str) -> None:
    selected = select_guards([f".github/workflows/{workflow}"])

    assert guard in selected, (
        f"changing {workflow} would not run {guard}, which is exactly how the "
        "break it guards against reached main"
    )


def test_a_guard_that_only_enumerates_is_selected_by_any_workflow() -> None:
    """It names no workflow, so nothing else can select it.

    test_workflow_live_window_posture.py globs the directory and checks every
    file's marker. Name-matching alone leaves it unreachable — the omission that
    made the first draft of this selector catch one regression out of three.
    """
    posture = "tests/test_workflow_live_window_posture.py"

    assert posture in select_guards([".github/workflows/ci.yml"])
    assert posture in select_guards([".github/workflows/docs-lint.yml"])


def test_a_bare_stem_counts_because_guards_append_the_extension() -> None:
    """test_workflow_databento_handoff_concurrency.py stores "smc-library-refresh"."""
    guard = "tests/test_workflow_databento_handoff_concurrency.py"
    text = (ROOT / guard).read_text(encoding="utf-8")

    # The premise, asserted rather than assumed: if that file ever spells the
    # extension, this test still passes for the wrong reason.
    assert '"smc-library-refresh"' in text
    assert "smc-library-refresh.yml" not in text

    assert guard in select_guards([".github/workflows/smc-library-refresh.yml"])


def test_a_neighbouring_stem_does_not_match() -> None:
    """Delimiters keep smc-library-refresh from dragging in every longer name."""
    changed = [".github/workflows/smc-library-refresh.yml"]
    selected = select_guards(changed)

    guard = "tests/test_smc_library_refresh_producer_guard.py"
    text = (ROOT / guard).read_text(encoding="utf-8")
    if "smc-library-refresh" not in text and "glob(" not in text:
        assert guard not in selected


def test_a_pr_that_touches_no_workflow_selects_nothing() -> None:
    """The whole cost model: PRs that do not touch workflows pay zero."""
    assert select_guards([]) == []
    assert select_guards(["scripts/smc_r1_rollout_contract.py", "README.md"]) == []


def test_selection_is_a_real_subset_of_the_workflow_readers(tmp_path: Path) -> None:
    """A selector that returns everything would pass every test above and be useless."""
    everything = select_guards([".github/workflows/ci.yml"])
    all_tests = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))

    assert everything, "selecting nothing for a changed workflow would be vacuous"
    assert len(everything) < len(all_tests) / 2, (
        f"selected {len(everything)} of {len(all_tests)} test files — the "
        "selector is not discriminating"
    )


def test_the_gate_actually_runs_the_selection() -> None:
    """A selector nothing calls is a library, not a gate.

    Every assertion above passes just as well with the step deleted from
    smc-fast-pr-gates.yml — which is the shape of vacuity this whole line of
    work exists to remove, so the wiring is pinned here rather than assumed.
    """
    gates = (ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml").read_text(encoding="utf-8")

    assert "python -m scripts.select_workflow_guards" in gates
    # Diff-scoped: a PR that changes no workflow must not pay for this.
    assert 'git diff --name-only "${BASE_SHA}..${HEAD_SHA}" -- .github/workflows/' in gates
    # And the selection has to be executed, not merely printed.
    assert "python -m pytest ${guards}" in gates
