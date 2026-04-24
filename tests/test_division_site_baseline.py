"""Pin: division-site inventory in numerical-core modules.

Background
==========

System review 2026-04-24 finding L-3 (Bug-Klasse #8): ``a / b``
divisions in ``smc_core/scoring.py`` and ``smc_core/fvg_quality.py``
need either an epsilon-guard, a structurally-non-zero divisor (e.g.
``1.0 + exp(x)``), or a caller-side guard. Building a per-site rule
that distinguishes these statically is unreliable; instead, this pin
**baselines the division count** per file. Any new division forces a
reviewer to confirm the denominator is provably non-zero — and, on
acceptance, to extend the baseline.

This is the same pattern as the ``@lru_cache`` baseline-pin in
``test_lru_cache_maxsize_discipline.py`` (PR #127).

Currently expected:
- ``smc_core/scoring.py``: 28 divisions (27 ``a / b`` + 1 ``a /= b``)
- ``smc_core/fvg_quality.py``: 7 divisions

If a division is removed (refactor to multiplication, vectorisation,
etc.) the pin also fails — adjust the baseline downward.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Baseline of approved division-site counts per audited file.
# Format: relative_path → expected_count.
_BASELINE_DIVISION_COUNT: dict[str, int] = {
    # Includes ``BinOp(op=Div)`` (``a / b``) AND ``AugAssign(op=Div)``
    # (``a /= b``) — the audit-relevant question (denominator non-zero?)
    # applies to both forms.
    "smc_core/scoring.py": 28,
    "smc_core/fvg_quality.py": 7,
}


def _count_divisions(path: Path) -> int:
    """Count ``a / b`` and ``a /= b`` divisions in *path*.

    Includes both ``ast.BinOp(op=ast.Div)`` and
    ``ast.AugAssign(op=ast.Div)`` so an in-place divide
    (``total /= len(features)``) cannot bypass the baseline pin.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div))
        or (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div))
    )


def _collect_division_lines(path: Path) -> list[int]:
    """Return a sorted list of line numbers for each division site
    (including ``/=`` augmented assignments)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div))
        or (isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Div))
    )


def test_division_site_counts_match_baseline() -> None:
    """Every audited numerical-core file matches the baseline division count.

    On failure: confirm each new (or removed) division either has a
    structurally-safe divisor (literal > 0, ``1.0 + exp(...)``, ``len(X)``
    with caller-side ``if X:`` guard, etc.) or an explicit epsilon-guard.
    Then bump the baseline in this test.
    """
    drift: list[str] = []
    for rel_path, expected in _BASELINE_DIVISION_COUNT.items():
        abs_path = REPO_ROOT / rel_path
        assert abs_path.exists(), f"Audited file missing: {rel_path}"
        actual = _count_divisions(abs_path)
        if actual != expected:
            sites = _collect_division_lines(abs_path)
            drift.append(
                f"{rel_path}: baseline={expected} actual={actual} "
                f"(division line numbers: {sites}). "
                "Review each new/removed site, confirm divisor is "
                "non-zero (literal, structural, or epsilon-guarded), "
                "then update _BASELINE_DIVISION_COUNT."
            )
    assert not drift, "Division-site baseline drift:\n  " + "\n  ".join(drift)


def test_baseline_files_exist_and_are_parseable() -> None:
    """Sanity: every baseline entry refers to an existing parseable file."""
    for rel_path in _BASELINE_DIVISION_COUNT:
        abs_path = REPO_ROOT / rel_path
        assert abs_path.exists(), f"Baseline references missing file: {rel_path}"
        # Will raise SyntaxError if unparseable — that's the assertion.
        _count_divisions(abs_path)
