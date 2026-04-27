"""C5 deep-review MINOR fix: pin ``MIN_TRADES_PER_REGIME`` against
``MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP``.

``scripts/regime_stratification.py`` documents that
``MIN_TRADES_PER_REGIME`` is "Mirror of ``MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP``
in scripts/run_ab_comparison.py — kept as a local constant so this
module does not pull the scripts package at import time. If the
canonical constant moves, update this in lockstep."

Without an actual mirror test the two constants can drift apart silently.
This is a stdlib + ast-only test (no heavy transitive imports).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _module_constant(relpath: str, name: str) -> object:
    tree = ast.parse((REPO_ROOT / relpath).read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise AssertionError(f"top-level assignment {name!r} not found in {relpath}")


def test_min_trades_per_regime_mirrors_min_events_per_arm() -> None:
    regime_value = _module_constant(
        "scripts/regime_stratification.py", "MIN_TRADES_PER_REGIME"
    )
    ab_value = _module_constant(
        "scripts/run_ab_comparison.py", "MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP"
    )
    assert regime_value == ab_value, (
        f"MIN_TRADES_PER_REGIME ({regime_value}) drifted away from "
        f"MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP ({ab_value}). The "
        "regime-stratification module documents these as a lockstep "
        "mirror; update both or delete the mirror comment."
    )
