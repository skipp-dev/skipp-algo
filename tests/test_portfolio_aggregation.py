from __future__ import annotations

from datetime import UTC, datetime

import pytest

from governance.portfolio_aggregation import project_portfolio
from governance.portfolio_contract import (
    PortfolioIntent,
    PortfolioRiskContextV1,
    PortfolioSnapshotV1,
    PositionSnapshot,
    Side,
    WorkingOrderRole,
    WorkingOrderSnapshot,
)

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


def _snapshot(*, complete: bool = True) -> PortfolioSnapshotV1:
    return PortfolioSnapshotV1.build(
        captured_at=NOW,
        account="DU123",
        base_currency="USD",
        equity=100_000.0,
        available_funds=50_000.0,
        positions=(
            PositionSnapshot(
                symbol="AAPL",
                account="DU123",
                quantity=100,
                avg_cost=190.0,
                market_price=200.0,
                stop_price=195.0,
                sector="Technology",
                strategy_families=("OB",),
            ),
        ),
        working_orders=(
            WorkingOrderSnapshot(
                order_id=1,
                order_ref="msft-entry",
                symbol="MSFT",
                account="DU123",
                side=Side.BUY,
                total_quantity=20,
                remaining_quantity=10,
                reference_price=400.0,
                role=WorkingOrderRole.ENTRY,
                strategy_family="FVG",
            ),
            WorkingOrderSnapshot(
                order_id=2,
                order_ref="aapl-stop",
                symbol="AAPL",
                account="DU123",
                side=Side.SELL,
                total_quantity=100,
                remaining_quantity=100,
                reference_price=195.0,
                role=WorkingOrderRole.EXIT,
            ),
        ),
        source="test",
        complete=complete,
    )


def test_snapshot_round_trip_and_id_are_deterministic() -> None:
    left = _snapshot()
    right = PortfolioSnapshotV1.from_dict(left.to_dict())
    assert right == left
    assert _snapshot().snapshot_id == left.snapshot_id


def test_snapshot_refuses_cross_account_state() -> None:
    with pytest.raises(ValueError, match="mixes accounts"):
        PortfolioSnapshotV1.build(
            captured_at=NOW,
            account="DU123",
            base_currency="USD",
            equity=100_000,
            available_funds=None,
            positions=(PositionSnapshot("AAPL", "DU999", 1, 100, 100),),
            source="test",
            complete=True,
        )


def test_complete_snapshot_cannot_hide_missing_market_price() -> None:
    with pytest.raises(ValueError, match="unmeasurable state"):
        PortfolioSnapshotV1.build(
            captured_at=NOW,
            account="DU123",
            base_currency="USD",
            equity=100_000,
            available_funds=None,
            positions=(PositionSnapshot("AAPL", "DU123", 1, 100, None),),
            source="test",
            complete=True,
        )


def test_projection_combines_positions_pending_entries_and_candidates() -> None:
    projection = project_portfolio(
        _snapshot(),
        (
            PortfolioIntent(
                intent_id="new-msft",
                symbol="MSFT",
                account="DU123",
                side=Side.BUY,
                quantity=5,
                entry_price=410.0,
                stop_price=400.0,
                strategy_family="BOS",
                sector="Technology",
            ),
        ),
    )
    assert projection.current_gross_usd == pytest.approx(20_000.0)
    assert projection.pending_entry_gross_usd == pytest.approx(4_000.0)
    assert projection.candidate_gross_usd == pytest.approx(2_050.0)
    assert projection.projected_gross_usd == pytest.approx(26_050.0)
    assert projection.projected_open_positions == 2
    assert projection.risk_at_stop_coverage_pct == pytest.approx(22_050 / 26_050 * 100)
    msft = next(item for item in projection.symbols if item.symbol == "MSFT")
    assert msft.strategy_families == ("BOS", "FVG")
    assert msft.projected_quantity == pytest.approx(15)
    # The protective AAPL exit must not be counted as a new short entry.
    aapl = next(item for item in projection.symbols if item.symbol == "AAPL")
    assert aapl.projected_quantity == pytest.approx(100)


def test_unknown_working_order_is_not_silently_counted_as_zero_risk() -> None:
    snapshot = PortfolioSnapshotV1.build(
        captured_at=NOW,
        account="DU123",
        base_currency="USD",
        equity=100_000,
        available_funds=100_000,
        working_orders=(
            WorkingOrderSnapshot(
                order_id=99,
                order_ref="manual-order",
                symbol="NVDA",
                account="DU123",
                side=Side.BUY,
                total_quantity=5,
                remaining_quantity=5,
                reference_price=100,
                role=WorkingOrderRole.UNKNOWN,
            ),
        ),
        source="test",
        complete=False,
        missing_fields=("working_order.role:99",),
    )
    projection = project_portfolio(snapshot, ())
    assert projection.unknown_working_orders == (99,)
    assert projection.projected_gross_usd == 0.0


def test_sector_and_correlation_context_are_applied_to_projected_symbols() -> None:
    context = PortfolioRiskContextV1(
        as_of=NOW,
        sector_by_symbol={"AAPL": "Technology", "MSFT": "Technology"},
        pair_correlations={"AAPL::MSFT": 0.91},
        observations_by_pair={"AAPL::MSFT": 60},
        complete=True,
    )
    projection = project_portfolio(
        _snapshot(),
        (
            PortfolioIntent("x", "MSFT", "DU123", Side.BUY, 5, 410, 400),
        ),
        context=context,
        correlation_threshold=0.8,
    )
    assert projection.correlation_coverage_pct == 100.0
    assert projection.max_correlated_cluster_exposure_pct == pytest.approx(26.05)
    assert projection.sector_gross_pct["Technology"] == pytest.approx(26.05)


def test_projection_rejects_intent_from_another_account() -> None:
    with pytest.raises(ValueError, match="belongs to"):
        project_portfolio(
            _snapshot(),
            (PortfolioIntent("x", "MSFT", "DU999", Side.BUY, 1, 400, 390),),
        )
