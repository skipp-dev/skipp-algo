"""Risk-Manager hard-constraint layer.

RL agents are advisory: this layer always has the final word on actions.
Enforces:
  * Per-trade size cap (fraction of account equity).
  * Maximum draw-down threshold (forces flat / TWAP fallback when violated).
  * Slice-size in [0, 1] regardless of upstream output.
  * Order-type whitelist.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rl.types import ExecutionAction, OrderType

VALID_ORDER_TYPES: tuple[OrderType, ...] = ("limit_at_mid", "limit_aggressive", "market")
SizingDecision = Literal["accept", "clamped", "rejected"]


@dataclass(frozen=True)
class GuardResult:
    action: ExecutionAction
    decision: SizingDecision
    reason: str


@dataclass
class HardConstraintLayer:
    """Last-line-of-defence for RL execution / sizing actions."""

    max_size_fraction: float = 0.01
    max_drawdown_pct: float = 0.10
    safe_order_type: OrderType = "limit_at_mid"

    def guard_action(self, action: ExecutionAction, *, drawdown_pct: float = 0.0) -> GuardResult:
        if drawdown_pct >= self.max_drawdown_pct:
            return GuardResult(
                ExecutionAction(slice_size=0.0, order_type=self.safe_order_type),
                "rejected",
                f"drawdown {drawdown_pct:.4f} >= cap {self.max_drawdown_pct}",
            )
        slice_size = action.slice_size
        clamped = False
        if slice_size < 0.0:
            slice_size = 0.0
            clamped = True
        if slice_size > 1.0:
            slice_size = 1.0
            clamped = True
        order_type: OrderType = action.order_type
        if order_type not in VALID_ORDER_TYPES:
            order_type = self.safe_order_type
            clamped = True
        new_action = ExecutionAction(slice_size=slice_size, order_type=order_type)
        return GuardResult(
            new_action,
            "clamped" if clamped else "accept",
            "ok" if not clamped else "clamped to safe range",
        )

    def guard_size_fraction(self, requested_fraction: float) -> tuple[float, SizingDecision, str]:
        if requested_fraction < 0.0:
            return 0.0, "rejected", "negative size requested"
        if requested_fraction > self.max_size_fraction:
            return self.max_size_fraction, "clamped", "size exceeded hard cap"
        return float(requested_fraction), "accept", "ok"


__all__ = ["HardConstraintLayer", "GuardResult", "VALID_ORDER_TYPES", "SizingDecision"]
