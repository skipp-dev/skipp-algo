#!/usr/bin/env bash
# check_branch_safety.sh — pre-commit guard against direct commits to main/master.
#
# Prints the current branch prominently on every commit so the committer
# (human or agent) always sees which branch is active.  Exits 1 and blocks
# the commit when the branch is main or master.
#
# Rationale: shared-checkout branch-race failures (skipp-algo, 2026-06-11/16)
# occurred because another session switched branches between an edit and the
# commit.  A visible, machine-enforced check closes this gap.

set -euo pipefail

branch=$(git branch --show-current)

echo ""
echo "  ┌─────────────────────────────────────────────┐"
printf "  │  BRANCH CHECK: currently on → %-13s│\n" "$branch"
echo "  └─────────────────────────────────────────────┘"
echo ""

if [[ "$branch" == "main" || "$branch" == "master" ]]; then
    echo "  ✗ ERROR: direct commit to '$branch' is blocked."
    echo "    Check out a feature/fix branch first."
    echo "    e.g.:  git checkout -b feat/my-change"
    echo ""
    exit 1
fi
