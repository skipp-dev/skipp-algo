"""Property tests for ``smc_core.ensemble_quality`` aggregation invariants.

Pins the mathematical contract of the five-component ensemble quality
aggregator that drives every ``ensemble_quality_<symbol>_<tf>.json``
artifact and the downstream tier-bucketed dashboards:

  * :func:`smc_core.ensemble_quality._clamp`
  * :func:`smc_core.ensemble_quality._finite_metric`
  * :func:`smc_core.ensemble_quality._median_metric`
  * :func:`smc_core.ensemble_quality._tier_from_score`
  * :func:`smc_core.ensemble_quality._bias_component`
  * :func:`smc_core.ensemble_quality._vol_regime_component`
  * :func:`smc_core.ensemble_quality._scoring_component`
  * :func:`smc_core.ensemble_quality._history_component`
  * :func:`smc_core.ensemble_quality.build_ensemble_quality`

Continues the PQ Re-Audit Tier-1 spillover series
(PR #2350, #2363, #2366, #2370, #2371, #2372, #2373). Pure stdlib; ≤ 2s.
"""

from __future__ import annotations

import math
import random
from typing import Any

import pytest

from smc_core.ensemble_quality import (
    _DEFAULT_WEIGHTS,
    _VOL_REGIME_BASE_SCORES,
    _bias_component,
    _clamp,
    _finite_metric,
    _history_component,
    _median_metric,
    _scoring_component,
    _tier_from_score,
    _vol_regime_component,
    build_ensemble_quality,
)
from smc_core.scoring import ScoringResult

# ---------------------------------------------------------------------------
# _clamp — bounds, default range, idempotency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "v,expected",
    ((0.5, 0.5), (-1.0, 0.0), (2.0, 1.0), (0.0, 0.0), (1.0, 1.0)),
)
def test_clamp_default_unit_interval(v: float, expected: float) -> None:
    assert _clamp(v) == expected


@pytest.mark.parametrize("seed", (0, 1, 7, 13))
def test_clamp_idempotent(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(25):
        v = rng.uniform(-100.0, 100.0)
        once = _clamp(v)
        assert _clamp(once) == once


# ---------------------------------------------------------------------------
# _finite_metric — non-numeric / NaN / inf rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    (None, "", "abc", float("nan"), float("inf"), float("-inf"), [1.0], {"a": 1}),
)
def test_finite_metric_rejects_non_finite_or_non_numeric(bad: Any) -> None:
    assert _finite_metric(bad) is None


@pytest.mark.parametrize(
    "v,expected",
    ((0.0, 0.0), (1.5, 1.5), (-3.25, -3.25), ("0.5", 0.5), (42, 42.0)),
)
def test_finite_metric_passes_through_finite(v: Any, expected: float) -> None:
    assert _finite_metric(v) == expected


# ---------------------------------------------------------------------------
# _median_metric — empty + matches statistics.median
# ---------------------------------------------------------------------------


def test_median_metric_empty_returns_none() -> None:
    assert _median_metric([]) is None


@pytest.mark.parametrize(
    "values,expected",
    (
        ([1.0], 1.0),
        ([1.0, 2.0, 3.0], 2.0),
        ([1.0, 2.0, 3.0, 4.0], 2.5),
        ([5.0, 1.0, 3.0], 3.0),  # order-independent
    ),
)
def test_median_metric_matches_statistics_median(
    values: list[float], expected: float
) -> None:
    assert _median_metric(values) == expected


# ---------------------------------------------------------------------------
# _tier_from_score — ladder cutoffs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    (
        (0.0, "low"),
        (0.2499, "low"),
        (0.25, "ok"),
        (0.4999, "ok"),
        (0.50, "good"),
        (0.7499, "good"),
        (0.75, "high"),
        (1.0, "high"),
    ),
)
def test_tier_from_score_ladder(score: float, expected: str) -> None:
    """Tier cutoffs: low < 0.25, ok < 0.50, good < 0.75, high >= 0.75."""
    assert _tier_from_score(score) == expected


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_tier_from_score_monotone_non_decreasing(seed: int) -> None:
    order = {"low": 0, "ok": 1, "good": 2, "high": 3}
    rng = random.Random(seed)
    scores = sorted(rng.uniform(0.0, 1.0) for _ in range(40))
    levels = [order[_tier_from_score(s)] for s in scores]
    for i in range(1, len(levels)):
        assert levels[i] >= levels[i - 1]


# ---------------------------------------------------------------------------
# _bias_component
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dir_in", (None, "", "neutral", "NEUTRAL", "  Neutral  "))
def test_bias_component_neutral_returns_half(dir_in: str | None) -> None:
    """Empty / None / any-case NEUTRAL → fixed 0.5 (no directional reward)."""
    value, detail = _bias_component(dir_in, 0.9)
    assert value == 0.5
    assert detail["direction"] == "NEUTRAL"


@pytest.mark.parametrize(
    "conf,expected",
    (
        (0.0, 0.4),    # 0.4 + 0.6*0
        (1.0, 1.0),    # 0.4 + 0.6*1
        (0.5, 0.7),    # 0.4 + 0.6*0.5
        (-1.0, 0.4),   # clamped to 0
        (2.0, 1.0),    # clamped to 1
        (None, 0.4),   # None → 0.0 → 0.4
    ),
)
def test_bias_component_directional_linear_in_confidence(
    conf: Any, expected: float
) -> None:
    value, _ = _bias_component("BULLISH", conf)
    assert value == pytest.approx(expected)


@pytest.mark.parametrize("seed", (0, 1, 7, 13))
def test_bias_component_directional_value_in_band(seed: int) -> None:
    """Directional bias value always in [0.4, 1.0]."""
    rng = random.Random(seed)
    for _ in range(25):
        v, _ = _bias_component("BEARISH", rng.uniform(-2.0, 2.0))
        assert 0.4 <= v <= 1.0


# ---------------------------------------------------------------------------
# _vol_regime_component
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "", "   "))
def test_vol_regime_component_empty_label_returns_none(bad: str | None) -> None:
    value, detail = _vol_regime_component(bad, 0.5)
    assert value is None
    assert detail["label"] is None


@pytest.mark.parametrize("label", tuple(_VOL_REGIME_BASE_SCORES.keys()))
def test_vol_regime_component_confidence_zero_is_neutral_half(label: str) -> None:
    """``confidence == 0`` collapses any label to neutral 0.5."""
    value, _ = _vol_regime_component(label, 0.0)
    assert value == 0.5


@pytest.mark.parametrize(
    "label,base", tuple(_VOL_REGIME_BASE_SCORES.items()),
)
def test_vol_regime_component_full_confidence_returns_base(
    label: str, base: float
) -> None:
    value, _ = _vol_regime_component(label, 1.0)
    assert value == pytest.approx(base)


def test_vol_regime_component_unknown_label_treated_as_neutral_base() -> None:
    """Unknown label uses base == 0.5 → value always 0.5 regardless of conf."""
    for conf in (0.0, 0.5, 1.0):
        value, _ = _vol_regime_component("MOON", conf)
        assert value == 0.5


@pytest.mark.parametrize("seed", (0, 1, 7, 13))
def test_vol_regime_component_value_in_unit_interval(seed: int) -> None:
    rng = random.Random(seed)
    labels = list(_VOL_REGIME_BASE_SCORES.keys()) + ["UNKNOWN_X"]
    for _ in range(25):
        label = rng.choice(labels)
        value, _ = _vol_regime_component(label, rng.uniform(-2.0, 2.0))
        if value is not None:
            assert 0.0 <= value <= 1.0


# ---------------------------------------------------------------------------
# _scoring_component
# ---------------------------------------------------------------------------


def _scoring_result(**kw: Any) -> ScoringResult:
    defaults = dict(n_events=10, brier_score=0.2, log_score=0.5, hit_rate=0.6)
    defaults.update(kw)
    return ScoringResult(**defaults)


def test_scoring_component_none_returns_none() -> None:
    value, detail = _scoring_component(None)
    assert value is None
    assert detail == {"n_events": 0}


def test_scoring_component_empty_n_events_returns_none() -> None:
    value, _ = _scoring_component(_scoring_result(n_events=0))
    assert value is None


def test_scoring_component_perfect_blend_close_to_one() -> None:
    """brier=0, log=0, hit_rate=1, four families → blend = 1.0."""
    fams = {f"F{i}": object() for i in range(4)}
    value, _ = _scoring_component(_scoring_result(
        n_events=10, brier_score=0.0, log_score=0.0, hit_rate=1.0,
        family_metrics=fams,
    ))
    assert value == pytest.approx(1.0)


def test_scoring_component_worst_blend_close_to_zero() -> None:
    """brier=1, log=1.5, hit_rate=0, no families → blend = 0.0."""
    value, _ = _scoring_component(_scoring_result(
        n_events=10, brier_score=1.0, log_score=1.5, hit_rate=0.0,
        family_metrics={},
    ))
    assert value == pytest.approx(0.0)


@pytest.mark.parametrize("seed", (0, 1, 7, 13))
def test_scoring_component_value_in_unit_interval(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(25):
        sr = _scoring_result(
            n_events=rng.randint(1, 100),
            brier_score=rng.uniform(-0.5, 1.5),
            log_score=rng.uniform(-0.5, 2.5),
            hit_rate=rng.uniform(-0.5, 1.5),
            family_metrics={f"F{i}": object() for i in range(rng.randint(0, 6))},
        )
        value, _ = _scoring_component(sr)
        assert value is not None
        assert 0.0 <= value <= 1.0


def test_scoring_component_family_coverage_clamped_at_four() -> None:
    """family_count > 4 still maps to coverage = 1.0 (clamped)."""
    fams_4 = _scoring_component(_scoring_result(
        n_events=10, brier_score=0.0, log_score=0.0, hit_rate=1.0,
        family_metrics={f"F{i}": object() for i in range(4)},
    ))[0]
    fams_10 = _scoring_component(_scoring_result(
        n_events=10, brier_score=0.0, log_score=0.0, hit_rate=1.0,
        family_metrics={f"F{i}": object() for i in range(10)},
    ))[0]
    assert fams_4 == fams_10 == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# _history_component
# ---------------------------------------------------------------------------


def test_history_component_no_rows_returns_none() -> None:
    value, _ = _history_component(_scoring_result(), [])
    assert value is None


def test_history_component_no_scoring_result_returns_none() -> None:
    value, _ = _history_component(None, [{"brier_score": 0.2}])
    assert value is None


def test_history_component_no_valid_baselines_returns_none() -> None:
    """Rows with no numeric baseline fields → all sub_scores empty → None."""
    rows = [{"junk": "x"}, {}]
    value, _ = _history_component(_scoring_result(), rows)
    assert value is None


def test_history_component_matches_or_beats_history_scores_high() -> None:
    """Current scoring matches the baseline exactly → sub-scores all 1.0."""
    sr = _scoring_result(n_events=10, brier_score=0.2, log_score=0.5)
    rows = [{"brier_score": 0.2, "log_score": 0.5, "n_events": 10}]
    value, detail = _history_component(sr, rows)
    assert value == pytest.approx(1.0)
    assert detail["history_runs"] == 1


def test_history_component_worse_than_history_drops_score() -> None:
    sr = _scoring_result(n_events=1, brier_score=0.9, log_score=1.5)
    rows = [{"brier_score": 0.1, "log_score": 0.2, "n_events": 100}]
    value, _ = _history_component(sr, rows)
    assert value is not None
    assert value < 0.5


@pytest.mark.parametrize("seed", (0, 1, 7, 13))
def test_history_component_value_in_unit_interval(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(20):
        sr = _scoring_result(
            n_events=rng.randint(1, 50),
            brier_score=rng.uniform(0.0, 1.0),
            log_score=rng.uniform(0.0, 1.5),
        )
        rows = [
            {
                "brier_score": rng.uniform(0.0, 1.0),
                "log_score": rng.uniform(0.0, 1.5),
                "n_events": rng.randint(1, 100),
            }
            for _ in range(rng.randint(1, 5))
        ]
        value, _ = _history_component(sr, rows)
        assert value is not None
        assert 0.0 <= value <= 1.0


def test_history_component_non_dict_rows_ignored() -> None:
    """Non-dict rows are silently filtered out."""
    sr = _scoring_result(n_events=10, brier_score=0.2, log_score=0.5)
    value, detail = _history_component(
        sr, ["not-a-dict", 42, None, {"brier_score": 0.2}]
    )
    assert value is not None
    assert detail["history_runs"] == 1


# ---------------------------------------------------------------------------
# build_ensemble_quality — aggregation invariants
# ---------------------------------------------------------------------------


def test_build_ensemble_quality_empty_inputs_yields_neutral_bias_only() -> None:
    """No inputs → only the bias component contributes (NEUTRAL → 0.5).

    ``_bias_component`` always returns a value (never ``None``) and the
    NEUTRAL branch fixes it at 0.5, so the aggregate is exactly 0.5 with
    ``active_weight == _DEFAULT_WEIGHTS['bias']``.
    """
    result = build_ensemble_quality()
    assert result.score == 0.5
    assert result.tier == "good"
    assert result.available_components == ["bias"]
    assert set(result.contributions) == {"bias"}


def test_build_ensemble_quality_all_components_dropped_yields_zero_low() -> None:
    """With every weight zeroed, ``active_weight == 0`` and score collapses to 0."""
    weights = {k: 0.0 for k in _DEFAULT_WEIGHTS}
    result = build_ensemble_quality(
        heuristic_quality=0.9,
        bias_direction="BULLISH",
        bias_confidence=1.0,
        weights=weights,
    )
    assert result.score == 0.0
    assert result.tier == "low"
    assert result.contributions == {}
    assert result.available_components == []


def test_build_ensemble_quality_score_in_unit_interval() -> None:
    """Aggregated score always in [0, 1] regardless of input scales."""
    result = build_ensemble_quality(
        heuristic_quality=2.5,            # over-range, clamped
        bias_direction="BULLISH",
        bias_confidence=10.0,             # over-range, clamped
        vol_regime_label="EXTREME",
        vol_regime_confidence=1.0,
        scoring_result=_scoring_result(n_events=10),
    )
    assert 0.0 <= result.score <= 1.0


def test_build_ensemble_quality_tier_matches_score_ladder() -> None:
    """``result.tier == _tier_from_score(result.score)`` is an invariant."""
    result = build_ensemble_quality(
        heuristic_quality=0.6,
        bias_direction="BULLISH",
        bias_confidence=0.5,
        vol_regime_label="NORMAL",
        vol_regime_confidence=0.8,
    )
    assert result.tier == _tier_from_score(result.score)


def test_build_ensemble_quality_contributions_normalised_by_active_weight() -> None:
    """With every other component suppressed via zero weights, ``score`` equals
    the single remaining component's clamped value (the active-weight
    normalisation cancels the weight out)."""
    suppress = {k: 0.0 for k in _DEFAULT_WEIGHTS if k != "heuristic"}
    result = build_ensemble_quality(heuristic_quality=0.42, weights=suppress)
    assert result.score == pytest.approx(0.42, abs=1e-6)
    assert result.available_components == ["heuristic"]


def test_build_ensemble_quality_weights_override_merged_with_defaults() -> None:
    """Caller-supplied weights merge with defaults (not replace them)."""
    result = build_ensemble_quality(
        heuristic_quality=0.5,
        weights={"heuristic": 0.99, "extra": 0.5},
    )
    assert result.weights["heuristic"] == 0.99
    # Other default keys still present.
    for k in _DEFAULT_WEIGHTS:
        if k != "heuristic":
            assert result.weights[k] == _DEFAULT_WEIGHTS[k]
    assert result.weights["extra"] == 0.5


def test_build_ensemble_quality_zero_or_negative_weight_excludes_component() -> None:
    """A non-positive weight drops the component from the aggregate."""
    result = build_ensemble_quality(
        heuristic_quality=0.9,
        bias_direction="BULLISH",
        bias_confidence=1.0,
        weights={"heuristic": 0.0, "bias": -0.1},
    )
    assert "heuristic" not in result.contributions
    assert "bias" not in result.contributions


def test_build_ensemble_quality_available_components_sorted() -> None:
    result = build_ensemble_quality(
        heuristic_quality=0.6,
        bias_direction="BULLISH",
        bias_confidence=0.5,
        vol_regime_label="NORMAL",
        vol_regime_confidence=0.8,
        scoring_result=_scoring_result(n_events=5),
    )
    assert result.available_components == sorted(result.available_components)


def test_build_ensemble_quality_contributions_rounded_to_six_places() -> None:
    """Every contribution value/weight/weighted_value rounded to 6 dp."""
    result = build_ensemble_quality(
        heuristic_quality=1.0 / 3.0,
        bias_direction="BULLISH",
        bias_confidence=1.0 / 7.0,
        vol_regime_label="NORMAL",
        vol_regime_confidence=1.0 / 11.0,
    )
    for c in result.contributions.values():
        for k in ("value", "weight", "weighted_value"):
            assert round(c[k], 6) == c[k]


def test_build_ensemble_quality_score_rounded_to_six_places() -> None:
    result = build_ensemble_quality(heuristic_quality=1.0 / 3.0)
    assert round(result.score, 6) == result.score


def test_build_ensemble_quality_generated_at_passthrough() -> None:
    """Caller-supplied ``generated_at`` is preserved exactly."""
    result = build_ensemble_quality(generated_at=1234567.5)
    assert result.generated_at == 1234567.5


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_build_ensemble_quality_property_random_inputs(seed: int) -> None:
    """Random plausible inputs always produce a well-formed result."""
    rng = random.Random(seed)
    for _ in range(15):
        result = build_ensemble_quality(
            heuristic_quality=rng.uniform(-0.5, 1.5),
            bias_direction=rng.choice(["BULLISH", "BEARISH", "NEUTRAL", None]),
            bias_confidence=rng.uniform(-0.5, 1.5),
            vol_regime_label=rng.choice(list(_VOL_REGIME_BASE_SCORES) + [None]),
            vol_regime_confidence=rng.uniform(-0.5, 1.5),
        )
        assert 0.0 <= result.score <= 1.0
        assert result.tier in {"low", "ok", "good", "high"}
        assert result.tier == _tier_from_score(result.score)
        assert math.isfinite(result.score)
