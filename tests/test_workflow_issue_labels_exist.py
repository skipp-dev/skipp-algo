"""Pin GitHub label references in workflows to existing repository labels.

Regression guard for Bug-Hunt 2026-05-01 Finding F-04.

Several CI workflows previously called ``gh issue create --label X,Y,Z``
with labels that did not exist in the repository (``c13``, ``critical``,
``drift``, ``drift-alert``, ``plan-2.8``, ``f2-rollback``). The CLI rejects
the unknown label, the issue creation step exits non-zero, and the alert is
silently lost — the failure that prompted the alert continues unnoticed.

This test parses every ``.github/workflows/*.yml`` file, extracts each
literal ``--label`` argument, and asserts that every label is present in
the pinned set of labels known to exist in the repository
(``gh label list --json name --jq '.[].name'`` snapshot taken
2026-05-01).

When a new label is intentionally added to the repository:

1. Run ``gh label create <name> ...`` (or have a workflow do it).
2. Add ``<name>`` to ``PINNED_KNOWN_LABELS`` below in the same PR.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Snapshot of ``gh label list --repo skippALGO/skipp-algo --json name``
# taken on 2026-05-01. If you intentionally add or remove a label in the
# repository, update this set in the same PR.
PINNED_KNOWN_LABELS: frozenset[str] = frozenset(
    {
        "automated",
        "boundary-contract",
        "breaking-change",
        "bug",
        "cron-failure",
        "dependencies",
        "documentation",
        "duplicate",
        "enhancement",
        "f2-recalibration",
        "good first issue",
        "help wanted",
        "invalid",
        "javascript",
        "question",
        "release-pending",
        "tech-debt",
        "wontfix",
    }
)

# Match ``--label <value>`` where <value> is a non-quoted whitespace-delimited
# token or a single/double-quoted string. We deliberately keep this simple:
# label arguments in our workflows are short, comma-separated literals.
_LABEL_ARG_RE = re.compile(r"--label[ \t=]+(?P<value>(?:\"[^\"]*\"|'[^']*'|\S+))")


def _split_labels(raw: str) -> list[str]:
    """Strip surrounding quotes and split a ``--label`` argument on commas."""
    cleaned = raw.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (
        cleaned.startswith("'") and cleaned.endswith("'")
    ):
        cleaned = cleaned[1:-1]
    return [part.strip() for part in cleaned.split(",") if part.strip()]


def _looks_dynamic(label: str) -> bool:
    """Skip labels that resolve at runtime — out of scope for this static lint."""
    return ("${" in label) or ("$(" in label) or label.startswith("$")


def _iter_label_references() -> list[tuple[Path, int, str]]:
    """Yield ``(file, line_number, label)`` for every literal ``--label`` arg."""
    findings: list[tuple[Path, int, str]] = []
    for workflow in sorted(WORKFLOWS_DIR.glob("*.yml")):
        for line_no, line in enumerate(
            workflow.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in _LABEL_ARG_RE.finditer(line):
                for label in _split_labels(match.group("value")):
                    if _looks_dynamic(label):
                        continue
                    findings.append((workflow, line_no, label))
    return findings


def test_workflows_directory_exists() -> None:
    assert WORKFLOWS_DIR.is_dir(), f"Missing workflows dir: {WORKFLOWS_DIR}"


def test_at_least_one_label_reference_exists() -> None:
    """Sanity guard: parser regression would silently make the test trivially pass."""
    refs = _iter_label_references()
    assert refs, (
        "No --label references found in any workflow. The label-arg regex "
        "may be broken, or all alerter steps were removed (verify intent)."
    )


def test_all_workflow_label_refs_use_known_labels() -> None:
    refs = _iter_label_references()
    unknown: list[tuple[Path, int, str]] = [
        (path, line, label)
        for path, line, label in refs
        if label not in PINNED_KNOWN_LABELS
    ]
    if not unknown:
        return

    rendered = "\n".join(
        f"  - {path.relative_to(REPO_ROOT)}:{line} references unknown label "
        f"'{label}'"
        for path, line, label in unknown
    )
    pinned = ", ".join(sorted(PINNED_KNOWN_LABELS))
    pytest.fail(
        "Workflow steps reference GitHub labels that do not exist in the "
        "repository — `gh issue create` will fail and the alert will be "
        "silently lost (Bug-Hunt 2026-05-01 Finding F-04).\n"
        f"{rendered}\n\n"
        "Either:\n"
        "  (a) replace with an existing label, or\n"
        f"  (b) create the label via `gh label create <name>` AND add it to "
        "`PINNED_KNOWN_LABELS` in this test in the same PR.\n"
        f"Currently pinned labels: {pinned}"
    )
