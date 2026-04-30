#!/usr/bin/env python3
"""ADR-0005 enforcement: pure-stdlib measurement runtime (CLI wrapper).

Standalone CLI front-end for the same AST scan that runs in
``tests/test_adr_0005_pure_stdlib_runtime.py``. Lets contributors
catch ADR-0005 violations locally **before** pushing, without
spinning up the full test suite, and lets the pre-commit hook
fail-fast on the same logic.

Exit codes:
* 0 — all measurement-runtime files are pure stdlib.
* 1 — at least one banned import detected (printed with file + module).
* 2 — a measurement-runtime file is missing.

Both the file list (``RUNTIME_FILES``) and the banned roots
(``BANNED_ROOTS``) are kept in sync with the test fixture by
re-importing them from the test module — single source of truth.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_FILE = REPO_ROOT / "tests" / "test_adr_0005_pure_stdlib_runtime.py"


def _load_test_module() -> object:
    """Load the test module without invoking pytest."""
    spec = importlib.util.spec_from_file_location(
        "_adr_0005_test", TEST_FILE
    )
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"Cannot load {TEST_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_imported_roots(source: str) -> set[str]:
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _check_file(path: Path, banned: frozenset[str]) -> set[str]:
    source = path.read_text(encoding="utf-8")
    return _collect_imported_roots(source) & banned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "Optional file paths to check. When omitted, scans the "
            "RUNTIME_FILES list defined by tests/test_adr_0005_pure_stdlib_runtime.py."
        ),
    )
    args = parser.parse_args(argv)

    test_module = _load_test_module()
    runtime_files: tuple[Path, ...] = test_module.RUNTIME_FILES  # type: ignore[attr-defined]
    banned: frozenset[str] = test_module.BANNED_ROOTS  # type: ignore[attr-defined]

    if args.files:
        # Pre-commit passes changed file paths; intersect with runtime set.
        candidates = []
        runtime_set = {p.resolve() for p in runtime_files}
        for raw in args.files:
            resolved = Path(raw).resolve()
            if resolved in runtime_set:
                candidates.append(resolved)
        if not candidates:
            return 0  # No measurement-runtime file in the change set.
    else:
        candidates = list(runtime_files)

    violations: list[tuple[Path, set[str]]] = []
    for path in candidates:
        if not path.is_file():
            print(
                f"ADR-0005: measurement-runtime file missing: {path}",
                file=sys.stderr,
            )
            return 2
        bad = _check_file(path, banned)
        if bad:
            violations.append((path, bad))

    if violations:
        print("ADR-0005 violations (pure-stdlib measurement runtime):", file=sys.stderr)
        for path, bad in violations:
            rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
            print(f"  - {rel}: banned imports {sorted(bad)}", file=sys.stderr)
        print(
            "\nIf the constraint is intentionally lifted, supersede ADR-0005 "
            "and update RUNTIME_FILES or BANNED_ROOTS in "
            "tests/test_adr_0005_pure_stdlib_runtime.py.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
