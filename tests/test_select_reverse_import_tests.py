"""The gate must run every test that imports a production module the PR changed.

2026-08-16: #4752 removed the Hold-Manager legacy route and merged green.
fast-gates runs fixed smoke sets, and ci.yml is status-only on pull requests
by design -- so ``tests/test_hold_manager_receiver_off_event_loop.py``, which
imports the changed module directly and fails deterministically on that tree,
first ran on the main push. Cost: two red main runs, a cross-session
misdiagnosis ("env-local"), and repair PR #4755.

scripts/select_reverse_import_tests.py closes the class the way the workflow
guard selector does: selection follows the diff. These tests pin three
things, each of which the others cannot carry alone:

* the selection RULES, executed against synthetic trees;
* the MOTIVATING regression, against the real tree, so a selector refactor
  that quietly drops the ``from A import B`` form re-fails loudly here;
* the WIRING and the COST MODEL -- a selector nothing calls is a library,
  and a stage whose worst case silently grows past its measured bound stops
  being the "seconds, not minutes" trade the gate signed up for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.select_reverse_import_tests import ROOT, _imported_names, select_tests


def _tree(tmp_path: Path, test_body: str) -> Path:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe.py").write_text(test_body, encoding="utf-8")
    return tests_dir


def test_the_regression_that_motivated_this_is_selected() -> None:
    """#4752's changed module must select the test that would have caught it."""
    selected = select_tests(
        ["services/live_overlay_daemon/hold_manager_shadow_receiver.py"]
    )
    assert "tests/test_hold_manager_receiver_off_event_loop.py" in selected, (
        "changing the receiver no longer selects the off-event-loop probe -- "
        "this is exactly how #4752 reached main red"
    )
    assert "tests/test_hold_manager_shadow_receiver.py" in selected


def test_the_from_import_form_counts(tmp_path: Path) -> None:
    """The #4752 test binds the module via ``from A import B``; a selector
    that only reads ``import A.B`` re-opens the class with all pins green."""
    tests_dir = _tree(tmp_path, "from pkg.sub import mod\n")
    assert select_tests(["pkg/sub/mod.py"], tests_dir=tests_dir) == [
        "tests/test_probe.py"
    ]


def test_the_plain_import_form_counts(tmp_path: Path) -> None:
    tests_dir = _tree(tmp_path, "import pkg.sub.mod\n")
    assert select_tests(["pkg/sub/mod.py"], tests_dir=tests_dir) == [
        "tests/test_probe.py"
    ]


def test_a_changed_package_init_selects_importers_of_its_children(
    tmp_path: Path,
) -> None:
    tests_dir = _tree(tmp_path, "from pkg.sub import mod\n")
    assert select_tests(["pkg/sub/__init__.py"], tests_dir=tests_dir) == [
        "tests/test_probe.py"
    ]


def test_a_similarly_named_module_does_not_match(tmp_path: Path) -> None:
    tests_dir = _tree(tmp_path, "from pkg.sub import mod_extra\n")
    assert select_tests(["pkg/sub/mod.py"], tests_dir=tests_dir) == []


def test_a_changed_test_file_selects_nothing(tmp_path: Path) -> None:
    """A changed test runs because the suite runs it; importing it would be
    self-selection noise."""
    tests_dir = _tree(tmp_path, "import tests.test_other\n")
    assert select_tests(["tests/test_other.py"], tests_dir=tests_dir) == []


def test_non_python_changes_select_nothing(tmp_path: Path) -> None:
    tests_dir = _tree(tmp_path, "from pkg.sub import mod\n")
    changed = [".github/workflows/ci.yml", "SMC_Long_Dip_Suite.pine", "pkg/sub/mod.md"]
    assert select_tests(changed, tests_dir=tests_dir) == []


def test_a_deleted_module_still_selects_its_importers(tmp_path: Path) -> None:
    """The importers die with ImportError at the PR -- which is precisely the
    signal a removal with leftover consumers deserves. Existence on disk must
    therefore not gate the selection."""
    tests_dir = _tree(tmp_path, "from pkg.sub import mod\n")
    assert not (tmp_path / "pkg").exists()
    assert select_tests(["pkg/sub/mod.py"], tests_dir=tests_dir) == [
        "tests/test_probe.py"
    ]


def test_an_unparseable_test_file_is_loud_not_invisible(tmp_path: Path) -> None:
    """"Could not read the imports" recorded as "imports nothing" is the
    2026-08-15/16 sweep class; the selector must raise instead."""
    tests_dir = _tree(tmp_path, "def broken(:\n")
    with pytest.raises(SyntaxError):
        select_tests(["pkg/sub/mod.py"], tests_dir=tests_dir)


def test_the_gate_actually_runs_the_selection() -> None:
    """A selector nothing calls is a library, not a gate (same pin shape as
    test_select_workflow_guards.py, which paid for it in run 30697585385)."""
    gates = (ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m scripts.select_reverse_import_tests" in gates
    assert "python -m pytest ${selected} -q --no-header" in gates

    install = gates.index("- name: Install dependencies")
    step = gates.index(
        "- name: Run every test that imports a production module this PR changed"
    )
    assert install < step, "the stage runs pytest, so it must follow the install"

    # The stage must not mask its second failure: the selection is small by
    # the cost-model pin below, so the INVOCATION runs without --maxfail.
    # (Checked on the pytest line, not the step text -- the step's own comment
    # names the flag while banning it, and a text-wide search read that
    # mention as a violation on the first run of this very test.)
    body = gates[step : gates.index("- name: ", step + 1)]
    pytest_lines = [
        line for line in body.splitlines() if "python -m pytest ${selected}" in line
    ]
    assert pytest_lines, "the stage's pytest invocation vanished from its step"
    assert all("--maxfail" not in line for line in pytest_lines), (
        "--maxfail on the reverse-import stage masks every failure after the "
        "first -- the known trap this stage exists to close"
    )


def test_the_cost_model_holds_for_every_production_module() -> None:
    """No module's reverse-import fan-in may silently outgrow the gate budget.

    Measured 2026-08-16 over the real tree: the most-imported production
    module (open_prep.realtime_signals) is imported by 26 test files; the
    historical per-PR selection over the last 60 merged PRs was 0 for 55 of
    them, median 5 and max 12 for the rest. The bound below is generous
    headroom over that, not a target: if a module legitimately accretes more
    than 100 direct test importers, re-measure the stage's runtime on a PR
    that changes it and raise this bound as a deliberate decision, with the
    new measurement in the commit message.
    """
    fan_in: dict[str, int] = {}
    for test_file in sorted((ROOT / "tests").glob("test_*.py")):
        for name in _imported_names(test_file):
            if name.startswith("tests"):
                continue
            if (ROOT / (name.replace(".", "/") + ".py")).exists():
                fan_in[name] = fan_in.get(name, 0) + 1

    assert fan_in, "the fan-in scan collected nothing -- the scan itself broke"
    worst = max(fan_in, key=fan_in.get)  # type: ignore[arg-type]
    assert fan_in[worst] <= 100, (
        f"{worst} is imported by {fan_in[worst]} test files; the reverse-import "
        "stage's cost model (seconds, not minutes) no longer holds -- re-measure "
        "before raising this bound"
    )

def test_the_stage_carries_no_marker_filter() -> None:
    """ADR-0012 Phase 2 would gut this stage -- 23 of 25 selected tests vanish.

    The stage exists to reach BEYOND the curated fast inventory: it runs every
    test that imports a production module the PR changed. Measured 2026-08-20
    for a one-file change to ``services/live_overlay_daemon/compute.py``: the
    selector returns 25 test files, of which only **2** are in
    ``FAST_TEST_FILES``. The root conftest auto-marks the other 23 ``slow``
    (1439 of 1696 test files repo-wide are auto-slow), so a marker filter on
    this invocation would silently reduce the stage to 2 files.

    That loss is not caught anywhere: ``ci.yml`` is status-only on ALL pull
    requests (its gate exits ``run_heavy=false`` for every ``pull_request``
    event, bot or not), so the full suite is a MAIN-PUSH backstop, not a PR
    one. The 23 would first run after the merge.

    ADR-0012 Phase 2 proposes replacing the enumerated file list in
    smc-fast-pr-gates.yml with a marker selection. That is coherent only
    together with the other half of the ADR -- promoting ``validate`` to a
    required check (Operator-Punkt 1). Wiring the fast half alone moves 85%
    of the corpus off the required path. This test is the tripwire for that
    half-step; it is not an objection to Phase 2.

    Checked on the INVOCATION line only, not the step text -- this docstring
    names the flag it forbids, and a text-wide search would read that as the
    violation (the trap the --maxfail pin above already paid for).
    """
    gates = (ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml").read_text(
        encoding="utf-8"
    )
    step = gates.index(
        "- name: Run every test that imports a production module this PR changed"
    )
    body = gates[step : gates.index("- name: ", step + 1)]
    pytest_lines = [
        line for line in body.splitlines() if "python -m pytest ${selected}" in line
    ]
    assert pytest_lines, "the stage's pytest invocation vanished from its step"
    for line in pytest_lines:
        # NUR den Teil hinter `pytest` pruefen: `python -m pytest` traegt selbst
        # ein ` -m `, das ist Pythons Modul-Flag und nicht pytests Marker-Filter.
        # (Die erste Fassung dieses Tests schlug genau daran an.)
        args = line.split("pytest", 1)[1]
        assert " -m " not in args, (
            "marker filter on the reverse-import stage: it would cut the "
            "selection to the fast inventory (measured 2 of 25 for a "
            "compute.py change) and the rest would first run post-merge, "
            "because ci.yml is status-only on every pull request. If this is "
            "ADR-0012 Phase 2, land the required-check half with it.\n"
            f"  offending line: {line.strip()}"
        )
