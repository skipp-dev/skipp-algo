"""Required-check coverage pin (Audit 2026-05-29).

Today's audit uncovered that PR #2415 merged at 16:44 with only
``fast-gates`` as the required status-check, while ``validate`` (which
runs ``test_workflow_issue_labels_exist.py`` and would have caught the
unknown ``release-pending`` / ``breaking-change`` labels introduced by
the same PR) only finished failing at 17:08 — **after** the merge. The
guard was already in the tree, it just wasn't on the required-check
boundary so main-governance let the PR through.

This test pins the inverse contract: the static workflow-shape lints
that catch the silent-skip class of regressions MUST be invoked inside
the ``smc-fast-pr-gates`` workflow's tripwire pytest call, because that
is the only check ``main-governance`` requires before merge.

Listed tests:
  * ``test_workflow_issue_labels_exist.py``  — catches ``--label X``
    where ``X`` is not in the repo's label snapshot (root cause of the
    PR #2419 auto-PR-create failure).
  * ``test_workflow_no_fake_push_success.py`` — catches workflows that
    paper over a rejected push with ``git push ... || echo`` (the GH013
    silent-success anti-pattern).
  * ``test_smc_library_refresh_workflow.py`` — pins the F-V8-N1 surfacing
    contract (::error annotation, release-pending auto-PR, override
    gate, retry wrapper) so a future refactor cannot silently revert
    back to the silent-skip behaviour that caused the 5-week
    publish-stall.
  * ``test_schema_version_manifest_alignment.py`` — catches the
    SCHEMA_VERSION-constant-vs-generated-manifest drift that produced
    the surprise MAJOR-bump in run 26598144143.

If any of these are removed from the fast-gates tripwire step (or moved
into the slower ``validate`` job that runs post-merge), the silent-skip
class of regressions re-opens.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAST_GATES_WORKFLOW = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

REQUIRED_PINNED_TESTS: tuple[str, ...] = (
    "tests/test_workflow_issue_labels_exist.py",
    "tests/test_workflow_no_fake_push_success.py",
    "tests/test_smc_library_refresh_workflow.py",
    "tests/test_schema_version_manifest_alignment.py",
)


def test_silent_skip_class_tests_are_pinned_in_fast_gates() -> None:
    workflow_text = FAST_GATES_WORKFLOW.read_text(encoding="utf-8")

    missing = [t for t in REQUIRED_PINNED_TESTS if t not in workflow_text]
    assert not missing, (
        "smc-fast-pr-gates.yml dropped tests from the silent-skip tripwire pin. "
        "Branch-protection only requires fast-gates, so any test that leaves this "
        "workflow loses its ability to block merge.\n\n"
        f"Missing pins: {missing}\n\n"
        "Re-add them to the 'Run pin / ledger drift guard' step's pytest invocation "
        "or document explicitly why coverage moves elsewhere AND update "
        "this guard."
    )
