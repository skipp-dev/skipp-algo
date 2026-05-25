"""Property tests for ``smc_core.fvg_quality`` scoring primitives.

Pins the mathematical invariants of the FVG quality-scoring building
blocks that the calibration report stratifies on and that the Phase-E
gate-on-quality wiring will eventually multiply into family weights:

  * :func:`smc_core.fvg_quality._clamp`
  * :func:`smc_core.fvg_quality._logistic`
  * :func:`smc_core.fvg_quality._component_gap`
  * :func:`smc_core.fvg_quality._component_distance`
  * :func:`smc_core.fvg_quality._component_hurst`
  * :func:`smc_core.fvg_quality.rolling_hurst`
  * :func:`smc_core.fvg_quality.score_fvg` (strict-default and lenient)

Continues the PQ Re-Audit Tier-1 spillover series
(PR #2350, #2363, #2366, #2370, #2371, #2372). Pure stdlib; ≤ 2s.
"""

from __future__ import annotations

import math
import random

import pytest

from smc_core.fvg_quality import (
    DEFAULT_DIRECTIONS,
    DEFAULT_MEANS,
    DEFAULT_WEIGHTS,
    LENIENT_DIRECTIONS,
    LENIENT_MEANS,
    LENIENT_WEIGHTS,
    STRICT_V1_NO_HURST_WEIGHTS,
    _clamp,
    _component_distance,
    _component_gap,
    _component_hurst,
    _logistic,
    rolling_hurst,
    score_events,
    score_fvg,
)

# ---------------------------------------------------------------------------
# _clamp — bounds, idempotency, pass-through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,lo,hi,expected",
    (
        (0.5, 0.0, 1.0, 0.5),     # interior pass-through
        (-1.0, 0.0, 1.0, 0.0),    # below
        (2.0, 0.0, 1.0, 1.0),     # above
        (0.0, 0.0, 1.0, 0.0),     # exact lower
        (1.0, 0.0, 1.0, 1.0),     # exact upper
        (-5.0, -10.0, -1.0, -5.0),
        (-100.0, -10.0, -1.0, -10.0),
    ),
)
def test_clamp_bounds_and_passthrough(
    value: float, lo: float, hi: float, expected: float
) -> None:
    assert _clamp(value, lo, hi) == expected


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_clamp_idempotent(seed: int) -> None:
    """``clamp(clamp(v, lo, hi), lo, hi) == clamp(v, lo, hi)``."""
    rng = random.Random(seed)
    for _ in range(30):
        v = rng.uniform(-100.0, 100.0)
        lo = rng.uniform(-10.0, 0.0)
        hi = rng.uniform(0.0, 10.0)
        once = _clamp(v, lo, hi)
        twice = _clamp(once, lo, hi)
        assert once == twice


# ---------------------------------------------------------------------------
# _logistic — range, monotonicity, overflow safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "x", (-1000.0, -10.0, -1.0, 0.0, 1.0, 10.0, 1000.0)
)
def test_logistic_range_unit_interval(x: float) -> None:
    """``_logistic(x) ∈ [0, 1]`` and finite for any input incl. overflow."""
    y = _logistic(x)
    assert math.isfinite(y)
    assert 0.0 <= y <= 1.0


def test_logistic_at_zero_is_half() -> None:
    assert _logistic(0.0) == pytest.approx(0.5)


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_logistic_strictly_monotone_in_non_saturated_range(seed: int) -> None:
    """``x1 < x2`` ⇒ ``_logistic(x1) < _logistic(x2)`` for |x| ≤ 10."""
    rng = random.Random(seed)
    xs = sorted(rng.uniform(-10.0, 10.0) for _ in range(30))
    ys = [_logistic(x) for x in xs]
    for i in range(1, len(ys)):
        assert ys[i] > ys[i - 1]


# ---------------------------------------------------------------------------
# _component_gap / _component_distance / _component_hurst — anchors + range
# ---------------------------------------------------------------------------


def test_component_gap_anchor_at_one_atr_is_half() -> None:
    """Per the docstring: 1 ATR → 0.5 (logistic centred at 1 ATR)."""
    assert _component_gap(1.0) == pytest.approx(0.5)


@pytest.mark.parametrize("gap", (0.0, 0.3, 1.0, 2.0, 5.0, 100.0))
def test_component_gap_in_unit_interval(gap: float) -> None:
    y = _component_gap(gap)
    assert math.isfinite(y) and 0.0 <= y <= 1.0


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_component_gap_monotone_in_gap(seed: int) -> None:
    rng = random.Random(seed)
    gaps = sorted(rng.uniform(0.0, 5.0) for _ in range(25))
    ys = [_component_gap(g) for g in gaps]
    for i in range(1, len(ys)):
        assert ys[i] >= ys[i - 1]


def test_component_distance_anchor_at_zero_is_one() -> None:
    """0 ATR away → maximum closeness score of 1.0."""
    assert _component_distance(0.0) == 1.0


@pytest.mark.parametrize("d", (0.0, 0.5, 1.0, 3.0, 10.0, 1e9))
def test_component_distance_in_unit_interval(d: float) -> None:
    y = _component_distance(d)
    assert math.isfinite(y) and 0.0 <= y <= 1.0


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_component_distance_monotone_non_increasing(seed: int) -> None:
    rng = random.Random(seed)
    ds = sorted(rng.uniform(0.0, 10.0) for _ in range(25))
    ys = [_component_distance(d) for d in ds]
    for i in range(1, len(ys)):
        assert ys[i] <= ys[i - 1]


def test_component_hurst_none_is_neutral_half() -> None:
    """Unmeasurable Hurst → neutral 0.5 (no reward, no penalty)."""
    assert _component_hurst(None) == 0.5


@pytest.mark.parametrize(
    "h,expected",
    (
        (0.5, 0.5),
        (0.7, pytest.approx(0.8)),
        (0.3, pytest.approx(0.2)),
        (0.0, pytest.approx(0.0)),     # clamped at lower edge
        (1.0, pytest.approx(1.0)),     # clamped at upper edge
        (2.0, 1.0),                    # extreme → clamped
        (-1.0, 0.0),                   # extreme → clamped
    ),
)
def test_component_hurst_linear_anchor_and_clamp(h: float, expected: float) -> None:
    assert _component_hurst(h) == expected


# ---------------------------------------------------------------------------
# rolling_hurst — degenerate-input contract + range
# ---------------------------------------------------------------------------


def test_rolling_hurst_short_series_returns_none() -> None:
    """< 16 samples → None (insufficient for an R/S estimate)."""
    assert rolling_hurst([100.0] * 15) is None
    assert rolling_hurst([]) is None


def test_rolling_hurst_flat_series_returns_none() -> None:
    """Flat series → R/S range collapses → None."""
    assert rolling_hurst([100.0] * 32) is None


def test_rolling_hurst_zero_or_negative_close_skipped() -> None:
    """Non-positive closes are filtered out before the log-return step."""
    closes = [100.0] * 8 + [0.0] * 4 + [100.0] * 8  # too few valid returns
    assert rolling_hurst(closes) is None


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_rolling_hurst_in_unit_interval_for_random_walk(seed: int) -> None:
    """Random-walk returns yield a finite Hurst estimate in [0, 1]."""
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(127):
        closes.append(closes[-1] * math.exp(rng.gauss(0.0, 0.01)))
    h = rolling_hurst(closes)
    assert h is not None
    assert math.isfinite(h)
    assert 0.0 <= h <= 1.0


def test_rolling_hurst_deterministic_for_same_input() -> None:
    """Pure function: same input ⇒ identical output (no hidden state)."""
    rng = random.Random(2026)
    closes = [100.0]
    for _ in range(63):
        closes.append(closes[-1] * math.exp(rng.gauss(0.0, 0.01)))
    a = rolling_hurst(closes)
    b = rolling_hurst(closes)
    assert a == b


# ---------------------------------------------------------------------------
# score_fvg — score range, multiplier mapping, tier ladder, defaults
# ---------------------------------------------------------------------------


def _lenient_kwargs() -> dict:
    return {
        "weights": LENIENT_WEIGHTS,
        "directions": LENIENT_DIRECTIONS,
        "means": LENIENT_MEANS,
    }


def _maxed_event() -> dict:
    # NB: ``distance_to_price_atr`` uses ``... or 10.0`` in production,
    # which treats 0.0 as falsy and overrides to 10.0 — a small,
    # documented quirk. Use 0.01 to stay just above zero while still
    # producing the maximum closeness signal (~0.99).
    return {
        "gap_size_atr": 5.0,
        "htf_aligned": True,
        "distance_to_price_atr": 0.01,
        "is_full_body": True,
        "hurst": 0.95,
    }


def _minimal_event() -> dict:
    return {
        "gap_size_atr": 0.0,
        "htf_aligned": False,
        "distance_to_price_atr": 10.0,
        "is_full_body": False,
        "hurst": 0.05,
    }


def test_score_fvg_lenient_maxed_features_score_high() -> None:
    """Lenient regime: all-max features → score ≥ 0.70 → HIGH tier."""
    out = score_fvg(_maxed_event(), **_lenient_kwargs())
    assert out.score >= 0.70
    assert out.tier == "HIGH"


def test_score_fvg_strict_default_minimal_features_score_high() -> None:
    """Strict default: minimal features → score ≥ 0.70 → HIGH tier.

    Inverted semantics relative to lenient — pinned by the production
    promotion of ``strict_v1_no_hurst`` (audit §2–3).
    """
    out = score_fvg(_minimal_event())
    assert out.score >= 0.70
    assert out.tier == "HIGH"


def test_score_fvg_strict_default_maxed_features_score_low() -> None:
    """Strict default: maxed features → score collapses → LOW tier."""
    out = score_fvg(_maxed_event())
    assert out.score < 0.5
    assert out.tier == "LOW"


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_score_fvg_score_in_unit_interval(seed: int) -> None:
    """``score ∈ [0, 1]`` for any random plausible event under both regimes."""
    rng = random.Random(seed)
    for _ in range(30):
        event = {
            "gap_size_atr": rng.uniform(0.0, 5.0),
            "htf_aligned": rng.random() < 0.5,
            "distance_to_price_atr": rng.uniform(0.0, 10.0),
            "is_full_body": rng.random() < 0.5,
            "hurst": rng.uniform(0.0, 1.0),
        }
        for kwargs in (_lenient_kwargs(), {}):
            out = score_fvg(event, **kwargs)
            assert 0.0 <= out.score <= 1.0
            assert math.isfinite(out.score)


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_score_fvg_multiplier_linear_in_score(seed: int) -> None:
    """``multiplier == round(0.5 + 1.0 * score, 4) ∈ [0.5, 1.5]``."""
    rng = random.Random(seed)
    for _ in range(30):
        event = {
            "gap_size_atr": rng.uniform(0.0, 5.0),
            "htf_aligned": rng.random() < 0.5,
            "distance_to_price_atr": rng.uniform(0.0, 10.0),
            "is_full_body": rng.random() < 0.5,
            "hurst": rng.uniform(0.0, 1.0),
        }
        out = score_fvg(event, **_lenient_kwargs())
        expected = round(0.5 + out.score, 4)
        assert out.multiplier == expected
        assert 0.5 <= out.multiplier <= 1.5


@pytest.mark.parametrize(
    "score_proxy_event,expected_tier",
    (
        # Lenient regime: high score ⇒ HIGH; mid ⇒ MEDIUM; low ⇒ LOW.
        (_maxed_event(), "HIGH"),
        (_minimal_event(), "LOW"),
    ),
)
def test_score_fvg_tier_ladder_lenient(
    score_proxy_event: dict, expected_tier: str
) -> None:
    out = score_fvg(score_proxy_event, **_lenient_kwargs())
    assert out.tier == expected_tier


@pytest.mark.parametrize(
    "score,expected_tier",
    (
        (0.95, "HIGH"),
        (0.70, "HIGH"),     # boundary `>=`
        (0.6999, "MEDIUM"),
        (0.50, "MEDIUM"),   # boundary `>=`
        (0.4999, "LOW"),
        (0.0, "LOW"),
    ),
)
def test_tier_ladder_thresholds_via_synthetic_score(
    score: float, expected_tier: str
) -> None:
    """Tier ladder cutoffs HIGH ≥ 0.70, MEDIUM ≥ 0.50, else LOW.

    Routed through ``score_fvg`` by passing a custom lenient weights
    dict (htf_aligned carries the full score) to produce a deterministic
    interior score; this avoids coupling the test to the inverted strict
    semantics.
    """
    # Drive the score directly via htf_aligned (binary 0/1) and tweak
    # the lenient weights so htf carries the full score.
    weights = {k: 0.0 for k in LENIENT_WEIGHTS}
    weights["htf_aligned"] = score  # contributes `score * 1` when aligned
    out = score_fvg(
        {"htf_aligned": True},
        weights=weights,
        directions=LENIENT_DIRECTIONS,
        means=LENIENT_MEANS,
    )
    assert out.tier == expected_tier


def test_score_fvg_components_rounded_to_four_places() -> None:
    """All component values are rounded to 4 decimal places in the output."""
    out = score_fvg(_maxed_event(), **_lenient_kwargs())
    for k, v in out.components.items():
        # round(v, 4) == v ⇔ v already has ≤4 decimals
        assert round(v, 4) == v, f"component {k} not rounded to 4dp: {v!r}"


def test_score_fvg_missing_keys_treated_as_worst_case() -> None:
    """Missing event keys → 0 / False / None (per docstring contract)."""
    empty = score_fvg({}, **_lenient_kwargs())
    minimal = score_fvg(
        {
            "gap_size_atr": 0.0,
            "htf_aligned": False,
            "distance_to_price_atr": 10.0,
            "is_full_body": False,
            "hurst": None,
        },
        **_lenient_kwargs(),
    )
    # Under lenient, both should produce the same low score / LOW tier.
    assert empty.score == minimal.score
    assert empty.tier == minimal.tier == "LOW"


def test_score_fvg_invalid_hurst_routes_to_neutral() -> None:
    """Non-numeric or non-finite hurst is coerced to None → neutral 0.5."""
    for bad in ("abc", float("nan"), float("inf"), None):
        out = score_fvg(
            {"hurst": bad, "gap_size_atr": 0.0, "htf_aligned": False,
             "distance_to_price_atr": 10.0, "is_full_body": False},
            **_lenient_kwargs(),
        )
        assert out.components["hurst"] == 0.5


def test_score_fvg_pure_function_identical_input_identical_output() -> None:
    """Determinism: same event ⇒ identical FvgQualityScore."""
    e = _maxed_event()
    a = score_fvg(e)
    b = score_fvg(e)
    assert a == b


def test_score_events_preserves_order_and_count() -> None:
    """Vectorised wrapper preserves input order."""
    events = [_maxed_event(), _minimal_event(), _maxed_event()]
    scores = score_events(events)
    assert len(scores) == len(events)
    # Strict default: maxed → low, minimal → high.
    assert scores[0].tier == "LOW"
    assert scores[1].tier == "HIGH"
    assert scores[2].tier == "LOW"


def test_default_weights_is_strict_regime() -> None:
    """Production default == ``STRICT_V1_NO_HURST_WEIGHTS`` (audit pin)."""
    assert DEFAULT_WEIGHTS is STRICT_V1_NO_HURST_WEIGHTS
    assert DEFAULT_DIRECTIONS["hurst_50"] == 0  # hurst disabled under strict
    assert all(v == 0.5 for v in DEFAULT_MEANS.values())


def test_lenient_weights_sum_to_one() -> None:
    """Legacy weight pin: lenient weights sum exactly to 1.0."""
    assert sum(LENIENT_WEIGHTS.values()) == pytest.approx(1.0)
