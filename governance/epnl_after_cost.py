"""ADR-0023 §5 — E[PnL]-after-cost secondary check (pure estimator).

A family can statistically *resolve* (the move-size signal sorts large from
small follow-through, ADR-0023 §2) and still **lose money after costs**. §5 is
the second, independent bar a candidate must clear before any real sizing:

    "Does sizing by the move-size score produce positive expected PnL,
     net of trading cost, on the triggered setups?"

Cost model
----------
Trading cost in :mod:`governance.family_returns` is a *bps haircut on notional*
(``realized_return = gross - cost_bps / 1e4``). Because both the gross move and
the cost scale linearly with position size ``s``, the sized net PnL of a trade
is simply ``s * realized_return`` -- no separate gross term is needed. This is
the key identity this module rests on.

Sizing rule (pre-registered, zero free parameters)
--------------------------------------------------
Positions are sized by the **rank** of the move-size score, normalised so the
mean size is 1 (the book carries the same gross exposure as the equal-weight
baseline -- this is a *reallocation*, not leverage). Higher score -> larger
size. With mean-1 weights, the sized mean equals the equal-weight mean unless
high-score trades earn more than low-score trades -- which is exactly the edge
ADR-0023 §2 claims to detect. So §5 asks whether that claimed edge survives
contact with costs.

Verdict (per candidate family)
------------------------------
* ``INCONCLUSIVE`` -- fewer than ``MIN_TRADES`` triggered setups (not measurable).
* ``PASS``         -- sized-PnL bootstrap CI-low > 0 **and** sizing is not
  value-destructive (sized mean >= equal-weight mean).
* ``FAIL``         -- measurable but one of those conditions fails; reasons are
  reported (``epnl_floor`` / ``sizing_destructive``).

This module is pure (no I/O). The CLI wrapper lives in
``scripts/run_epnl_after_cost_gate.py``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from governance.family_calibration import MIN_OOS_SAMPLES, _quantile
from governance.family_returns import DEFAULT_COST_BPS
from governance.magnitude_resolution_gate import DEFAULT_N_BOOTSTRAP, DEFAULT_SEED

# Minimum triggered setups before E[PnL] is considered measurable. Reuses the
# same out-of-sample floor the calibration/resolution arm uses.
MIN_TRADES = MIN_OOS_SAMPLES

# Pre-registered profitability bar: the lower bound of the 95% bootstrap CI of
# the sized expected PnL must clear zero (profitable after cost, not merely
# point-estimate positive).
EPNL_CI_FLOOR = 0.0

# Two-sided 95% CI by default.
_CI_LOW_Q = 0.025
_CI_HIGH_Q = 0.975


@dataclass(frozen=True)
class EPnLResult:
    """Per-family E[PnL]-after-cost verdict."""

    family: str
    n_trades: int
    cost_bps: float
    equal_mean: float
    equal_ci_low: float
    equal_ci_high: float
    sized_mean: float
    sized_ci_low: float
    sized_ci_high: float
    sizing_uplift: float
    n_bootstrap: int
    seed: int
    min_sample_pass: bool
    equal_profitable: bool
    sized_profitable: bool
    sizing_non_destructive: bool
    passes: bool
    verdict: str
    fail_reasons: tuple[str, ...] = field(default_factory=tuple)


def rank_weights(scores: list[float]) -> list[float]:
    """Mean-1 normalised average-rank weights (higher score -> larger size).

    Ties share the average rank, so the mapping is deterministic and
    order-independent. With ``n`` trades the average rank is ``(n + 1) / 2``,
    hence ``w_i = rank_i / ((n + 1) / 2)`` and ``mean(w) == 1`` exactly.
    """
    n = len(scores)
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    order = sorted(range(n), key=lambda i: scores[i])
    # Assign 1-based ranks, averaging across tied runs.
    avg_rank = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0  # average of 1-based ranks i+1..j+1
        for k in range(i, j + 1):
            avg_rank[order[k]] = shared
        i = j + 1

    mean_rank = (n + 1) / 2.0
    return [r / mean_rank for r in avg_rank]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bootstrap_mean_ci(
    values: list[float],
    *,
    n_bootstrap: int,
    rng: random.Random,
) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean of ``values``."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    means: list[float] = []
    for _ in range(n_bootstrap):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    return (_quantile(means, _CI_LOW_Q), _quantile(means, _CI_HIGH_Q))


def evaluate_family_epnl(
    family: str,
    scores: list[float],
    returns: list[float],
    *,
    cost_bps: float = DEFAULT_COST_BPS,
    min_trades: int = MIN_TRADES,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> EPnLResult:
    """E[PnL]-after-cost verdict for one family.

    ``scores`` and ``returns`` must be parallel: ``returns[i]`` is the
    cost-netted directional return of the setup whose move-size score is
    ``scores[i]`` (as produced by
    :func:`governance.family_returns.extract_family_calibration_samples`).
    """
    if len(scores) != len(returns):
        raise ValueError("scores and returns must be the same length")

    n = len(returns)
    weights = rank_weights(scores)
    sized = [w * r for w, r in zip(weights, returns)]

    equal_mean = _mean(returns)
    sized_mean = _mean(sized)
    uplift = sized_mean - equal_mean

    min_sample_pass = n >= min_trades

    if not min_sample_pass:
        # Too thin to measure -- emit a measure-only INCONCLUSIVE shell.
        return EPnLResult(
            family=family,
            n_trades=n,
            cost_bps=cost_bps,
            equal_mean=equal_mean,
            equal_ci_low=0.0,
            equal_ci_high=0.0,
            sized_mean=sized_mean,
            sized_ci_low=0.0,
            sized_ci_high=0.0,
            sizing_uplift=uplift,
            n_bootstrap=n_bootstrap,
            seed=seed,
            min_sample_pass=False,
            equal_profitable=False,
            sized_profitable=False,
            sizing_non_destructive=uplift >= 0.0,
            passes=False,
            verdict="INCONCLUSIVE",
            fail_reasons=("min_sample",),
        )

    rng = random.Random(seed)
    equal_ci_low, equal_ci_high = _bootstrap_mean_ci(
        returns, n_bootstrap=n_bootstrap, rng=rng
    )
    sized_ci_low, sized_ci_high = _bootstrap_mean_ci(
        sized, n_bootstrap=n_bootstrap, rng=rng
    )

    equal_profitable = equal_ci_low > EPNL_CI_FLOOR
    sized_profitable = sized_ci_low > EPNL_CI_FLOOR
    sizing_non_destructive = uplift >= 0.0

    reasons: list[str] = []
    if not sized_profitable:
        reasons.append("epnl_floor")
    if not sizing_non_destructive:
        reasons.append("sizing_destructive")

    passes = sized_profitable and sizing_non_destructive
    verdict = "PASS" if passes else "FAIL"

    return EPnLResult(
        family=family,
        n_trades=n,
        cost_bps=cost_bps,
        equal_mean=equal_mean,
        equal_ci_low=equal_ci_low,
        equal_ci_high=equal_ci_high,
        sized_mean=sized_mean,
        sized_ci_low=sized_ci_low,
        sized_ci_high=sized_ci_high,
        sizing_uplift=uplift,
        n_bootstrap=n_bootstrap,
        seed=seed,
        min_sample_pass=True,
        equal_profitable=equal_profitable,
        sized_profitable=sized_profitable,
        sizing_non_destructive=sizing_non_destructive,
        passes=passes,
        verdict=verdict,
        fail_reasons=tuple(reasons),
    )
