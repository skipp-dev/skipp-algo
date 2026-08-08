from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from governance.portfolio_contract import PortfolioSnapshotV1, PositionSnapshot, Side
from governance.portfolio_reconciliation import PortfolioFill, reconcile_portfolio_positions

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _snapshot(snapshot_time: datetime, aapl: float, msft: float = 0) -> PortfolioSnapshotV1:
    positions = [PositionSnapshot("AAPL", "DU1", aapl, 100, 100)]
    if msft:
        positions.append(PositionSnapshot("MSFT", "DU1", msft, 200, 200))
    return PortfolioSnapshotV1.build(
        captured_at=snapshot_time,
        account="DU1",
        base_currency="USD",
        equity=100_000,
        available_funds=50_000,
        positions=tuple(positions),
        source="test",
        complete=True,
    )


def test_reconciles_signed_fill_deltas() -> None:
    before = _snapshot(NOW, 10)
    after = _snapshot(NOW + timedelta(minutes=1), 15, 2)
    fills = (
        PortfolioFill("e1", "AAPL", "DU1", Side.BUY, 5, 101),
        PortfolioFill("e2", "MSFT", "DU1", Side.BUY, 2, 201),
    )
    result = reconcile_portfolio_positions(before, after, fills)
    assert result.reconciled is True
    assert result.max_abs_quantity_delta == 0


def test_duplicate_fill_is_deduplicated_and_reported() -> None:
    before = _snapshot(NOW, 10)
    after = _snapshot(NOW + timedelta(minutes=1), 15)
    duplicate = PortfolioFill("e1", "AAPL", "DU1", Side.BUY, 5, 101)
    result = reconcile_portfolio_positions(before, after, (duplicate, duplicate))
    assert result.duplicate_fill_ids == ("e1",)
    assert result.reconciled is False


def test_unexplained_position_delta_fails_reconciliation() -> None:
    before = _snapshot(NOW, 10)
    after = _snapshot(NOW + timedelta(minutes=1), 16)
    result = reconcile_portfolio_positions(
        before,
        after,
        (PortfolioFill("e1", "AAPL", "DU1", Side.BUY, 5, 101),),
    )
    assert result.reconciled is False
    assert result.max_abs_quantity_delta == pytest.approx(1)
