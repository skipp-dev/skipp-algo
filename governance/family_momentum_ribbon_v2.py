"""ADR-0019 candidate: momentum-ribbon features (family score v2).

Why this exists
---------------
The v1 per-family score (``governance.family_event_score``,
``SCORE_SOURCE = "atr_normalised_geometry_strength_v1"``) is ONE ATR-normalised
geometry feature. The Murphy/Brier decomposition of the EV-20 run pins the
binding promotion deficit on **resolution (discrimination)**, and the verified
feature-gap analysis (``docs/governance/resolution_feature_gap_analysis.md``,
ADR-0019) shows the score looks at NO momentum / trend-maturity signal at all.

This module supplies a **clean-room momentum-ribbon feature** as a pure,
leak-free extractor. It is a public-domain TA reconstruction (smoothed-RSI
ribbon), built only from the documented *concepts* of multi-length oscillator
ribbons -- no proprietary code is reused. The pieces are textbook:

  * USI ("Ultimate Strength Index") -- a marketing name for a **smoothed RSI**.
    Here: a deterministic Cutler RSI (SMA of gains/losses, no Wilder seeding
    ambiguity) optionally EMA-smoothed. The exact proprietary smoothing is
    irrelevant to the edge and is treated as a hyperparameter, not guessed.
  * Multi-length ribbon -- ``len(lengths)`` USIs at different RSI lengths laid
    over each other (a Guppy/GMMA ribbon on the oscillator instead of price).
    The STACK ORDER encodes trend: in an uptrend the faster (shorter-length)
    lines sit above the slower ones; in a downtrend below.
  * Stack state / spread -- the ordering collapses to a categorical state
    (bull / mixed / bear) and a continuous signed spread (trend strength and
    maturity), which are the actual model-usable features.

What this is NOT
----------------
NOT wired into ``raw_score`` / ``SCORE_SOURCE`` or the promotion gate. Like
``governance.family_score_features_v2.relative_volume_at`` this is shadow-first
measurement groundwork: ADR-0019 mandates a pre-registered purged walk-forward
A/B (``governance.family_feature_ab``) proving the ribbon feature lifts OOS
**resolution** over the v1 score BEFORE any wiring. A momentum ribbon on a daily
breakout setup is expected to OVERLAP heavily with the existing SMC edge, so the
A/B must separate additive lift from redundancy -- this module only produces the
candidate, it certifies nothing.

Point-in-time guarantee
-----------------------
Every value at ``anchor_idx`` reads only closes at indices ``<= anchor_idx``;
the RSI window and the EMA smoothing both look strictly backward. It never reads
a bar after the anchor, so the feature is leak-free by construction, consistent
with the EV-04 lookahead guard and ``family_event_score.atr_at``.

Honest omission semantics
-------------------------
Returns ``None`` (feature absent -- never invented, never zero-filled) when a
close is missing/invalid, there is not enough trailing history for the longest
ribbon length plus the smoothing warmup, or an input window is degenerate.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from typing import Any

# Provenance tag recording how each event's momentum-ribbon feature was
# produced. The ``_v2`` suffix marks it as an ADR-0019 candidate feature,
# distinct from the v1 ``SCORE_SOURCE``.
MOMENTUM_RIBBON_SOURCE = "momentum_usi_ribbon_v2"

# Default ribbon: five RSI lengths shortest -> longest. A spread of lengths a
# breakout setup plausibly separates winners from losers on; kept fixed (no
# per-family tuning) to minimise degrees of freedom. Calibration of these is an
# A/B hyperparameter question, not a runtime default to guess.
DEFAULT_RIBBON_LENGTHS: tuple[int, ...] = (3, 5, 7, 11, 13)

# Default EMA smoothing applied to each RSI line (the "USI" smoothing). 1
# disables smoothing (USI == RSI). 3 is a light de-noise that keeps the lines
# responsive; treated as a hyperparameter, not a claimed-optimal value.
DEFAULT_SMOOTH_PERIOD = 3


def _bar_close(bar: Mapping[str, Any]) -> float | None:
    """Finite float close for one bar, or ``None`` when absent/invalid."""
    raw = bar.get("close")
    if raw is None:
        return None
    try:
        close = float(raw)
    except (TypeError, ValueError):
        return None
    if close != close or close in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return close


def _cutler_rsi_at(
    closes: Sequence[float], idx: int, period: int
) -> float | None:
    """Deterministic Cutler RSI at ``idx`` over the trailing ``period`` deltas.

    Uses a simple average of gains/losses across the ``period`` price changes
    ending at ``idx`` (closes ``[idx - period .. idx]``), so there is no Wilder
    seeding ambiguity and the value is a pure function of the window. Strictly
    backward-looking: never reads a close after ``idx``.

    Standard boundary conventions for a degenerate window: all-gains -> 100,
    all-losses -> 0, perfectly flat -> 50 (neutral). Returns ``None`` only when
    ``period`` is non-positive or there is not enough history.
    """
    if period <= 0 or idx < period or idx >= len(closes):
        return None
    gains = 0.0
    losses = 0.0
    for k in range(idx - period + 1, idx + 1):
        delta = closes[k] - closes[k - 1]
        if delta > 0.0:
            gains += delta
        elif delta < 0.0:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss <= 0.0:
        if avg_gain <= 0.0:
            return 50.0  # perfectly flat window -> neutral RSI
        return 100.0  # only gains
    if avg_gain <= 0.0:
        return 0.0  # only losses
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def usi_at(
    closes: Sequence[float],
    idx: int,
    *,
    rsi_period: int,
    smooth_period: int = DEFAULT_SMOOTH_PERIOD,
) -> float | None:
    """Smoothed-RSI "USI" value at ``idx``.

    Computes an EMA of length ``smooth_period`` over the Cutler-RSI series
    ending at ``idx``. The EMA is seeded with the oldest RSI value in the
    trailing smoothing window and rolled forward, so the result is a
    deterministic, strictly backward-looking function of closes up to ``idx``.
    ``smooth_period == 1`` returns the raw RSI (no smoothing).

    Returns ``None`` when ``rsi_period``/``smooth_period`` are non-positive,
    there is not enough trailing history (``idx < rsi_period + smooth_period -
    1``), or any RSI in the window is undefined.
    """
    if rsi_period <= 0 or smooth_period <= 0:
        return None
    warmup = rsi_period + smooth_period - 1
    if idx < warmup or idx >= len(closes):
        return None

    start = idx - smooth_period + 1
    alpha = 2.0 / (smooth_period + 1.0)
    ema: float | None = None
    for j in range(start, idx + 1):
        rsi = _cutler_rsi_at(closes, j, rsi_period)
        if rsi is None:
            return None
        ema = rsi if ema is None else alpha * rsi + (1.0 - alpha) * ema
    return ema


def ribbon_values_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    lengths: Sequence[int] = DEFAULT_RIBBON_LENGTHS,
    smooth_period: int = DEFAULT_SMOOTH_PERIOD,
) -> list[float] | None:
    """The ribbon's USI values at ``anchor_idx``, one per ribbon length.

    Returned in the same order as ``lengths`` (by convention shortest ->
    longest). Strictly point-in-time: every USI reads only closes at indices
    ``<= anchor_idx``.

    Returns ``None`` (ribbon honestly absent) when ``lengths`` is empty or holds
    a non-positive length, any close in the required window is missing/invalid,
    or any USI is undefined for lack of history.
    """
    if not lengths or any(length <= 0 for length in lengths):
        return None
    if anchor_idx < 0 or anchor_idx >= len(bars):
        return None

    longest = max(lengths)
    needed = longest + smooth_period - 1
    if anchor_idx < needed:
        return None

    closes: list[float] = []
    for k in range(anchor_idx - needed, anchor_idx + 1):
        close = _bar_close(bars[k])
        if close is None:
            return None
        closes.append(close)
    local_anchor = len(closes) - 1  # anchor mapped into the local closes window

    values: list[float] = []
    for length in lengths:
        usi = usi_at(
            closes, local_anchor, rsi_period=length, smooth_period=smooth_period
        )
        if usi is None:
            return None
        values.append(usi)
    return values


def ribbon_stack_state_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    lengths: Sequence[int] = DEFAULT_RIBBON_LENGTHS,
    smooth_period: int = DEFAULT_SMOOTH_PERIOD,
) -> int | None:
    """Categorical ribbon stack state at ``anchor_idx``.

    With ``lengths`` ordered shortest -> longest, returns:

      * ``+1`` -- fully bull-stacked: the faster (shorter) lines sit strictly
        above the slower ones (values strictly decreasing along ``lengths``).
      * ``-1`` -- fully bear-stacked: values strictly increasing along
        ``lengths``.
      * ``0``  -- mixed / interleaved (no clean ordering).

    Returns ``None`` when the ribbon itself is absent (see
    :func:`ribbon_values_at`). The fully-stacked states are the documented
    high-conviction trend regimes; ``0`` is the ambiguous regime the discrete
    feature would treat as no-signal.
    """
    values = ribbon_values_at(
        bars, anchor_idx, lengths=lengths, smooth_period=smooth_period
    )
    if values is None:
        return None
    if all(a > b for a, b in itertools.pairwise(values)):
        return 1
    if all(a < b for a, b in itertools.pairwise(values)):
        return -1
    return 0


def ribbon_stack_score_at(
    bars: Sequence[Mapping[str, Any]],
    anchor_idx: int,
    *,
    lengths: Sequence[int] = DEFAULT_RIBBON_LENGTHS,
    smooth_period: int = DEFAULT_SMOOTH_PERIOD,
) -> float | None:
    """Continuous signed ribbon spread at ``anchor_idx`` -- the A/B candidate.

    The mean over all ordered pairs ``i < j`` (by ``lengths`` shortest ->
    longest) of ``value_i - value_j``. It is positive when the faster lines
    generally sit above the slower ones (bullish stacking), negative when the
    reverse holds, and its magnitude grows with how cleanly and widely the
    ribbon is separated (trend strength / maturity). Unlike the plain
    first-minus-last difference this all-pairs form does not telescope, so it
    actually reflects the interior ribbon order -- the single scalar the
    ADR-0019 A/B harness can grade against the v1 score.

    Returns ``None`` when the ribbon is absent (see :func:`ribbon_values_at`) or
    there are fewer than two lines (no pair to compare).
    """
    values = ribbon_values_at(
        bars, anchor_idx, lengths=lengths, smooth_period=smooth_period
    )
    if values is None or len(values) < 2:
        return None
    total = 0.0
    pairs = 0
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            total += values[i] - values[j]
            pairs += 1
    return total / pairs


__all__ = [
    "DEFAULT_RIBBON_LENGTHS",
    "DEFAULT_SMOOTH_PERIOD",
    "MOMENTUM_RIBBON_SOURCE",
    "ribbon_stack_score_at",
    "ribbon_stack_state_at",
    "ribbon_values_at",
    "usi_at",
]
