"""ADR-0023 §5 — empirical execution-cost calibration from C8 paper fills.

The §5 E[PnL]-after-cost check (:mod:`governance.epnl_after_cost`) needs a
``cost_bps`` haircut. Until now that was the flat pre-registered placeholder
``DEFAULT_COST_BPS = 5.0`` — the findings doc records the §5 verdicts for
BOS/SWEEP as *deferred* precisely because no empirical cost figure existed.
This module closes that gap: it measures realized round-turn trading cost
from the C8 Phase-A IBKR paper-execution sessions (the audit JSON written by
``scripts/run_ibkr_open_execution.py``).

Cost components (per filled order leg)
--------------------------------------
* **Slippage** — signed difference between the fill VWAP and the order's own
  limit price, in bps of the limit price. Positive = paid more than intended
  (BUY above limit cannot happen at IBKR, so measured slippage is usually
  ≤ 0 — price improvement — but partial fills across snapshots and paper-sim
  quirks can produce either sign; we keep the sign so improvement reduces
  cost honestly). Legs without a limit reference (e.g. trailing stops:
  ``*-trail`` carries a trail amount, not a price level) contribute **fee
  only** to the per-side cost samples (slippage unmeasured, treated as 0)
  and are counted in ``fee_only_legs`` for transparency.
* **Commission** — the IBKR Fixed US-equity schedule:
  ``max($1.00, $0.005/share)`` capped at 1 % of trade value, expressed in bps
  of the leg's notional.

Round-turn cost
---------------
A *round-turn* is two sides (entry + exit). The estimator is per-side:

    ``per_side_cost_bps[i] = slippage_bps[i] + fee_bps[i]``

over every measurable filled leg, and the round-turn point estimate is
``2 * mean(per_side_cost_bps)``. The bootstrap CI resamples the per-side list
(percentile method, same mechanics as :mod:`governance.epnl_after_cost`) and
doubles the resampled means. ``conservative_cost_bps`` is the CI **upper**
bound — the §5 gate must hold against the pessimistic cost, not the point
estimate.

Fill probability
----------------
``fill_rate`` = entry orders with at least one fill ÷ entry orders submitted.
An unfilled entry is a missed trade, not a cost — it does not enter the bps
estimate, but a low fill rate undermines the claim that the measured trades
represent the strategy, so it is reported and bounded by
``MIN_FILL_RATE`` for the calibration to count as measurable.

Measurability (fail-closed)
---------------------------
``measurable`` requires at least ``MIN_FILL_SAMPLES`` per-side cost samples
AND ``fill_rate >= MIN_FILL_RATE``. Consumers (the §5 CLI) must refuse to
substitute an unmeasurable calibration for the flat default — silently
falling back would defeat the purpose of the empirical bar.

This module is pure (stdlib only, no I/O). The CLI wrapper lives in
``scripts/calibrate_execution_costs.py``.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from governance.family_calibration import _quantile

# Minimum measurable per-side cost samples before the calibration may be
# consumed by the §5 gate. Below this the bootstrap CI on the mean is too
# wide to bound the cost meaningfully.
MIN_FILL_SAMPLES = 20

# Minimum entry fill rate for the measured sample to plausibly represent the
# strategy's triggered setups. Below this, survivors are a biased subsample.
MIN_FILL_RATE = 0.5

# IBKR Fixed pricing, US equities (https://www.interactivebrokers.com/en/
# pricing/commissions-stocks.php): $0.005/share, $1.00 minimum,
# capped at 1% of trade value.
IBKR_FIXED_PER_SHARE = 0.005
IBKR_FIXED_MINIMUM = 1.00
IBKR_FIXED_VALUE_CAP_PCT = 0.01

# Two-sided 95% CI (matches governance.epnl_after_cost).
_CI_LOW_Q = 0.025
_CI_HIGH_Q = 0.975

DEFAULT_N_BOOTSTRAP = 1000
DEFAULT_SEED = 230022

# Order-ref suffixes assigned by scripts/execute_ibkr_watchlist.py.
ENTRY_SUFFIX = "-entry"
_LIMIT_EXIT_SUFFIXES = ("-tp",)
_KNOWN_EXIT_SUFFIXES = ("-tp", "-trail")


@dataclass(frozen=True)
class LegCost:
    """One filled order leg with its measured cost components."""

    order_ref: str
    symbol: str
    side: str
    shares: float
    fill_vwap: float
    limit_price: float | None
    slippage_bps: float | None  # None when no limit reference exists
    fee_bps: float


@dataclass(frozen=True)
class CostCalibration:
    """Empirical round-turn cost estimate from paper-execution sessions."""

    n_sessions: int
    n_entry_orders: int
    n_entry_filled: int
    fill_rate: float
    n_cost_samples: int
    fee_only_legs: int
    slippage_bps_mean: float
    fee_bps_mean: float
    per_side_cost_bps_mean: float
    round_turn_cost_bps: float
    round_turn_ci_low: float
    round_turn_ci_high: float
    conservative_cost_bps: float
    n_bootstrap: int
    seed: int
    min_fill_samples: int
    min_fill_rate: float
    measurable: bool
    fail_reasons: tuple[str, ...] = field(default_factory=tuple)


def commission_bps(shares: float, price: float) -> float:
    """IBKR Fixed US-equity commission for one leg, in bps of notional."""
    if shares <= 0 or price <= 0:
        raise ValueError("shares and price must be positive")
    notional = shares * price
    commission = max(IBKR_FIXED_MINIMUM, IBKR_FIXED_PER_SHARE * shares)
    commission = min(commission, IBKR_FIXED_VALUE_CAP_PCT * notional)
    return commission / notional * 1e4


def slippage_bps(side: str, fill_vwap: float, limit_price: float) -> float:
    """Signed slippage of a fill vs. its limit reference, in bps.

    Positive = worse than the limit (cost); negative = price improvement.
    ``side`` follows the IBKR execution record (``BOT``/``SLD`` — buy/sell).
    """
    if limit_price <= 0 or fill_vwap <= 0:
        raise ValueError("prices must be positive")
    raw = (fill_vwap - limit_price) / limit_price * 1e4
    normalized = side.strip().upper()
    if normalized in ("BOT", "BUY", "B"):
        return raw
    if normalized in ("SLD", "SELL", "S"):
        return -raw
    raise ValueError(f"unrecognized fill side: {side!r}")


def _dedupe_fills(fills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop snapshot-repeated fill records (same execution seen twice)."""
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for f in fills:
        key = (
            f.get("perm_id"),
            f.get("order_id"),
            f.get("order_ref"),
            f.get("time"),
            f.get("price"),
            f.get("shares"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


def _collect_session_fills(session: dict[str, Any]) -> list[dict[str, Any]]:
    """All deduped fill records from one execution-session JSON."""
    supervisor = session.get("supervisor") or {}
    fills: list[dict[str, Any]] = []
    for snapshot in supervisor.get("snapshots", []) or []:
        fills.extend(snapshot.get("fills", []) or [])
    fills.extend((supervisor.get("final") or {}).get("fills", []) or [])
    return _dedupe_fills(fills)


def _order_index(session: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map order_ref -> submitted order record (limit price, action)."""
    submission = session.get("submission") or {}
    index: dict[str, dict[str, Any]] = {}
    for placement in submission.get("placements", []) or []:
        for order in placement.get("orders", []) or []:
            ref = str(order.get("order_ref", ""))
            if ref:
                index[ref] = {**order, "symbol": placement.get("symbol")}
    return index


def extract_leg_costs(sessions: list[dict[str, Any]]) -> tuple[list[LegCost], int, int]:
    """Measured leg costs + entry-order fill statistics across sessions.

    Returns ``(legs, n_entry_orders, n_entry_filled)``. Fills are grouped per
    ``order_ref`` (VWAP across partial fills); each group becomes one leg.
    Legs whose submitted order carries a limit price get a slippage
    measurement; others (trailing stops, market legs) are fee-only.
    """
    legs: list[LegCost] = []
    n_entry_orders = 0
    n_entry_filled = 0

    for session in sessions:
        orders = _order_index(session)
        fills = _collect_session_fills(session)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for f in fills:
            ref = str(f.get("order_ref", ""))
            shares = float(f.get("shares", 0) or 0)
            price = float(f.get("price", 0) or 0)
            if not ref or shares <= 0 or price <= 0:
                continue
            grouped.setdefault(ref, []).append(f)

        for ref in orders:
            if ref.endswith(ENTRY_SUFFIX):
                n_entry_orders += 1
                if ref in grouped:
                    n_entry_filled += 1

        for ref, group in sorted(grouped.items()):
            total_shares = sum(float(f["shares"]) for f in group)
            vwap = sum(float(f["shares"]) * float(f["price"]) for f in group) / total_shares
            side = str(group[0].get("side", ""))
            order = orders.get(ref, {})
            symbol = str(order.get("symbol") or group[0].get("symbol") or "")

            limit_price: float | None = None
            raw_limit = order.get("lmt_price")
            if raw_limit is not None and (
                ref.endswith(ENTRY_SUFFIX) or any(ref.endswith(s) for s in _LIMIT_EXIT_SUFFIXES)
            ):
                limit_price = float(raw_limit)
                if limit_price <= 0:
                    limit_price = None

            slip: float | None = None
            if limit_price is not None:
                try:
                    slip = slippage_bps(side, vwap, limit_price)
                except ValueError:
                    slip = None

            legs.append(
                LegCost(
                    order_ref=ref,
                    symbol=symbol,
                    side=side,
                    shares=total_shares,
                    fill_vwap=vwap,
                    limit_price=limit_price,
                    slippage_bps=slip,
                    fee_bps=commission_bps(total_shares, vwap),
                )
            )

    return legs, n_entry_orders, n_entry_filled


def _bootstrap_mean_ci(
    values: list[float], *, n_bootstrap: int, rng: random.Random
) -> tuple[float, float]:
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


def calibrate_costs(
    sessions: list[dict[str, Any]],
    *,
    min_fill_samples: int = MIN_FILL_SAMPLES,
    min_fill_rate: float = MIN_FILL_RATE,
    n_bootstrap: int = DEFAULT_N_BOOTSTRAP,
    seed: int = DEFAULT_SEED,
) -> CostCalibration:
    """Empirical round-turn cost calibration over paper-execution sessions."""
    legs, n_entry_orders, n_entry_filled = extract_leg_costs(sessions)

    per_side: list[float] = []
    slippages: list[float] = []
    fee_only = 0
    for leg in legs:
        if leg.slippage_bps is None:
            # No limit reference (e.g. trailing stop): the leg still costs
            # its commission, so it contributes fee-only to the per-side
            # estimate (slippage unmeasured, treated as 0 — see module
            # docstring). Excluding it entirely would under-estimate the
            # round-turn cost for every trade that exits via a trail.
            fee_only += 1
            per_side.append(leg.fee_bps)
            continue
        slippages.append(leg.slippage_bps)
        per_side.append(leg.slippage_bps + leg.fee_bps)

    fill_rate = (n_entry_filled / n_entry_orders) if n_entry_orders else 0.0
    fees = [leg.fee_bps for leg in legs]
    fee_mean = sum(fees) / len(fees) if fees else 0.0
    slip_mean = sum(slippages) / len(slippages) if slippages else 0.0
    per_side_mean = sum(per_side) / len(per_side) if per_side else 0.0
    point = 2.0 * per_side_mean

    reasons: list[str] = []
    if len(per_side) < min_fill_samples:
        reasons.append("min_fill_samples")
    if fill_rate < min_fill_rate:
        reasons.append("min_fill_rate")
    measurable = not reasons

    if measurable:
        rng = random.Random(seed)
        ci_low_side, ci_high_side = _bootstrap_mean_ci(
            per_side, n_bootstrap=n_bootstrap, rng=rng
        )
        ci_low, ci_high = 2.0 * ci_low_side, 2.0 * ci_high_side
    else:
        ci_low, ci_high = 0.0, 0.0

    return CostCalibration(
        n_sessions=len(sessions),
        n_entry_orders=n_entry_orders,
        n_entry_filled=n_entry_filled,
        fill_rate=fill_rate,
        n_cost_samples=len(per_side),
        fee_only_legs=fee_only,
        slippage_bps_mean=slip_mean,
        fee_bps_mean=fee_mean,
        per_side_cost_bps_mean=per_side_mean,
        round_turn_cost_bps=point,
        round_turn_ci_low=ci_low,
        round_turn_ci_high=ci_high,
        conservative_cost_bps=ci_high if measurable else 0.0,
        n_bootstrap=n_bootstrap,
        seed=seed,
        min_fill_samples=min_fill_samples,
        min_fill_rate=min_fill_rate,
        measurable=measurable,
        fail_reasons=tuple(reasons),
    )
