from __future__ import annotations

from datetime import date, time

import pandas as pd

from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
    IBKRExecutionConfig,
    _build_tp_trail_orders,
    _parse_time_of_day,
    _resolve_trigger_datetime,
    build_order_intents,
    build_preview_payload,
    filter_watchlist,
    monitor_open_orders,
    reconcile_fills_and_positions,
    resolve_trade_date,
    supervise_open_execution,
)
from scripts.run_ibkr_open_execution import build_execution_event_log, build_parser as build_supervisor_parser, write_execution_event_log_csv


def _sample_watchlist() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 7), date(2026, 3, 8)],
            "watchlist_rank": [2, 1],
            "symbol": ["AAA", "BBB"],
            "premarket_last": [10.0, 12.0],
            "prev_close_to_premarket_pct": [8.0, 11.0],
            "l1_quantity": [100, 120],
            "l1_limit_buy": [9.96, 11.952],
            "l1_take_profit": [10.1094, 12.1313],
            "l1_stop_loss": [9.8006, 11.7608],
            "l1_trailing_stop_pct": [0.01, 0.01],
            "l1_trailing_stop_anchor": [9.8604, 11.8325],
            "l2_quantity": [150, 180],
            "l2_limit_buy": [9.91, 11.892],
            "l2_take_profit": [10.0587, 12.0704],
            "l2_stop_loss": [9.7514, 11.7017],
            "l2_trailing_stop_pct": [0.01, 0.01],
            "l2_trailing_stop_anchor": [9.8109, 11.7731],
            "l3_quantity": [200, 220],
            "l3_limit_buy": [9.83, 11.796],
            "l3_take_profit": [9.9774, 11.9729],
            "l3_stop_loss": [9.6727, 11.6073],
            "l3_trailing_stop_pct": [0.01, 0.01],
            "l3_trailing_stop_anchor": [9.7317, 11.678],
        }
    )


def test_resolve_trade_date_defaults_to_latest() -> None:
    watchlist = _sample_watchlist()
    assert resolve_trade_date(watchlist, None) == date(2026, 3, 8)


def test_filter_watchlist_applies_trade_date_and_symbols() -> None:
    watchlist = _sample_watchlist()
    filtered = filter_watchlist(watchlist, trade_date=date(2026, 3, 8), symbols=["BBB"], top_n=1)
    assert filtered[["trade_date", "symbol"]].to_dict(orient="records") == [
        {"trade_date": date(2026, 3, 8), "symbol": "BBB"}
    ]


def test_build_order_intents_creates_three_level_orders() -> None:
    watchlist = filter_watchlist(_sample_watchlist(), trade_date=date(2026, 3, 8))
    intents = build_order_intents(watchlist, IBKRExecutionConfig(exit_mode="tp-stop"))

    assert [intent.level_tag for intent in intents] == ["L1", "L2", "L3"]
    assert [intent.quantity for intent in intents] == [120, 180, 220]
    assert intents[0].order_ref == "skipp-2026-03-08-BBB-L1"
    assert intents[2].take_profit == 11.9729


def test_build_order_intents_rejects_invalid_price_values() -> None:
    watchlist = filter_watchlist(_sample_watchlist(), trade_date=date(2026, 3, 8)).copy()
    watchlist.loc[watchlist.index[0], "l2_limit_buy"] = float("nan")

    try:
        build_order_intents(watchlist, IBKRExecutionConfig(exit_mode="tp-stop"))
        raise AssertionError("Expected ValueError for NaN order price")
    except ValueError as exc:
        assert "l2_limit_buy" in str(exc)


def test_build_preview_payload_is_json_ready() -> None:
    watchlist = filter_watchlist(_sample_watchlist(), trade_date=date(2026, 3, 8))
    intents = build_order_intents(watchlist, IBKRExecutionConfig(exit_mode="tp-trail"))
    payload = build_preview_payload(intents, connection_cfg=None, source_metadata={"source": "unit_test"})

    assert payload["source"] == {"source": "unit_test"}
    assert payload["connection"] is None
    assert payload["order_count"] == 3
    assert payload["orders"][0]["exit_mode"] == "tp-trail"


def test_parse_time_of_day_supports_disable_and_hms() -> None:
    assert _parse_time_of_day("15:30:20") == time(15, 30, 20)
    assert _parse_time_of_day("15:31") == time(15, 31, 0)
    assert _parse_time_of_day("off") is None


def test_resolve_trigger_datetime_uses_timezone() -> None:
    trigger = _resolve_trigger_datetime(date(2026, 3, 8), "15:30:20", "Europe/Berlin")

    assert trigger is not None
    assert trigger.date() == date(2026, 3, 8)
    assert trigger.hour == 15
    assert trigger.minute == 30
    assert trigger.second == 20
    assert str(trigger.tzinfo) == "Europe/Berlin"


def test_build_tp_trail_orders_sets_oca_group_and_anchor() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self._next_id = 100

        def getReqId(self) -> int:
            value = self._next_id
            self._next_id += 1
            return value

    class FakeIB:
        def __init__(self) -> None:
            self.client = FakeClient()

    class FakeOrder:
        def __init__(self, **kwargs) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    class FakeLimitOrder(FakeOrder):
        def __init__(self, action: str, quantity: int, limit_price: float) -> None:
            super().__init__(action=action, totalQuantity=quantity, lmtPrice=limit_price, orderType="LMT")

    watchlist = filter_watchlist(_sample_watchlist(), trade_date=date(2026, 3, 8))
    intent = build_order_intents(watchlist, IBKRExecutionConfig(exit_mode="tp-trail"))[0]

    orders = _build_tp_trail_orders(
        ib=FakeIB(),
        LimitOrder=FakeLimitOrder,
        Order=FakeOrder,
        intent=intent,
        connection_cfg=IBKRConnectionConfig(),
    )

    assert len(orders) == 3
    assert orders[1].ocaGroup == orders[2].ocaGroup
    assert orders[1].ocaType == 1
    assert orders[2].ocaType == 1
    assert orders[2].trailStopPrice == intent.trailing_stop_anchor


def test_monitor_open_orders_returns_filtered_snapshot() -> None:
    class FakeContract:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

    class FakeOrder:
        def __init__(self, order_id: int, order_ref: str) -> None:
            self.orderId = order_id
            self.permId = order_id + 1000
            self.parentId = 0
            self.orderRef = order_ref
            self.orderType = "LMT"
            self.action = "BUY"
            self.totalQuantity = 100
            self.lmtPrice = 9.96
            self.auxPrice = None

    class FakeOrderStatus:
        def __init__(self, status: str) -> None:
            self.status = status
            self.filled = 0
            self.remaining = 100
            self.avgFillPrice = 0

    class FakeTrade:
        def __init__(self, symbol: str, order_id: int, order_ref: str, status: str) -> None:
            self.contract = FakeContract(symbol)
            self.order = FakeOrder(order_id, order_ref)
            self.orderStatus = FakeOrderStatus(status)

    class FakeIB:
        def openTrades(self):
            return [
                FakeTrade("AAA", 1, "skipp-2026-03-08-AAA-L1-entry", "Submitted"),
                FakeTrade("BBB", 2, "skipp-2026-03-08-BBB-L1-entry", "Submitted"),
            ]

    snapshot = monitor_open_orders(FakeIB(), symbols=["BBB"], related_order_refs=["skipp-2026-03-08-BBB-L1-entry"])

    assert snapshot == [
        {
            "symbol": "BBB",
            "order_id": 2,
            "perm_id": 1002,
            "parent_id": 0,
            "order_ref": "skipp-2026-03-08-BBB-L1-entry",
            "order_type": "LMT",
            "action": "BUY",
            "total_quantity": 100.0,
            "filled": 0.0,
            "remaining": 100.0,
            "avg_fill_price": 0.0,
            "lmt_price": 9.96,
            "aux_price": None,
            "status": "Submitted",
        }
    ]


def test_reconcile_fills_and_positions_filters_account_and_symbols() -> None:
    class FakeContract:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol

    class FakeExecution:
        def __init__(self, order_id: int, order_ref: str, side: str, shares: float, price: float, when: str) -> None:
            self.orderId = order_id
            self.permId = order_id + 100
            self.orderRef = order_ref
            self.side = side
            self.shares = shares
            self.price = price
            self.time = when

    class FakeFill:
        def __init__(self, symbol: str, order_id: int, order_ref: str) -> None:
            self.contract = FakeContract(symbol)
            self.execution = FakeExecution(order_id, order_ref, "BOT", 50, 10.0, "2026-03-08T15:30:01")

    class FakePosition:
        def __init__(self, symbol: str, account: str, position: float, avg_cost: float) -> None:
            self.contract = FakeContract(symbol)
            self.account = account
            self.position = position
            self.avgCost = avg_cost

    class FakeIB:
        def openTrades(self):
            return []

        def fills(self):
            return [
                FakeFill("AAA", 1, "skipp-2026-03-08-AAA-L1-entry"),
                FakeFill("BBB", 2, "skipp-2026-03-08-BBB-L1-entry"),
            ]

        def positions(self):
            return [
                FakePosition("AAA", "DU123", 50, 10.1),
                FakePosition("BBB", "DU999", 75, 11.2),
            ]

    reconciliation = reconcile_fills_and_positions(
        FakeIB(),
        symbols=["AAA"],
        related_order_refs=["skipp-2026-03-08-AAA-L1-entry"],
        account="DU123",
    )

    assert reconciliation["fills"] == [
        {
            "symbol": "AAA",
            "order_id": 1,
            "perm_id": 101,
            "order_ref": "skipp-2026-03-08-AAA-L1-entry",
            "side": "BOT",
            "shares": 50.0,
            "price": 10.0,
            "time": "2026-03-08T15:30:01",
        }
    ]
    assert reconciliation["positions"] == [
        {"symbol": "AAA", "account": "DU123", "position": 50.0, "avg_cost": 10.1}
    ]


def test_supervisor_parser_requires_explicit_place_orders_flag_from_caller() -> None:
    args = build_supervisor_parser().parse_args(["--place-orders"])

    assert args.place_orders is True
    assert args.poll_interval_seconds == 1.0
    assert args.supervisor_timeout_seconds == 900.0
    assert args.reconnect_max_attempts == 3


def test_supervise_open_execution_recovers_from_initial_disconnect() -> None:
    class FakeIB:
        def __init__(self) -> None:
            self.connected = False
            self.connect_calls = 0

        def isConnected(self) -> bool:
            return self.connected

        def connect(self, host: str, port: int, clientId: int, timeout: float, readonly: bool) -> None:
            self.connect_calls += 1
            self.connected = True

        def openTrades(self):
            return []

        def fills(self):
            return []

        def positions(self):
            return []

    ib = FakeIB()
    supervisor = supervise_open_execution(
        ib,
        connection_cfg=IBKRConnectionConfig(),
        execution_cfg=IBKRExecutionConfig(cancel_unfilled_after=None, time_stop_after=None),
        trade_dates_by_symbol={"AAA": "2026-03-08"},
        entry_order_refs_by_symbol={"AAA": ["skipp-2026-03-08-AAA-L1-entry"]},
        all_order_refs_by_symbol={"AAA": ["skipp-2026-03-08-AAA-L1-entry"]},
        poll_interval_seconds=0.01,
        timeout_seconds=1.0,
        reconnect_max_attempts=2,
        reconnect_wait_seconds=0.0,
    )

    reconnect_events = [event for event in supervisor["events"] if event.get("action") == "reconnect"]

    assert ib.connect_calls == 1
    assert supervisor["timed_out"] is False
    assert len(reconnect_events) == 1
    assert reconnect_events[0]["status"] == "reconnected"


def test_build_execution_event_log_and_csv_export(tmp_path) -> None:
    submission = {
        "placements": [
            {
                "symbol": "AAA",
                "level_tag": "L1",
                "exit_mode": "tp-stop",
                "orders": [
                    {
                        "placed_at": "2026-03-08T14:30:00+00:00",
                        "order_id": 101,
                        "order_ref": "skipp-2026-03-08-AAA-L1-entry",
                        "order_type": "LMT",
                        "action": "BUY",
                        "status": "Submitted",
                    }
                ],
            }
        ]
    }
    supervisor = {
        "timed_out": False,
        "events": [
            {
                "action": "reconnect",
                "status": "reconnected",
                "captured_at": "2026-03-08T14:30:05+00:00",
                "reason": "reconcile_snapshot:precheck",
            },
            {
                "action": "flatten",
                "status": "Submitted",
                "symbol": "AAA",
                "trigger_at": "2026-03-08T15:31:00+01:00",
            },
        ],
        "snapshots": [
            {
                "captured_at": "2026-03-08T14:30:01+00:00",
                "open_orders": [{"symbol": "AAA"}],
                "fills": [],
                "positions": [],
            },
            {
                "captured_at": "2026-03-08T14:30:02+00:00",
                "open_orders": [],
                "fills": [{"symbol": "AAA"}],
                "positions": [{"symbol": "AAA", "position": 100.0}],
            },
        ],
        "final": {"open_orders": [], "fills": [{"symbol": "AAA"}], "positions": []},
    }

    rows = build_execution_event_log(submission, supervisor)

    assert [row["event_type"] for row in rows] == [
        "order_submitted",
        "state_change",
        "state_change",
        "reconnect",
        "flatten",
        "final_state",
    ]

    output_csv = tmp_path / "ibkr_events.csv"
    write_execution_event_log_csv(rows, output_csv)

    contents = output_csv.read_text(encoding="utf-8")
    assert "order_submitted" in contents
    assert "reconnect" in contents
    assert "final_state" in contents