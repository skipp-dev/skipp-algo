"""Risk-Manager hard-constraint layer.

RL agents are advisory: this layer always has the final word on actions.
Enforces:
  * Per-trade size cap (fraction of account equity).
  * Maximum draw-down threshold (forces flat / TWAP fallback when violated).
  * Slice-size in [0, 1] regardless of upstream output.
  * Order-type whitelist.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from rl.types import ExecutionAction, OrderType

if TYPE_CHECKING:  # avoid an import cycle at runtime; only used for typing
    from rl.extensions import ConstraintHitLog

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
    # Sprint C12: optional audit sink. When provided, every clamp /
    # rejection in ``guard_action`` / ``guard_size_fraction`` is
    # appended as a ``ConstraintHit``. Kept optional so the legacy
    # constructor signature (no audit) keeps working.
    hit_log: "ConstraintHitLog | None" = field(default=None, repr=False)

    def guard_action(self, action: ExecutionAction, *, drawdown_pct: float = 0.0) -> GuardResult:
        if not math.isfinite(drawdown_pct):
            self._log(
                constraint="drawdown",
                requested=float(drawdown_pct),
                enforced=float(self.max_drawdown_pct),
                reason="non-finite drawdown rejected",
                extras={"order_type": str(action.order_type)},
            )
            return GuardResult(
                ExecutionAction(slice_size=0.0, order_type=self.safe_order_type),
                "rejected",
                "non-finite drawdown rejected",
            )
        if drawdown_pct >= self.max_drawdown_pct:
            self._log(
                constraint="drawdown",
                requested=float(drawdown_pct),
                enforced=float(self.max_drawdown_pct),
                reason=f"drawdown {drawdown_pct:.4f} >= cap {self.max_drawdown_pct}",
                extras={"order_type": str(action.order_type)},
            )
            return GuardResult(
                ExecutionAction(slice_size=0.0, order_type=self.safe_order_type),
                "rejected",
                f"drawdown {drawdown_pct:.4f} >= cap {self.max_drawdown_pct}",
            )
        slice_size = action.slice_size
        clamped = False
        if not math.isfinite(slice_size):
            slice_size = 0.0
            clamped = True
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
        if clamped:
            self._log(
                constraint="slice_size_or_order_type",
                requested=float(action.slice_size),
                enforced=float(slice_size),
                reason="clamped to safe range",
                extras={
                    "requested_order_type": str(action.order_type),
                    "enforced_order_type": str(order_type),
                },
            )
        return GuardResult(
            new_action,
            "clamped" if clamped else "accept",
            "ok" if not clamped else "clamped to safe range",
        )

    def guard_size_fraction(self, requested_fraction: float) -> tuple[float, SizingDecision, str]:
        if not math.isfinite(requested_fraction):
            self._log(
                constraint="size_fraction",
                requested=float(requested_fraction),
                enforced=0.0,
                reason="non-finite size requested",
            )
            return 0.0, "rejected", "non-finite size requested"
        if requested_fraction < 0.0:
            self._log(
                constraint="size_fraction",
                requested=float(requested_fraction),
                enforced=0.0,
                reason="negative size requested",
            )
            return 0.0, "rejected", "negative size requested"
        if requested_fraction > self.max_size_fraction:
            self._log(
                constraint="size_fraction",
                requested=float(requested_fraction),
                enforced=float(self.max_size_fraction),
                reason="size exceeded hard cap",
            )
            return self.max_size_fraction, "clamped", "size exceeded hard cap"
        return float(requested_fraction), "accept", "ok"

    def _log(
        self,
        *,
        constraint: str,
        requested: float,
        enforced: float,
        reason: str,
        extras: dict | None = None,
    ) -> None:
        if self.hit_log is None:
            return
        try:
            self.hit_log.record_clamp(
                constraint=constraint,
                requested=requested,
                enforced=enforced,
                reason=reason,
                extras=extras or {},
            )
        except Exception:
            # An audit-log failure must never block the guard decision.
            pass


__all__ = ["VALID_ORDER_TYPES", "GuardResult", "HardConstraintLayer", "SizingDecision"]
