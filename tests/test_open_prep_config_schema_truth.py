"""The scoring weight label must not look configurable while it is hardcoded.

History: ``open_prep.config_validation`` used to carry a ``_CONFIG_SCHEMA``
whose ``weight_label`` entry advertised a knob that could not be set — no code
anywhere read ``config["weight_label"]``, and the live pipeline hardcodes
``weight_label="_regime_adjusted"`` at its ``rank_candidates_v2`` calls. The
dead knob is what made the G3 A/B experiment in ``docs/STRATEGY_2026_Q3.md``
look reachable when its arms were never wired up. The entry was removed
2026-07-27; ``validate_config`` + ``_CONFIG_SCHEMA`` themselves were removed
2026-07-29 (zero callers repo-wide, Verdrahtungs-Sweep).

This anchor test remains: if the call sites ever become configurable, that is
the moment to re-introduce a validated config schema — together with a reader.
"""
from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPEN_PREP = _REPO_ROOT / "open_prep"


def test_live_pipeline_still_hardcodes_the_scoring_weight_label() -> None:
    """Anchors *why* the removed schema entry was dead, so docs can't drift.

    2026-07-29: #4174 added a second call site (exact §15 shadow replay next to
    the baseline ranking); both remain hardcoded to the same label.
    """
    source = (_OPEN_PREP / "run_open_prep.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    literals: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "rank_candidates_v2":
            continue
        for kw in node.keywords:
            if kw.arg == "weight_label" and isinstance(kw.value, ast.Constant):
                literals.append(str(kw.value.value))

    assert literals == ["_regime_adjusted", "_regime_adjusted"], (
        f"expected the baseline and §15-shadow rank_candidates_v2 calls to both "
        f"hardcode the weight_label, got {literals!r}"
    )
