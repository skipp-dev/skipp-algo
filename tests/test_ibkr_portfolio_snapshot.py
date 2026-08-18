from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts.ibkr_portfolio_snapshot import capture_ibkr_portfolio_snapshot

NOW = datetime(2026, 8, 8, 14, 0, tzinfo=UTC)


class FakeIB:
    """Orders are served ONLY via ``reqAllOpenOrders``; ``openTrades`` is
    always empty. This mirrors the broker truth measured 2026-08-18 (bracket
    legs rest under the submitter's client id, invisible to ``openTrades`` of
    any other client) and makes every test below fail if the capture path
    regresses to the client-bound read."""

    def __init__(self, *, orders=()) -> None:
        self._orders = tuple(orders)
        self.managedAccounts = self._managed_accounts
        self.accountSummary = self._account_summary
        self.openTrades = lambda: []
        self.reqAllOpenOrders = self._open_trades

    def _managed_accounts(self):
        return ["DU123"]

    def _account_summary(self, account):
        assert account == "DU123"
        return [
            SimpleNamespace(account=account, tag="NetLiquidation", value="100000", currency="USD"),
            SimpleNamespace(account=account, tag="AvailableFunds", value="50000", currency="USD"),
        ]

    def portfolio(self, account):
        assert account == "DU123"
        return [
            SimpleNamespace(
                account=account,
                contract=SimpleNamespace(symbol="AAPL", currency="USD"),
                position=10,
                averageCost=190,
                marketPrice=200,
            )
        ]

    def _open_trades(self):
        return list(self._orders)


def _trade(*, order_id: int, order_ref: str, action: str, parent_id: int, order_type: str, price: float):
    return SimpleNamespace(
        contract=SimpleNamespace(symbol="AAPL", currency="USD"),
        order=SimpleNamespace(
            orderId=order_id,
            orderRef=order_ref,
            action=action,
            parentId=parent_id,
            orderType=order_type,
            totalQuantity=10,
            lmtPrice=price if order_type == "LMT" else 0,
            auxPrice=price if order_type == "STP" else 0,
            trailStopPrice=0,
            account="DU123",
        ),
        orderStatus=SimpleNamespace(remaining=10),
    )


def test_capture_uses_market_value_and_active_stop() -> None:
    stop = _trade(
        order_id=2,
        order_ref="aapl-stop",
        action="SELL",
        parent_id=1,
        order_type="STP",
        price=195,
    )
    snapshot = capture_ibkr_portfolio_snapshot(FakeIB(orders=(stop,)), captured_at=NOW)
    assert snapshot.complete is True
    assert snapshot.account == "DU123"
    assert snapshot.equity == pytest.approx(100_000)
    assert snapshot.positions[0].market_price == pytest.approx(200)
    assert snapshot.positions[0].stop_price == pytest.approx(195)
    assert snapshot.working_orders[0].role.value == "exit"


def test_other_clients_working_orders_reach_the_snapshot() -> None:
    """A stop resting under ANOTHER client id must still cover the position.

    2026-08-18: client 73's capture reported ``working_orders: 0`` while ten
    of client 71's bracket legs were resting — every coverage figure derived
    from that path was wrong. The capture must read ``reqAllOpenOrders``
    (all clients), never the client-bound ``openTrades``.
    """
    stop = _trade(
        order_id=2,
        order_ref="smc-AAPL-2026-08-18-port7497-sl",
        action="SELL",
        parent_id=1,
        order_type="STP",
        price=195,
    )
    ib = FakeIB(orders=(stop,))
    assert ib.openTrades() == []  # the client-bound view is genuinely blind here
    snapshot = capture_ibkr_portfolio_snapshot(ib, captured_at=NOW)
    assert snapshot.positions[0].stop_price == pytest.approx(195)
    assert len(snapshot.working_orders) == 1


def test_unknown_manual_order_marks_snapshot_incomplete() -> None:
    manual = _trade(
        order_id=9,
        order_ref="manual",
        action="BUY",
        parent_id=0,
        order_type="LMT",
        price=201,
    )
    snapshot = capture_ibkr_portfolio_snapshot(FakeIB(orders=(manual,)), captured_at=NOW)
    assert snapshot.complete is False
    assert "working_order.role:9" in snapshot.missing_fields


def test_multiple_accounts_require_explicit_selection() -> None:
    ib = FakeIB()
    ib.managedAccounts = lambda: ["DU1", "DU2"]
    with pytest.raises(ValueError, match="explicit account"):
        capture_ibkr_portfolio_snapshot(ib, captured_at=NOW)


def test_zero_available_funds_is_valid_account_state() -> None:
    ib = FakeIB()
    ib.accountSummary = lambda account: [
        SimpleNamespace(account=account, tag="NetLiquidation", value="100000", currency="USD"),
        SimpleNamespace(account=account, tag="AvailableFunds", value="0", currency="USD"),
    ]
    snapshot = capture_ibkr_portfolio_snapshot(ib, captured_at=NOW)
    assert snapshot.available_funds == 0.0
    assert snapshot.complete is True


def test_dimensionless_summary_rows_do_not_override_base_currency() -> None:
    ib = FakeIB()
    ib.accountSummary = lambda account: [
        SimpleNamespace(account=account, tag="Cushion", value="0.75", currency=""),
        SimpleNamespace(account=account, tag="NetLiquidation", value="100000", currency="EUR"),
        SimpleNamespace(account=account, tag="AvailableFunds", value="50000", currency="EUR"),
    ]
    ib.portfolio = lambda account: []

    snapshot = capture_ibkr_portfolio_snapshot(ib, captured_at=NOW)

    assert snapshot.base_currency == "USD"
    assert snapshot.equity == 0.0
    assert snapshot.available_funds is None
    assert snapshot.complete is False
    assert "account.fx_conversion:EUR->USD" in snapshot.missing_fields


def test_non_usd_account_values_are_normalized_from_broker_market_value() -> None:
    ib = FakeIB()
    ib.accountSummary = lambda account: [
        SimpleNamespace(account=account, tag="Cushion", value="0.75", currency=""),
        SimpleNamespace(account=account, tag="NetLiquidation", value="92000", currency="EUR"),
        SimpleNamespace(account=account, tag="AvailableFunds", value="46000", currency="EUR"),
    ]
    ib.portfolio = lambda account: [
        SimpleNamespace(
            account=account,
            contract=SimpleNamespace(symbol="AAPL", currency="USD"),
            position=10,
            averageCost=190,
            marketPrice=200,
            marketValue=1840,
        )
    ]

    snapshot = capture_ibkr_portfolio_snapshot(ib, captured_at=NOW)

    assert snapshot.base_currency == "USD"
    assert snapshot.equity == pytest.approx(100_000)
    assert snapshot.available_funds == pytest.approx(50_000)
    assert snapshot.complete is True


def test_inconsistent_broker_fx_evidence_marks_snapshot_incomplete() -> None:
    ib = FakeIB()
    ib.accountSummary = lambda account: [
        SimpleNamespace(account=account, tag="NetLiquidation", value="92000", currency="EUR"),
        SimpleNamespace(account=account, tag="AvailableFunds", value="46000", currency="EUR"),
    ]
    ib.portfolio = lambda account: [
        SimpleNamespace(
            account=account,
            contract=SimpleNamespace(symbol=symbol, currency="USD"),
            position=10,
            averageCost=190,
            marketPrice=200,
            marketValue=market_value,
        )
        for symbol, market_value in (("AAPL", 1840), ("MSFT", 1600))
    ]

    snapshot = capture_ibkr_portfolio_snapshot(ib, captured_at=NOW)

    assert snapshot.complete is False
    assert snapshot.equity == 0.0
    assert "account.fx_conversion:EUR->USD" in snapshot.missing_fields
