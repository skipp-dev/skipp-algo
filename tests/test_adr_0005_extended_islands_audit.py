"""ADR-0005 extended pure-stdlib island audit.

PR #120 introduced ``RUNTIME_FILES = (run_ab_comparison.py,
smc_sprt_stop_rule.py)`` as the canonical pure-stdlib measurement
runtime. Phase-F audit from ``smc-system-review-2026-04-24.md``:
several other scripts in ``scripts/`` are **also** pure-stdlib today
and would benefit from the same anti-regression guard, but they live
outside the ADR-0005 enforcement set.

This module locks in the **current** pure-stdlib status of three
secondary islands as a *soft pin* — failure means a contributor added
a banned import and either:

  * extended the contract (intentional → migrate the file into
    RUNTIME_FILES + update ADR-0005), or
  * made the file numpy/pandas-dependent (intentional → drop it from
    this audit list and document in CHANGELOG).

Files audited here are **not** enforced by the ADR-0005 pre-commit
hook (PR #121); this is observability, not enforcement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Re-use the AST scanner from the canonical ADR-0005 test so we have a
# single source of truth for the "what is a banned root" definition.
from tests.test_adr_0005_pure_stdlib_runtime import (
    BANNED_ROOTS,
    REPO_ROOT,
    _collect_imported_roots,
)

# Secondary pure-stdlib islands. Verified manually 2026-04-24:
# none of these files imports numpy / scipy / pandas / sklearn /
# statsmodels / torch / tensorflow at module top level.
_AUDIT_FILES: tuple[Path, ...] = (
    REPO_ROOT / "scripts" / "smc_hero_state.py",
    REPO_ROOT / "scripts" / "smc_hero_action.py",
    REPO_ROOT / "scripts" / "smc_pine_evidence_gate.py",
)


@pytest.mark.parametrize("path", _AUDIT_FILES, ids=lambda p: p.name)
def test_audit_island_remains_pure_stdlib(path: Path) -> None:
    assert path.exists(), (
        f"Audit-island file vanished: {path.relative_to(REPO_ROOT)}. "
        "Update _AUDIT_FILES if the script was renamed or removed."
    )
    source = path.read_text(encoding="utf-8")
    roots = _collect_imported_roots(source)
    violations = roots & BANNED_ROOTS
    assert not violations, (
        f"{path.relative_to(REPO_ROOT)} introduced banned import(s) "
        f"{sorted(violations)} — was pure-stdlib at the time of the "
        "audit (2026-04-24).\n\n"
        "Decide:\n"
        "  (a) Promote into the canonical ADR-0005 RUNTIME_FILES set "
        "and the pre-commit hook scope. The file becomes part of the "
        "lean measurement runtime contract.\n"
        "  (b) Drop the file from _AUDIT_FILES in this test and note "
        "the change in CHANGELOG.md (rationale for why the lean "
        "fence no longer applies).\n"
        "Do NOT silently relax the audit set."
    )


def test_audit_set_is_disjoint_from_canonical_runtime() -> None:
    """The audit set must NOT shadow the canonical RUNTIME_FILES.

    Otherwise the soft audit would create the false impression that
    those files are not yet enforced.
    """
    from tests.test_adr_0005_pure_stdlib_runtime import RUNTIME_FILES

    overlap = set(_AUDIT_FILES) & set(RUNTIME_FILES)
    assert not overlap, (
        f"Audit-island file already in canonical RUNTIME_FILES: "
        f"{[p.name for p in overlap]}. Remove from _AUDIT_FILES — "
        "it is enforced by tests/test_adr_0005_pure_stdlib_runtime.py "
        "and the pre-commit hook."
    )
