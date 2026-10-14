"""FDR defense pin for ``scripts/run_ab_comparison.py``.

The A/B comparison pipeline depends on a Benjamini–Hochberg FDR layer to
control the family-wise rejection rate when multiple metrics are compared
in parallel. This test pins the structural surface so that future edits
cannot quietly drop or bypass the FDR layer.

Pinned guarantees:
  * Module exposes ``benjamini_hochberg`` and ``_family_fdr_layer`` defs.
  * Module-level constant ``FDR_Q`` exists and is a ``float`` literal.
  * ``compare()`` invokes ``_family_fdr_layer`` (the family-level FDR
    layer is wired into the main entry point).
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TARGET = _REPO_ROOT / "scripts" / "run_ab_comparison.py"


def _module() -> ast.Module:
    return ast.parse(_TARGET.read_text(encoding="utf-8"))


def _top_level_defs(module: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in module.body
        if isinstance(node, ast.FunctionDef)
    }


def test_required_fdr_functions_present() -> None:
    defs = _top_level_defs(_module())
    assert "benjamini_hochberg" in defs, (
        "benjamini_hochberg() must remain a module-level def in "
        "scripts/run_ab_comparison.py — multi-metric A/B comparisons "
        "rely on it for family-wise FDR control."
    )
    assert "_family_fdr_layer" in defs, (
        "_family_fdr_layer() must remain a module-level def — it is the "
        "wiring layer that applies BH-FDR across the metric family."
    )


def test_fdr_q_constant_is_float_literal() -> None:
    """``FDR_Q`` must be a numeric literal so reviewers can audit it."""
    module = _module()
    found: float | None = None
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id == "FDR_Q"):
            continue
        value = node.value
        assert isinstance(value, ast.Constant) and isinstance(value.value, (int, float)), (
            "FDR_Q must be a bare numeric literal (currently the BH "
            "threshold; auditors should be able to read the q value "
            "without resolving aliases)."
        )
        found = float(value.value)
        break
    assert found is not None, "FDR_Q constant not found at module level."
    assert 0.0 < found < 1.0, f"FDR_Q must be a probability in (0, 1); got {found!r}"


def _function_call_names(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
    return names


def test_compare_invokes_family_fdr_layer() -> None:
    """The main entry must wire the FDR layer into the digest."""
    defs = _top_level_defs(_module())
    compare = defs.get("compare")
    assert compare is not None, "compare() entry point missing."
    calls = _function_call_names(compare)
    assert "_family_fdr_layer" in calls, (
        "compare() must call _family_fdr_layer(); without this call the "
        "BH-FDR layer is defined but unused and per-metric p-values would "
        "be reported uncorrected."
    )
