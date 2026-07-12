"""Tests for the reaction-zone shadow follow-through study."""
from __future__ import annotations

from typing import Any

from scripts.eval_reaction_zone_shadow import (
    LIFT_PROMOTE_THRESHOLD,
    MIN_SAMPLES,
    collect_samples,
    derive_variants,
    evaluate,
    evaluate_variant,
)


def _event(*, direction: str, reclaimed: bool, in_band: bool, dist: float,
           width: float, outcome_late: bool) -> dict[str, Any]:
    return {
        "family": "SWEEP",
        "features": {
            "reaction_schema_version": 1,
            "reaction_direction": direction,
            "reaction_level_reclaimed": reclaimed,
            "reaction_in_rejection_band": in_band,
            "reaction_close_distance_pct": dist,
            "reaction_band_width_pct": width,
            "reaction_outcome_late": outcome_late,
        },
    }


def test_derive_variants_mirrored_needs_reclaim_and_within_band() -> None:
    # reclaimed, close 0.3% past a 0.76%-wide band → mirrored True
    assert derive_variants({"reaction_level_reclaimed": True, "reaction_in_rejection_band": False,
                            "reaction_close_distance_pct": 0.3, "reaction_band_width_pct": 0.76}) == {
        "old_band": False, "level_cross": True, "mirrored_band": True}
    # reclaimed but 2% past a 0.76% band → beyond the mirrored band
    assert derive_variants({"reaction_level_reclaimed": True, "reaction_in_rejection_band": False,
                            "reaction_close_distance_pct": 2.0, "reaction_band_width_pct": 0.76})["mirrored_band"] is False
    # not reclaimed → mirrored impossible even if a band close happened
    assert derive_variants({"reaction_level_reclaimed": False, "reaction_in_rejection_band": True,
                            "reaction_close_distance_pct": 0.0, "reaction_band_width_pct": 0.76})["mirrored_band"] is False


def test_collect_samples_filters_non_reaction_and_non_sweep() -> None:
    events = [
        _event(direction="bull", reclaimed=True, in_band=False, dist=0.2, width=0.7, outcome_late=True),
        {"family": "BOS", "features": {"reaction_schema_version": 1, "reaction_direction": "bull",
                                       "reaction_level_reclaimed": True, "reaction_in_rejection_band": False,
                                       "reaction_close_distance_pct": 0.2, "reaction_band_width_pct": 0.7,
                                       "reaction_outcome_late": True}},  # wrong family
        {"family": "SWEEP", "features": {"sweep_trap_quality_score": 0.5}},  # no reaction fields
    ]
    assert len(collect_samples(events)) == 1


def test_evaluate_variant_lift() -> None:
    # confirmed → 3/4 outcome; not confirmed → 1/4 outcome → lift = 0.75 - 0.25
    pairs = [(True, 1), (True, 1), (True, 1), (True, 0), (False, 1), (False, 0), (False, 0), (False, 0)]
    m = evaluate_variant(pairs)
    assert m["n"] == 8 and m["n_confirmed"] == 4
    assert m["p_outcome_if_confirmed"] == 0.75
    assert m["p_outcome_if_not"] == 0.25
    assert m["lift"] == 0.5


def test_evaluate_ranks_level_cross_over_old_band() -> None:
    # Build a bull set where the level-reclaim perfectly predicts follow-through
    # and the old rejection band is anti-correlated (recovered-but-failed).
    events: list[dict[str, Any]] = []
    for _ in range(30):  # reclaimed → follows through
        events.append(_event(direction="bull", reclaimed=True, in_band=False,
                             dist=0.3, width=0.7, outcome_late=True))
    for _ in range(30):  # only recovered into the band, no reclaim → fades
        events.append(_event(direction="bull", reclaimed=False, in_band=True,
                             dist=0.0, width=0.7, outcome_late=False))

    result = evaluate(events)
    bull = result["by_direction"]["bull"]
    assert bull["n"] == 60
    assert bull["best_variant"] == "level_cross"
    lc = bull["variants"]["level_cross"]
    ob = bull["variants"]["old_band"]
    assert lc["lift"] == 1.0  # perfect separation
    assert ob["lift"] == -1.0  # old band fires exactly on the failures
    assert lc["verdict"] == "PROMOTABLE"  # n=60 >= MIN_SAMPLES, lift > threshold
    assert ob["verdict"] == "SHADOW"  # measured but not promotable (lift <= threshold)


def test_thresholds_are_sane() -> None:
    assert MIN_SAMPLES >= 20
    assert 0.0 < LIFT_PROMOTE_THRESHOLD < 1.0
