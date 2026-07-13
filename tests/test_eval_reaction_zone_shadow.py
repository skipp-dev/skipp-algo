"""Tests for the reaction-zone shadow follow-through study."""
from __future__ import annotations

from typing import Any

from scripts.eval_reaction_zone_shadow import (
    LIFT_PROMOTE_THRESHOLD,
    MIN_CELL_SAMPLES,
    MIN_SAMPLES,
    _verdict,
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
            "reaction_schema_version": 2,
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
        {"family": "BOS", "features": {"reaction_schema_version": 2, "reaction_direction": "bull",
                                       "reaction_level_reclaimed": True, "reaction_in_rejection_band": False,
                                       "reaction_close_distance_pct": 0.2, "reaction_band_width_pct": 0.7,
                                       "reaction_outcome_late": True}},  # wrong family
        {"family": "SWEEP", "features": {"sweep_trap_quality_score": 0.5}},  # no reaction fields
    ]
    assert len(collect_samples(events)) == 1


def test_collect_samples_reads_outcome_from_extras_schema_1_1() -> None:
    # Schema 1.1: reaction_outcome_late (the label) lives in outcome_extras; the
    # reaction geometry stays in features. The evaluator must read the label there.
    ev = {
        "family": "SWEEP",
        "features": {
            "reaction_schema_version": 2, "reaction_direction": "bull",
            "reaction_level_reclaimed": True, "reaction_in_rejection_band": False,
            "reaction_close_distance_pct": 0.2, "reaction_band_width_pct": 0.7,
        },
        "outcome_extras": {"reaction_outcome_late": True},
    }
    samples = collect_samples([ev])
    assert len(samples) == 1
    assert samples[0][2] == 1  # outcome read from outcome_extras


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
    assert MIN_CELL_SAMPLES >= 1


# ── gradeable-outcome guard: an unresolved late window is NOT a silent miss ────
def _reaction_feats(**overrides: Any) -> dict[str, Any]:
    feats: dict[str, Any] = {
        "reaction_schema_version": 2,
        "reaction_direction": "bull",
        "reaction_level_reclaimed": True,
        "reaction_in_rejection_band": False,
        "reaction_close_distance_pct": 0.2,
        "reaction_band_width_pct": 0.7,
        "reaction_outcome_late": True,
    }
    feats.update(overrides)
    return {"family": "SWEEP", "features": feats}


def test_missing_late_outcome_is_dropped_not_counted_as_miss() -> None:
    ev = _reaction_feats()
    del ev["features"]["reaction_outcome_late"]  # unresolved late window
    assert collect_samples([ev]) == []  # excluded, never outcome=0


def test_non_bool_late_outcome_is_dropped() -> None:
    # A truthy non-bool (e.g. a "pending" sentinel) must not be read as outcome=1.
    assert collect_samples([_reaction_feats(reaction_outcome_late="pending")]) == []
    assert collect_samples([_reaction_feats(reaction_outcome_late=None)]) == []
    assert collect_samples([_reaction_feats(reaction_outcome_late=1)]) == []  # int, not bool


def test_real_bool_late_outcome_is_kept() -> None:
    out = collect_samples([
        _reaction_feats(reaction_outcome_late=True),
        _reaction_feats(reaction_outcome_late=False),
    ])
    assert [o for _, _, o in out] == [1, 0]


# ── cell-size floor: a lopsided split cannot manufacture a PROMOTABLE verdict ──
def test_verdict_lopsided_cell_cannot_promote() -> None:
    n = MIN_SAMPLES
    # Huge lift but only one confirmed sample → not promotable.
    assert _verdict(n, 1, n - 1, 0.9) == "SHADOW"
    # Symmetric: only one not-confirmed sample.
    assert _verdict(n, n - 1, 1, 0.9) == "SHADOW"


def test_verdict_balanced_cells_with_lift_promote() -> None:
    n = MIN_SAMPLES
    assert _verdict(n, MIN_CELL_SAMPLES, n - MIN_CELL_SAMPLES, 0.2) == "PROMOTABLE"


def test_verdict_below_min_samples_is_inconclusive() -> None:
    assert _verdict(MIN_SAMPLES - 1, 15, 15, 0.9) == "INCONCLUSIVE"


def test_single_confirmed_hit_does_not_manufacture_promotion_end_to_end() -> None:
    # 1 confirmed reclaim that hit + (MIN_SAMPLES-1) not-confirmed that missed:
    # raw lift is 1.0, but the confirmed cell has a single sample → stays SHADOW.
    events = [_event(direction="bull", reclaimed=True, in_band=False,
                     dist=0.3, width=0.7, outcome_late=True)]
    events += [_event(direction="bull", reclaimed=False, in_band=True,
                      dist=0.0, width=0.7, outcome_late=False) for _ in range(MIN_SAMPLES - 1)]
    lc = evaluate(events)["by_direction"]["bull"]["variants"]["level_cross"]
    assert lc["n"] >= MIN_SAMPLES and lc["n_confirmed"] == 1
    assert lc["lift"] == 1.0  # the effect looks huge...
    assert lc["verdict"] == "SHADOW"  # ...but the single-sample cell blocks promotion


def test_schema_v1_rows_are_excluded_era_cut() -> None:
    # v1 labels may be right-censored at the data edge (pre-edge-censoring fix).
    ev = _reaction_feats(reaction_schema_version=1)
    assert collect_samples([ev]) == []


def test_band_close_after_reclaim_is_not_the_early_rejection_cohort() -> None:
    """Producer scans on after a reclaim, so both raw flags can be True with the
    band close AFTER the reclaim — that sample is a reclaim, not an early
    rejection, and must not contaminate the ``old_band`` cohort."""
    ev = _reaction_feats(
        reaction_level_reclaimed=True, reaction_in_rejection_band=True,
        reaction_bars_to_reclaim=1, reaction_bars_to_rejection_band=2,
    )
    [(direction, variants, _outcome)] = collect_samples([ev])
    assert direction == "bull"
    assert variants["old_band"] is False   # band fired after the reclaim
    assert variants["level_cross"] is True


def test_band_close_before_reclaim_stays_in_the_early_rejection_cohort() -> None:
    ev = _reaction_feats(
        reaction_level_reclaimed=True, reaction_in_rejection_band=True,
        reaction_bars_to_reclaim=3, reaction_bars_to_rejection_band=1,
    )
    [(_direction, variants, _outcome)] = collect_samples([ev])
    assert variants["old_band"] is True    # at band time no reclaim had happened yet
    assert variants["level_cross"] is True


def test_band_without_reclaim_stays_in_the_cohort() -> None:
    ev = _reaction_feats(
        reaction_level_reclaimed=False, reaction_in_rejection_band=True,
        reaction_bars_to_rejection_band=2,
    )
    [(_direction, variants, _outcome)] = collect_samples([ev])
    assert variants["old_band"] is True
    assert variants["level_cross"] is False


def test_missing_schema_version_is_excluded_era_cut() -> None:
    # Mirror of the sweep evaluator's pin: no version field -> default 0 < 2 -> skip.
    ev = _reaction_feats()
    del ev["features"]["reaction_schema_version"]
    assert collect_samples([ev]) == []


def test_corrupt_bars_to_fields_fail_closed_on_old_band_only_not_whole_sample() -> None:
    """A missing OR corrupt bars_to_* value orders ONLY the old_band cohort, so it
    must fail-closed on old_band (drop from that cohort) while preserving the
    still-valid level_cross / mirrored_band variants — the two failure modes are
    symmetric. Reachable only via --events-json (the producer emits real ints)."""
    base = {"reaction_level_reclaimed": True, "reaction_in_rejection_band": True,
            "reaction_close_distance_pct": 0.3, "reaction_band_width_pct": 0.76}
    # corrupt (non-castable) bars → sample NOT dropped; old_band fail-closed False,
    # the other two variants still derived.
    corrupt = derive_variants({**base, "reaction_bars_to_rejection_band": None,
                               "reaction_bars_to_reclaim": "x"})
    assert corrupt == {"old_band": False, "level_cross": True, "mirrored_band": True}
    # missing bars → identical outcome (symmetry with the corrupt case).
    missing = derive_variants(base)
    assert missing == corrupt
    # a genuinely essential corrupt field (dist) still drops the whole sample.
    assert derive_variants({**base, "reaction_close_distance_pct": None}) is None
    # a non-reclaimed band stays in the cohort regardless of corrupt bars.
    no_reclaim = derive_variants({**base, "reaction_level_reclaimed": False,
                                  "reaction_bars_to_rejection_band": "bad"})
    assert no_reclaim["old_band"] is True and no_reclaim["level_cross"] is False
