#!/usr/bin/env python3
"""check_branch_safety.py — pre-commit guard against direct commits to main/master.

Prints the current branch prominently on every commit so the committer
(human or agent) always sees which branch is active.  Exits 1 and blocks
the commit when the branch is main or master.

Rationale: shared-checkout branch-race failures (skipp-algo, 2026-06-11/16)
occurred because another session switched branches between an edit and the
commit.  A visible, machine-enforced check closes this gap.

Replaced check_branch_safety.sh (bash) because bash is not portable to
Windows self-hosted runners (Copilot review #2799).
"""

from __future__ import annotations

import subprocess
import sys


def _branch_state() -> tuple[str, str | None, int | None, int | None]:
    """Return ``(branch, upstream, ahead, behind)`` from git porcelain output.

    ``ahead`` / ``behind`` are ``None`` when no upstream relation is available
    (detached HEAD, unborn branch, or repository without remote tracking).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=2", "--branch"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        branch = ""
        upstream: str | None = None
        ahead: int | None = None
        behind: int | None = None
        for raw in result.stdout.splitlines():
            if raw.startswith("# branch.head "):
                branch = raw.removeprefix("# branch.head ").strip()
            elif raw.startswith("# branch.upstream "):
                upstream = raw.removeprefix("# branch.upstream ").strip() or None
            elif raw.startswith("# branch.ab "):
                parts = raw.split()
                if len(parts) >= 4:
                    try:
                        ahead = int(parts[2].removeprefix("+"))
                        behind = int(parts[3].removeprefix("-"))
                    except ValueError:
                        ahead = None
                        behind = None
        return branch, upstream, ahead, behind
    except (subprocess.CalledProcessError, OSError):
        return "", None, None, None


def main() -> int:
    branch, upstream, ahead, behind = _branch_state()
    label = branch or "(detached HEAD)"

    print()
    print("  +---------------------------------------------+")
    print(f"  |  BRANCH CHECK: currently on -> {label:<13s}|")
    print("  +---------------------------------------------+")
    print()

    if branch in ("main", "master"):
        print(f"  ERROR: direct commit to '{branch}' is blocked.")
        print("    Check out a feature/fix branch first.")
        print("    e.g.:  git checkout -b feat/my-change")
        print()
        return 1

    if upstream and ahead is not None and behind is not None and (ahead > 0 or behind > 0):
        if ahead > 0 and behind > 0:
            state = "DIVERGED"
        elif behind > 0:
            state = "BEHIND"
        else:
            state = "AHEAD"
        print(f"  Branch lifecycle observation: {state} vs upstream '{upstream}' (ahead={ahead}, behind={behind})")
        print("  Advice: sync branch proactively before PR merge/housekeeping to avoid drift loops.")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
