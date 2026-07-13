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

Both the file list (``RUNTIME_FILES``) and the banned roots (``BANNED_ROOTS``)
are the shared, pure-stdlib SSOT in ``scripts/adr_0005_runtime_manifest.py``,
loaded here by path — so this CLI (and the pre-commit hook) runs in a stdlib-only
interpreter and never imports pytest.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = REPO_ROOT / "scripts" / "adr_0005_runtime_manifest.py"


def _load_manifest() -> object:
    """Load the pure-stdlib ADR-0005 SSOT manifest by path (no pytest, no package)."""
    spec = importlib.util.spec_from_file_location("_adr_0005_manifest", MANIFEST_FILE)
    if spec is None or spec.loader is None:  # pragma: no cover — defensive
        raise RuntimeError(f"Cannot load {MANIFEST_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_file(path: Path, banned: frozenset[str], imported_roots) -> set[str]:
    source = path.read_text(encoding="utf-8")
    return imported_roots(source) & banned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="*",
        help=(
            "Optional file paths to check. When omitted, scans the "
            "RUNTIME_FILES list defined by scripts/adr_0005_runtime_manifest.py."
        ),
    )
    args = parser.parse_args(argv)

    manifest = _load_manifest()
    runtime_files: tuple[Path, ...] = manifest.RUNTIME_FILES  # type: ignore[attr-defined]
    banned: frozenset[str] = manifest.BANNED_ROOTS  # type: ignore[attr-defined]
    imported_roots = manifest.imported_roots  # type: ignore[attr-defined]

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
        bad = _check_file(path, banned, imported_roots)
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
            "scripts/adr_0005_runtime_manifest.py.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
