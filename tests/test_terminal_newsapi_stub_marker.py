"""Pin: ``terminal_newsapi.py`` stub keeps cross-reference to the active
NewsAPI implementation in ``scripts/smc_newsapi_ai.py``.

Audit follow-up to :file:`docs/reviews/2026-04-24-system-review.md` finding
**L-1** (Klasse #40, "Decommissioned stub"): the 44-line top-level stub
file co-exists with the ~750-line active implementation under ``scripts/``.
Reviewers (and audit greps) need to know about both paths.

This pin asserts the stub's module docstring contains a pointer to the
active sibling, so future docstring rewrites cannot silently drop the
cross-reference.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STUB_PATH = _REPO_ROOT / "terminal_newsapi.py"
_ACTIVE_PATH = _REPO_ROOT / "scripts" / "smc_newsapi_ai.py"


def test_active_implementation_exists() -> None:
    # Sanity: if the active path moves, this pin needs an update too.
    assert _ACTIVE_PATH.is_file(), (
        f"expected active NewsAPI implementation at {_ACTIVE_PATH} — pin "
        "needs the sibling file to validate the cross-reference."
    )


def test_stub_file_exists() -> None:
    # Sanity: assert the stub exists before any test reads it, so a
    # rename/move surfaces as a clear assertion message instead of a
    # downstream FileNotFoundError from read_text().
    assert _STUB_PATH.is_file(), (
        f"expected NewsAPI stub at {_STUB_PATH} — if the stub was moved "
        "or renamed, update _STUB_PATH in this pin (and the L-1 audit "
        "anchor) accordingly."
    )


def test_stub_docstring_cross_references_active_module() -> None:
    src = _STUB_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    docstring = ast.get_docstring(tree) or ""
    assert "scripts/smc_newsapi_ai.py" in docstring, (
        "terminal_newsapi.py module docstring must reference the active "
        "implementation path 'scripts/smc_newsapi_ai.py' so audit-greps for "
        "'newsapi' surface both files. Audit finding L-1 (Klasse #40)."
    )
    # Audit anchor: keep the L-1 finding-id reachable via grep so future
    # reviewers land on the rationale.
    assert "L-1" in docstring or "L\u20111" in docstring, (
        "terminal_newsapi.py docstring must mention audit anchor 'L-1' so "
        "'grep L-1' across the repo lands here."
    )
