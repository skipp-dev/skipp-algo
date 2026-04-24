"""Pin: AST-level structural guarantee that ``decide()`` returns only
literal members of the SPRT ``Decision`` vocabulary.

Companion pin to ``tests/test_sprt_decision_vocab_pin.py``:

* The behavioural pin verifies ``decide()`` *returns* a vocab member on
  representative inputs (sample-based).
* This pin verifies ``decide()`` *can only* return vocab members by
  walking its AST: every ``Return`` node must wrap a ``Constant(str)``
  whose value is in the frozen 5-member vocab.

Together they close the "structural ↔ usage" gap: future refactors
cannot introduce ``return f"continue"`` (formatted string) or
``return state.last_decision`` (variable) without tripping this pin.

Scope: only ``decide()``. ``evaluate()`` and ``terminal_decision()``
delegate to ``decide()`` or use richer logic (state construction +
return tuples) that is harder to constrain at AST level without false
positives — they are covered by the behavioural pin.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = REPO_ROOT / "scripts" / "smc_sprt_stop_rule.py"

_EXPECTED_VOCAB: frozenset[str] = frozenset({
    "continue",
    "accept_h0",
    "accept_h1",
    "max_n_reached",
    "inconclusive",
})


def _decide_function() -> ast.FunctionDef:
    tree = ast.parse(TARGET_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "decide":
            return node
    raise AssertionError(
        f"Could not find top-level `def decide(...)` in {TARGET_FILE}."
    )


def _return_nodes(func: ast.FunctionDef) -> list[ast.Return]:
    return [n for n in ast.walk(func) if isinstance(n, ast.Return)]


def test_decide_function_is_present() -> None:
    func = _decide_function()
    assert func.name == "decide"


def test_decide_has_at_least_one_return_per_branch_outcome() -> None:
    """Sanity: ``decide()`` must contain >= 4 return statements (one per
    branch: upper bound, lower bound, max_n cap, default continue).
    Catches accidental refactors that collapse the branching into a
    single dynamic return."""
    returns = _return_nodes(_decide_function())
    assert len(returns) >= 4, (
        f"decide() has only {len(returns)} return statement(s); "
        f"expected at least 4 (accept_h1, accept_h0, max_n_reached, continue)."
    )


def test_every_return_in_decide_is_vocab_string_literal() -> None:
    func = _decide_function()
    violations: list[tuple[int, str]] = []
    seen_literals: set[str] = set()
    for ret in _return_nodes(func):
        value = ret.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            violations.append((ret.lineno, ast.unparse(ret)))
            continue
        if value.value not in _EXPECTED_VOCAB:
            violations.append((ret.lineno, ast.unparse(ret)))
            continue
        seen_literals.add(value.value)
    assert not violations, (
        "decide() contains return(s) that are NOT a literal vocab "
        "string member:\n"
        + "\n".join(f"  L{ln}: {txt}" for ln, txt in violations)
        + f"\nAllowed literals: {sorted(_EXPECTED_VOCAB)}"
    )
    # Must cover at least the 4 explicit decisions; "inconclusive" lives
    # in terminal_decision() and is not expected inside decide().
    expected_in_decide = {"continue", "accept_h0", "accept_h1", "max_n_reached"}
    missing = sorted(expected_in_decide - seen_literals)
    assert not missing, (
        f"decide() no longer returns required vocab member(s): {missing}. "
        f"This is a contract break — downstream gates depend on these "
        f"sentinels being reachable from decide()."
    )
