"""`_CONFIG_SCHEMA` must not advertise knobs that nothing reads.

A schema entry is a promise: it tells an operator "this key is supported".
``weight_label`` sat in the schema for a knob that could not be set — no code
anywhere read ``config["weight_label"]``, and the live pipeline hardcodes
``weight_label="_regime_adjusted"`` at its ``rank_candidates_v2`` call. The
dead knob is what made the G3 A/B experiment in ``docs/STRATEGY_2026_Q3.md``
look reachable when its arms were never wired up.

Re-adding it is fine — but only together with a reader.
"""
from __future__ import annotations

import ast
from pathlib import Path

from open_prep.config_validation import _CONFIG_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPEN_PREP = _REPO_ROOT / "open_prep"


def test_weight_label_is_not_advertised_without_a_reader() -> None:
    assert "weight_label" not in _CONFIG_SCHEMA, (
        "weight_label was removed from _CONFIG_SCHEMA on 2026-07-27 because nothing "
        "read config['weight_label']. If you are re-adding it, wire a reader in the "
        "same change — see docs/STRATEGY_2026_Q3.md §G3."
    )


def test_live_pipeline_still_hardcodes_the_scoring_weight_label() -> None:
    """Anchors *why* the schema entry was dead, so the two can't drift apart.

    If this ever fails because the call became configurable, that is the moment
    to put ``weight_label`` back into ``_CONFIG_SCHEMA``.
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

    assert literals == ["_regime_adjusted"], (
        f"expected exactly one hardcoded weight_label at the rank_candidates_v2 call, "
        f"got {literals!r}"
    )
