"""Positive controls for the guard subprocess budget.

Every branch below is exercised against a real subprocess, because the module
exists to change what a reader sees at 2 a.m. and a mocked timeout would not
prove that the message survives the path it actually takes.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from tests import _subprocess_budget as budget


def test_a_fast_command_returns_normally():
    result = budget.run_within_budget(
        [sys.executable, "-c", "print('ok')"],
        what="a trivial probe",
        default_budget_s=30,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_an_overrun_fails_with_the_class_named_not_a_raw_timeout():
    with pytest.raises(AssertionError) as raised:
        budget.run_within_budget(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            what="a deliberately hanging probe",
            default_budget_s=5,
            capture_output=True,
        )
    message = str(raised.value)
    assert "WALL-CLOCK BUDGET EXCEEDED" in message
    assert "a deliberately hanging probe" in message
    assert "re-run THIS test alone" in message
    assert budget.BUDGET_ENV in message


def test_an_overrun_is_not_a_bare_timeout_expired():
    """The whole point: the reader must not meet ``TimeoutExpired`` raw."""
    with pytest.raises(AssertionError):
        budget.run_within_budget(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            what="probe",
            default_budget_s=5,
            capture_output=True,
        )
    # And the original is not chained in, so pytest shows the diagnosis, not
    # a traceback ending in someone else's exception class.
    try:
        budget.run_within_budget(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            what="probe",
            default_budget_s=5,
            capture_output=True,
        )
    except AssertionError as exc:
        assert exc.__cause__ is None
        assert not isinstance(exc, subprocess.TimeoutExpired)


def test_the_environment_can_raise_the_budget(monkeypatch):
    monkeypatch.setenv(budget.BUDGET_ENV, "123")
    assert budget.budget_seconds(60) == 123.0


def test_an_unset_environment_keeps_the_call_sites_default(monkeypatch):
    monkeypatch.delenv(budget.BUDGET_ENV, raising=False)
    assert budget.budget_seconds(60) == 60.0
    assert budget.budget_seconds(90) == 90.0


@pytest.mark.parametrize("bad", ["", "  "])
def test_a_blank_override_is_treated_as_unset(monkeypatch, bad):
    monkeypatch.setenv(budget.BUDGET_ENV, bad)
    assert budget.budget_seconds(60) == 60.0


def test_a_nonsense_override_is_refused_not_ignored(monkeypatch):
    monkeypatch.setenv(budget.BUDGET_ENV, "soon")
    with pytest.raises(AssertionError, match="not a number of seconds"):
        budget.budget_seconds(60)


def test_an_override_below_the_floor_is_refused(monkeypatch):
    """A typo must not disable the hang detection it looks like it configures."""
    monkeypatch.setenv(budget.BUDGET_ENV, "0.1")
    with pytest.raises(AssertionError, match="floor"):
        budget.budget_seconds(60)


# ---------------------------------------------------------------------------
# Wiring. The helper is only worth anything if the three call sites that
# produced the 2026-08-29 flakes actually route through it; a later refactor
# back to a bare `timeout=` literal would restore the unreadable failure
# without turning anything red.
# ---------------------------------------------------------------------------

_CALL_SITES = {
    "tests/_workflow_step_shell.py": "run_within_budget",
    "tests/test_import_safety.py": "run_within_budget",
    "tests/test_workflow_invoked_scripts_importable.py": "budget_seconds",
}


def test_the_guard_subprocess_call_sites_route_through_the_budget():
    """Each call site must CALL the helper, not merely import it.

    First written as a substring check, which a mutation proof immediately
    defeated: replacing the call with ``subprocess.run`` left the import line
    behind, so the name was still "in" the file and the test stayed green.
    """
    import ast

    from tests._guard_corpus import repo_root

    root = repo_root()
    checked = 0
    for relative, expected_symbol in sorted(_CALL_SITES.items()):
        path = root / relative
        assert path.is_file(), f"call site vanished: {relative}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert expected_symbol in called, (
            f"{relative} does not CALL {expected_symbol}; a bare subprocess "
            "timeout there fails as an unreadable TimeoutExpired again"
        )
        checked += 1
    assert checked == len(_CALL_SITES), "not every call site was inspected"


def test_no_guard_call_site_passes_a_bare_timeout_literal():
    """`timeout=<number>` handed straight to subprocess is the pattern this replaces."""
    import re

    from tests._guard_corpus import repo_root

    root = repo_root()
    offenders = []
    for relative in sorted(_CALL_SITES):
        source = (root / relative).read_text(encoding="utf-8")
        # `timeout=probe_budget` and `default_budget_s=60` are fine; a literal
        # `timeout=90` is the shape that skips the diagnosis.
        for match in re.finditer(r"\btimeout=(\d+(?:\.\d+)?)\b", source):
            offenders.append(f"{relative}: timeout={match.group(1)}")
    assert not offenders, (
        "bare wall-clock literals back in the guard subprocess call sites: "
        f"{offenders}"
    )
