"""Tests for smc_core.sweep_trap (Phase B — Sweep Trap Classifier).

Covers:
- ``classify_sweep_trap`` correct TrapType for immediate / delayed / failed
- ``reclaim_strength`` computation for bullish and bearish sweeps
- ``fib_retrace_depth`` computation
- ``trap_quality_score`` is bounded 0.0–1.0
- Failed trap when no reclaim in look-ahead window
- Degenerate sweep (zero-body candle) → failed
- ``SweepTrapResult`` is immutable (frozen dataclass)
"""

from __future__ import annotations

import pytest

from smc_core.sweep_trap import (
    DELAYED_RECLAIM_BARS,
    classify_sweep_trap,
)

# ---------------------------------------------------------------------------
# Helpers to build synthetic bar sequences
# ---------------------------------------------------------------------------


def _bars(
    n: int,
    *,
    close_on: int | None = None,
    close_below: float | None = None,
    close_above: float | None = None,
    base_close: float = 103.0,  # default: ABOVE 102.0 swept_level so no accidental reclaim
) -> list[dict]:
    """Build a list of n synthetic OHLC bars.

    If ``close_on`` is set (1-indexed), that bar closes below ``close_below``
    or above ``close_above`` (sweep reclaim trigger).
    All other bars close at ``base_close``.
    """
    bars = []
    for i in range(n):
        if close_on is not None and i + 1 == close_on:
            c = (close_below - 0.10) if close_below is not None else (close_above + 0.10)
        else:
            c = base_close  # stays above swept_level → no accidental reclaim
        bars.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c})
    return bars


# ---------------------------------------------------------------------------
# TrapType classification
# ---------------------------------------------------------------------------


class TestTrapType:
    def test_immediate_reclaim_within_3_bars_bull_sweep(self) -> None:
        """Bullish sweep: price went above swept_level, reclaim = close below."""
        # Bar 1: still above → close at 103.0 (no reclaim)
        # Bar 2: reclaim → close at 101.9 (below swept_level 102.0)
        post = _bars(5, close_on=2, close_below=102.0)  # bar[1] = 103, bar[2] = 101.9
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=103.5,
            origin_level=99.0,
            is_bullish_sweep=True,
            post_sweep_bars=post,
        )
        assert result.trap_type == "immediate"
        assert result.sweep_reclaim_bars == 2

    def test_immediate_single_bar_reclaim(self) -> None:
        post = _bars(5, close_on=1, close_below=102.0)
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=104.0,
            origin_level=98.0,
            is_bullish_sweep=True,
            post_sweep_bars=post,
        )
        assert result.trap_type == "immediate"
        assert result.sweep_reclaim_bars == 1

    def test_delayed_reclaim_at_bar_4(self) -> None:
        # Bars 1-3 above swept_level (base_close=103.0), bar 4 reclaims
        post = _bars(12, close_on=4, close_below=102.0)
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=103.0,
            origin_level=100.0,
            is_bullish_sweep=True,
            post_sweep_bars=post,
        )
        assert result.trap_type == "delayed"
        assert result.sweep_reclaim_bars == 4

    def test_delayed_reclaim_at_max_delayed_bar(self) -> None:
        # All bars before DELAYED_RECLAIM_BARS stay above; last one reclaims
        post = _bars(DELAYED_RECLAIM_BARS + 2, close_on=DELAYED_RECLAIM_BARS, close_below=102.0)
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=103.0,
            origin_level=100.0,
            is_bullish_sweep=True,
            post_sweep_bars=post,
        )
        assert result.trap_type == "delayed"

    def test_failed_trap_no_reclaim_in_window(self) -> None:
        post = _bars(20, base_close=103.0)  # All bars stay above swept_level
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=103.0,
            origin_level=100.0,
            is_bullish_sweep=True,
            post_sweep_bars=post,
        )
        assert result.trap_type == "failed"
        assert result.sweep_reclaim_bars == -1

    def test_failed_trap_empty_post_bars(self) -> None:
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=103.0,
            origin_level=100.0,
            is_bullish_sweep=True,
            post_sweep_bars=[],
        )
        assert result.trap_type == "failed"

    def test_failed_degenerate_zero_body_sweep(self) -> None:
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=102.0,  # zero body
            origin_level=100.0,
            is_bullish_sweep=True,
            post_sweep_bars=_bars(5),
        )
        assert result.trap_type == "failed"

    def test_bearish_sweep_reclaim_closes_above(self) -> None:
        """Bearish sweep: price swept below swept_level; reclaim = close above."""
        post = _bars(5, close_on=2, close_above=98.0)
        result = classify_sweep_trap(
            swept_level=98.0,
            sweep_extreme=96.5,
            origin_level=101.0,
            is_bullish_sweep=False,
            post_sweep_bars=post,
        )
        assert result.trap_type == "immediate"


# ---------------------------------------------------------------------------
# Quality score bounds and monotonicity
# ---------------------------------------------------------------------------


class TestQualityScore:
    def test_quality_score_bounded_0_1(self) -> None:
        post = _bars(5, close_on=1, close_below=102.0)
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=105.0,
            origin_level=95.0,
            is_bullish_sweep=True,
            post_sweep_bars=post,
        )
        assert 0.0 <= result.trap_quality_score <= 1.0

    def test_failed_trap_has_zero_quality(self) -> None:
        result = classify_sweep_trap(
            swept_level=102.0,
            sweep_extreme=103.0,
            origin_level=100.0,
            is_bullish_sweep=True,
            post_sweep_bars=_bars(20, base_close=103.0),
        )
        assert result.trap_quality_score == 0.0
        assert result.reclaim_strength == 0.0

    def test_immediate_trap_higher_type_weight_than_delayed(self) -> None:
        """Immediate trap type has type_weight=1.0 vs delayed<=0.8, so with
        identical reclaim_strength and fib_retrace, immediate scores higher."""
        # Deep reclaim: close at 99.0 vs swept_level 102.0 → big reclaim_strength
        post_imm = _bars(15, close_on=1, close_below=102.0, base_close=103.0)
        # Override bar 1 to a deep reclaim
        post_imm[0]["close"] = 99.0
        post_imm[0]["open"] = 99.0
        post_del = _bars(15, close_on=8, close_below=102.0, base_close=103.0)
        post_del[7]["close"] = 99.0
        post_del[7]["open"] = 99.0

        immediate = classify_sweep_trap(
            swept_level=102.0, sweep_extreme=104.0, origin_level=99.0,
            is_bullish_sweep=True, post_sweep_bars=post_imm,
        )
        delayed = classify_sweep_trap(
            swept_level=102.0, sweep_extreme=104.0, origin_level=99.0,
            is_bullish_sweep=True, post_sweep_bars=post_del,
        )
        assert immediate.trap_type == "immediate"
        assert delayed.trap_type == "delayed"
        # With same reclaim depth, immediate type_weight (1.0) > delayed (<= 0.8)
        assert immediate.trap_quality_score > delayed.trap_quality_score

    def test_fib_retrace_depth_bounded_0_1(self) -> None:
        post = _bars(5, close_on=2, close_below=102.0)
        result = classify_sweep_trap(
            swept_level=102.0, sweep_extreme=103.5, origin_level=100.0,
            is_bullish_sweep=True, post_sweep_bars=post,
        )
        assert 0.0 <= result.fib_retrace_depth <= 1.0

    def test_reclaim_strength_bounded_0_1(self) -> None:
        post = _bars(5, close_on=1, close_below=102.0)
        result = classify_sweep_trap(
            swept_level=102.0, sweep_extreme=104.0, origin_level=99.0,
            is_bullish_sweep=True, post_sweep_bars=post,
        )
        assert 0.0 <= result.reclaim_strength <= 1.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_sweep_trap_result_is_frozen() -> None:
    post = _bars(5, close_on=1, close_below=102.0)
    result = classify_sweep_trap(
        swept_level=102.0, sweep_extreme=103.0, origin_level=99.0,
        is_bullish_sweep=True, post_sweep_bars=post,
    )
    with pytest.raises((AttributeError, TypeError)):
        result.trap_type = "delayed"  # type: ignore[misc]
