#!/usr/bin/env python3
"""Fail on non-approved commit author/committer identities (audit P2 MED).

The repo's single-maintainer authorship mandate (see ``.mailmap``) previously
had no automated enforcement: a clone carrying a corporate git config (e.g. the
Cisco EMU ``spreuss_cisco`` identity) could land commits unnoticed. This guard
runs in fast-gates over the PR commit range and, in ``--check-config`` mode,
as a local pre-commit hook.

Approved identities are the maintainer's own emails plus CI bots. Anything else
fails closed with the offending commits listed.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

# Approved author/committer emails. The maintainer's canonical + historical
# no-reply/personal addresses (mirrors .mailmap targets) and the CI bots.
# The Cisco EMU address (227788186+spreuss_cisco@…) is deliberately NOT here:
# the whole point is to catch an accidental corporate-config commit.
_APPROVED_EMAILS: frozenset[str] = frozenset(
    {
        "221361569+skipp-dev@users.noreply.github.com",
        "skipp-dev@users.noreply.github.com",
        "preuss.steffen@yahoo.com",
        "github-actions[bot]@users.noreply.github.com",
        "41898282+github-actions[bot]@users.noreply.github.com",
        # Dependabot version updates (#4407/#4421). Measured on PR #4424: the
        # bot authors as this numbered no-reply (committer is web-flow
        # noreply@github.com, approved committer-only below). Without this
        # entry every update PR failed this gate regardless of content.
        "49699333+dependabot[bot]@users.noreply.github.com",
    }
)

# Committer-only. GitHub stamps its own identity when a merge is performed
# through the web UI. ``--no-merges`` below exempts a real merge commit, but a
# SQUASH-merge has a single parent and slips past that filter — so stacking a
# PR onto another PR's branch and squashing it in used to fail this gate.
# Approved as committer only: the author check stays closed against it, so the
# human who wrote the code must still be an approved identity.
_APPROVED_COMMITTER_ONLY_EMAILS: frozenset[str] = frozenset({"noreply@github.com"})


def _run(args: list[str]) -> str:
    result = subprocess.run(  # noqa: S603
        args, capture_output=True, text=True, check=True,
    )
    return result.stdout


def _commit_identities(rev_range: str) -> list[tuple[str, str, str]]:
    """Return ``(sha, author_email, committer_email)`` for each commit in range."""
    # Record-separated to survive empty fields; %ae author-email, %ce committer.
    out = _run(["git", "log", "--no-merges", "--format=%H%x1f%ae%x1f%ce", rev_range])
    rows: list[tuple[str, str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) == 3:
            rows.append((parts[0], parts[1].strip().lower(), parts[2].strip().lower()))
    return rows


def _offenders(rows: list[tuple[str, str, str]]) -> list[str]:
    approved = {e.lower() for e in _APPROVED_EMAILS}
    approved_committers = approved | {
        e.lower() for e in _APPROVED_COMMITTER_ONLY_EMAILS
    }
    bad: list[str] = []
    for sha, author, committer in rows:
        if author not in approved:
            bad.append(f"{sha[:12]} author={author}")
        if committer not in approved_committers:
            bad.append(f"{sha[:12]} committer={committer}")
    return bad


def _check_range(rev_range: str) -> int:
    rows = _commit_identities(rev_range)
    if not rows:
        print(f"No commits in range {rev_range!r} — nothing to check.")
        return 0
    offenders = _offenders(rows)
    if offenders:
        print(
            "Non-approved commit identity in the PR range. Every commit must be "
            "authored AND committed by an approved maintainer/bot email "
            "(see scripts/check_commit_authors.py::_APPROVED_EMAILS and .mailmap). "
            "Re-author with `git rebase --exec` / fix your local git config:",
            file=sys.stderr,
        )
        for o in offenders:
            print(f"  - {o}", file=sys.stderr)
        return 1
    print(f"All {len(rows)} commit(s) in {rev_range!r} carry approved identities.")
    return 0


def _check_config() -> int:
    """Pre-commit mode: reject a non-approved *configured* identity up front."""
    try:
        email = _run(["git", "config", "user.email"]).strip().lower()
    except subprocess.CalledProcessError:
        print("git user.email is not configured.", file=sys.stderr)
        return 1
    if email not in {e.lower() for e in _APPROVED_EMAILS}:
        print(
            f"Configured git user.email {email!r} is not an approved maintainer "
            "identity. Set an approved email (see .mailmap) before committing.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="base ref (e.g. origin/main)")
    parser.add_argument("--head", default="HEAD", help="head ref (default HEAD)")
    parser.add_argument("--range", dest="rev_range", help="explicit git range A..B")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="pre-commit mode: validate the configured user.email only",
    )
    args = parser.parse_args(argv)

    if args.check_config:
        return _check_config()
    if args.rev_range:
        return _check_range(args.rev_range)
    if args.base:
        return _check_range(f"{args.base}..{args.head}")
    print("Provide --range, --base/--head, or --check-config.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
