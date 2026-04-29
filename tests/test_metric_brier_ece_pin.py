"""Closed-form pins for ``_metric_brier`` and ``_metric_ece``.

Both helpers live in ``scripts.run_ab_comparison`` and are part of
the ADR-0005 measurement-runtime surface (`docs/adr/0005-pure-stdlib-measurement-runtime.md`).
They feed the calibration-FDR layer (PR #117) and the comparison-row
metrics. Subtle re-implementations (e.g. dropping the
``min(int(p*bins), bins-1)`` clamp, mis-applying weights, or swapping
the squared-error formula) would silently shift Brier/ECE for every
A/B run.

Pinned with stdlib-only reference computations — no scipy/sklearn.
"""

from __future__ import annotations

import math

from scripts.run_ab_comparison import _metric_brier, _metric_ece

# ---------------------------------------------------------------------------
# Brier: mean((p - o)^2)
# ---------------------------------------------------------------------------


def test_brier_perfect_prediction_is_zero() -> None:
    """All predictions match outcomes → Brier = 0."""
    events = [(1.0, True), (1.0, True), (0.0, False), (0.0, False)]
    assert _metric_brier(events) == 0.0


def test_brier_worst_prediction_is_one() -> None:
    """All predictions inverted from outcomes → Brier = 1."""
    events = [(1.0, False), (1.0, False), (0.0, True), (0.0, True)]
    assert _metric_brier(events) == 1.0


def test_brier_uniform_50_50_random_baseline() -> None:
    """All predictions = 0.5 → Brier = 0.25 regardless of outcomes."""
    for outcomes in ([True, False], [True, True], [False, False, False, False]):
        events = [(0.5, o) for o in outcomes]
        assert _metric_brier(events) == 0.25


def test_brier_single_event_closed_form() -> None:
    # (0.7, True) → (0.7 - 1.0)^2 = 0.09
    assert math.isclose(_metric_brier([(0.7, True)]), 0.09, abs_tol=1e-12)
    # (0.3, False) → (0.3 - 0.0)^2 = 0.09
    assert math.isclose(_metric_brier([(0.3, False)]), 0.09, abs_tol=1e-12)


def test_brier_empty_returns_nan() -> None:
    assert math.isnan(_metric_brier([]))


def test_brier_two_event_average() -> None:
    # [(0.8, True), (0.4, False)]:
    # squared errors = (0.8-1)^2 + (0.4-0)^2 = 0.04 + 0.16 = 0.20
    # mean = 0.10
    assert math.isclose(
        _metric_brier([(0.8, True), (0.4, False)]),
        0.10,
        abs_tol=1e-12,
    )


# ---------------------------------------------------------------------------
# ECE: weighted |avg_prob - avg_outcome| per bin
# ---------------------------------------------------------------------------


def test_ece_perfect_calibration_is_zero() -> None:
    """In each bin, mean(prob) == mean(outcome) → ECE = 0."""
    # Bin 5 (p=0.5–0.6): two events, 1 hit → mean_prob=0.55, mean_o=0.5? No.
    # Use exact-bin alignment: every event has p == its bin-midpoint and
    # outcomes match prob exactly.
    events = [(0.0, False), (0.0, False), (1.0, True), (1.0, True)]
    assert _metric_ece(events) == 0.0


def test_ece_total_miscalibration_one_bucket() -> None:
    """All events in one bin with mean_prob=1.0, mean_outcome=0.0 → ECE = 1.0."""
    events = [(1.0, False) for _ in range(10)]
    assert _metric_ece(events) == 1.0


def test_ece_random_50_50_baseline() -> None:
    """All p=0.5 in one bin (bin 5), 50% hit rate → |0.5 - 0.5| = 0."""
    events = [(0.5, True), (0.5, False), (0.5, True), (0.5, False)]
    assert _metric_ece(events) == 0.0


def test_ece_all_p05_with_imbalanced_outcomes() -> None:
    """All p=0.5 in bin 5, 75% hit rate → weight=1, |0.5 - 0.75| = 0.25."""
    events = [(0.5, True), (0.5, True), (0.5, True), (0.5, False)]
    assert math.isclose(_metric_ece(events), 0.25, abs_tol=1e-12)


def test_ece_two_bins_weighted_average() -> None:
    """Two bins:
    Bin 1 (p in [0.1, 0.2)): two events at p=0.1, both False
      → mean_p=0.1, mean_o=0.0, |diff|=0.1, weight=2/4=0.5
    Bin 9 (p in [0.9, 1.0)): two events at p=0.9, both True
      → mean_p=0.9, mean_o=1.0, |diff|=0.1, weight=2/4=0.5
    ECE = 0.5*0.1 + 0.5*0.1 = 0.10
    """
    events = [(0.1, False), (0.1, False), (0.9, True), (0.9, True)]
    assert math.isclose(_metric_ece(events), 0.10, abs_tol=1e-12)


def test_ece_clips_probability_above_one() -> None:
    """``p`` outside [0, 1] is clipped before bin assignment."""
    # p=1.5 clips to 1.0 → bin 9 (last bin).
    events = [(1.5, True), (1.0, True)]
    # Both end up in bin 9 with mean_p=1.0, mean_o=1.0 → ECE = 0.
    assert _metric_ece(events) == 0.0


def test_ece_clips_negative_probability() -> None:
    events = [(-0.5, False), (0.0, False)]
    # Both clip to 0 → bin 0, mean_p=0, mean_o=0 → ECE = 0.
    assert _metric_ece(events) == 0.0


def test_ece_empty_returns_nan() -> None:
    assert math.isnan(_metric_ece([]))


def test_ece_in_unit_interval() -> None:
    """ECE is bounded in [0, 1] for any prob/outcome combination."""
    import random as _r

    rng = _r.Random(42)
    for _ in range(50):
        n = rng.randint(1, 50)
        events = [(rng.random(), rng.random() < 0.5) for _ in range(n)]
        ece = _metric_ece(events)
        assert 0.0 <= ece <= 1.0
