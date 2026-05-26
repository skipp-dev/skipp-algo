"""Property tests for ``smc_core.bias_merge`` HTF + session merge invariants.

Pins the merge contract that funnels every HTF + session bias signal
through a single deterministic ``BiasVerdict`` consumed by layering and
service orchestration:

  * :func:`smc_core.bias_merge._direction_from_counter`
  * :func:`smc_core.bias_merge._direction_from_killzones`
  * :func:`smc_core.bias_merge.merge_bias`

Continues the PQ Re-Audit Tier-1 spillover series
(PR #2350, #2363, #2366, #2370, #2371). Stdlib + pytest + ``smc_core.bias_merge``; ≤ 1s runtime.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from smc_core.bias_merge import (
    _direction_from_counter,
    _direction_from_killzones,
    merge_bias,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _htf_ctx(counter: int | None) -> dict[str, Any] | None:
    """Build an HTF context whose last fvg_bias_counter entry == ``counter``."""
    if counter is None:
        return None
    return {"fvg_bias_counter": [{"counter": counter}]}


def _session_ctx(
    *,
    high: float | None = None,
    low: float | None = None,
    mid: float | None = None,
) -> dict[str, Any] | None:
    """Build a session context with a single killzone."""
    if high is None and low is None and mid is None:
        return None
    return {"killzones": [{"high": high or 0.0, "low": low or 0.0, "mid": mid or 0.0}]}


# ---------------------------------------------------------------------------
# _direction_from_counter — sign-mapping invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "counter,expected",
    (
        (1, "BULLISH"),
        (10, "BULLISH"),
        (10_000, "BULLISH"),
        (-1, "BEARISH"),
        (-10, "BEARISH"),
        (-10_000, "BEARISH"),
        (0, "NEUTRAL"),
    ),
)
def test_direction_from_counter_sign_mapping(counter: int, expected: str) -> None:
    """Strict-sign mapping: ``>0 → BULLISH``, ``<0 → BEARISH``, ``==0 → NEUTRAL``."""
    assert _direction_from_counter(counter) == expected


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_direction_from_counter_label_set(seed: int) -> None:
    """Output always one of the three documented directions."""
    rng = random.Random(seed)
    for _ in range(50):
        c = rng.randint(-1_000, 1_000)
        assert _direction_from_counter(c) in {"BULLISH", "BEARISH", "NEUTRAL"}


# ---------------------------------------------------------------------------
# _direction_from_killzones — ratio-band invariants
# ---------------------------------------------------------------------------


def test_direction_from_killzones_empty_neutral() -> None:
    """Empty killzone list → NEUTRAL."""
    assert _direction_from_killzones([]) == "NEUTRAL"


@pytest.mark.parametrize(
    "high,low,mid,expected",
    (
        # Degenerate range (high == low) → NEUTRAL regardless of mid.
        (100.0, 100.0, 100.0, "NEUTRAL"),
        (100.0, 100.0, 50.0, "NEUTRAL"),
        # Mid exactly at top / bottom.
        (100.0, 0.0, 100.0, "BULLISH"),   # ratio = 1.0
        (100.0, 0.0, 0.0, "BEARISH"),     # ratio = 0.0
        # Mid at exact center → NEUTRAL band.
        (100.0, 0.0, 50.0, "NEUTRAL"),    # ratio = 0.5
        # Just inside the 0.55 / 0.45 cutoffs.
        (100.0, 0.0, 55.0, "NEUTRAL"),    # ratio = 0.55 (strict > 0.55)
        (100.0, 0.0, 55.01, "BULLISH"),
        (100.0, 0.0, 45.0, "NEUTRAL"),    # ratio = 0.45 (strict < 0.45)
        (100.0, 0.0, 44.99, "BEARISH"),
    ),
)
def test_direction_from_killzones_ratio_bands(
    high: float, low: float, mid: float, expected: str
) -> None:
    """Ratio bands: ``(mid-low)/(high-low) > 0.55 → BULLISH``, ``< 0.45 → BEARISH``."""
    out = _direction_from_killzones([{"high": high, "low": low, "mid": mid}])
    assert out == expected


def test_direction_from_killzones_uses_latest_entry_only() -> None:
    """Only the last killzone in the list drives the direction."""
    kz = [
        {"high": 100.0, "low": 0.0, "mid": 90.0},  # bullish — must be ignored
        {"high": 100.0, "low": 0.0, "mid": 10.0},  # bearish — drives result
    ]
    assert _direction_from_killzones(kz) == "BEARISH"


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_direction_from_killzones_monotone_in_mid(seed: int) -> None:
    """For a fixed (high, low) range, the direction is monotone in ``mid``
    along the ladder ``BEARISH < NEUTRAL < BULLISH``."""
    order = {"BEARISH": 0, "NEUTRAL": 1, "BULLISH": 2}
    rng = random.Random(seed)
    high = rng.uniform(10.0, 100.0)
    low = 0.0
    mids = sorted(rng.uniform(low, high) for _ in range(40))
    levels = [
        order[_direction_from_killzones([{"high": high, "low": low, "mid": m}])]
        for m in mids
    ]
    for i in range(1, len(levels)):
        assert levels[i] >= levels[i - 1], (
            f"direction not monotone in mid at {mids[i - 1]!r} → {mids[i]!r}: "
            f"{levels[i - 1]} → {levels[i]}"
        )


# ---------------------------------------------------------------------------
# merge_bias — merge contract invariants
# ---------------------------------------------------------------------------


def test_merge_bias_both_missing_returns_neutral_none() -> None:
    """Both contexts absent → NEUTRAL / conf=0 / source=NONE / no conflict."""
    v = merge_bias(None, None)
    assert v.direction == "NEUTRAL"
    assert v.confidence == 0.0
    assert v.htf_direction == "NEUTRAL"
    assert v.session_direction == "NEUTRAL"
    assert v.conflict is False
    assert v.source == "NONE"


@pytest.mark.parametrize("ctx", ({}, {"fvg_bias_counter": []}, {"fvg_bias_counter": None}))
def test_merge_bias_empty_htf_treated_as_unavailable(ctx: dict[str, Any]) -> None:
    """Empty / null fvg_bias_counter does not count as HTF available."""
    v = merge_bias(ctx, None)
    assert v.source == "NONE"
    assert v.direction == "NEUTRAL"


@pytest.mark.parametrize(
    "session_dir_input,expected",
    (
        ((100.0, 0.0, 90.0), "BULLISH"),
        ((100.0, 0.0, 10.0), "BEARISH"),
        ((100.0, 0.0, 50.0), "NEUTRAL"),
    ),
)
def test_merge_bias_session_only_fallback(
    session_dir_input: tuple[float, float, float], expected: str
) -> None:
    """HTF absent → session bias drives, confidence == 0.5, source == SESSION."""
    high, low, mid = session_dir_input
    v = merge_bias(None, _session_ctx(high=high, low=low, mid=mid))
    assert v.source == "SESSION"
    assert v.direction == expected
    assert v.session_direction == expected
    assert v.htf_direction == "NEUTRAL"
    assert v.confidence == 0.5
    assert v.conflict is False


@pytest.mark.parametrize(
    "counter,expected_dir",
    ((5, "BULLISH"), (-5, "BEARISH"), (0, "NEUTRAL")),
)
def test_merge_bias_htf_only_source_is_HTF(counter: int, expected_dir: str) -> None:
    """HTF available, session absent → source=HTF, direction=HTF dir."""
    v = merge_bias(_htf_ctx(counter), None)
    assert v.source == "HTF"
    assert v.direction == expected_dir
    assert v.htf_direction == expected_dir
    assert v.session_direction == "NEUTRAL"
    assert v.conflict is False


@pytest.mark.parametrize("counter", (1, 5, -1, -5))
def test_merge_bias_concordant_bonus(counter: int) -> None:
    """HTF == session (both non-NEUTRAL) → conf = round(0.8 * 1.15, 4) = 0.92."""
    mid = 90.0 if counter > 0 else 10.0
    v = merge_bias(_htf_ctx(counter), _session_ctx(high=100.0, low=0.0, mid=mid))
    assert v.source == "MERGED"
    assert v.conflict is False
    assert v.confidence == 0.92
    assert v.direction == v.htf_direction


@pytest.mark.parametrize("counter", (1, 5, -1, -5))
def test_merge_bias_conflict_reduces_confidence(counter: int) -> None:
    """HTF != session (both non-NEUTRAL) → conf = round(0.8 * 0.6, 4) = 0.48."""
    mid = 10.0 if counter > 0 else 90.0  # opposite of HTF
    v = merge_bias(_htf_ctx(counter), _session_ctx(high=100.0, low=0.0, mid=mid))
    assert v.source == "MERGED"
    assert v.conflict is True
    assert v.confidence == 0.48
    # HTF still dominates direction even on conflict.
    assert v.direction == v.htf_direction


@pytest.mark.parametrize("counter", (1, -1, 5, -5))
def test_merge_bias_session_neutral_no_bonus_no_conflict(counter: int) -> None:
    """Session NEUTRAL never triggers conflict and never bonus → conf = 0.8."""
    v = merge_bias(_htf_ctx(counter), _session_ctx(high=100.0, low=0.0, mid=50.0))
    assert v.session_direction == "NEUTRAL"
    assert v.conflict is False
    assert v.confidence == 0.8
    assert v.source == "MERGED"
    assert v.direction == v.htf_direction


def test_merge_bias_htf_neutral_no_conflict_with_directional_session() -> None:
    """HTF NEUTRAL + session directional → no conflict (conflict requires both non-NEUTRAL)."""
    v = merge_bias(_htf_ctx(0), _session_ctx(high=100.0, low=0.0, mid=90.0))
    assert v.htf_direction == "NEUTRAL"
    assert v.session_direction == "BULLISH"
    assert v.conflict is False
    # HTF still dominates: direction = NEUTRAL.
    assert v.direction == "NEUTRAL"
    assert v.source == "MERGED"


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_merge_bias_confidence_in_unit_interval(seed: int) -> None:
    """``confidence ∈ [0, 1]`` for any input combination."""
    rng = random.Random(seed)
    for _ in range(40):
        c = rng.choice((None, rng.randint(-10, 10)))
        if rng.random() < 0.3:
            session = None
        else:
            session = _session_ctx(
                high=rng.uniform(10.0, 100.0),
                low=0.0,
                mid=rng.uniform(0.0, 100.0),
            )
        v = merge_bias(_htf_ctx(c), session)
        assert 0.0 <= v.confidence <= 1.0, f"confidence out of [0,1]: {v.confidence!r}"


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_merge_bias_htf_dominates_direction_when_available(seed: int) -> None:
    """When HTF is available, ``verdict.direction == verdict.htf_direction``
    regardless of session — HTF is the directional anchor."""
    rng = random.Random(seed)
    for _ in range(40):
        c = rng.randint(-10, 10)
        if rng.random() < 0.3:
            session = None
        else:
            session = _session_ctx(
                high=rng.uniform(10.0, 100.0),
                low=0.0,
                mid=rng.uniform(0.0, 100.0),
            )
        v = merge_bias(_htf_ctx(c), session)
        assert v.direction == v.htf_direction


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_merge_bias_source_invariant(seed: int) -> None:
    """``source`` is fully determined by (htf_available, session_available)."""
    rng = random.Random(seed)
    for _ in range(40):
        htf_c = rng.choice((None, rng.randint(-10, 10)))
        if rng.random() < 0.5:
            session = None
        else:
            session = _session_ctx(
                high=rng.uniform(10.0, 100.0),
                low=0.0,
                mid=rng.uniform(0.0, 100.0),
            )
        htf_available = htf_c is not None
        session_available = session is not None
        v = merge_bias(_htf_ctx(htf_c), session)
        if not htf_available and not session_available:
            assert v.source == "NONE"
        elif htf_available and session_available:
            assert v.source == "MERGED"
        elif htf_available:
            assert v.source == "HTF"
        else:
            assert v.source == "SESSION"


def test_merge_bias_uses_only_last_htf_counter() -> None:
    """Only the last fvg_bias_counter entry drives the HTF direction."""
    ctx = {"fvg_bias_counter": [{"counter": 100}, {"counter": -3}]}  # last is bearish
    v = merge_bias(ctx, None)
    assert v.direction == "BEARISH"
    assert v.htf_direction == "BEARISH"
