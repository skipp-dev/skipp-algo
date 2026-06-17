#!/usr/bin/env python3
"""check_branch_safety.py — pre-commit guard against direct commits to main/master.

Prints the current branch prominently on every commit so the committer
(human or agent) always sees which branch is active.  Exits 1 and blocks
the commit when the branch is main or master.

Rationale: shared-checkout branch-race failures (skipp-algo, 2026-06-11/16)
occurred because another session switched branches between an edit and the
commit.  A visible, machine-enforced check closes this gap.

Replaced check_branch_safety.sh (bash) which has been removed from the repo
because bash is not portable to
Windows self-hosted runners (Copilot review #2799).
"""

from __future__ import annotations

import subprocess
import sys


def _current_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return ""


def main() -> int:
    branch = _current_branch()
    label = branch or "(detached HEAD)"

    print()
    print("  ┌─────────────────────────────────────────────┐")
    print(f"  │  BRANCH CHECK: currently on → {label:<13s}│")
    print("  └─────────────────────────────────────────────┘")
    print()

    if branch in ("main", "master"):
        print(f"  ✗ ERROR: direct commit to '{branch}' is blocked.")
        print("    Check out a feature/fix branch first.")
        print("    e.g.:  git checkout -b feat/my-change")
        print()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
