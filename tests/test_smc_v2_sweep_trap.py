"""Tests for smc_core.sweep_trap (Phase B — Sweep Trap Classifier).

Direction convention (matches the repo + the measurement_evidence call site):
``is_bullish_sweep=True`` is a BULLISH setup — a swing LOW was swept
(``side == "SELL_SIDE"``): the sweep candle's extreme is BELOW ``swept_level``
and the reclaim is a close back ABOVE it. ``is_bullish_sweep=False`` is the
bearish mirror (swing HIGH swept, extreme above, reclaim below).

Covers:
- correct TrapType for immediate / delayed / failed
- ``reclaim_strength`` / ``fib_retrace_depth`` for both directions
- ``trap_quality_score`` bounded 0.0–1.0
- failed / degenerate cases
- regression: a bullish (SELL_SIDE) sweep is NOT mis-classified as failed/zero
  (the pre-fix classifier read direction inverted and clamped fib to 0)
- ``SweepTrapResult`` is immutable
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
    base_close: float,
    reclaim_on: int | None = None,
    reclaim_close: float | None = None,
) -> list[dict]:
    """Build n synthetic OHLC bars all closing at ``base_close``.

    Bar ``reclaim_on`` (1-indexed) instead closes at ``reclaim_close`` — the
    reclaim trigger. ``base_close`` must sit on the *non-reclaimed* side of
    ``swept_level`` so no earlier bar reclaims by accident.
    """
    out = []
    for i in range(n):
        c = reclaim_close if (reclaim_on is not None and i + 1 == reclaim_on and reclaim_close is not None) else base_close
        out.append({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c})
    return out


# Canonical bullish setup: swing low 100 swept down to 98, origin (prior high) 103.
_BULL = dict(swept_level=100.0, sweep_extreme=98.0, origin_level=103.0, is_bullish_sweep=True)
# Canonical bearish setup: swing high 100 swept up to 102, origin (prior low) 97.
_BEAR = dict(swept_level=100.0, sweep_extreme=102.0, origin_level=97.0, is_bullish_sweep=False)


# ---------------------------------------------------------------------------
# TrapType classification
# ---------------------------------------------------------------------------


class TestTrapType:
    def test_immediate_reclaim_within_3_bars_bull_sweep(self) -> None:
        # Bar 1 stays below (99, no reclaim); bar 2 closes back above 100.
        post = _bars(5, base_close=99.0, reclaim_on=2, reclaim_close=100.5)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert result.trap_type == "immediate"
        assert result.sweep_reclaim_bars == 2

    def test_immediate_single_bar_reclaim(self) -> None:
        post = _bars(5, base_close=99.0, reclaim_on=1, reclaim_close=100.5)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert result.trap_type == "immediate"
        assert result.sweep_reclaim_bars == 1

    def test_delayed_reclaim_at_bar_4(self) -> None:
        post = _bars(12, base_close=99.0, reclaim_on=4, reclaim_close=100.5)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert result.trap_type == "delayed"
        assert result.sweep_reclaim_bars == 4

    def test_delayed_reclaim_at_max_delayed_bar(self) -> None:
        post = _bars(DELAYED_RECLAIM_BARS + 2, base_close=99.0, reclaim_on=DELAYED_RECLAIM_BARS, reclaim_close=100.5)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert result.trap_type == "delayed"

    def test_failed_trap_no_reclaim_in_window(self) -> None:
        post = _bars(20, base_close=99.0)  # never closes back above 100
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert result.trap_type == "failed"
        assert result.sweep_reclaim_bars == -1

    def test_failed_trap_empty_post_bars(self) -> None:
        result = classify_sweep_trap(**_BULL, post_sweep_bars=[])
        assert result.trap_type == "failed"

    def test_failed_degenerate_zero_body_sweep(self) -> None:
        result = classify_sweep_trap(
            swept_level=100.0, sweep_extreme=100.0, origin_level=103.0,
            is_bullish_sweep=True, post_sweep_bars=_bars(5, base_close=99.0),
        )
        assert result.trap_type == "failed"

    def test_bearish_sweep_reclaim_closes_below(self) -> None:
        # Bearish: swing high 100 swept to 102; reclaim = close back below 100.
        post = _bars(5, base_close=101.0, reclaim_on=2, reclaim_close=99.5)
        result = classify_sweep_trap(**_BEAR, post_sweep_bars=post)
        assert result.trap_type == "immediate"
        assert result.sweep_reclaim_bars == 2


# ---------------------------------------------------------------------------
# Direction correctness (regression against the pre-fix inversion)
# ---------------------------------------------------------------------------


class TestDirectionCorrectness:
    def test_bullish_sell_side_sweep_is_not_inverted(self) -> None:
        # This is the exact call-site geometry (SELL_SIDE → is_bullish_sweep=True):
        # extreme BELOW swept_level, reclaim close ABOVE. The pre-fix classifier
        # looked for a reclaim below and computed a negative fib → failed/0.
        post = _bars(5, base_close=99.0, reclaim_on=1, reclaim_close=101.0)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert result.trap_type == "immediate"
        assert result.reclaim_strength > 0.0
        assert result.fib_retrace_depth > 0.0
        assert result.trap_quality_score > 0.0

    def test_fib_depth_positive_for_both_directions(self) -> None:
        bull = classify_sweep_trap(**_BULL, post_sweep_bars=_bars(3, base_close=99.0, reclaim_on=1, reclaim_close=100.5))
        bear = classify_sweep_trap(**_BEAR, post_sweep_bars=_bars(3, base_close=101.0, reclaim_on=1, reclaim_close=99.5))
        # Both pierced the level by 2 over a 3-wide pre-sweep leg → depth ≈ 0.667.
        assert bull.fib_retrace_depth == pytest.approx(2.0 / 3.0, abs=1e-9)
        assert bear.fib_retrace_depth == pytest.approx(2.0 / 3.0, abs=1e-9)

    def test_deeper_reclaim_gives_higher_strength(self) -> None:
        shallow = classify_sweep_trap(**_BULL, post_sweep_bars=_bars(3, base_close=99.0, reclaim_on=1, reclaim_close=100.2))
        deep = classify_sweep_trap(**_BULL, post_sweep_bars=_bars(3, base_close=99.0, reclaim_on=1, reclaim_close=101.5))
        assert deep.reclaim_strength > shallow.reclaim_strength


# ---------------------------------------------------------------------------
# Quality score bounds and monotonicity
# ---------------------------------------------------------------------------


class TestQualityScore:
    def test_quality_score_bounded_0_1(self) -> None:
        post = _bars(5, base_close=99.0, reclaim_on=1, reclaim_close=101.0)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert 0.0 <= result.trap_quality_score <= 1.0

    def test_failed_trap_has_zero_quality(self) -> None:
        result = classify_sweep_trap(**_BULL, post_sweep_bars=_bars(20, base_close=99.0))
        assert result.trap_quality_score == 0.0
        assert result.reclaim_strength == 0.0

    def test_immediate_trap_higher_type_weight_than_delayed(self) -> None:
        # Same deep reclaim (101.5), immediate (bar 1) vs delayed (bar 8).
        post_imm = _bars(15, base_close=99.0, reclaim_on=1, reclaim_close=101.5)
        post_del = _bars(15, base_close=99.0, reclaim_on=8, reclaim_close=101.5)
        immediate = classify_sweep_trap(**_BULL, post_sweep_bars=post_imm)
        delayed = classify_sweep_trap(**_BULL, post_sweep_bars=post_del)
        assert immediate.trap_type == "immediate"
        assert delayed.trap_type == "delayed"
        assert immediate.trap_quality_score > delayed.trap_quality_score

    def test_fib_retrace_depth_bounded_0_1(self) -> None:
        post = _bars(5, base_close=99.0, reclaim_on=2, reclaim_close=100.5)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert 0.0 <= result.fib_retrace_depth <= 1.0

    def test_reclaim_strength_bounded_0_1(self) -> None:
        # Reclaim far above swept_level → strength clamps to 1.0, not > 1.
        post = _bars(5, base_close=99.0, reclaim_on=1, reclaim_close=110.0)
        result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
        assert 0.0 <= result.reclaim_strength <= 1.0


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_sweep_trap_result_is_frozen() -> None:
    post = _bars(5, base_close=99.0, reclaim_on=1, reclaim_close=100.5)
    result = classify_sweep_trap(**_BULL, post_sweep_bars=post)
    with pytest.raises((AttributeError, TypeError)):
        result.trap_type = "delayed"  # type: ignore[misc]
