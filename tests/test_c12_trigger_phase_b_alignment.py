"""Pin the C12 trigger gate to the C8 Phase-B criteria.

The C12 RL-execution gate is only safe once a family has reached
**Phase-B (live_small)**, not Phase-A (paper). This anchor ensures
that the numeric thresholds in :mod:`scripts.check_c12_trigger`
(``MIN_LIVE_DAYS``, ``MIN_LIVE_TRADES``) cannot silently drift away
from the runbook contract encoded in
``scripts.run_smc_live_incubation.PHASE_B_CRITERIA``.

If anyone lowers the C12 thresholds back toward Phase-A (e.g. 28d),
this test will fire and force a deliberate review.

stdlib only — modules are parsed via :mod:`ast` (Copilot #301), so
heavy transitive imports of the runner module (pandas via
``scripts.execute_ibkr_watchlist``) never load.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_module(relpath: str) -> ast.Module:
    return ast.parse((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def _module_constant(tree: ast.Module, name: str) -> object:
    """Return the literal value of a top-level assignment ``name = <literal>``.

    Supports ``frozenset({...})`` calls (used by
    ``ACCEPTABLE_DRIFT_VERDICTS``) by literal-evaluating the inner set.
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == "frozenset"
                    and len(value.args) == 1
                ):
                    return frozenset(ast.literal_eval(value.args[0]))
                return ast.literal_eval(value)
    raise AssertionError(f"top-level assignment {name!r} not found")


def _phase_b_kwargs() -> dict[str, object]:
    """Extract the kwargs of the ``PHASE_B_CRITERIA = PhasePassCriteria(...)`` call."""
    tree = _parse_module("scripts/run_smc_live_incubation.py")
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (
            len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "PHASE_B_CRITERIA"
        ):
            continue
        assert isinstance(node.value, ast.Call), "PHASE_B_CRITERIA must be a call"
        return {kw.arg: ast.literal_eval(kw.value) for kw in node.value.keywords if kw.arg}
    raise AssertionError("PHASE_B_CRITERIA assignment not found")


_C12 = _parse_module("scripts/check_c12_trigger.py")
_PHASE_B = _phase_b_kwargs()


def test_c12_min_live_days_matches_phase_b_runbook() -> None:
    assert _module_constant(_C12, "MIN_LIVE_DAYS") == _PHASE_B["min_phase_days"], (
        "C12 trigger MIN_LIVE_DAYS must mirror PHASE_B_CRITERIA.min_phase_days. "
        "Phase-A (paper, 28d) is NOT sufficient for RL hand-off."
    )


def test_c12_min_live_trades_matches_phase_b_runbook() -> None:
    assert (
        _module_constant(_C12, "MIN_LIVE_TRADES") == _PHASE_B["min_trades_closed"]
    ), (
        "C12 trigger MIN_LIVE_TRADES must mirror "
        "PHASE_B_CRITERIA.min_trades_closed."
    )


def test_c12_acceptable_drift_verdicts_match_phase_b() -> None:
    c12_verdicts = set(_module_constant(_C12, "ACCEPTABLE_DRIFT_VERDICTS"))
    assert c12_verdicts == set(_PHASE_B["require_drift_verdict_in"]), (
        "C12 ACCEPTABLE_DRIFT_VERDICTS must mirror "
        "PHASE_B_CRITERIA.require_drift_verdict_in."
    )
