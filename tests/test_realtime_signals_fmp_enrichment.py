"""Regression coverage for bounded realtime FMP watchlist enrichment."""

from __future__ import annotations

from typing import Any

import open_prep.realtime_signals as rs


class _Client:
    def __init__(self) -> None:
        self.profile_calls: list[str] = []
        self.earnings_calls = 0

    def get_profile_bulk(self) -> list[dict[str, Any]]:
        raise AssertionError("realtime enrichment must never scan profile-bulk")

    def get_company_profile(self, symbol: str) -> dict[str, Any]:
        self.profile_calls.append(symbol)
        if symbol == "GOOD":
            return {"symbol": symbol, "averageVolume": 2_000_000}
        return {"symbol": symbol}

    def get_earnings_calendar(self, _start: Any, _end: Any) -> list[dict[str, Any]]:
        self.earnings_calls += 1
        return [{"symbol": "GOOD", "time": "bmo"}]


def _engine(client: _Client) -> rs.RealtimeEngine:
    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = client
    engine._client_disabled_reason = None
    engine._watchlist = [
        {"symbol": "GOOD", "avg_volume": 0},
        {"symbol": "MISSING", "avg_volume": 0},
    ]
    engine._avg_vol_cache = {}
    engine._earnings_today_cache = {}
    return engine


def test_realtime_enrichment_is_targeted_and_negative_cached(monkeypatch) -> None:
    client = _Client()
    engine = _engine(client)
    monkeypatch.setattr(rs.time, "sleep", lambda _seconds: None)

    engine._enrich_watchlist_live()
    engine._enrich_watchlist_live()

    assert client.profile_calls == ["GOOD", "MISSING"]
    assert client.earnings_calls == 1
    assert engine._avg_vol_cache == {"GOOD": 2_000_000.0}
    assert engine._avg_vol_retry_after["MISSING"] > rs.time.time()
    assert engine._watchlist[0]["avg_volume"] == 2_000_000.0
    assert engine._watchlist[0]["earnings_today"] is True
    assert engine._watchlist[0]["earnings_timing"] == "bmo"


def test_new_symbol_is_enriched_without_retrying_negative_cache(monkeypatch) -> None:
    client = _Client()
    engine = _engine(client)
    monkeypatch.setattr(rs.time, "sleep", lambda _seconds: None)
    engine._enrich_watchlist_live()

    engine._watchlist.append({"symbol": "NEW", "avg_volume": 0})
    engine._enrich_watchlist_live()

    assert client.profile_calls == ["GOOD", "MISSING", "NEW"]
    assert client.earnings_calls == 1
