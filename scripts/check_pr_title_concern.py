"""ADR-0013 enforcement: validate a PR title declares exactly one concern.

ADR-0013 ("Atomic vs cross-cutting workflow PRs", Option C — one *concern*
per PR) makes PR titles self-checking by requiring the
``concern(scope): subject`` convention. A bundle like #2449 (concurrency +
marker + SHA bump) is exactly the cross-concern collision this guards
against; a single declared ``concern(scope)`` prefix forces the author to
name the one concern the PR carries.

This module is the *tested* half of that enforcement. The companion
workflow ``.github/workflows/pr-title-concern-lint.yml`` calls it with the
live PR title (passed via the ``PR_TITLE`` environment variable — never
interpolated into the shell, to avoid script injection).

Convention enforced
--------------------
``<concern>(<scope>): <subject>`` where:

* ``<concern>`` is one of the accepted Conventional-Commit types below,
* ``<scope>`` is a non-empty identifier naming the area touched,
* ``<subject>`` is a non-empty description.

GitHub's auto-generated ``Revert "<original title>"`` titles are accepted
as-is (the revert's concern is inherited from the original PR).

Exit codes
----------
0  Title satisfies the convention.
1  Title violates the convention (reasons printed to stderr).
2  No title supplied (missing ``PR_TITLE`` env and no CLI argument).
"""

from __future__ import annotations

import os
import re
import sys

# Accepted concern types. Conventional-Commit vocabulary as used across this
# repo's PR history (feat/fix/test/docs/refactor/perf/build/ci/chore/revert/
# style). Adding a type is a deliberate edit here.
ACCEPTED_CONCERNS: frozenset[str] = frozenset(
    {
        "feat",
        "fix",
        "test",
        "docs",
        "refactor",
        "perf",
        "build",
        "ci",
        "chore",
        "revert",
        "style",
    }
)

# ``concern(scope): subject`` — scope is REQUIRED (ADR-0013 writes the
# convention as ``concern(scope): …``; the scope is the part that actually
# names the single concern). An optional ``!`` flags a breaking change.
_TITLE_RE = re.compile(
    r"^(?P<concern>[a-z]+)\((?P<scope>[^)]+)\)(?P<breaking>!?): (?P<subject>.+)$"
)

# GitHub generates these verbatim for the "Revert" button; accept as-is.
_REVERT_RE = re.compile(r'^Revert ".+"$')


def validate_pr_title(title: str) -> list[str]:
    """Return a list of human-readable reasons the title is invalid.

    An empty list means the title satisfies the ADR-0013 convention.
    """
    reasons: list[str] = []
    stripped = title.strip()

    if not stripped:
        return ["PR title is empty."]

    if _REVERT_RE.match(stripped):
        return reasons  # auto-generated revert title — inherits its concern

    match = _TITLE_RE.match(stripped)
    if match is None:
        reasons.append(
            "PR title must follow `concern(scope): subject` (ADR-0013). "
            f"Got: {title!r}."
        )
        # Best-effort hint when the colon form is close but scope is missing.
        if re.match(r"^[a-z]+: ", stripped):
            reasons.append(
                "A scope is required: write `concern(scope): subject`, "
                "e.g. `ci(actions): bump upload-artifact to v7`."
            )
        return reasons

    concern = match.group("concern")
    scope = match.group("scope").strip()
    subject = match.group("subject").strip()

    if concern not in ACCEPTED_CONCERNS:
        reasons.append(
            f"Unknown concern type {concern!r}. "
            f"Use one of: {', '.join(sorted(ACCEPTED_CONCERNS))}."
        )
    if not scope:
        reasons.append("Scope (the text inside the parentheses) must not be empty.")
    if not subject:
        reasons.append("Subject (after `: `) must not be empty.")

    return reasons


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    title = os.environ.get("PR_TITLE")
    if title is None and args:
        title = args[0]

    if title is None:
        print(
            "error: no PR title supplied (set PR_TITLE env or pass as argument).",
            file=sys.stderr,
        )
        return 2

    reasons = validate_pr_title(title)
    if reasons:
        print(f"PR title rejected by ADR-0013 concern-lint: {title!r}", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1

    print(f"PR title OK (ADR-0013): {title!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
