"""Reconcile broker position deltas against deduplicated execution fills."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from governance.portfolio_contract import PortfolioSnapshotV1, Side


@dataclass(frozen=True, slots=True)
class PortfolioFill:
    execution_id: str
    symbol: str
    account: str
    side: Side
    quantity: float
    price: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_id", str(self.execution_id).strip())
        object.__setattr__(self, "symbol", str(self.symbol).strip().upper())
        object.__setattr__(self, "account", str(self.account).strip())
        object.__setattr__(self, "side", Side(str(self.side).upper()))
        if not self.execution_id or not self.symbol or not self.account:
            raise ValueError("fill execution_id, symbol and account must be non-empty")
        if not math.isfinite(self.quantity) or self.quantity <= 0.0:
            raise ValueError("fill quantity must be finite and positive")
        if not math.isfinite(self.price) or self.price <= 0.0:
            raise ValueError("fill price must be finite and positive")


@dataclass(frozen=True, slots=True)
class SymbolReconciliation:
    symbol: str
    before_quantity: float
    signed_fill_quantity: float
    expected_after_quantity: float
    actual_after_quantity: float
    quantity_delta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "before_quantity": self.before_quantity,
            "signed_fill_quantity": self.signed_fill_quantity,
            "expected_after_quantity": self.expected_after_quantity,
            "actual_after_quantity": self.actual_after_quantity,
            "quantity_delta": self.quantity_delta,
        }


@dataclass(frozen=True, slots=True)
class PortfolioReconciliation:
    before_snapshot_id: str
    after_snapshot_id: str
    before_captured_at: datetime
    after_captured_at: datetime
    account: str
    fill_count: int
    duplicate_fill_ids: tuple[str, ...]
    symbols: tuple[SymbolReconciliation, ...]
    max_abs_quantity_delta: float
    reconciled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "before_snapshot_id": self.before_snapshot_id,
            "after_snapshot_id": self.after_snapshot_id,
            "before_captured_at": self.before_captured_at.isoformat(),
            "after_captured_at": self.after_captured_at.isoformat(),
            "account": self.account,
            "fill_count": self.fill_count,
            "duplicate_fill_ids": list(self.duplicate_fill_ids),
            "symbols": [item.to_dict() for item in self.symbols],
            "max_abs_quantity_delta": self.max_abs_quantity_delta,
            "reconciled": self.reconciled,
        }


def reconcile_portfolio_positions(
    before: PortfolioSnapshotV1,
    after: PortfolioSnapshotV1,
    fills: tuple[PortfolioFill, ...],
    *,
    quantity_tolerance: float = 1e-9,
) -> PortfolioReconciliation:
    if before.account != after.account:
        raise ValueError("portfolio reconciliation snapshots must use the same account")
    if before.base_currency != after.base_currency:
        raise ValueError("portfolio reconciliation snapshots must use the same base currency")
    if after.captured_at < before.captured_at:
        raise ValueError("after snapshot predates before snapshot")
    if quantity_tolerance < 0.0 or not math.isfinite(quantity_tolerance):
        raise ValueError("quantity_tolerance must be finite and non-negative")

    seen: set[str] = set()
    duplicates: set[str] = set()
    fill_delta: dict[str, float] = {}
    for fill in fills:
        if fill.account != before.account:
            raise ValueError(
                f"fill {fill.execution_id!r} belongs to {fill.account!r}, "
                f"expected {before.account!r}"
            )
        if fill.execution_id in seen:
            duplicates.add(fill.execution_id)
            continue
        seen.add(fill.execution_id)
        fill_delta[fill.symbol] = fill_delta.get(fill.symbol, 0.0) + fill.side.sign * fill.quantity

    before_quantity: dict[str, float] = {}
    after_quantity: dict[str, float] = {}
    for position in before.positions:
        before_quantity[position.symbol] = before_quantity.get(position.symbol, 0.0) + position.quantity
    for position in after.positions:
        after_quantity[position.symbol] = after_quantity.get(position.symbol, 0.0) + position.quantity

    symbols = sorted(set(before_quantity) | set(after_quantity) | set(fill_delta))
    rows = []
    for symbol in symbols:
        start = before_quantity.get(symbol, 0.0)
        delta = fill_delta.get(symbol, 0.0)
        expected = start + delta
        actual = after_quantity.get(symbol, 0.0)
        rows.append(
            SymbolReconciliation(
                symbol=symbol,
                before_quantity=start,
                signed_fill_quantity=delta,
                expected_after_quantity=expected,
                actual_after_quantity=actual,
                quantity_delta=actual - expected,
            )
        )
    max_delta = max((abs(item.quantity_delta) for item in rows), default=0.0)
    return PortfolioReconciliation(
        before_snapshot_id=before.snapshot_id,
        after_snapshot_id=after.snapshot_id,
        before_captured_at=before.captured_at,
        after_captured_at=after.captured_at,
        account=before.account,
        fill_count=len(seen),
        duplicate_fill_ids=tuple(sorted(duplicates)),
        symbols=tuple(rows),
        max_abs_quantity_delta=max_delta,
        reconciled=not duplicates and max_delta <= quantity_tolerance,
    )


__all__ = [
    "PortfolioFill",
    "PortfolioReconciliation",
    "SymbolReconciliation",
    "reconcile_portfolio_positions",
]
