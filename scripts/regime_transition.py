"""Sprint C5.1 — regime-transition bucket tagging.

Sparse regimes with N < ``min_n_per_regime`` already get a ``degraded``
posture via :func:`scripts.regime_stratification.compute_regime_conditional_metrics`
(``skipped_reason="insufficient_n"``). What is *not* surfaced today is
that the most damaging failures usually happen **during** regime
transitions — the bars surrounding a regime flip. A "high-vol-asia"
strategy that is profitable inside the regime but loses on every
transition will be invisible to in-regime stratification.

This module provides a pure-stdlib helper that re-tags trades within
``bars_around`` bars (or seconds, or any monotonic unit) of a regime
change into a synthetic ``"TRANSITION"`` bucket. Downstream consumers
(``compute_regime_conditional_metrics``) treat it as a regular regime
and surface its own per-bucket Sharpe / win-rate.

Out of scope (separate spike):
- Sliding-volatility regime detector (lives in smc_core.vol_regime)
- Auto-tuning of ``bars_around`` from autocorrelation half-life

Roadmap: docs/IMPROVEMENTS_C2_C12_ROADMAP_2026-04-26.md#c51
"""
from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from typing import Any

TRANSITION_LABEL = "TRANSITION"

Trade = Mapping[str, Any]


def assign_transition_bucket(
    trades: Sequence[Trade],
    *,
    regime_col: str = "regime_at_entry",
    bar_index_col: str = "bar_index",
    bars_around: int = 3,
    transition_label: str = TRANSITION_LABEL,
) -> list[dict[str, Any]]:
    """Return a list of trades with a ``regime_at_entry`` tag rewritten to
    ``transition_label`` for trades within ``bars_around`` bars of a regime
    change in the **input order**.

    Parameters
    ----------
    trades:
        Sequence of trade mappings sorted by ``bar_index_col`` (or any
        monotonically-increasing index). The function does not re-sort.
    regime_col:
        Field name whose value is the source-of-truth regime label.
    bar_index_col:
        Field name with the trade's monotonic bar index. Used to compute
        bar-distance to the nearest regime change.
    bars_around:
        Number of bars before *and* after a regime change that get
        re-tagged. ``bars_around=0`` is a no-op.
    transition_label:
        Label written into ``regime_col`` for transition trades.

    Returns
    -------
    A new list of dicts (input not mutated). Each dict has all original
    fields plus, when re-tagged:

      - ``regime_at_entry`` (or ``regime_col``) replaced with
        ``transition_label``,
      - ``regime_original``: the pre-rewrite label (preserved for audit;
        always uses the fixed key ``regime_original`` regardless of the
        user-supplied ``regime_col``).
    """
    if bars_around < 0:
        raise ValueError(f"bars_around must be >= 0, got {bars_around}")
    if not trades:
        return []

    regimes: list[Any] = [t.get(regime_col) for t in trades]
    bars: list[Any] = [t[bar_index_col] for t in trades]

    # Indices where the regime label changes (compared to previous trade).
    change_bars: list[Any] = []
    for i in range(1, len(regimes)):
        if regimes[i] != regimes[i - 1]:
            change_bars.append(bars[i])

    if bars_around == 0 or not change_bars:
        return [dict(t) for t in trades]

    # change_bars is in monotonic order (bars are monotonic by contract).
    # Use bisect to find the nearest change in O(log n) instead of O(n).
    out: list[dict[str, Any]] = []
    for trade, bar in zip(trades, bars, strict=False):
        new = dict(trade)
        idx = bisect.bisect_left(change_bars, bar)
        candidates = []
        if idx < len(change_bars):
            candidates.append(abs(bar - change_bars[idx]))
        if idx > 0:
            candidates.append(abs(bar - change_bars[idx - 1]))
        nearest = min(candidates) if candidates else float("inf")
        if nearest <= bars_around:
            # ``regime_original`` is the fixed audit key regardless of
            # the user-supplied ``regime_col`` to keep downstream
            # consumers (PromotionGate, dashboards) unambiguous.
            new["regime_original"] = trade.get(regime_col)
            new[regime_col] = transition_label
        out.append(new)
    return out


def transition_share(
    original_trades: Sequence[Trade],
    rewritten_trades: Sequence[Mapping[str, Any]],
    *,
    transition_label: str = TRANSITION_LABEL,
    regime_col: str = "regime_at_entry",
) -> float:
    """Fraction of trades that ended up in the transition bucket.

    Useful for a top-of-dashboard banner: "37 % of trades landed in
    a regime transition" tells the operator the stratification is
    transition-dominated even before they look at per-regime Sharpes.
    """
    n = len(original_trades)
    if n == 0:
        return 0.0
    if len(rewritten_trades) != n:
        raise ValueError(
            f"original/rewritten length mismatch: {n} vs {len(rewritten_trades)}"
        )
    n_trans = sum(
        1 for t in rewritten_trades if t.get(regime_col) == transition_label
    )
    return n_trans / n


def is_degraded(record: Mapping[str, Any]) -> bool:
    """Helper: True if a per-regime metric record is in the degraded set.

    Recognises both the legacy ``skipped_reason`` field (set by
    :func:`compute_regime_conditional_metrics`) and an explicit
    ``degraded`` boolean. Lets X2 PromotionGate downstream answer
    "did any regime drop into degraded posture this run?" with one call.
    """
    if record.get("degraded") is True:
        return True
    return record.get("skipped_reason") in {"insufficient_n", "insufficient_finite_n"}


def degraded_regimes(
    per_regime: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return regimes whose record is degraded, in iteration order."""
    return [r for r, rec in per_regime.items() if is_degraded(rec)]


__all__ = [
    "TRANSITION_LABEL",
    "assign_transition_bucket",
    "degraded_regimes",
    "is_degraded",
    "transition_share",
]
