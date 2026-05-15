"""Guard: scripts that compare ``Path.relative_to()`` results must use ``.as_posix()``.

Root cause that prompted this guard: ``scripts/check_layer_violations.py``
used ``str(py_file.relative_to(SMC_INTEGRATION))`` to build a path string
and then compared it against a set of forward-slash strings.  On Windows,
``str(Path)`` returns backslashes, so the comparison always fails, causing
every known violation to appear as a *new* violation and blocking the CI gate.

**Required pattern**::

    rel = py_file.relative_to(ROOT).as_posix()   # always forward slashes

**Forbidden pattern**::

    rel = str(py_file.relative_to(ROOT))          # backslashes on Windows

This test scans every ``scripts/*.py`` file and flags any occurrence of
``str(...)`` wrapping a ``.relative_to(`` call that is NOT immediately
followed by ``.as_posix()`` or ``.replace``.  The check is intentionally
conservative — it only inspects ``scripts/`` because that is where CI guard
scripts live; first-party modules and tests use ``str(Path)`` legitimately
for display/logging purposes and are excluded.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def _str_relative_to_sites(py_file: Path) -> list[tuple[str, int]]:
    """Return (relpath, lineno) for every ``str(expr.relative_to(...))``
    call that does NOT chain ``.as_posix()`` — i.e. the raw ``str()``
    wrapper that produces backslashes on Windows.

    Detects the pattern::

        str(some_path.relative_to(base))

    but NOT::

        some_path.relative_to(base).as_posix()
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []

    rel = py_file.relative_to(ROOT).as_posix()
    violations: list[tuple[str, int]] = []

    for node in ast.walk(tree):
        # We're looking for: Call(func=Name('str'), args=[Call(func=Attribute(attr='relative_to'), ...)])
        if not isinstance(node, ast.Call):
            continue
        # Outer call must be str(...)
        if not (isinstance(node.func, ast.Name) and node.func.id == "str"):
            continue
        if len(node.args) != 1:
            continue
        inner = node.args[0]
        # Inner must be a call whose func is an Attribute
        if not isinstance(inner, ast.Call):
            continue
        if not isinstance(inner.func, ast.Attribute):
            continue
        if inner.func.attr != "relative_to":
            continue
        # This is str(something.relative_to(...)) — flag it
        violations.append((rel, node.lineno))

    return violations


def test_scripts_use_as_posix_not_str_for_relative_paths() -> None:
    """Every ``scripts/*.py`` file that calls ``path.relative_to(...)`` must
    chain ``.as_posix()`` rather than wrap in ``str()`` to avoid producing
    backslash paths on Windows that break set/dict comparisons against
    hard-coded forward-slash strings.
    """
    violations: list[tuple[str, int]] = []
    for py_file in sorted(SCRIPTS_DIR.glob("*.py")):
        violations.extend(_str_relative_to_sites(py_file))

    assert not violations, (
        "``str(path.relative_to(...))`` detected in scripts/.  "
        "Use ``path.relative_to(...).as_posix()`` instead — "
        "``str(Path)`` returns backslashes on Windows, which breaks "
        "comparisons against forward-slash strings in sets/dicts.\n\n"
        "Violations:\n"
        + "\n".join(f"  {rel}:{line}" for rel, line in sorted(violations))
    )
