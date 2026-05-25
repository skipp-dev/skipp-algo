"""Property tests for ``smc_core.vol_regime`` classifier primitives.

Pins the mathematical invariants of the two pure mapping functions that
drive every downstream volatility-regime / volume-regime label in the
snapshot pipeline:

  * :func:`smc_core.vol_regime._classify` — ATR-ratio → regime label
  * :func:`smc_core.vol_regime.classify_volume_regime_from_rvol`
        — relative-volume → volume-regime label + thin-fraction

Continues the PQ Re-Audit Tier-1 spillover series (PR #2350, #2363,
#2366, #2370). Pure stdlib (``math`` + ``random``); ≤ 1s runtime.
"""

from __future__ import annotations

import math
import random

import pytest

from smc_core.vol_regime import _classify, classify_volume_regime_from_rvol

# ---------------------------------------------------------------------------
# _classify(atr_ratio) — boundary + monotonicity invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ratio,expected",
    (
        # Exact threshold values (boundary semantics).
        (0.0, "LOW_VOL"),
        (0.5, "LOW_VOL"),     # `<= 0.5` → LOW_VOL
        (1.5, "HIGH_VOL"),    # `>= 1.5` → HIGH_VOL
        (2.5, "EXTREME"),     # `>= 2.5` → EXTREME
        # Just-inside / just-outside each band.
        (0.499999, "LOW_VOL"),
        (0.500001, "NORMAL"),
        (1.0, "NORMAL"),
        (1.499999, "NORMAL"),
        (1.500001, "HIGH_VOL"),
        (2.499999, "HIGH_VOL"),
        (2.500001, "EXTREME"),
        # Far-extremes.
        (1e-9, "LOW_VOL"),
        (1e9, "EXTREME"),
    ),
)
def test_classify_threshold_boundaries(ratio: float, expected: str) -> None:
    """Boundary semantics: LOW_VOL ≤ 0.5 < NORMAL < 1.5 ≤ HIGH_VOL < 2.5 ≤ EXTREME."""
    assert _classify(ratio) == expected


_REGIME_ORDER = {"LOW_VOL": 0, "NORMAL": 1, "HIGH_VOL": 2, "EXTREME": 3}


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42, 99))
def test_classify_monotone_non_decreasing(seed: int) -> None:
    """``r1 <= r2`` ⇒ ``order(_classify(r1)) <= order(_classify(r2))``."""
    rng = random.Random(seed)
    ratios = sorted(rng.uniform(0.0, 3.5) for _ in range(40))
    levels = [_REGIME_ORDER[_classify(r)] for r in ratios]
    for i in range(1, len(levels)):
        assert levels[i] >= levels[i - 1], (
            f"classify not monotone at r={ratios[i - 1]!r} → {ratios[i]!r}: "
            f"{levels[i - 1]} → {levels[i]}"
        )


@pytest.mark.parametrize(
    "ratio",
    (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 10.0),
)
def test_classify_output_in_known_label_set(ratio: float) -> None:
    """Output is always one of the four documented labels."""
    assert _classify(ratio) in {"LOW_VOL", "NORMAL", "HIGH_VOL", "EXTREME"}


# ---------------------------------------------------------------------------
# classify_volume_regime_from_rvol — boundary + thin-fraction invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rvol,expected_label",
    (
        # Boundary values (`<=` semantics at each cutoff).
        (0.35, "HOLIDAY_SUSPECT"),
        (0.85, "LOW_VOLUME"),
        # Just inside each band.
        (0.001, "HOLIDAY_SUSPECT"),
        (0.349999, "HOLIDAY_SUSPECT"),
        (0.350001, "LOW_VOLUME"),
        (0.5, "LOW_VOLUME"),
        (0.849999, "LOW_VOLUME"),
        (0.850001, "NORMAL"),
        (1.0, "NORMAL"),
        (2.5, "NORMAL"),
        (1e6, "NORMAL"),
    ),
)
def test_volume_regime_threshold_boundaries(rvol: float, expected_label: str) -> None:
    """Boundary semantics: HOLIDAY_SUSPECT ≤ 0.35 < LOW_VOLUME ≤ 0.85 < NORMAL."""
    label, thin = classify_volume_regime_from_rvol(rvol)
    assert label == expected_label
    assert thin is not None
    assert 0.0 <= thin <= 1.0


@pytest.mark.parametrize(
    "bad",
    (
        None, "", "abc", float("nan"), float("inf"), float("-inf"),
        0.0, -0.0, -0.001, -1.0, -1e9,
    ),
)
def test_volume_regime_unknown_on_invalid_input(bad: object) -> None:
    """Non-numeric, NaN, non-finite, and non-positive ``rvol`` → UNKNOWN/None."""
    label, thin = classify_volume_regime_from_rvol(bad)
    assert label == "UNKNOWN"
    assert thin is None


@pytest.mark.parametrize(
    "rvol",
    (1.0, 1.0000001, 1.5, 2.0, 10.0, 1e6),
)
def test_volume_regime_thin_fraction_zero_when_rvol_ge_one(rvol: float) -> None:
    """``rvol >= 1`` clips ``thin_fraction`` to exactly 0.0."""
    _, thin = classify_volume_regime_from_rvol(rvol)
    assert thin == 0.0


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_volume_regime_thin_fraction_matches_one_minus_rvol(seed: int) -> None:
    """For ``rvol ∈ (0, 1]``, ``thin_fraction == round(1 - rvol, 4)``."""
    rng = random.Random(seed)
    for _ in range(40):
        rvol = rng.uniform(1e-6, 1.0)
        _, thin = classify_volume_regime_from_rvol(rvol)
        assert thin is not None
        assert thin == pytest.approx(round(1.0 - rvol, 4), abs=1e-9)


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_volume_regime_thin_fraction_monotone_non_increasing(seed: int) -> None:
    """``r1 <= r2`` ⇒ ``thin(r1) >= thin(r2)`` (more volume ⇒ less thin)."""
    rng = random.Random(seed)
    rvols = sorted(rng.uniform(1e-6, 3.0) for _ in range(30))
    thins = [classify_volume_regime_from_rvol(r)[1] for r in rvols]
    assert all(t is not None for t in thins)
    for i in range(1, len(thins)):
        assert thins[i] <= thins[i - 1] + 1e-9, (
            f"thin_fraction not monotone non-increasing at r={rvols[i - 1]!r} → "
            f"{rvols[i]!r}: {thins[i - 1]!r} → {thins[i]!r}"
        )


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_volume_regime_label_monotone_non_decreasing(seed: int) -> None:
    """``r1 <= r2`` ⇒ ``order(label(r1)) <= order(label(r2))`` over valid rvol."""
    order = {"HOLIDAY_SUSPECT": 0, "LOW_VOLUME": 1, "NORMAL": 2}
    rng = random.Random(seed)
    rvols = sorted(rng.uniform(1e-6, 3.0) for _ in range(30))
    levels = [order[classify_volume_regime_from_rvol(r)[0]] for r in rvols]
    for i in range(1, len(levels)):
        assert levels[i] >= levels[i - 1], (
            f"volume label not monotone at r={rvols[i - 1]!r} → {rvols[i]!r}: "
            f"{levels[i - 1]} → {levels[i]}"
        )


@pytest.mark.parametrize(
    "rvol",
    (1e-6, 0.1, 0.35, 0.5, 0.85, 1.0, 1.5, 5.0),
)
def test_volume_regime_thin_fraction_in_unit_interval(rvol: float) -> None:
    """``thin_fraction`` always lives in ``[0, 1]`` for any valid ``rvol``."""
    _, thin = classify_volume_regime_from_rvol(rvol)
    assert thin is not None
    assert 0.0 <= thin <= 1.0
    assert math.isfinite(thin)


@pytest.mark.parametrize(
    "rvol_str",
    ("0.5", "1.0", "0.85", "  0.35 "),
)
def test_volume_regime_accepts_numeric_strings(rvol_str: str) -> None:
    """Stringified numerics are coerced via ``float`` and route normally."""
    label, thin = classify_volume_regime_from_rvol(rvol_str)
    assert label != "UNKNOWN"
    assert thin is not None
