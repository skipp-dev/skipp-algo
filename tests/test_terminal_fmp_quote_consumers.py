from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from terminal_fmp_insights import fetch_fmp_quotes
from terminal_fmp_technicals import _fetch_price
from terminal_poller import (
    fetch_defense_watchlist,
    fetch_economic_calendar,
    fetch_industry_performance,
    fetch_sector_performance,
    fetch_ticker_sectors,
)
from terminal_spike_scanner import enrich_with_batch_quote, fetch_gainers, fetch_most_active


def test_spike_scanner_enrich_with_batch_quote_uses_shared_client() -> None:
    with patch(
        "terminal_spike_scanner.FMPClient.get_batch_quotes",
        autospec=True,
        return_value=[{"symbol": "NVDA", "volume": 999, "marketCap": 123456}],
    ) as mock_quotes, patch(
        "terminal_spike_scanner.FMPClient.get_profiles",
        autospec=True,
        return_value=[{"symbol": "NVDA", "averageVolume": 1200, "sector": "Semis"}],
    ) as mock_profiles:
        rows = enrich_with_batch_quote("key", [{"symbol": "NVDA"}])

    assert rows[0]["volume"] == 999
    assert rows[0]["marketCap"] == 123456
    assert rows[0]["avgVolume"] == 1200
    assert rows[0]["sector"] == "Semis"
    assert mock_quotes.call_args.args[1] == ["NVDA"]
    assert mock_profiles.call_args.args[1] == ["NVDA"]


def test_fetch_gainers_uses_shared_client() -> None:
    with patch(
        "terminal_spike_scanner.FMPClient.get_biggest_gainers",
        autospec=True,
        return_value=[{"symbol": "AAPL"}],
    ) as mock_gainers:
        rows = fetch_gainers("key")

    assert rows == [{"symbol": "AAPL"}]
    mock_gainers.assert_called_once()


def test_fetch_most_active_fail_soft_on_client_error() -> None:
    with patch(
        "terminal_spike_scanner.FMPClient.get_premarket_movers",
        autospec=True,
        side_effect=RuntimeError("down"),
    ):
        rows = fetch_most_active("key")

    assert rows == []


def test_fetch_defense_watchlist_uses_shared_client_symbols() -> None:
    with patch(
        "terminal_poller.FMPClient.get_batch_quotes",
        autospec=True,
        return_value=[{"symbol": "LMT"}, {"symbol": "NOC"}],
    ) as mock_quotes:
        rows = fetch_defense_watchlist("key", tickers="LMT, NOC")

    assert [row["symbol"] for row in rows] == ["LMT", "NOC"]
    assert mock_quotes.call_args.args[1] == ["LMT", "NOC"]


def test_fetch_economic_calendar_uses_shared_client_dates() -> None:
    with patch(
        "terminal_poller.FMPClient.get_macro_calendar",
        autospec=True,
        return_value=[{"event": "CPI"}],
    ) as mock_calendar:
        rows = fetch_economic_calendar("key", "2026-03-24", "2026-03-25")

    assert rows == [{"event": "CPI"}]
    assert mock_calendar.call_args.args[1] == date(2026, 3, 24)
    assert mock_calendar.call_args.args[2] == date(2026, 3, 25)


def test_fetch_ticker_sectors_uses_shared_profiles() -> None:
    with patch(
        "terminal_poller.FMPClient.get_profiles",
        autospec=True,
        return_value=[
            {"symbol": "LMT", "sector": "Industrials"},
            {"symbol": "RTX", "sector": "Industrials"},
            {"symbol": "EMPTY", "sector": ""},
        ],
    ) as mock_profiles:
        result = fetch_ticker_sectors("key", ["lmt", "rtx"])

    assert result == {"LMT": "Industrials", "RTX": "Industrials"}
    assert mock_profiles.call_args.args[1] == ["LMT", "RTX"]


def test_fetch_sector_performance_uses_shared_snapshot_and_aggregates() -> None:
    with patch(
        "terminal_poller.FMPClient.get_sector_performance_snapshot",
        autospec=True,
        return_value=[
            {"sector": "Technology", "averageChange": 1.0},
            {"sector": "Technology", "averageChange": 3.0},
            {"sector": "Energy", "averageChange": -2.0},
        ],
    ) as mock_snapshot:
        rows = fetch_sector_performance("key")

    assert {row["sector"]: row["changesPercentage"] for row in rows} == {
        "Technology": 2.0,
        "Energy": -2.0,
    }
    mock_snapshot.assert_called()


def test_fetch_industry_performance_uses_company_screener_and_sorts() -> None:
    with patch(
        "terminal_poller.FMPClient.get_company_screener",
        autospec=True,
        return_value=[
            {"symbol": "AAA", "marketCap": 10},
            {"symbol": "BBB", "marketCap": 50},
        ],
    ) as mock_screener:
        rows = fetch_industry_performance("key", industry="Aerospace & Defense", limit=10)

    assert [row["symbol"] for row in rows] == ["BBB", "AAA"]
    assert mock_screener.call_args.kwargs["industry"] == "Aerospace & Defense"
    assert mock_screener.call_args.kwargs["exchange"] == "NYSE,NASDAQ,AMEX"


def test_fetch_ticker_sectors_fail_soft_on_client_error() -> None:
    with patch(
        "terminal_poller.FMPClient.get_profiles",
        autospec=True,
        side_effect=RuntimeError("down"),
    ):
        result = fetch_ticker_sectors("key", ["LMT"])

    assert result == {}


def test_fetch_fmp_quotes_uses_shared_client() -> None:
    with patch(
        "terminal_fmp_insights.FMPClient.get_batch_quotes",
        autospec=True,
        return_value=[{"symbol": "AAPL", "price": 200.0}],
    ) as mock_quotes:
        rows = fetch_fmp_quotes("key", ["aapl", "msft"])

    assert rows == [{"symbol": "AAPL", "price": 200.0}]
    assert mock_quotes.call_args.args[1] == ["AAPL", "MSFT"]


def test_fetch_price_uses_shared_quote_path() -> None:
    with patch(
        "terminal_fmp_technicals.FMPClient.get_index_quote",
        autospec=True,
        return_value={"symbol": "AAPL", "price": "123.45"},
    ) as mock_quote:
        price = _fetch_price("aapl", "key")

    assert price == 123.45
    assert mock_quote.call_args.args[1] == "AAPL"