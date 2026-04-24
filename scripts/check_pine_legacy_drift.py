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
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_FILE = REPO_ROOT / "PINE_LEGACY.md"


def list_root_pine_files(root: Path) -> set[str]:
    """Return the basenames of all root-level ``*.pine`` files."""
    return {p.name for p in root.glob("*.pine") if p.is_file()}


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
    args = parser.parse_args(argv)

    actual = list_root_pine_files(args.root)
    indexed = parse_index_file_names(args.index)

    missing_from_index = sorted(actual - indexed)
    stale_in_index = sorted(indexed - actual)

    if not missing_from_index and not stale_in_index:
        print(f"OK: PINE_LEGACY.md is in sync ({len(actual)} root *.pine files).")
        return 0

    print("FAIL: PINE_LEGACY.md is out of sync with root *.pine files.")
    if missing_from_index:
        print()
        print("Missing from PINE_LEGACY.md (add these as LEGACY or active):")
        for name in missing_from_index:
            print(f"  + {name}")
    if stale_in_index:
        print()
        print("Stale entries in PINE_LEGACY.md (file no longer at root):")
        for name in stale_in_index:
            print(f"  - {name}")
    print()
    print("Update PINE_LEGACY.md or move/rename the file accordingly.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
