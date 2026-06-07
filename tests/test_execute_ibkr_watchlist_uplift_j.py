"""Coverage uplift bucket J — `scripts/execute_ibkr_watchlist.py`.

Targets the IBKR helper layer, reconnect plumbing, schedule-driven
operations (`cancel_symbol_orders_after`, `flatten_after`),
`place_order_intents_with_ib`/`place_order_intents`,
`check_ibkr_connection`, and the CLI entry point.

All ib_async types are stubbed via `_import_ibkr_types` patches; no
TWS/IB Gateway is touched and `time_module.sleep` is patched out so
schedule helpers run instantly.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from scripts import execute_ibkr_watchlist as mod
from scripts.execute_ibkr_watchlist import (
    IBKRConnectionConfig,
    IBKRExecutionConfig,
    IBKROrderIntent,
    _apply_common_order_fields,
    _as_valid_nonnegative_fraction,
    _as_valid_price,
    _attempt_ibkr_reconnect,
    _call_with_reconnect,
    _coerce_watchlist_trade_dates,
    _is_live_order_status,
    _looks_like_connection_error,
    _normalize_order_ref_filter,
    _normalize_schedule_value,
    _normalize_symbol_filter,
    _normalize_trade_date,
    _parse_symbol_filter,
    _parse_time_of_day,
    _resolve_trigger_datetime,
    _sanitize_error_text,
    _sleep_until,
    cancel_symbol_orders_after,
    check_ibkr_connection,
    flatten_after,
    load_watchlist_frame,
    place_order_intents,
    place_order_intents_with_ib,
)

# ── small pure helpers ─────────────────────────────────────────


class TestNormalizeTradeDate:
    def test_string_iso_date(self):
        assert _normalize_trade_date("2026-04-23") == date(2026, 4, 23)

    def test_pandas_timestamp(self):
        ts = pd.Timestamp("2026-04-22")
        assert _normalize_trade_date(ts) == date(2026, 4, 22)

    def test_invalid_raises(self):
        with pytest.raises((ValueError, TypeError, pd.errors.ParserError)):
            _normalize_trade_date("not-a-date")


class TestParseSymbolFilter:
    def test_none_or_empty(self):
        assert _parse_symbol_filter(None) == []
        assert _parse_symbol_filter("") == []

    def test_uppercase_split_and_strip(self):
        assert _parse_symbol_filter(" aapl ,tsla, , msft") == ["AAPL", "TSLA", "MSFT"]


class TestNormalizeScheduleValue:
    def test_none_passthrough(self):
        assert _normalize_schedule_value(None) is None

    def test_blank_returns_none(self):
        assert _normalize_schedule_value("   ") is None

    def test_disable_keywords(self):
        for v in ["off", "OFF", "None", "disable", "Disabled"]:
            assert _normalize_schedule_value(v) is None

    def test_normal_value_kept(self):
        assert _normalize_schedule_value("15:30") == "15:30"


class TestParseTimeOfDay:
    def test_none_passthrough(self):
        assert _parse_time_of_day(None) is None

    def test_off_returns_none(self):
        assert _parse_time_of_day("off") is None

    def test_hh_mm(self):
        assert _parse_time_of_day("15:30") == time(15, 30, 0)

    def test_hh_mm_ss(self):
        assert _parse_time_of_day("15:30:20") == time(15, 30, 20)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid time-of-day"):
            _parse_time_of_day("15")

    def test_too_many_parts_raises(self):
        with pytest.raises(ValueError, match="Invalid time-of-day"):
            _parse_time_of_day("15:30:20:99")


class TestResolveTriggerDatetime:
    def test_none_input_returns_none(self):
        assert _resolve_trigger_datetime(date(2026, 4, 23), None, "Europe/Berlin") is None

    def test_valid_combine_with_tz(self):
        out = _resolve_trigger_datetime(date(2026, 4, 23), "15:30", "Europe/Berlin")
        assert out == datetime(2026, 4, 23, 15, 30, tzinfo=ZoneInfo("Europe/Berlin"))

    def test_unknown_timezone_raises(self):
        with pytest.raises(ValueError, match="Unknown timezone"):
            _resolve_trigger_datetime(date(2026, 4, 23), "15:30", "Mars/Olympus")


class TestSleepUntil:
    def test_none_returns_immediately(self):
        with patch.object(mod.time_module, "sleep") as sleep_mock:
            _sleep_until(None)
        assert not sleep_mock.called

    def test_past_target_returns_without_sleep(self):
        past = datetime.now(UTC).replace(year=2020)
        with patch.object(mod.time_module, "sleep") as sleep_mock:
            _sleep_until(past)
        assert not sleep_mock.called


class TestIsLiveOrderStatus:
    @pytest.mark.parametrize("status", ["Submitted", "PreSubmitted", "PendingCancel"])
    def test_live(self, status):
        assert _is_live_order_status(status) is True

    # NOTE: sorted() is required for pytest-xdist worker collection determinism.
    # mod.TERMINAL_ORDER_STATUSES is a set/frozenset; iteration order varies per
    # worker which causes "Different tests were collected between gw0 and gw1".
    @pytest.mark.parametrize("status", sorted(mod.TERMINAL_ORDER_STATUSES))
    def test_terminal(self, status):
        assert _is_live_order_status(status) is False


class TestNormalizeFilters:
    def test_symbol_filter_uppercases_and_skips_blank(self):
        # Implementation uppercases but does NOT strip surrounding whitespace.
        assert _normalize_symbol_filter(["aapl", "", "tsla"]) == {"AAPL", "TSLA"}

    def test_symbol_filter_none(self):
        assert _normalize_symbol_filter(None) == set()

    def test_order_ref_filter(self):
        assert _normalize_order_ref_filter(["a", "  ", "b"]) == {"a", "b"}

    def test_order_ref_filter_none(self):
        assert _normalize_order_ref_filter(None) == set()


class TestLooksLikeConnectionError:
    @pytest.mark.parametrize(
        "msg",
        [
            "Not Connected",
            "TCP socket dropped",
            "Broken pipe",
            "Peer closed",
            "EOF on read",
            "disconnect happened",
        ],
    )
    def test_truthy(self, msg):
        assert _looks_like_connection_error(Exception(msg)) is True

    def test_other_exception(self):
        assert _looks_like_connection_error(ValueError("bad input")) is False


class TestSanitizeErrorText:
    def test_redacts_api_key(self):
        out = _sanitize_error_text("oops api_key=abc123 failed")
        assert "abc123" not in out
        assert "***" in out

    def test_redacts_token_and_bearer(self):
        out = _sanitize_error_text("Authorization: Bearer xyz789 token=qqq")
        assert "xyz789" not in out
        assert "qqq" not in out

    def test_passthrough_when_safe(self):
        assert _sanitize_error_text("nothing sensitive") == "nothing sensitive"


class TestAsValidPrice:
    def test_valid_number(self):
        assert _as_valid_price(12.5, field_name="x") == 12.5

    @pytest.mark.parametrize("v", [0, -1, float("inf"), float("nan")])
    def test_invalid(self, v):
        with pytest.raises(ValueError, match="x must be"):
            _as_valid_price(v, field_name="x")


class TestAsValidNonnegativeFraction:
    def test_zero_ok(self):
        assert _as_valid_nonnegative_fraction(0, field_name="frac") == 0.0

    def test_positive_ok(self):
        assert _as_valid_nonnegative_fraction(0.25, field_name="frac") == 0.25

    @pytest.mark.parametrize("v", [-1, float("inf"), float("nan")])
    def test_invalid(self, v):
        with pytest.raises(ValueError, match="frac must be"):
            _as_valid_nonnegative_fraction(v, field_name="frac")


# ── reconnect plumbing ─────────────────────────────────────────


class _FakeIB:
    def __init__(
        self,
        *,
        connect_results: list[bool] | None = None,
        connect_side_effects: list[Any] | None = None,
        is_connected_returns: list[bool] | None = None,
    ):
        self._connect_results = list(connect_results or [])
        self._connect_side_effects = list(connect_side_effects or [])
        self._is_connected_returns = list(is_connected_returns or [])
        self._is_connected_default = False
        self.connect_calls: list[dict[str, Any]] = []

    def connect(self, host, port, *, clientId, timeout, readonly):
        self.connect_calls.append(dict(host=host, port=port, clientId=clientId, timeout=timeout, readonly=readonly))
        if self._connect_side_effects:
            effect = self._connect_side_effects.pop(0)
            if isinstance(effect, Exception):
                self._is_connected_default = False
                raise effect
        if self._connect_results:
            self._is_connected_default = self._connect_results.pop(0)
        else:
            self._is_connected_default = True

    def isConnected(self):  # noqa: N802 - mirrors ib_insync IB API
        if self._is_connected_returns:
            return self._is_connected_returns.pop(0)
        return self._is_connected_default


class TestAttemptIbkrReconnect:
    cfg = IBKRConnectionConfig()

    def test_disabled_when_max_attempts_zero(self):
        ib = _FakeIB()
        out = _attempt_ibkr_reconnect(ib, connection_cfg=self.cfg, max_attempts=0, wait_seconds=0.0, reason="rebooted")
        assert out["status"] == "disabled"
        assert out["attempts"] == []
        assert out["reason"] == "rebooted"

    def test_succeeds_first_attempt(self):
        ib = _FakeIB(connect_results=[True])
        with patch.object(mod.time_module, "sleep"):
            out = _attempt_ibkr_reconnect(ib, connection_cfg=self.cfg, max_attempts=3, wait_seconds=0.0, reason="x")
        assert out["status"] == "reconnected"
        assert len(out["attempts"]) == 1
        assert out["attempts"][0]["connected"] is True

    def test_fails_then_succeeds(self):
        ib = _FakeIB(connect_results=[False, True])
        with patch.object(mod.time_module, "sleep"):
            out = _attempt_ibkr_reconnect(ib, connection_cfg=self.cfg, max_attempts=3, wait_seconds=0.5, reason="x")
        assert out["status"] == "reconnected"
        assert len(out["attempts"]) == 2

    def test_all_attempts_raise(self):
        ib = _FakeIB(
            connect_side_effects=[
                RuntimeError("api_key=secret123 boom"),
                RuntimeError("again"),
            ]
        )
        with patch.object(mod.time_module, "sleep"):
            out = _attempt_ibkr_reconnect(ib, connection_cfg=self.cfg, max_attempts=2, wait_seconds=0.0, reason="x")
        assert out["status"] == "failed"
        assert len(out["attempts"]) == 2
        # error text was sanitized
        assert "secret123" not in out["attempts"][0]["error"]


class TestCallWithReconnect:
    cfg = IBKRConnectionConfig()

    def test_op_runs_when_connected(self):
        ib = _FakeIB(is_connected_returns=[True])
        events: list[dict] = []
        out = _call_with_reconnect(
            ib,
            operation_name="op",
            operation=lambda: "ok",
            connection_cfg=self.cfg,
            reconnect_max_attempts=0,
            reconnect_wait_seconds=0.0,
            events=events,
        )
        assert out == "ok"
        assert events == []

    def test_precheck_reconnects_then_runs(self):
        # First isConnected -> False (precheck triggers reconnect),
        # then reconnect succeeds (sets default True), op then runs.
        ib = _FakeIB(is_connected_returns=[False])
        events: list[dict] = []
        with patch.object(mod.time_module, "sleep"):
            out = _call_with_reconnect(
                ib,
                operation_name="op",
                operation=lambda: "after-recon",
                connection_cfg=self.cfg,
                reconnect_max_attempts=2,
                reconnect_wait_seconds=0.0,
                events=events,
            )
        assert out == "after-recon"
        assert events and events[0]["status"] == "reconnected"

    def test_precheck_reconnect_fails_raises(self):
        ib = _FakeIB(is_connected_returns=[False], connect_side_effects=[RuntimeError("denied")])
        events: list[dict] = []
        with (
            patch.object(mod.time_module, "sleep"),
            pytest.raises(RuntimeError, match="reconnect failed before op"),
        ):
            _call_with_reconnect(
                ib,
                operation_name="op",
                operation=lambda: "x",
                connection_cfg=self.cfg,
                reconnect_max_attempts=1,
                reconnect_wait_seconds=0.0,
                events=events,
            )
        assert events[-1]["status"] == "failed"

    def test_op_raises_non_connection_error_rethrows(self):
        ib = _FakeIB(is_connected_returns=[True, True])
        with pytest.raises(ValueError, match="bad"):
            _call_with_reconnect(
                ib,
                operation_name="op",
                operation=lambda: (_ for _ in ()).throw(ValueError("bad")),
                connection_cfg=self.cfg,
                reconnect_max_attempts=0,
                reconnect_wait_seconds=0.0,
                events=[],
            )

    def test_op_raises_connection_error_recovers_and_reruns(self):
        # First isConnected True, op throws connection error, then connect_results give True.
        ib = _FakeIB(is_connected_returns=[True, False], connect_results=[True])
        calls = {"n": 0}

        def op():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("not connected: socket lost")
            return "recovered"

        events: list[dict] = []
        with patch.object(mod.time_module, "sleep"):
            out = _call_with_reconnect(
                ib,
                operation_name="op",
                operation=op,
                connection_cfg=self.cfg,
                reconnect_max_attempts=2,
                reconnect_wait_seconds=0.0,
                events=events,
            )
        assert out == "recovered"
        assert events[-1]["status"] == "reconnected"

    def test_op_raises_connection_error_reconnect_fails_wraps_error(self):
        ib = _FakeIB(is_connected_returns=[True, False], connect_side_effects=[RuntimeError("nope")])

        def op():
            raise RuntimeError("not connected: peer closed")

        events: list[dict] = []
        with (
            patch.object(mod.time_module, "sleep"),
            pytest.raises(RuntimeError, match="reconnect failed during op"),
        ):
            _call_with_reconnect(
                ib,
                operation_name="op",
                operation=op,
                connection_cfg=self.cfg,
                reconnect_max_attempts=1,
                reconnect_wait_seconds=0.0,
                events=events,
            )


# ── coerce + load watchlist frame ──────────────────────────────


class TestCoerceWatchlistTradeDates:
    def test_normalizes_dates_and_uppercases_symbols(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["2026-04-23", "2026-04-22"],
                "symbol": ["aapl", "tsla"],
            }
        )
        out = _coerce_watchlist_trade_dates(frame)
        assert out["trade_date"].tolist() == [date(2026, 4, 23), date(2026, 4, 22)]
        assert out["symbol"].tolist() == ["AAPL", "TSLA"]


class TestLoadWatchlistFrame:
    def test_csv_path_loads(self, tmp_path: Path):
        csv = tmp_path / "wl.csv"
        csv.write_text("trade_date,symbol\n2026-04-23,aapl\n", encoding="utf-8")
        cfg = MagicMock()
        out, meta = load_watchlist_frame(watchlist_csv=csv, bundle=None, export_dir=None, watchlist_cfg=cfg)
        assert meta["source"] == "watchlist_csv"
        assert out["symbol"].tolist() == ["AAPL"]

    def test_csv_path_missing_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_watchlist_frame(
                watchlist_csv=tmp_path / "nope.csv", bundle=None, export_dir=None, watchlist_cfg=MagicMock()
            )

    def test_bundle_path_uses_loader(self, tmp_path: Path):
        cfg = MagicMock()
        fake_daily, fake_prem, fake_diag = MagicMock(), MagicMock(), MagicMock()
        meta = {"source": "bundle"}
        wl_frame = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]})
        with (
            patch.object(
                mod, "load_watchlist_inputs", return_value=(fake_daily, fake_prem, fake_diag, meta)
            ) as load_mock,
            patch.object(mod, "build_daily_watchlists", return_value=wl_frame) as build_mock,
        ):
            out, out_meta = load_watchlist_frame(
                watchlist_csv=None, bundle=tmp_path / "manifest", export_dir=None, watchlist_cfg=cfg
            )
        assert out_meta == meta
        assert load_mock.called and build_mock.called
        assert out.equals(wl_frame)


# ── apply_common_order_fields ──────────────────────────────────


def _make_intent(**kwargs) -> IBKROrderIntent:
    defaults = dict(
        trade_date=date(2026, 4, 23),
        symbol="AAPL",
        watchlist_rank=1,
        level_tag="L1",
        quantity=10,
        entry_limit=100.0,
        take_profit=110.0,
        stop_loss=95.0,
        trailing_stop_pct=0.02,
        trailing_stop_anchor=105.0,
        premarket_last=99.5,
        gap_pct=-1.5,
        tif="DAY",
        outside_rth=False,
        exit_mode="tp-stop",
        order_ref="ref-1",
    )
    defaults.update(kwargs)
    return IBKROrderIntent(**defaults)


class TestApplyCommonOrderFields:
    def test_sets_tif_outside_rth_orderref(self):
        order = SimpleNamespace()
        intent = _make_intent(tif="GTC", outside_rth=True)
        cfg = IBKRConnectionConfig(account=None)
        _apply_common_order_fields(order, intent, cfg, order_ref="X")
        assert order.tif == "GTC"
        assert order.outsideRth is True
        assert order.orderRef == "X"
        assert not hasattr(order, "account")

    def test_account_set_when_configured(self):
        order = SimpleNamespace()
        intent = _make_intent()
        cfg = IBKRConnectionConfig(account="DU123")
        _apply_common_order_fields(order, intent, cfg, order_ref="X")
        assert order.account == "DU123"


# ── check_ibkr_connection ──────────────────────────────────────


def _patch_ibkr_types(
    IB: Any = None, Stock: Any = None, LimitOrder: Any = None, MarketOrder: Any = None, Order: Any = None
):
    types = (
        IB or MagicMock(),
        Stock or MagicMock(),
        LimitOrder or MagicMock(),
        MarketOrder or MagicMock(),
        Order or MagicMock(),
    )
    return patch.object(mod, "_import_ibkr_types", return_value=types)


class TestCheckIbkrConnection:
    def test_returns_handshake_metadata(self):
        ib_instance = MagicMock()
        ib_instance.isConnected.return_value = True
        ib_instance.client.serverVersion.return_value = 178
        ib_instance.client.getReqId.return_value = 999
        ib_instance.wrapper.accounts = ["DU111", "DU222"]
        IB = MagicMock(return_value=ib_instance)
        with _patch_ibkr_types(IB=IB):
            out = check_ibkr_connection(IBKRConnectionConfig(host="h", port=1234, client_id=7))
        assert out["connected"] is True
        assert out["host"] == "h"
        assert out["server_version"] == 178
        assert out["accounts"] == ["DU111", "DU222"]
        ib_instance.disconnect.assert_called_once()

    def test_disconnects_only_if_connected(self):
        ib_instance = MagicMock()
        ib_instance.isConnected.return_value = False
        IB = MagicMock(return_value=ib_instance)
        with _patch_ibkr_types(IB=IB):
            out = check_ibkr_connection(IBKRConnectionConfig())
        assert out["connected"] is False
        ib_instance.disconnect.assert_not_called()


# ── cancel_symbol_orders_after ─────────────────────────────────


def _make_trade(symbol: str, order_ref: str, status: str = "Submitted", order_id: int = 1) -> SimpleNamespace:
    contract = SimpleNamespace(symbol=symbol)
    order = SimpleNamespace(orderRef=order_ref, orderId=order_id)
    order_status = SimpleNamespace(status=status)
    return SimpleNamespace(contract=contract, order=order, orderStatus=order_status)


class TestCancelSymbolOrdersAfter:
    def test_no_trigger_returns_unscheduled(self):
        ib = MagicMock()
        out = cancel_symbol_orders_after(
            ib,
            trade_date=date(2026, 4, 23),
            symbol="AAPL",
            entry_order_refs=["r1"],
            trigger_at=None,
            timezone_name="Europe/Berlin",
        )
        assert out == {"action": "cancel_unfilled", "symbol": "AAPL", "scheduled": False, "canceled_order_ids": []}

    def test_cancels_matching_live_order(self):
        ib = MagicMock()
        ib.openTrades.return_value = [
            _make_trade("AAPL", "r1", status="Submitted", order_id=10),
            _make_trade("AAPL", "r-other", status="Submitted", order_id=11),
            _make_trade("AAPL", "r1", status="Filled", order_id=12),  # terminal -> skip
            _make_trade("TSLA", "r1", status="Submitted", order_id=13),  # wrong symbol
        ]
        with patch.object(mod, "_sleep_until"):
            out = cancel_symbol_orders_after(
                ib,
                trade_date=date(2026, 4, 23),
                symbol="aapl",
                entry_order_refs=["r1"],
                trigger_at="15:30",
                timezone_name="Europe/Berlin",
            )
        assert out["scheduled"] is True
        assert out["canceled_order_ids"] == [10]
        ib.cancelOrder.assert_called_once()


# ── flatten_after ──────────────────────────────────────────────


class TestFlattenAfter:
    cfg = IBKRConnectionConfig(account="DU111")
    exec_cfg = IBKRExecutionConfig()

    def test_no_trigger_returns_unscheduled(self):
        ib = MagicMock()
        out = flatten_after(
            ib,
            trade_date=date(2026, 4, 23),
            symbol="AAPL",
            related_order_refs=["r1"],
            trigger_at=None,
            timezone_name="Europe/Berlin",
            connection_cfg=self.cfg,
            execution_cfg=self.exec_cfg,
        )
        assert out == {"action": "flatten", "symbol": "AAPL", "scheduled": False, "flattened_quantity": 0}

    def test_no_open_position_returns_status_no_open(self):
        ib = MagicMock()
        ib.openTrades.return_value = []
        ib.positions.return_value = []
        with patch.object(mod, "_sleep_until"):
            out = flatten_after(
                ib,
                trade_date=date(2026, 4, 23),
                symbol="AAPL",
                related_order_refs=["r1"],
                trigger_at="15:31",
                timezone_name="Europe/Berlin",
                connection_cfg=self.cfg,
                execution_cfg=self.exec_cfg,
            )
        assert out["status"] == "no_open_position"
        assert out["flattened_quantity"] == 0

    def test_with_long_position_places_sell_market_order(self):
        ib = MagicMock()
        ib.openTrades.return_value = [
            _make_trade("AAPL", "r1", status="Submitted", order_id=42),
        ]
        ib.positions.return_value = [
            SimpleNamespace(contract=SimpleNamespace(symbol="AAPL"), account="DU111", position=10.0),
            SimpleNamespace(contract=SimpleNamespace(symbol="AAPL"), account="OTHER", position=99.0),  # filtered out
            SimpleNamespace(contract=SimpleNamespace(symbol="TSLA"), account="DU111", position=5.0),  # wrong symbol
        ]
        market_order_mock = MagicMock()
        market_order_mock.orderId = 7
        Stock = MagicMock(return_value=SimpleNamespace(symbol="AAPL"))
        MarketOrder = MagicMock(return_value=market_order_mock)
        trade = SimpleNamespace(orderStatus=SimpleNamespace(status="Submitted"))
        ib.placeOrder.return_value = trade
        with patch.object(mod, "_sleep_until"), _patch_ibkr_types(Stock=Stock, MarketOrder=MarketOrder):
            out = flatten_after(
                ib,
                trade_date=date(2026, 4, 23),
                symbol="AAPL",
                related_order_refs=["r1"],
                trigger_at="15:31",
                timezone_name="Europe/Berlin",
                connection_cfg=self.cfg,
                execution_cfg=self.exec_cfg,
            )
        assert out["flattened_quantity"] == 10
        assert out["status"] == "Submitted"
        MarketOrder.assert_called_once_with("SELL", 10)
        assert market_order_mock.account == "DU111"
        assert market_order_mock.orderRef.endswith("-flatten")

    def test_with_short_position_buys_to_cover(self):
        ib = MagicMock()
        ib.openTrades.return_value = []
        ib.positions.return_value = [
            SimpleNamespace(contract=SimpleNamespace(symbol="AAPL"), account="DU111", position=-3.0),
        ]
        market_order_mock = MagicMock()
        market_order_mock.orderId = 1
        Stock = MagicMock(return_value=SimpleNamespace())
        MarketOrder = MagicMock(return_value=market_order_mock)
        ib.placeOrder.return_value = SimpleNamespace(orderStatus=SimpleNamespace(status="Submitted"))
        with patch.object(mod, "_sleep_until"), _patch_ibkr_types(Stock=Stock, MarketOrder=MarketOrder):
            out = flatten_after(
                ib,
                trade_date=date(2026, 4, 23),
                symbol="AAPL",
                related_order_refs=[],
                trigger_at="15:31",
                timezone_name="Europe/Berlin",
                connection_cfg=self.cfg,
                execution_cfg=self.exec_cfg,
            )
        assert out["flattened_quantity"] == 3
        MarketOrder.assert_called_once_with("BUY", 3)


# ── place_order_intents_with_ib ────────────────────────────────


def _make_bracket_order(
    order_id: int, action: str, order_type: str, lmt: float | None = None, aux: float | None = None
) -> Any:
    o = SimpleNamespace(
        orderId=order_id,
        permId=order_id + 100,
        orderRef="placeholder",
        orderType=order_type,
        action=action,
        lmtPrice=lmt,
        auxPrice=aux,
    )
    return o


class TestPlaceOrderIntentsWithIb:
    cfg = IBKRConnectionConfig(account="DU111")
    exec_cfg_stop = IBKRExecutionConfig(exit_mode="tp-stop")
    exec_cfg_trail = IBKRExecutionConfig(exit_mode="tp-trail")

    def test_tp_stop_places_three_orders_per_intent(self):
        ib = MagicMock()
        # bracketOrder returns 3 stub orders that get mutated by _apply_common_order_fields
        bracket = [
            _make_bracket_order(1, "BUY", "LMT", lmt=100.0),
            _make_bracket_order(2, "SELL", "LMT", lmt=110.0),
            _make_bracket_order(3, "SELL", "STP", aux=95.0),
        ]
        ib.bracketOrder.return_value = bracket
        ib.placeOrder.return_value = SimpleNamespace(orderStatus=SimpleNamespace(status="Submitted"))
        Stock = MagicMock(return_value=SimpleNamespace(symbol="AAPL"))
        with _patch_ibkr_types(Stock=Stock):
            out = place_order_intents_with_ib(
                ib, [_make_intent()], connection_cfg=self.cfg, execution_cfg=self.exec_cfg_stop
            )
        placement = out["placements"][0]
        assert placement["symbol"] == "AAPL"
        assert len(placement["orders"]) == 3
        # entry/tp/sl suffixes were applied
        suffixes = [o["order_ref"].rsplit("-", 1)[-1] for o in placement["orders"]]
        assert suffixes == ["entry", "tp", "sl"]
        assert "AAPL" in out["entry_order_refs_by_symbol"]

    def test_tp_trail_uses_build_tp_trail_orders(self):
        ib = MagicMock()
        ib.client.getReqId.side_effect = [1, 2, 3]
        ib.placeOrder.return_value = SimpleNamespace(orderStatus=SimpleNamespace(status="Submitted"))
        Stock = MagicMock(return_value=SimpleNamespace(symbol="AAPL"))
        # Use the real LimitOrder/Order via SimpleNamespace constructors
        def LimitOrder(action, qty, price):  # noqa: N802 - mirrors ib_insync LimitOrder
            return SimpleNamespace(
                action=action,
                totalQuantity=qty,
                lmtPrice=price,
                orderId=0,
                permId=0,
                orderRef="",
                orderType="LMT",
                auxPrice=None,
                transmit=True,
            )

        def Order(**kw):  # noqa: N802 - mirrors ib_insync Order
            return SimpleNamespace(
                **kw, orderId=0, permId=0, orderRef="", lmtPrice=None, auxPrice=None, transmit=True
            )
        with _patch_ibkr_types(Stock=Stock, LimitOrder=LimitOrder, Order=Order):
            out = place_order_intents_with_ib(
                ib, [_make_intent()], connection_cfg=self.cfg, execution_cfg=self.exec_cfg_trail
            )
        placement = out["placements"][0]
        assert len(placement["orders"]) == 3


class TestPlaceOrderIntents:
    def test_connects_then_delegates_then_disconnects(self):
        ib_instance = MagicMock()
        ib_instance.isConnected.return_value = True
        IB = MagicMock(return_value=ib_instance)
        with (
            _patch_ibkr_types(IB=IB),
            patch.object(mod, "place_order_intents_with_ib", return_value={"placements": []}) as place_mock,
        ):
            out = place_order_intents([], connection_cfg=IBKRConnectionConfig(), execution_cfg=IBKRExecutionConfig())
        assert out == {"placements": []}
        place_mock.assert_called_once()
        ib_instance.disconnect.assert_called_once()

    def test_disconnect_skipped_when_not_connected(self):
        ib_instance = MagicMock()
        ib_instance.isConnected.return_value = False
        IB = MagicMock(return_value=ib_instance)
        with (
            _patch_ibkr_types(IB=IB),
            patch.object(mod, "place_order_intents_with_ib", return_value={"placements": []}),
        ):
            place_order_intents([], connection_cfg=IBKRConnectionConfig(), execution_cfg=IBKRExecutionConfig())
        ib_instance.disconnect.assert_not_called()


# ── main / CLI ────────────────────────────────────────────────


def _write_minimal_watchlist(path: Path) -> None:
    columns = [
        "trade_date",
        "symbol",
        "watchlist_rank",
        "premarket_last",
        "prev_close_to_premarket_pct",
        "l1_quantity",
        "l1_limit_buy",
        "l1_take_profit",
        "l1_stop_loss",
        "l1_trailing_stop_pct",
        "l1_trailing_stop_anchor",
        "l2_quantity",
        "l2_limit_buy",
        "l2_take_profit",
        "l2_stop_loss",
        "l2_trailing_stop_pct",
        "l2_trailing_stop_anchor",
        "l3_quantity",
        "l3_limit_buy",
        "l3_take_profit",
        "l3_stop_loss",
        "l3_trailing_stop_pct",
        "l3_trailing_stop_anchor",
    ]
    row = ["2026-04-23", "AAPL", 1, 99.5, -1.5, 10, 99.0, 102.0, 95.0, 0.02, 100.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    pd.DataFrame([dict(zip(columns, row, strict=False))]).to_csv(path, index=False)


class TestMainCli:
    def test_dry_run_writes_preview_json(self, tmp_path: Path, monkeypatch, capsys):
        csv_path = tmp_path / "wl.csv"
        _write_minimal_watchlist(csv_path)
        out_json = tmp_path / "preview.json"
        argv = [
            "execute_ibkr_watchlist",
            "--watchlist-csv",
            str(csv_path),
            "--output-json",
            str(out_json),
            "--no-smc-bundles",
        ]
        monkeypatch.setattr("sys.argv", argv)
        mod.main()
        assert out_json.exists()
        payload = json.loads(out_json.read_text())
        assert payload["order_count"] == 1
        printed = capsys.readouterr().out
        assert "PREVIEW_JSON" in printed
        assert "ORDER_INTENTS 1" in printed

    def test_check_connection_invokes_helper(self, tmp_path: Path, monkeypatch, capsys):
        csv_path = tmp_path / "wl.csv"
        _write_minimal_watchlist(csv_path)
        out_json = tmp_path / "preview.json"
        argv = [
            "execute_ibkr_watchlist",
            "--watchlist-csv",
            str(csv_path),
            "--output-json",
            str(out_json),
            "--no-smc-bundles",
            "--check-connection",
        ]
        monkeypatch.setattr("sys.argv", argv)
        with patch.object(mod, "check_ibkr_connection", return_value={"connected": True}) as chk:
            mod.main()
        chk.assert_called_once()
        assert "IBKR_CONNECTION" in capsys.readouterr().out

    def test_place_orders_no_intents_short_circuits(self, tmp_path: Path, monkeypatch, capsys):
        # Build a watchlist whose rows produce zero intents (all l*_quantity=0).
        csv_path = tmp_path / "wl.csv"
        columns = [
            "trade_date",
            "symbol",
            "watchlist_rank",
            "premarket_last",
            "prev_close_to_premarket_pct",
            "l1_quantity",
            "l1_limit_buy",
            "l1_take_profit",
            "l1_stop_loss",
            "l1_trailing_stop_pct",
            "l1_trailing_stop_anchor",
            "l2_quantity",
            "l2_limit_buy",
            "l2_take_profit",
            "l2_stop_loss",
            "l2_trailing_stop_pct",
            "l2_trailing_stop_anchor",
            "l3_quantity",
            "l3_limit_buy",
            "l3_take_profit",
            "l3_stop_loss",
            "l3_trailing_stop_pct",
            "l3_trailing_stop_anchor",
        ]
        row = ["2026-04-23", "AAPL", 1, 99.5, -1.5] + [0] * 18
        pd.DataFrame([dict(zip(columns, row, strict=False))]).to_csv(csv_path, index=False)
        out_json = tmp_path / "preview.json"
        argv = [
            "execute_ibkr_watchlist",
            "--watchlist-csv",
            str(csv_path),
            "--output-json",
            str(out_json),
            "--no-smc-bundles",
            "--place-orders",
        ]
        monkeypatch.setattr("sys.argv", argv)
        mod.main()
        assert "PLACEMENTS []" in capsys.readouterr().out

    def test_smc_bundles_invoked_when_not_disabled(self, tmp_path: Path, monkeypatch, capsys):
        csv_path = tmp_path / "wl.csv"
        _write_minimal_watchlist(csv_path)
        out_json = tmp_path / "preview.json"
        argv = [
            "execute_ibkr_watchlist",
            "--watchlist-csv",
            str(csv_path),
            "--output-json",
            str(out_json),
        ]
        monkeypatch.setattr("sys.argv", argv)
        with patch.object(
            mod, "export_smc_snapshot_bundles_for_watchlist", return_value={"manifest_path": "/tmp/m.json"}
        ) as exp:
            mod.main()
        exp.assert_called_once()
        assert "SMC_BUNDLE_MANIFEST" in capsys.readouterr().out
