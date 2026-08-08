"""Capture a canonical, account-scoped portfolio snapshot from ``ib_async``.

The capture function accepts an already connected client so execution code can
take the snapshot in the same broker session immediately before submission.
The CLI is read-only and exists for shadow/paper evidence collection.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from governance.portfolio_contract import (
    PortfolioSnapshotV1,
    PositionSnapshot,
    Side,
    WorkingOrderRole,
    WorkingOrderSnapshot,
)
from scripts.smc_atomic_write import atomic_write_text


def _positive(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0.0 else None


def _finite_number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _accounts(ib: Any) -> tuple[str, ...]:
    managed = getattr(ib, "managedAccounts", None)
    if callable(managed):
        values = managed()
    else:
        values = getattr(getattr(ib, "wrapper", None), "accounts", ())
    return tuple(sorted({str(item).strip() for item in values or () if str(item).strip()}))


def _select_account(ib: Any, requested: str | None) -> str:
    accounts = _accounts(ib)
    if requested:
        account = requested.strip()
        if accounts and account not in accounts:
            raise ValueError(f"requested IBKR account {account!r} not in managed accounts {accounts!r}")
        return account
    if len(accounts) != 1:
        raise ValueError(
            "portfolio capture requires an explicit account when the broker session "
            f"exposes {len(accounts)} accounts: {accounts!r}"
        )
    return accounts[0]


def _account_values(ib: Any, account: str) -> tuple[float | None, float | None, str]:
    getter = getattr(ib, "accountSummary", None)
    if not callable(getter):
        return None, None, "USD"
    try:
        rows = getter(account)
    except TypeError:
        rows = getter()
    values: dict[tuple[str, str], float] = {}
    monetary_currencies: set[str] = set()
    for row in rows or ():
        row_account = str(getattr(row, "account", account) or account)
        if row_account != account:
            continue
        tag = str(getattr(row, "tag", ""))
        currency = str(getattr(row, "currency", "") or "").upper()
        numeric = _finite_number(getattr(row, "value", None))
        if numeric is not None:
            values[(tag, currency)] = numeric
        if tag in {"NetLiquidation", "AvailableFunds"} and currency not in {"BASE", ""}:
            monetary_currencies.add(currency)
    base_currency = (
        next(iter(monetary_currencies)) if len(monetary_currencies) == 1 else "USD"
    )

    def resolve(tag: str) -> float | None:
        direct = values.get((tag, base_currency))
        return direct if direct is not None else values.get((tag, "BASE"))

    return resolve("NetLiquidation"), resolve("AvailableFunds"), base_currency


def _portfolio_items(ib: Any, account: str) -> tuple[Any, ...]:
    getter = getattr(ib, "portfolio", None)
    if not callable(getter):
        return ()
    try:
        rows = getter(account)
    except TypeError:
        rows = getter()
    return tuple(
        row
        for row in rows or ()
        if str(getattr(row, "account", account) or account) == account
    )


def _usd_to_account_base_rate(
    portfolio_items: tuple[Any, ...], account_base_currency: str
) -> float | None:
    """Infer a broker-valued USD conversion with a strict consistency check."""
    if account_base_currency == "USD":
        return 1.0
    rates: list[float] = []
    for item in portfolio_items:
        contract = getattr(item, "contract", None)
        if str(getattr(contract, "currency", "")).upper() != "USD":
            continue
        quantity = _finite_number(getattr(item, "position", None))
        market_price = _positive(getattr(item, "marketPrice", None))
        market_value = _finite_number(getattr(item, "marketValue", None))
        if quantity in {None, 0.0} or market_price is None or market_value is None:
            continue
        rate = market_value / (quantity * market_price)
        if math.isfinite(rate) and rate > 0.0:
            rates.append(rate)
    if not rates:
        return None
    center = median(rates)
    if any(abs(rate - center) / center > 0.01 for rate in rates):
        return None
    return center


def _working_order_role(order: Any) -> WorkingOrderRole:
    order_ref = str(getattr(order, "orderRef", "")).lower()
    parent_id = int(getattr(order, "parentId", 0) or 0)
    if parent_id > 0 or order_ref.endswith(("-tp", "-sl", "-stop", "-trail", "-exit")):
        return WorkingOrderRole.EXIT
    if order_ref.endswith("-entry"):
        return WorkingOrderRole.ENTRY
    return WorkingOrderRole.UNKNOWN


def _order_reference_price(order: Any) -> float | None:
    for value in (
        _positive(getattr(order, "lmtPrice", None)),
        _positive(getattr(order, "auxPrice", None)),
        _positive(getattr(order, "trailStopPrice", None)),
    ):
        if value is not None:
            return value
    return None


def _active_stop_prices(open_trades: tuple[Any, ...], positions: dict[str, float]) -> dict[str, float]:
    candidates: dict[str, list[float]] = {}
    for trade in open_trades:
        symbol = str(getattr(getattr(trade, "contract", None), "symbol", "")).strip().upper()
        order = getattr(trade, "order", None)
        if not symbol or order is None or _working_order_role(order) is not WorkingOrderRole.EXIT:
            continue
        order_type = str(getattr(order, "orderType", "")).upper()
        if order_type not in {"STP", "STP LMT", "TRAIL", "TRAIL LIMIT"}:
            continue
        price = _order_reference_price(order)
        if price is not None:
            candidates.setdefault(symbol, []).append(price)
    resolved: dict[str, float] = {}
    for symbol, prices in candidates.items():
        quantity = positions.get(symbol, 0.0)
        if quantity > 0.0:
            resolved[symbol] = max(prices)
        elif quantity < 0.0:
            resolved[symbol] = min(prices)
    return resolved


def capture_ibkr_portfolio_snapshot(
    ib: Any,
    *,
    account: str | None = None,
    captured_at: datetime | None = None,
) -> PortfolioSnapshotV1:
    """Capture positions, working orders and account values from one account."""
    instant = captured_at or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("captured_at must be timezone-aware")
    selected_account = _select_account(ib, account)
    equity, available_funds, account_base_currency = _account_values(ib, selected_account)
    portfolio_items = _portfolio_items(ib, selected_account)
    missing: set[str] = set()
    usd_to_account_base = _usd_to_account_base_rate(portfolio_items, account_base_currency)
    if usd_to_account_base is None:
        missing.add(f"account.fx_conversion:{account_base_currency}->USD")
        equity = None
        available_funds = None
    else:
        equity = equity / usd_to_account_base if equity is not None else None
        available_funds = (
            available_funds / usd_to_account_base if available_funds is not None else None
        )
    base_currency = "USD"
    if equity is None:
        equity = 0.0
        missing.add("equity")

    open_trades = tuple(ib.openTrades() or ())
    raw_quantities = {
        str(getattr(getattr(item, "contract", None), "symbol", "")).strip().upper(): float(
            getattr(item, "position", 0.0) or 0.0
        )
        for item in portfolio_items
    }
    stop_prices = _active_stop_prices(open_trades, raw_quantities)
    positions: list[PositionSnapshot] = []
    for item in portfolio_items:
        contract = getattr(item, "contract", None)
        symbol = str(getattr(contract, "symbol", "")).strip().upper()
        if not symbol:
            missing.add("position.symbol")
            continue
        market_price = _positive(getattr(item, "marketPrice", None))
        if market_price is None:
            missing.add(f"position.market_price:{symbol}")
        currency = str(getattr(contract, "currency", base_currency) or base_currency).upper()
        if currency != base_currency:
            missing.add(f"position.fx_conversion:{symbol}:{currency}")
        positions.append(
            PositionSnapshot(
                symbol=symbol,
                account=selected_account,
                quantity=float(getattr(item, "position", 0.0) or 0.0),
                avg_cost=float(getattr(item, "averageCost", 0.0) or 0.0),
                market_price=market_price,
                currency=currency,
                stop_price=stop_prices.get(symbol),
            )
        )

    working_orders: list[WorkingOrderSnapshot] = []
    for trade in open_trades:
        contract = getattr(trade, "contract", None)
        order = getattr(trade, "order", None)
        status = getattr(trade, "orderStatus", None)
        if contract is None or order is None:
            missing.add("working_order.contract_or_order")
            continue
        order_account = str(getattr(order, "account", selected_account) or selected_account)
        if order_account != selected_account:
            continue
        role = _working_order_role(order)
        reference_price = _order_reference_price(order)
        if role is WorkingOrderRole.ENTRY and reference_price is None:
            missing.add(f"working_order.reference_price:{getattr(order, 'orderId', 0)}")
        if role is WorkingOrderRole.UNKNOWN:
            missing.add(f"working_order.role:{getattr(order, 'orderId', 0)}")
        total = float(getattr(order, "totalQuantity", 0.0) or 0.0)
        remaining_raw = getattr(status, "remaining", total)
        remaining = float(total if remaining_raw is None else remaining_raw)
        working_orders.append(
            WorkingOrderSnapshot(
                order_id=int(getattr(order, "orderId", 0) or 0),
                order_ref=str(getattr(order, "orderRef", "")),
                symbol=str(getattr(contract, "symbol", "")),
                account=selected_account,
                side=Side(str(getattr(order, "action", "")).upper()),
                total_quantity=total,
                remaining_quantity=remaining,
                reference_price=reference_price,
                role=role,
                parent_id=int(getattr(order, "parentId", 0) or 0),
            )
        )

    return PortfolioSnapshotV1.build(
        captured_at=instant,
        account=selected_account,
        base_currency=base_currency,
        equity=equity,
        available_funds=available_funds,
        positions=tuple(sorted(positions, key=lambda item: item.symbol)),
        working_orders=tuple(sorted(working_orders, key=lambda item: (item.symbol, item.order_id))),
        source="ibkr",
        complete=not missing,
        missing_fields=tuple(sorted(missing)),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a read-only IBKR portfolio snapshot.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=73)
    parser.add_argument("--account")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from ib_async import IB  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("ib_async is required for IBKR portfolio capture") from exc
    ib = IB()
    try:
        ib.connect(
            args.host,
            args.port,
            clientId=args.client_id,
            readonly=True,
        )
        snapshot = capture_ibkr_portfolio_snapshot(ib, account=args.account)
        atomic_write_text(
            json.dumps(snapshot.to_dict(), sort_keys=True, indent=2) + "\n",
            args.output,
            fsync=True,
        )
    finally:
        if ib.isConnected():
            ib.disconnect()
    print(json.dumps({"snapshot_id": snapshot.snapshot_id, "complete": snapshot.complete}))
    return 0 if snapshot.complete else 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["capture_ibkr_portfolio_snapshot", "main"]
