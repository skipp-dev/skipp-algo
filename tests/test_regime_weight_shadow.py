"""Shadow measurement for the scorer's §15 SYMBOL-layer regime weights.

Anchors the defect being measured: ``score_candidate`` resolves
``symbol_regime`` from ``quote["adx"]`` / ``quote["bb_width_pct"]``
(scorer.py), but no producer populates those keys on the premarket quote
path, so the fallback defaults always yield ``NEUTRAL`` and
``resolve_regime_weights`` is a no-op in production.

The shadow is observation-only: it records what the MEASURED regime (computed
later in the run from daily bars) would have done to the weighted components,
without changing any live score.
"""
from __future__ import annotations

import pytest

from open_prep.regime_shadow import (
    SCORING_REGIME,
    compute_regime_weight_shadow,
)
from open_prep.scorer import DEFAULT_WEIGHTS
from open_prep.technical_analysis import detect_symbol_regime, resolve_regime_weights

# ── The defect the shadow exists to measure ──────────────────────────


def test_scorer_regime_fallback_defaults_resolve_to_neutral() -> None:
    """The scorer's ``quote.get`` defaults (15.0 / 3.0) classify as NEUTRAL."""
    assert detect_symbol_regime(adx=15.0, bb_width_pct=3.0) == "NEUTRAL"


def test_neutral_regime_leaves_every_weight_untouched() -> None:
    """NEUTRAL runs the cap but applies no tilt — so §15 is inert."""
    base = dict(DEFAULT_WEIGHTS)
    resolved = resolve_regime_weights(dict(base), "NEUTRAL")
    assert {k: v for k, v in base.items() if resolved.get(k) != v} == {}


@pytest.mark.parametrize(
    ("adx", "bb_width_pct", "expected"),
    [(30.0, 5.0, "TRENDING"), (10.0, 1.0, "RANGING")],
)
def test_measured_inputs_would_move_weights(
    adx: float, bb_width_pct: float, expected: str,
) -> None:
    """With real ADX/BB the regime is non-NEUTRAL and does shift weights."""
    regime = detect_symbol_regime(adx=adx, bb_width_pct=bb_width_pct)
    assert regime == expected
    base = dict(DEFAULT_WEIGHTS)
    resolved = resolve_regime_weights(dict(base), regime)
    moved = {k for k, v in base.items() if resolved.get(k) != v}
    assert moved == {
        "gap",
        "gap_sector_relative",
        "rvol",
        "momentum_z",
        "ext_hours",
    }


# ── The shadow itself ────────────────────────────────────────────────


def _row(**components: float) -> dict[str, object]:
    breakdown = {
        "gap_component": 0.0,
        "gap_sector_rel_component": 0.0,
        "rvol_component": 0.0,
        "momentum_component": 0.0,
        "ext_hours_component": 0.0,
    }
    breakdown.update(components)
    return {"score": 12.5, "score_breakdown": breakdown}


def test_shadow_reports_no_delta_for_neutral() -> None:
    """A NEUTRAL measurement matches what scoring already used → zero delta."""
    out = compute_regime_weight_shadow(
        _row(gap_component=1.6, momentum_component=0.5),
        "NEUTRAL",
        base_weights=dict(DEFAULT_WEIGHTS),
    )
    assert out["measured_regime"] == "NEUTRAL"
    assert out["regime_at_scoring"] == SCORING_REGIME
    assert out["score_delta"] == 0.0
    assert out["would_change_score"] is False


def test_shadow_delta_is_exact_for_trending() -> None:
    """Score is linear in the weights, so the delta is reconstructible exactly.

    ``component = w * f`` ⇒ under ``w'`` it becomes ``component * w' / w``.
    """
    base = dict(DEFAULT_WEIGHTS)
    baseline = resolve_regime_weights(dict(base), SCORING_REGIME)
    trending = resolve_regime_weights(dict(base), "TRENDING")

    gap_component = 1.6
    momentum_component = 0.5
    row = _row(gap_component=gap_component, momentum_component=momentum_component)

    out = compute_regime_weight_shadow(row, "TRENDING", base_weights=base)

    expected_gap = gap_component * (trending["gap"] / baseline["gap"]) - gap_component
    expected_mom = (
        momentum_component * (trending["momentum_z"] / baseline["momentum_z"])
        - momentum_component
    )
    assert out["component_delta"]["gap_component"] == pytest.approx(expected_gap)
    assert out["component_delta"]["momentum_component"] == pytest.approx(expected_mom)
    assert out["score_delta"] == pytest.approx(expected_gap + expected_mom)
    assert out["would_change_score"] is True
    # TRENDING dampens gap and boosts momentum — opposite signs.
    assert expected_gap < 0.0 < expected_mom


def test_shadow_does_not_mutate_the_row_or_the_weights() -> None:
    """Observation-only: neither the live row nor the weight dict is touched."""
    base = dict(DEFAULT_WEIGHTS)
    base_snapshot = dict(base)
    row = _row(gap_component=1.6)
    row_snapshot = {"score": row["score"], "breakdown": dict(row["score_breakdown"])}

    compute_regime_weight_shadow(row, "RANGING", base_weights=base)

    assert base == base_snapshot
    assert row["score"] == row_snapshot["score"]
    assert row["score_breakdown"] == row_snapshot["breakdown"]


def test_shadow_flags_missing_breakdown_instead_of_inventing_a_delta() -> None:
    """A row without ``score_breakdown`` yields zero delta + an audit trail."""
    out = compute_regime_weight_shadow({}, "TRENDING", base_weights=dict(DEFAULT_WEIGHTS))
    assert out["score_delta"] == 0.0
    assert out["would_change_score"] is False
    assert sorted(out["unresolved"]) == [
        "ext_hours_component",
        "gap_component",
        "gap_sector_rel_component",
        "momentum_component",
        "rvol_component",
    ]


def test_shadow_ignores_non_finite_components() -> None:
    """NaN/inf components are reported unresolved, never folded into the sum."""
    out = compute_regime_weight_shadow(
        _row(gap_component=float("nan"), momentum_component=0.5),
        "TRENDING",
        base_weights=dict(DEFAULT_WEIGHTS),
    )
    assert "gap_component" in out["unresolved"]
    assert "gap_component" not in out["component_delta"]
    assert out["score_delta"] == pytest.approx(out["component_delta"]["momentum_component"])
