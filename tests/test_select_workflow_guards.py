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

from scripts.select_workflow_guards import _CONFIG_SURFACES, ROOT, select_guards

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
    # Diff-scoped: a PR that changes no CI surface must not pay for this.
    assert 'git diff --name-only "${BASE_SHA}..${HEAD_SHA}" --' in gates
    assert ".github/workflows/" in gates
    # And the selection has to be executed, not merely printed.
    assert "python -m pytest ${guards}" in gates

    # Placement, not just presence. The first attempt sat beside the R1 guard,
    # which needs only the standard library, and died on "No module named
    # pytest" (run 30697585385) -- the selection was correct and unusable.
    install = gates.index("- name: Install dependencies")
    step = gates.index("- name: Run every guard that reads a CI surface this PR changed")
    assert install < step, "the selection runs pytest, so it must follow the dependency install"


def test_the_diff_feeds_every_surface_the_selector_knows() -> None:
    """The superset relation, which is where this mechanism actually breaks.

    The selector and the step are two halves of one gate, and they fail
    silently in OPPOSITE directions. A surface the selector knows but the diff
    never hands it selects nothing and looks exactly like "no guard reads
    this" -- which is how a PR editing ``.github/dependabot.yml`` came to run
    its own guard only after merge, on 2026-08-06.

    Asserted against the step's real pathspec, sliced out of the workflow, so
    the check cannot be satisfied by the surface appearing somewhere else in
    the file (the ``ignore:`` block names ``dependabot`` too).
    """
    gates = (ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml").read_text(encoding="utf-8")
    start = gates.index('git diff --name-only "${BASE_SHA}..${HEAD_SHA}" --')
    pathspec = gates[start : gates.index(")", start)]

    missing = [
        surface
        for surface in _CONFIG_SURFACES
        # `.github/actions/*/action.yml` is fed as the directory `.github/actions/`
        if surface.split("*")[0] not in pathspec
    ]
    assert not missing, (
        f"scripts/select_workflow_guards.py knows {missing} but the fast-gates diff "
        "never hands them over, so their guards are selected by nothing. Add them to "
        "the pathspec of the 'Run every guard that reads a CI surface this PR changed' "
        "step, or drop them from _CONFIG_SURFACES."
    )


@pytest.mark.parametrize("surface", _CONFIG_SURFACES)
def test_every_declared_surface_selects_at_least_one_guard(surface: str) -> None:
    """No surface may be listed that nothing reads.

    Without this, ``_CONFIG_SURFACES`` accumulates entries that look like
    coverage and select nothing -- the failure mode this repo calls vacuity.
    Measured 2026-08-06 while choosing the list: ``.pre-commit-config.yaml``
    has zero readers and was left out for exactly this reason.
    """
    probe = surface.replace("*", "setup-python-pinned")
    # THIS file does not count as a reader. It discusses the surfaces by name --
    # including the ones deliberately left out -- so counting itself would let
    # any surface satisfy the check on the strength of the prose explaining why
    # it should not. Measured: a mutation adding `.pre-commit-config.yaml`
    # (zero real readers) stayed GREEN until this line existed.
    selected = [s for s in select_guards([probe]) if not s.endswith(Path(__file__).name)]
    assert selected, (
        f"{surface} is declared a config surface but no test under tests/ names it, "
        "so changing it selects nothing. Either a guard is missing, or the surface "
        "does not belong in _CONFIG_SURFACES."
    )


def test_a_config_surface_does_not_drag_in_the_workflow_enumerators() -> None:
    """Over-selection is cheap; THIS over-selection was not.

    ``.github/dependabot.yml`` is a ``.yml`` like any other, so before the
    stems were restricted to ``.github/workflows/`` it produced the stem
    ``dependabot`` and selected all 38 guards that merely enumerate the
    workflow directory -- none of which read it. Measured 2026-08-06.
    """
    dependabot = select_guards([".github/dependabot.yml"])
    workflow = select_guards([".github/workflows/ci.yml"])

    assert len(dependabot) < len(workflow) / 4, (
        f"a dependabot-only change selected {len(dependabot)} guards against "
        f"{len(workflow)} for a workflow change — the workflow enumerators are "
        "being dragged in by a stem that is not a workflow"
    )
    # Named, not merely counted: a count alone would pass on any four files.
    assert {
        "tests/test_dependabot_local_version_pins.py",
        "tests/test_dependabot_typescript_major_hold.py",
    } <= set(dependabot), f"the dependabot guards themselves were not selected: {dependabot}"
    # This file is in the selection too, and belongs there: it names the surface
    # in the tests above, so a change to that surface should re-run the guard
    # that decides which guards run. Self-selection is the mechanism working.
    assert "tests/test_select_workflow_guards.py" in dependabot
