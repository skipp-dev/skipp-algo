"""Session routing and off-hours quote suppression for the realtime producer."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import open_prep.realtime_signals as rs

ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def test_market_session_boundaries_on_regular_day() -> None:
    assert rs._market_session(_et(2026, 7, 6, 3, 59)) == "closed"
    assert rs._market_session(_et(2026, 7, 6, 4, 0)) == "premarket"
    assert rs._market_session(_et(2026, 7, 6, 9, 29)) == "premarket"
    assert rs._market_session(_et(2026, 7, 6, 9, 30)) == "regular"
    assert rs._market_session(_et(2026, 7, 6, 15, 59)) == "regular"
    assert rs._market_session(_et(2026, 7, 6, 16, 0)) == "postmarket"
    assert rs._market_session(_et(2026, 7, 6, 19, 59)) == "postmarket"
    assert rs._market_session(_et(2026, 7, 6, 20, 0)) == "closed"


def test_market_session_closed_on_weekend_and_holiday() -> None:
    assert rs._market_session(_et(2026, 7, 4, 12, 0)) == "closed"
    assert rs._market_session(_et(2026, 7, 3, 12, 0)) == "closed"


def test_closed_poll_keeps_heartbeat_without_fetching_quotes(monkeypatch) -> None:
    class _Client:
        def get_stable_batch_quotes(self, _symbols):
            raise AssertionError("closed market must not fetch quotes")

    monkeypatch.setattr(rs.RealtimeEngine, "_load_watchlist", lambda self: None)
    monkeypatch.setattr(rs.RealtimeEngine, "_restore_signals_from_disk", lambda self: None)
    monkeypatch.setattr(rs, "_market_session", lambda: "closed")

    engine = rs.RealtimeEngine(fmp_client=_Client())
    engine._watchlist = [{"symbol": "AAPL", "avg_volume": 1_000_000}]
    engine._async_newsstack = SimpleNamespace(latest=lambda: {})
    saved: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        engine,
        "_save_signals",
        lambda **_kwargs: saved.append((engine._market_session_name, engine._quotes_polled)),
    )

    assert engine.poll_once() == []
    assert saved == [("closed", False)]
    assert engine.last_poll_success_epoch > 0
    assert engine._in_market_hours is False


def test_extended_hours_override_cannot_enable_regular_quote_endpoint(monkeypatch) -> None:
    class _Client:
        def get_stable_batch_quotes(self, _symbols):
            raise AssertionError("premarket must not use the regular quote endpoint")

    monkeypatch.setenv("RT_EXTENDED_SIGNALS_MODE", "live")
    monkeypatch.setattr(rs.RealtimeEngine, "_load_watchlist", lambda self: None)
    monkeypatch.setattr(rs.RealtimeEngine, "_restore_signals_from_disk", lambda self: None)
    monkeypatch.setattr(rs, "_market_session", lambda: "premarket")

    engine = rs.RealtimeEngine(fmp_client=_Client())
    engine._watchlist = [{"symbol": "AAPL", "avg_volume": 1_000_000}]
    engine._async_newsstack = SimpleNamespace(latest=lambda: {})
    monkeypatch.setattr(engine, "_save_signals", lambda **_kwargs: None)

    assert engine.extended_signals_mode == "off"
    assert engine.poll_once() == []
    assert engine._market_session_name == "premarket"
    assert engine._quotes_polled is False


def test_realtime_fetch_uses_true_batch_method() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def get_stable_batch_quotes(self, symbols: list[str]):
            self.calls.append(symbols)
            return [{"symbol": symbol, "price": 1.0} for symbol in symbols]

    client = _Client()
    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = client
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]

    quotes = engine._fetch_realtime_quotes()

    assert client.calls == [["AAPL", "MSFT"]]
    assert sorted(quotes) == ["AAPL", "MSFT"]


def test_extended_shadow_compares_fresh_dedicated_feeds_without_signaling(monkeypatch) -> None:
    now_epoch = 1_784_221_934.0

    class _Client:
        def get_stable_batch_quotes(self, _symbols):
            return [{"symbol": "AAPL", "price": 101.0, "timestamp": now_epoch}]

        def get_stable_batch_aftermarket_quotes(self, _symbols):
            return [{
                "symbol": "AAPL",
                "bidPrice": 100.0,
                "askPrice": 102.0,
                "timestamp": now_epoch * 1000,
            }]

        def get_stable_batch_aftermarket_trades(self, _symbols):
            return [{"symbol": "AAPL", "price": 100.5, "timestamp": now_epoch * 1000}]

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = _Client()
    engine._watchlist = [{"symbol": "AAPL"}]
    engine.extended_shadow_enabled = True
    engine._extended_shadow = {}
    monkeypatch.setattr(rs.time, "time", lambda: now_epoch)

    engine._poll_extended_shadow("premarket")

    assert engine._extended_shadow["fresh_regular_rows"] == 1
    assert engine._extended_shadow["fresh_quote_rows"] == 1
    assert engine._extended_shadow["fresh_trade_rows"] == 1
    assert engine._extended_shadow["overlap_rows"] == 1
    assert engine._extended_shadow["mean_reference_delta_bps"] > 0
