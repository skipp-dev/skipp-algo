#!/usr/bin/env python3
"""Select the tests that import a production module a pull request changed.

2026-08-16: #4752 removed the Hold-Manager legacy route. Its fast-gates run
was green -- the gate's pytest lists are fixed smoke sets, and CI on pull
requests is status-only by design (ci.yml gate step, documented 2026-08-04).
So nothing before the merge ran ``tests/test_hold_manager_receiver_off_event_
loop.py``, which imports the changed module directly and fails
deterministically on that tree. The full suite met the regression for the
first time on the main push: two red main runs, a cross-session misdiagnosis
("env-local"), and a repair PR (#4755).

This selector closes that CLASS the same way select_workflow_guards.py closes
the workflow-guard class: scope it to the diff. A PR that changes no
production module selects nothing; a PR that changes one runs every test file
whose import statements name it, whether or not any roster remembered it.

What "imports" means here -- static, from the AST, both forms:

1. ``import services.live_overlay_daemon.hold_manager_shadow_receiver``
2. ``from services.live_overlay_daemon import hold_manager_shadow_receiver``
   -- which is why every ``from A import B`` contributes BOTH ``A`` and
   ``A.B``: B may be a module, and the test that binds it this way is
   exactly the one that must run (measured: the #4752 test uses this form).

Deliberate boundaries, stated so nobody reads this as full coverage:

* Direct imports only. A test reaching the changed module through a chain of
  intermediate imports is not selected -- the transitive closure over a
  ~25k-test suite is the full suite by another name, and the main-push CI
  remains the designed backstop for it (ci.yml keeps that decision).
* Static imports only. ``importlib``/``__import__`` with computed strings and
  monkeypatching by dotted string are invisible to the AST.
* A DELETED production module still selects its importers on purpose: they
  die with ImportError at the PR, which is precisely the signal a removal
  with leftover consumers deserves.

Over-selection is deliberate on the cheap side, same doctrine as the
workflow-guard selector: ``from A import B`` where B is a function selects on
a change to a same-named module path that does not exist; that costs seconds.
Under-selection costs a red main after the merge.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def _changed_modules(changed: list[str]) -> tuple[set[str], set[str]]:
    """Dotted names of changed production modules, packages listed separately.

    ``tests/`` is excluded -- a changed test runs because the suite runs it,
    not because something imports it. Everything else that is importable
    counts; a ``.py`` nobody imports simply selects nothing.
    """
    modules: set[str] = set()
    packages: set[str] = set()
    for raw in changed:
        path = Path(raw)
        if path.suffix != ".py" or raw.startswith("tests/"):
            continue
        if path.name == "__init__.py":
            packages.add(".".join(path.parent.parts))
        else:
            modules.add(".".join(path.with_suffix("").parts))
    modules.discard("")
    packages.discard("")
    return modules, packages


def _imported_names(test_file: Path) -> set[str]:
    """Every dotted name a test file's import statements bind.

    A file that does not parse raises: an unparseable test is a broken guard,
    and "could not read the imports" must never be recorded as "imports
    nothing" (the 2026-08-15/16 sweep class).
    """
    tree = ast.parse(test_file.read_text(encoding="utf-8"), filename=str(test_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level or node.module is None:
                continue  # relative imports cannot name a repo-root module
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
    return names


def select_tests(changed: list[str], tests_dir: Path | None = None) -> list[str]:
    """Test files importing any changed module, as repo-relative POSIX paths."""
    tests_dir = TESTS if tests_dir is None else tests_dir
    modules, packages = _changed_modules(changed)
    if not modules and not packages:
        return []

    selected: set[Path] = set()
    for candidate in sorted(tests_dir.glob("test_*.py")):
        imported = _imported_names(candidate)
        if imported & modules:
            selected.add(candidate)
            continue
        for package in packages:
            prefix = package + "."
            if any(name == package or name.startswith(prefix) for name in imported):
                selected.add(candidate)
                break

    root = tests_dir.resolve().parent
    # as_posix() for the same reason select_workflow_guards.py uses it: the
    # result is handed to pytest and compared against forward-slash literals.
    return sorted(path.resolve().relative_to(root).as_posix() for path in selected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("changed", nargs="*", help="paths changed by the pull request")
    args = parser.parse_args()

    tests = select_tests(args.changed)
    if not tests:
        print("no reverse-import tests selected", file=sys.stderr)
        return 0
    print("\n".join(tests))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
