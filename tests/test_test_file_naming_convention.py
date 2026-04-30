"""Pin: every ``tests/test_*.py`` file must define at least one
``def test_*`` callable.

A ``tests/test_*.py`` file with no actual test functions is dead test
code: it does not contribute coverage, runs no assertions, and silently
hides intent (was the test deleted? did someone forget to add it?).
This pin is a one-line tripwire that catches the failure mode at
authoring time.

Scope: only top-level ``tests/`` (not ``conftest.py``,
``__init__.py``, helpers without ``test_`` prefix, or fixtures).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = REPO_ROOT / "tests"

# Allowlist: test files that intentionally use module-level assertions
# instead of `def test_*` (legacy smoke scripts run directly, not via
# pytest discovery). New entries should be rare and justified.
_MODULE_LEVEL_ASSERT_ALLOWLIST: frozenset[str] = frozenset({
    # Module-level smoke assertions; runs as a standalone script
    # (`python tests/test_smoke_v2_features.py`), not via pytest discovery.
    "tests/test_smoke_v2_features.py",
})


def _candidate_files() -> list[Path]:
    return sorted(
        p
        for p in TESTS_DIR.rglob("test_*.py")
        if p.is_file() and "__pycache__" not in p.parts
    )


def _has_test_function(text: str) -> bool:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                return True
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if (
                    isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and sub.name.startswith("test_")
                ):
                    return True
    return False


def test_tests_directory_is_present() -> None:
    assert TESTS_DIR.is_dir(), f"Expected {TESTS_DIR} to exist."


def test_every_test_file_defines_at_least_one_test() -> None:
    empty: list[str] = []
    for path in _candidate_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in _MODULE_LEVEL_ASSERT_ALLOWLIST:
            continue
        text = path.read_text(encoding="utf-8")
        if not _has_test_function(text):
            empty.append(rel)
    assert not empty, (
        "Test file(s) with no `def test_*` function "
        "(dead test code — fail-author-time tripwire):\n"
        + "\n".join(f"  {p}" for p in empty)
        + "\nEither add a real test, rename the file (drop the "
        "``test_`` prefix if it's a helper), delete the file, or — "
        "only if module-level smoke asserts are intentional — add to "
        "_MODULE_LEVEL_ASSERT_ALLOWLIST in this pin with justification."
    )


def test_module_level_assert_allowlist_entries_exist() -> None:
    """Catch allowlist rot: every allowlisted file must still exist."""
    missing = sorted(
        rel for rel in _MODULE_LEVEL_ASSERT_ALLOWLIST
        if not (REPO_ROOT / rel).is_file()
    )
    assert not missing, (
        f"Stale entries in _MODULE_LEVEL_ASSERT_ALLOWLIST "
        f"(file deleted or renamed): {missing}. Remove from the allowlist."
    )
