"""Typed contracts for rl/. Stdlib-only."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

OrderType = Literal["limit_at_mid", "limit_aggressive", "market"]
VALID_ORDER_TYPES: tuple[OrderType, ...] = (
    "limit_at_mid",
    "limit_aggressive",
    "market",
)


@dataclass(frozen=True)
class ExecutionState:
    """Schema-aligned with rl/schemas/v1_execution_state.json."""

    remaining_qty: float
    remaining_time: float
    current_volatility: float
    current_spread: float
    recent_volume_profile: tuple[float, ...]
    signal_strength: float


@dataclass(frozen=True)
class ExecutionAction:
    slice_size: float          # fraction of remaining_qty in [0, 1]
    order_type: OrderType

    def __post_init__(self) -> None:
        if not 0.0 <= self.slice_size <= 1.0:
            raise ValueError(f"slice_size out of range: {self.slice_size}")
        if self.order_type not in VALID_ORDER_TYPES:
            raise ValueError(
                f"order_type {self.order_type!r} not in {VALID_ORDER_TYPES}"
            )


@dataclass(frozen=True)
class SlippageEstimate:
    """Output of the Almgren-Chriss-style calibrator."""

    expected_bps: float
    permanent_impact_bps: float
    temporary_impact_bps: float
    confidence_low_bps: float
    confidence_high_bps: float


@dataclass(frozen=True)
class TradeRecord:
    """A single live or simulated child-order fill.

    Quantities in shares/contracts, prices in price-units, times in seconds.
    ``mid_at_signal`` is the mid-price at the moment the parent decision was
    issued (used as the implementation-shortfall anchor).
    """

    order_id: str
    family: str
    side: int  # +1 buy, -1 sell
    quantity: float
    mid_at_signal: float
    fill_price: float
    volume_at_signal: float
    duration_s: float
    timestamp_s: float = 0.0


@dataclass
class TradeBlotter:
    records: list[TradeRecord] = field(default_factory=list)

    def add(self, record: TradeRecord) -> None:
        self.records.append(record)

    def __len__(self) -> int:
        return len(self.records)

    def to_features_targets(self):
        """Return ``(X, y_bps)`` arrays for slippage calibration.

        Features: [signed_pct_of_volume, sqrt_duration, abs_signed_pct].
        Target:   slippage in bps from mid_at_signal.
        """
        import numpy as np

        if not self.records:
            raise ValueError("empty blotter")
        X_rows: list[list[float]] = []
        y_vals: list[float] = []
        for r in self.records:
            v = max(r.volume_at_signal, 1.0)
            spct = (r.side * r.quantity) / v
            dur = max(r.duration_s, 1e-6)
            X_rows.append([spct, dur**0.5, abs(spct)])
            slip = (r.fill_price - r.mid_at_signal) / max(r.mid_at_signal, 1e-12) * 1e4
            y_vals.append(r.side * slip)  # positive = adverse
        return np.asarray(X_rows, dtype=float), np.asarray(y_vals, dtype=float)
