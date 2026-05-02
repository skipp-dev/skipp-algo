"""Drift check between root ``*.pine`` files and ``PINE_LEGACY.md``.

Closes the **D-1 v2 follow-up** from
``docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md``.

Background
----------
A physical ``git mv`` of legacy Pine files into ``pine/legacy/`` was
deferred (TradingView-saved-script URLs would break). Instead, the
`PINE_LEGACY.md` index at the repo root classifies every root-level
``*.pine`` file as ``LEGACY`` / active / test fixture.

The risk that index falls out of sync is real: when a contributor adds a
new ``*.pine`` at the root, nothing today forces them to update
`PINE_LEGACY.md`. This script closes that gap by enforcing:

1. **Every root-level ``*.pine`` file is mentioned in PINE_LEGACY.md.**
2. **Every file mentioned in PINE_LEGACY.md exists at the root.**

It exits non-zero when either invariant is violated and prints the diff.
Designed to be wired into ``smc-fast-pr-gates`` as a sub-second step.

**D-1 v2 extension** (ADR-0003): LEGACY files now physically live under
``pine/legacy/``. The lint scans **both** the repo root and
``pine/legacy/`` and additionally fails when a basename appears in both
locations (collision — the resolver shim cannot disambiguate).
"""

from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import os
import re
import sys
from pathlib import Path

# Allow direct script invocation (``python scripts/check_pine_legacy_drift.py``)
# in addition to module form. ``smc-fast-pr-gates`` runs this script
# directly, so the repo root must be on ``sys.path`` before the
# ``scripts.pine_path_resolver`` import below resolves.
_REPO_ROOT_FOR_BOOTSTRAP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT_FOR_BOOTSTRAP not in sys.path:
    sys.path.insert(0, _REPO_ROOT_FOR_BOOTSTRAP)

from scripts.pine_path_resolver import PINE_LEGACY_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = REPO_ROOT / "PINE_LEGACY.md"


def list_root_pine_files(root: Path) -> set[str]:
    """Return basenames of all root-level ``*.pine`` files."""
    return {p.name for p in root.glob("*.pine") if p.is_file()}


def list_legacy_pine_files(legacy_dir: Path) -> set[str]:
    """Return basenames of all ``pine/legacy/*.pine`` files."""
    if not legacy_dir.is_dir():
        return set()
    return {p.name for p in legacy_dir.glob("*.pine") if p.is_file()}


def find_basename_collisions(root: Path, legacy_dir: Path) -> set[str]:
    """Return basenames present in BOTH root and ``pine/legacy/``."""
    return list_root_pine_files(root) & list_legacy_pine_files(legacy_dir)


def parse_index_file_names(index_path: Path) -> set[str]:
    """Extract every ``<name>.pine`` token mentioned in an index table row.

    Only Markdown table rows (``| ``...`` |``) count; prose mentions and
    historical notes are intentionally excluded so the lint cannot be
    fooled by descriptive backticks. The leading column of each row is
    expected to wrap the filename in backticks.
    """
    if not index_path.is_file():
        raise FileNotFoundError(f"PINE_LEGACY.md not found at {index_path}")
    text = index_path.read_text(encoding="utf-8")
    names: set[str] = set()
    row_pattern = re.compile(r"^\s*\|\s*`([^`]+\.pine)`")
    for line in text.splitlines():
        match = row_pattern.match(line)
        if match:
            name = match.group(1)
            # Skip nested paths and glob patterns just in case.
            if "/" in name or "*" in name:
                continue
            names.add(name)
    return names


def main(argv: list[str] | None = None) -> int:
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root (default: derived from script location).",
    )
    parser.add_argument(
        "--index",
        type=Path,
        default=INDEX_FILE,
        help="Path to PINE_LEGACY.md (default: <root>/PINE_LEGACY.md).",
    )
    parser.add_argument(
        "--legacy-dir",
        type=Path,
        default=None,
        help="Path to pine/legacy/ (default: <root>/pine/legacy/).",
    )
    args = parser.parse_args(argv)

    if args.legacy_dir is not None:
        legacy_dir = args.legacy_dir
    elif args.root == PINE_LEGACY_DIR.parent.parent:
        # Default repo layout — use the canonical constant so the
        # location stays single-sourced (H-8).
        legacy_dir = PINE_LEGACY_DIR
    else:
        # Test/alternate roots: derive from the supplied --root so the
        # CLI remains relocatable.
        legacy_dir = args.root / "pine" / "legacy"
    root_files = list_root_pine_files(args.root)
    legacy_files = list_legacy_pine_files(legacy_dir)
    actual = root_files | legacy_files
    indexed = parse_index_file_names(args.index)

    missing_from_index = sorted(actual - indexed)
    stale_in_index = sorted(indexed - actual)
    collisions = sorted(root_files & legacy_files)

    if not missing_from_index and not stale_in_index and not collisions:
        print(
            f"OK: PINE_LEGACY.md is in sync "
            f"({len(root_files)} root + {len(legacy_files)} pine/legacy *.pine files)."
        )
        return 0

    print("FAIL: PINE_LEGACY.md / pine-tree are out of sync.")
    if missing_from_index:
        print()
        print("Missing from PINE_LEGACY.md (add as LEGACY or active):")
        for name in missing_from_index:
            print(f"  + {name}")
    if stale_in_index:
        print()
        print("Stale entries in PINE_LEGACY.md (file no longer present):")
        for name in stale_in_index:
            print(f"  - {name}")
    if collisions:
        print()
        print(
            "Basename collisions (same name in repo root AND pine/legacy/ — "
            "resolver cannot disambiguate):"
        )
        for name in collisions:
            print(f"  ! {name}")
    print()
    print("Update PINE_LEGACY.md or move/rename the file accordingly.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
