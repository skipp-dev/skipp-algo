"""Pin: per-file ``request.security`` call budget for active Pine surface.

TradingView Pine Script enforces a hard quota on ``request.security``
calls per script (~40 in v6, depending on engine version). Even
well-below-quota usage is a code-smell signal: each additional
cross-symbol or cross-timeframe call adds latency, increases the
chance of a ``Pine cannot use this resolution`` runtime error, and
multiplies the risk of inadvertent lookahead bias.

This pin freezes a per-file budget that mirrors current usage with a
small headroom (current_count + 1, capped). New calls force an
explicit budget bump, prompting a code-review conversation about
whether the call is genuinely needed or whether an existing call's
result can be reused.

Companion pin:
``tests/test_pine_request_security_discipline.py`` enforces *qualitative*
discipline (no same-symbol+same-TF, mandatory ``lookahead=``). This pin
adds *quantitative* discipline (per-file budget).

Discovery (2026-04-24): only two active files use ``request.security``:

* ``SMC_Core_Engine.pine`` — 5 calls (HTF trend, LTF FVG)
* ``SMC++/smc_utils.pine`` — 4 calls (cross-symbol regime context)

Legacy files under ``pine/legacy/`` are excluded.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-file budget = current_count + 1 (small headroom for low-friction
# additions; new calls beyond budget force explicit bump + review).
_BUDGETS: dict[str, int] = {
    "SMC_Core_Engine.pine": 6,
    "SMC++/smc_utils.pine": 5,
}

_EXCLUDED_DIR_PREFIXES: tuple[str, ...] = ("pine/legacy/", "tests/")
_CALL_RE = re.compile(r"\brequest\.security[a-zA-Z_]*\s*\(")


def _active_pine_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.pine"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(rel.startswith(prefix) for prefix in _EXCLUDED_DIR_PREFIXES):
            continue
        files.append(path)
    return sorted(files)


def _count_security_calls(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    return len(_CALL_RE.findall(text))


def test_per_file_request_security_budgets_are_honored() -> None:
    over_budget: list[tuple[str, int, int]] = []
    for path in _active_pine_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        observed = _count_security_calls(path)
        if observed == 0:
            continue
        budget = _BUDGETS.get(rel)
        if budget is None:
            over_budget.append((rel, observed, 0))
            continue
        if observed > budget:
            over_budget.append((rel, observed, budget))
    assert not over_budget, (
        "request.security per-file budget exceeded:\n"
        + "\n".join(
            (f"  {rel}: {obs} calls (NEW file — add explicit budget)"
             if budget == 0
             else f"  {rel}: {obs} calls > budget {budget}")
            for rel, obs, budget in over_budget
        )
        + "\nEither (a) refactor to reuse an existing security() result, "
        "or (b) bump the per-file budget in this pin with a justification."
    )


def test_budgeted_files_actually_contain_security_calls() -> None:
    """Catch budget-entry rot: if a file no longer uses request.security,
    its budget entry should be removed (and the call site re-justified
    if re-added later)."""
    stale: list[tuple[str, int]] = []
    for rel, budget in _BUDGETS.items():
        path = REPO_ROOT / rel
        if not path.is_file():
            stale.append((rel, -1))
            continue
        if _count_security_calls(path) == 0:
            stale.append((rel, budget))
    assert not stale, (
        "Stale budget entries (file missing or no longer uses "
        "request.security):\n"
        + "\n".join(
            f"  {rel}: " + ("file missing" if budget == -1 else f"budget={budget} but 0 calls")
            for rel, budget in stale
        )
        + "\nRemove the entry from _BUDGETS in this pin."
    )
