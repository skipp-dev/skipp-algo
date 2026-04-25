"""Pin: Lint-suppression budget for ``# type: ignore`` and ``# noqa``.

Suppressions silently expand the technical-debt surface. Each one
is a permanently disabled lint check. We track totals as a budget
that can only shrink (or stay flat) without explicit review.

Today:
  * `# type: ignore` total: 81
  * `# noqa` total: 27

Both numbers are *budgets* — the test fails if either grows.
A test passes if the count is **less than or equal to** the budget,
so removing suppressions is always safe and encouraged. To raise
the budget, you must edit this file (review opportunity).

Defense-only — no production code changes.

Why these classes:
  * `# type: ignore` — disables mypy/pyright checks at a specific site
  * `# noqa` — disables ruff/flake8 checks at a specific site

OWASP A04 (Insecure Design — silently relaxed verifications).
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DIR_EXCLUDE = frozenset({
    ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
    "tests", "SMC++",
})

# Frozen budgets. Lower at will; raising requires explicit review.
_TYPE_IGNORE_BUDGET = 81
_NOQA_BUDGET = 27


def _iter_prod_py() -> list[Path]:
    out: list[Path] = []
    for p in sorted(_REPO_ROOT.rglob("*.py")):
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _count_suppressions() -> tuple[int, int]:
    """Return (type_ignore_count, noqa_count)."""
    type_ignore = 0
    noqa = 0
    for p in _iter_prod_py():
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line in src.splitlines():
            lower = line.lower()
            if "type: ignore" in line:
                type_ignore += 1
            if "# noqa" in lower or "#noqa" in lower:
                noqa += 1
    return type_ignore, noqa


def test_type_ignore_budget_not_exceeded() -> None:
    """``# type: ignore`` count must not exceed the frozen budget.

    Each `type: ignore` permanently disables type-checking at one
    site. Growth is silent technical debt accumulation.
    """
    actual, _ = _count_suppressions()
    assert actual <= _TYPE_IGNORE_BUDGET, (
        f"# type: ignore budget exceeded: {actual} > "
        f"{_TYPE_IGNORE_BUDGET}. Remove a suppression or raise "
        f"_TYPE_IGNORE_BUDGET (review-only)."
    )


def test_noqa_budget_not_exceeded() -> None:
    """``# noqa`` count must not exceed the frozen budget."""
    _, actual = _count_suppressions()
    assert actual <= _NOQA_BUDGET, (
        f"# noqa budget exceeded: {actual} > {_NOQA_BUDGET}. "
        f"Remove a suppression or raise _NOQA_BUDGET (review-only)."
    )


def test_budgets_match_today_or_have_been_lowered() -> None:
    """Detect when the budget has fallen out of date (counts < budget).

    This is informational — a *passing* assert here confirms that
    if counts have dropped below the budget, the budget should be
    lowered to lock in the improvement.

    We only emit a warning-style failure when the budget overshoots
    the actual by more than 5 (significant drift).
    """
    actual_ti, actual_noqa = _count_suppressions()
    drift_ti = _TYPE_IGNORE_BUDGET - actual_ti
    drift_noqa = _NOQA_BUDGET - actual_noqa
    assert drift_ti <= 5, (
        f"_TYPE_IGNORE_BUDGET drift: budget={_TYPE_IGNORE_BUDGET}, "
        f"actual={actual_ti}, drift={drift_ti}. Lower the budget "
        f"to lock in the improvement."
    )
    assert drift_noqa <= 5, (
        f"_NOQA_BUDGET drift: budget={_NOQA_BUDGET}, "
        f"actual={actual_noqa}, drift={drift_noqa}. Lower the "
        f"budget to lock in the improvement."
    )
