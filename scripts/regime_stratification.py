"""Regime-conditional aggregation for trade outcomes (Sprint C5 / T3).

Splits a trade list by ``regime_at_entry`` (or any caller-supplied
column) and computes per-regime metrics + a regime-frequency-weighted
aggregate. Designed to make the implicit assumption "the aggregate
Sharpe is the right Sharpe" testable: a setup whose 95% of profit
comes from one regime will be flagged here even if the aggregate
Sharpe looks fine.

Reuses ``MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP`` from
``scripts.run_ab_comparison`` as the per-regime n-floor so we stay
consistent with the C3/C4 pipelines.

Out-of-scope here (explicit deferrals from
``docs/SPRINT_PLAN_C5_REGIME_STRATIFICATION_2026-04-26.md``):

- T1 data-contract audit doc — separate PR
- T2 historical regime backfill — only needed if T1 finds gaps
- T4 regime-stratified bootstrap / permutation calls — wait for the
  C3/C4 modules to land in main
- T5 regime-transition early warning — stretch
"""

from __future__ import annotations

import math
import statistics
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

__all__ = [
    "MIN_TRADES_PER_REGIME",
    "compute_regime_aware_aggregate",
    "compute_regime_conditional_metrics",
    "detect_regime_concentration",
    "stratify_trades_by_regime",
    "unknown_regime_share",
]


# Mirror of ``MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP`` in
# scripts/run_ab_comparison.py — kept as a local constant so this module
# does not pull the scripts package at import time. If the canonical
# constant moves, update this in lockstep.
MIN_TRADES_PER_REGIME = 30


# A "trade" in this module is a Mapping with at minimum:
#   - "pnl" (float, signed return or R-multiple)
#   - the regime column (default "regime_at_entry")
Trade = Mapping[str, Any]


def stratify_trades_by_regime(
    trades: Sequence[Trade],
    *,
    regime_col: str = "regime_at_entry",
) -> dict[str, list[Trade]]:
    """Split a trade sequence into per-regime buckets.

    Trades whose regime label is ``None`` or an empty string are
    bucketed under ``"UNKNOWN"`` so the caller can spot data-contract
    gaps rather than getting silent drops.

    Non-string regime labels (numbers, dicts, etc.) are coerced via
    ``str(...)``. Callers that emit a ``dict`` regime label will see
    e.g. ``"{'phase': 'A'}"`` as the bucket name — by design, since
    the upstream regime-tagging contract is *string label per trade*
    and a dict label indicates a producer-side bug. The stringified
    representation makes the defect visible on the dashboard instead
    of crashing with an unhashable-key error.

    Note: legitimately-falsy non-None labels such as ``0`` or
    ``False`` are stringified (``"0"``, ``"False"``) rather than
    bucketed as UNKNOWN — only ``None`` and ``""`` are treated as
    missing so numeric/boolean regime IDs survive intact.

    Returns an ``OrderedDict`` so iteration order is deterministic
    (alphabetical by regime label, with ``"UNKNOWN"`` last).
    """

    buckets: dict[str, list[Trade]] = {}
    for trade in trades:
        regime = trade.get(regime_col)
        key = "UNKNOWN" if regime is None or regime == "" else str(regime)
        buckets.setdefault(key, []).append(trade)

    def sort_key(name: str) -> tuple[int, str]:
        return (1 if name == "UNKNOWN" else 0, name)

    return OrderedDict((k, buckets[k]) for k in sorted(buckets, key=sort_key))


def unknown_regime_share(
    trades_per_regime: Mapping[str, Sequence[Trade]],
) -> float:
    """Fraction of trades that fell into the ``"UNKNOWN"`` bucket.

    A high share (> 0.10) usually means the upstream pipeline forgot
    to emit ``regime_at_entry`` and the per-regime stratification is
    effectively un-stratified. The caller should surface this as a
    warning on the dashboard payload.
    """

    total = sum(len(t) for t in trades_per_regime.values())
    if total <= 0:
        return 0.0
    return len(trades_per_regime.get("UNKNOWN", [])) / total


def _sharpe(pnls: Sequence[float]) -> float | None:
    if len(pnls) < 2:
        return None
    mean = statistics.fmean(pnls)
    var = statistics.variance(pnls)  # ddof=1
    if var <= 0.0:
        return None
    return mean / math.sqrt(var)


def _max_drawdown(pnls: Sequence[float]) -> float:
    """Max drawdown of the cumulative PnL curve (additive PnL).

    Returns a non-positive number; 0.0 if the curve never drops.
    """

    if not pnls:
        return 0.0
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _win_rate(pnls: Sequence[float]) -> float | None:
    if not pnls:
        return None
    wins = sum(1 for p in pnls if p > 0)
    return wins / len(pnls)


def _profit_factor(pnls: Sequence[float]) -> float | None:
    """Sum of positive PnLs over the absolute sum of negative PnLs.

    Returns ``None`` when there are no losing trades, since the
    canonical "gross-profit / gross-loss" definition is undefined
    (loss-denominator is zero). The caller should treat the ``None``
    as *insufficient data to compute*, not as *infinite profit factor*
    — the dashboard renderer therefore prints a dash for the cell
    rather than ``+inf``.
    """

    gains = sum(p for p in pnls if p > 0)
    losses = -sum(p for p in pnls if p < 0)
    if losses <= 0.0:
        return None
    return gains / losses


_DEFAULT_METRIC_FNS: dict[str, Callable[[Sequence[float]], float | None]] = {
    "sharpe": _sharpe,
    "max_dd": _max_drawdown,
    "win_rate": _win_rate,
    "profit_factor": _profit_factor,
}


def compute_regime_conditional_metrics(
    trades_per_regime: Mapping[str, Sequence[Trade]],
    *,
    pnl_col: str = "pnl",
    metric_fns: Mapping[str, Callable[[Sequence[float]], float | None]] | None = None,
    min_n_per_regime: int = MIN_TRADES_PER_REGIME,
) -> dict[str, dict[str, Any]]:
    """Per-regime metrics + ``regime_frequency_pct`` + n-floor handling.

    Output schema per regime:
      - ``n`` (int): *raw* trade count for the regime, always equal to
        ``len(trades_per_regime[regime])``. Used as the canonical
        weight base for ``regime_frequency_pct`` so weights stay
        consistent across skipped and active regimes.
      - ``n_finite`` (int, optional): number of finite PnLs after
        dropping NaN/inf; emitted only when at least one drop
        occurred or the regime was skipped because ``n_finite`` fell
        below the floor.
      - ``n_non_finite_dropped`` (int, optional): explicit drop
        count, emitted only when ``> 0``.
      - ``regime_frequency_pct`` (float in [0, 1]): ``n / total_n``
        across *all* regimes (raw counts), independent of any
        non-finite filtering — keeps the aggregate weights consistent
        when a regime drops some trades.
      - ``skipped_reason`` (str, optional): one of
        ``"insufficient_n"`` (raw trade count below the floor) or
        ``"insufficient_finite_n"`` (raw count was sufficient but the
        finite count after the non-finite filter was not). Distinct
        reasons let the dashboard surface upstream data-feed defects
        separately from regime sparsity.
      - per-metric numeric values (``sharpe``, ``max_dd``,
        ``win_rate``, ``profit_factor``, …) only on non-skipped
        regimes.
    """

    fns = dict(metric_fns) if metric_fns is not None else dict(_DEFAULT_METRIC_FNS)
    total_n = sum(len(t) for t in trades_per_regime.values())
    out: dict[str, dict[str, Any]] = {}
    for regime, trades in trades_per_regime.items():
        n = len(trades)
        freq_pct = (n / total_n) if total_n > 0 else 0.0
        if n < min_n_per_regime:
            out[regime] = {
                "skipped_reason": "insufficient_n",
                "n": n,
                "regime_frequency_pct": freq_pct,
            }
            continue
        # C-sprint deep-review: filter non-finite PnLs at the boundary
        # so a NaN/inf data-feed defect cannot silently produce a NaN
        # Sharpe / 0.0 max_dd that the dashboard then renders as a
        # healthy regime. Drops are recorded so the operator can spot
        # the upstream gap.
        raw_pnls = [float(t[pnl_col]) for t in trades]
        pnls = [p for p in raw_pnls if math.isfinite(p)]
        n_dropped = len(raw_pnls) - len(pnls)
        if len(pnls) < min_n_per_regime:
            out[regime] = {
                "skipped_reason": "insufficient_finite_n",
                "n": n,
                "n_finite": len(pnls),
                "n_non_finite_dropped": n_dropped,
                "regime_frequency_pct": freq_pct,
            }
            continue
        # Keep ``n`` aligned with the raw regime size so callers that
        # reconstruct ``regime_frequency_pct`` from ``n / sum(n)``
        # land on the same number we recorded. The actual evaluation
        # count after the non-finite filter is exposed separately as
        # ``n_finite`` whenever it differs.
        record: dict[str, Any] = {
            "n": n,
            "regime_frequency_pct": freq_pct,
        }
        if n_dropped > 0:
            record["n_finite"] = len(pnls)
            record["n_non_finite_dropped"] = n_dropped
        for name, fn in fns.items():
            record[name] = fn(pnls)
        out[regime] = record
    return out


def compute_regime_aware_aggregate(
    per_regime: Mapping[str, Mapping[str, Any]],
    *,
    metric: str = "sharpe",
    freq_weighting: bool = True,
    unknown_share: float | None = None,
    unknown_share_warn_threshold: float = 0.05,
) -> dict[str, Any]:
    """Frequency-weighted aggregate of a single per-regime metric.

    Skipped regimes are excluded from both the numerator and the
    denominator so the aggregate is computed only over regimes that
    cleared ``min_n_per_regime``.

    Weighting (when ``freq_weighting=True``): each non-skipped regime
    contributes its *finite* trade count (``n_finite`` if non-finite
    PnLs were dropped, else raw ``n``) — i.e. the actual sample count
    behind the metric value, not the raw regime frequency. This avoids
    over-weighting regimes that lost a large fraction of their trades
    to NaN/inf upstream-data defects (Copilot #306 follow-up).

    When ``unknown_share`` is provided (the value returned by
    :func:`unknown_regime_share` for the same trade-set) and exceeds
    ``unknown_share_warn_threshold`` (default 5%, per the C5 deep-review
    finding), the result dict gains a ``warning`` key describing how
    much of the trade-set could not be stratified — downstream
    consumers (dashboard payload, public calibration report) can
    surface this so a low ``regime_concentration`` is not silently
    interpreted as "well-diversified" when in fact the regime tag is
    just missing.

    Returns:
        ``{"value": float | None, "method": str, "regimes_used": list[str],
        "regimes_skipped": list[str], "unknown_share": float | None,
        "warning": str | None}``
    """

    used: list[str] = []
    skipped: list[str] = []
    contributions: list[tuple[float, float]] = []
    for regime, record in per_regime.items():
        if record.get("skipped_reason"):
            skipped.append(regime)
            continue
        value = record.get(metric)
        if value is None:
            skipped.append(regime)
            continue
        if freq_weighting:
            # C-sprint Copilot #306: weight by the *finite* trade count
            # actually used to compute the metric (``n_finite`` if drops
            # occurred, else raw ``n``) — not by the raw
            # ``regime_frequency_pct`` which still includes non-finite
            # trades. Otherwise a regime that lost (e.g.) half its
            # trades to NaN PnLs would be weighted as if all of them
            # contributed to the metric, mis-weighting the aggregate
            # toward regimes with high upstream-data drop rates.
            weight = float(record.get("n_finite", record.get("n", 0)))
        else:
            weight = 1.0
        used.append(regime)
        contributions.append((float(value), weight))

    if not contributions:
        result: dict[str, Any] = {
            "value": None,
            "method": "frequency_weighted" if freq_weighting else "equal_weighted",
            "regimes_used": used,
            "regimes_skipped": skipped,
            "unknown_share": (None if unknown_share is None else float(unknown_share)),
        }
        if (
            unknown_share is not None
            and unknown_share > unknown_share_warn_threshold
        ):
            result["warning"] = (
                f"unknown_regime_share={unknown_share:.3f} exceeds "
                f"warn-threshold {unknown_share_warn_threshold:.3f}; "
                "regime stratification is partial."
            )
        return result
    total_weight = sum(w for _, w in contributions)
    if total_weight <= 0.0:  # pragma: no cover - defensive: unreachable
        # Defensive guard only. With ``freq_weighting=True`` each weight
        # is the regime's finite trade count (``n_finite`` if drops
        # occurred, else raw ``n``); a non-skipped regime by
        # construction has ``n_finite >= min_n_per_regime > 0`` so the
        # sum is always > 0. With ``freq_weighting=False`` weights are
        # 1.0 each. Kept so a future caller passing custom weights
        # can't get a ZeroDivision.
        agg = sum(v for v, _ in contributions) / len(contributions)
        method = "equal_weighted_fallback"
    else:
        agg = sum(v * w for v, w in contributions) / total_weight
        method = "frequency_weighted" if freq_weighting else "equal_weighted"
    result = {
        "value": agg,
        "method": method,
        "regimes_used": used,
        "regimes_skipped": skipped,
        "unknown_share": (None if unknown_share is None else float(unknown_share)),
    }
    if (
        unknown_share is not None
        and unknown_share > unknown_share_warn_threshold
    ):
        result["warning"] = (
            f"unknown_regime_share={unknown_share:.3f} exceeds "
            f"warn-threshold {unknown_share_warn_threshold:.3f}; "
            "regime stratification is partial."
        )
    return result


def detect_regime_concentration(
    trades_per_regime: Mapping[str, Sequence[Trade]],
    *,
    pnl_col: str = "pnl",
    threshold: float = 0.80,
) -> dict[str, Any]:
    """Flag setups whose ≥``threshold`` of total positive PnL is one regime.

    Concentration risk is the C5 headline finding: a setup that looks
    fine in aggregate but lives or dies by one regime is a regime-bet,
    not an alpha-bet. Anything at-or-above ``threshold`` is reported
    via ``concentrated=True`` plus the dominant regime.

    Returns:
        ``{"concentrated": bool, "dominant_regime": str | None,
        "share_of_total_pnl": float, "threshold": float,
        "per_regime_pnl": {regime: float}}``
    """

    if not (0.0 < threshold <= 1.0):
        raise ValueError(f"threshold must be in (0,1], got {threshold}")
    per_regime_pnl: dict[str, float] = {}
    for regime, trades in trades_per_regime.items():
        per_regime_pnl[regime] = sum(float(t[pnl_col]) for t in trades)
    # Concentration is defined on positive contributions only — a
    # negative-PnL regime can't "dominate" via positive concentration.
    positive_total = sum(v for v in per_regime_pnl.values() if v > 0.0)
    if positive_total <= 0.0:
        return {
            "concentrated": False,
            "dominant_regime": None,
            "share_of_total_pnl": 0.0,
            "threshold": threshold,
            "per_regime_pnl": per_regime_pnl,
        }
    dominant_regime, dominant_pnl = max(per_regime_pnl.items(), key=lambda kv: kv[1])
    share = dominant_pnl / positive_total if dominant_pnl > 0 else 0.0
    return {
        "concentrated": share >= threshold,
        "dominant_regime": dominant_regime if share > 0 else None,
        "share_of_total_pnl": share,
        "threshold": threshold,
        "per_regime_pnl": per_regime_pnl,
    }
