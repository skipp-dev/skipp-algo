"""Pin: no hand-maintained file list in a workflow names the same path twice.

Background
==========

``.github/workflows/smc-library-publish.yml`` stages the refreshed Pine
consumers with a backslash-continued ``git add`` list. On 2026-08-14 that list
named ``SMC_Hold_Manager.pine`` twice — once inside the coherent first group and
once appended after ``SMC_Event_Overlay.pine``.

For ``git add`` the duplicate is inert: staging the same path twice is a no-op.
It matters because of what it reveals. These lists are maintained by hand, they
decide which customer-facing ``.pine`` files a refresh run commits, and this repo
has already been bitten once by that list being wrong in the other direction
(#4653: a refresh committed consumer sources wholesale from a days-old tree,
guarded afterwards by #4668/#4669). A list that has silently absorbed a
duplicate is a list nobody is reading, and the next edit to it is the one that
drops an entry instead of doubling one.

Scope
=====

Both shapes these workflows use:

* backslash-continued shell lists (``git add a \\`` / ``   b \\`` / ``   c``)
* single-line lists (the ``npx tsx --test <many files>`` run steps and the
  ``paths:``/``paths-ignore:`` YAML blocks)

What this does NOT do
---------------------

It does not check that a list is *complete* — that a consumer which exists is
actually named. Completeness is per-list domain knowledge and belongs with the
workflow that owns it. This is the cheap half: a list may be wrong, but it may
not contradict itself.
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

# A token worth de-duplicating: something that names a file or a path. Bare
# words (shell flags, subcommands, YAML keys) are deliberately out of scope —
# `--force` twice in one command is a different kind of bug.
_PATHLIKE = re.compile(r"^[\w.@/-]+\.(?:pine|ts|py|yml|yaml|json|md|sh|toml)$|^[\w./-]+/\*{1,2}$")

WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))


def _pathlike(tokens: list[str]) -> list[str]:
    return [t for t in tokens if _PATHLIKE.match(t)]


def _is_command_invocation(tokens: list[str]) -> bool:
    """True for a command line with flags, false for a bare file list.

    ``smc-deeper-integration-gates.yml`` runs an in-place baseline update:

        python scripts/update_measurement_baseline_summary.py \\
          --current artifacts/ci/smc_deeper_evidence_summary.json \\
          --baseline reports/smc_measurement_baseline_summary.json \\
          --out reports/smc_measurement_baseline_summary.json

    ``--baseline`` and ``--out`` name the same file deliberately — it is read
    and rewritten. That is not a list contradicting itself, so flagged
    invocations are out of scope. Only bare enumerations (``git add a b c``)
    are checked.
    """
    return any(t.startswith("-") and len(t) > 1 for t in tokens)


def _continuation_lists(text: str) -> list[tuple[int, list[str]]]:
    """Every backslash-continued shell list, as (first line number, tokens)."""
    out: list[tuple[int, list[str]]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].rstrip().endswith("\\"):
            start = i + 1
            block: list[str] = []
            while i < len(lines) and lines[i].rstrip().endswith("\\"):
                block.extend(lines[i].rstrip().rstrip("\\").split())
                i += 1
            if i < len(lines):
                block.extend(lines[i].split())
            out.append((start, block))
        i += 1
    return out


def _single_line_lists(text: str) -> list[tuple[int, list[str]]]:
    return [
        (n, line.split())
        for n, line in enumerate(text.splitlines(), 1)
        if len(_pathlike(line.split())) >= 3
    ]


def _yaml_path_blocks(text: str) -> list[tuple[int, list[str]]]:
    out: list[tuple[int, list[str]]] = []
    cur: list[str] | None = None
    start = 0
    for n, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped in ("paths:", "paths-ignore:"):
            cur, start = [], n
            continue
        if cur is not None and stripped.startswith("- "):
            cur.append(stripped[2:].strip().strip("'\""))
            continue
        if cur is not None:
            out.append((start, cur))
            cur = None
    if cur is not None:
        out.append((start, cur))
    return out


def test_no_workflow_file_list_names_a_path_twice() -> None:
    # Not parametrized over WORKFLOWS on purpose. A parametrized roster that
    # discovers nothing produces zero test cases, so a non-emptiness assertion
    # inside the case body would never run — the guard would report green while
    # observing no workflow at all. One test with the roster assertion in the
    # same scope as the loop is the idiom this repo uses, and it keeps the check
    # out of [vacuous_claim_guard.exemptions].
    assert WORKFLOWS, f"no workflows found under {WORKFLOW_DIR} — this test would pass vacuously"

    offenders: list[str] = []
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for label, lists in (
            ("continuation list", _continuation_lists(text)),
            ("single-line list", _single_line_lists(text)),
            ("paths block", _yaml_path_blocks(text)),
        ):
            for line_no, tokens in lists:
                if _is_command_invocation(tokens):
                    continue
                paths = _pathlike(tokens)
                duplicated = sorted(
                    name for name, count in collections.Counter(paths).items() if count > 1
                )
                if duplicated:
                    offenders.append(
                        f"{workflow.name}:{line_no} ({label}) names twice: {', '.join(duplicated)}"
                    )

    assert not offenders, (
        "a hand-maintained workflow file list contradicts itself:\n  - "
        + "\n  - ".join(offenders)
        + "\nRemove the duplicate. A list that absorbed one silently is a list "
        "nobody reads, and the next edit drops an entry instead of doubling one."
    )
