"""Massive-native routing for the terminal quote/mover fetchers.

With ``BENZINGA_PROVIDER=massive`` (the paid Massive key), ``fetch_benzinga_quotes``
and ``fetch_benzinga_movers`` must route to the Massive snapshot endpoints
(Stocks Starter: 15-min delayed) and map the snapshot rows into the exact
flat shapes the terminal tabs already consume — bz-direct stays the default.
Companion to test_benzinga_massive_provider.py (the news transport switch).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from newsstack_fmp.ingest_benzinga_calendar import (
    MASSIVE_SNAPSHOT_BASE,
    MOVERS_URL,
    _massive_snapshot_to_quote,
    fetch_benzinga_movers,
    fetch_benzinga_quotes,
)


def _snap_row(ticker: str = "AAPL", **over):
    row = {
        "ticker": ticker,
        "day": {"o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 1_000_000},
        "min": {"c": 104.5, "v": 5_000},
        "prevDay": {"c": 101.0, "v": 900_000},
        "todaysChange": 3.5,
        "todaysChangePerc": 3.47,
        "updated": 1_752_000_000_000_000_000,
    }
    row.update(over)
    return row


# ── snapshot -> quote mapping ────────────────────────────────────────


def test_snapshot_maps_to_flat_quote_shape():
    q = _massive_snapshot_to_quote(_snap_row())
    assert q["symbol"] == "AAPL"
    assert q["last"] == 104.5  # latest minute close preferred
    assert q["change"] == 3.5
    assert q["changePercent"] == 3.47
    assert (q["open"], q["high"], q["low"], q["close"]) == (100.0, 105.0, 99.0, 104.0)
    assert q["volume"] == 1_000_000
    assert q["previousClose"] == 101.0
    # snapshot doesn't carry these — consumers .get() them
    assert q["name"] == ""
    assert q["fiftyTwoWeekHigh"] is None and q["fiftyTwoWeekLow"] is None


def test_snapshot_last_falls_back_day_then_prevday():
    # min.c missing -> day.c; day.c zero/absent -> prevDay.c (0 is not a price)
    q = _massive_snapshot_to_quote(_snap_row(min={}, day={"c": 104.0}))
    assert q["last"] == 104.0
    q = _massive_snapshot_to_quote(_snap_row(min={}, day={"c": 0}, prevDay={"c": 101.0}))
    assert q["last"] == 101.0
    q = _massive_snapshot_to_quote(_snap_row(min={}, day={}, prevDay={}))
    assert q["last"] is None


def test_snapshot_volume_falls_back_to_min_av_when_day_zeroed():
    # Delayed Starter feed: `day` is all-zero intraday (live 2026-07-09);
    # the session volume lives in min.av. Zeros must map to None, not 0.
    q = _massive_snapshot_to_quote(
        _snap_row(day={"o": 0, "h": 0, "l": 0, "c": 0, "v": 0}, min={"c": 104.5, "av": 249_841})
    )
    assert q["volume"] == 249_841
    assert q["open"] is None and q["close"] is None  # no bogus zeros
    q = _massive_snapshot_to_quote(_snap_row(day={"v": 0}, min={}))
    assert q["volume"] is None


# ── provider routing: movers ─────────────────────────────────────────


@patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
def test_movers_massive_routes_to_snapshots(mock_req, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    resp = MagicMock()
    resp.json.return_value = {"tickers": [_snap_row("XYZ")]}
    mock_req.return_value = resp

    out = fetch_benzinga_movers("massive_key")

    urls = [c.args[1] for c in mock_req.call_args_list]
    assert urls == [f"{MASSIVE_SNAPSHOT_BASE}/gainers", f"{MASSIVE_SNAPSHOT_BASE}/losers"]
    assert all(c.args[2] == {"apiKey": "massive_key"} for c in mock_req.call_args_list)
    row = out["gainers"][0]
    assert row["symbol"] == "XYZ"
    assert row["price"] == 104.5
    assert row["changePercent"] == 3.47
    # bz-only fields present-but-empty so tab .get()s stay harmless
    assert row["marketCap"] is None and row["companyName"] == ""


@patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
def test_movers_direct_default_unchanged(mock_req, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BENZINGA_PROVIDER", raising=False)
    resp = MagicMock()
    resp.json.return_value = {"result": {"gainers": [], "losers": []}}
    mock_req.return_value = resp

    fetch_benzinga_movers("direct_key")

    assert mock_req.call_args_list[0].args[1] == MOVERS_URL
    assert mock_req.call_args_list[0].args[2] == {"token": "direct_key"}


@patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
def test_movers_massive_fail_soft(mock_req, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    mock_req.side_effect = Exception("boom")
    assert fetch_benzinga_movers("k") == {"gainers": [], "losers": []}


# ── provider routing: quotes ─────────────────────────────────────────


@patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
def test_quotes_massive_routes_and_maps(mock_req, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    resp = MagicMock()
    resp.json.return_value = {"tickers": [_snap_row("AAPL"), _snap_row("MSFT")]}
    mock_req.return_value = resp

    out = fetch_benzinga_quotes("massive_key", ["aapl", " msft "])

    call = mock_req.call_args_list[0]
    assert call.args[1] == f"{MASSIVE_SNAPSHOT_BASE}/tickers"
    assert call.args[2]["tickers"] == "AAPL,MSFT"  # cleaned + uppercased
    assert [q["symbol"] for q in out] == ["AAPL", "MSFT"]
    assert out[0]["previousClose"] == 101.0


@patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
def test_quotes_massive_chunks_over_50(mock_req, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    resp = MagicMock()
    resp.json.return_value = {"tickers": []}
    mock_req.return_value = resp

    fetch_benzinga_quotes("k", [f"S{i}" for i in range(120)])

    assert len(mock_req.call_args_list) == 3  # 50 + 50 + 20
    assert len(mock_req.call_args_list[0].args[2]["tickers"].split(",")) == 50
    assert len(mock_req.call_args_list[2].args[2]["tickers"].split(",")) == 20


@patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
def test_quotes_massive_fail_soft_returns_empty(mock_req, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
    mock_req.side_effect = Exception("boom")
    assert fetch_benzinga_quotes("k", ["AAPL"]) == []
