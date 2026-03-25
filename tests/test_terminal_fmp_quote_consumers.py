from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

from terminal_fmp_insights import fetch_fmp_profiles, fetch_fmp_quotes, fetch_fmp_ratios
from terminal_forecast import _fetch_fmp
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


def test_fetch_fmp_profiles_uses_shared_client() -> None:
    with patch(
        "terminal_fmp_insights.FMPClient.get_profiles",
        autospec=True,
        return_value=[{"symbol": "AAPL", "sector": "Technology"}],
    ) as mock_profiles:
        rows = fetch_fmp_profiles("key", ["aapl", "msft"])

    assert rows == [{"symbol": "AAPL", "sector": "Technology"}]
    assert mock_profiles.call_args.args[1] == ["AAPL", "MSFT"]


def test_fetch_fmp_ratios_uses_shared_client_per_symbol() -> None:
    def _fake_ratios(_client: object, symbol: str) -> list[dict[str, object]]:
        if symbol == "AAPL":
            return [{"priceToBookRatioTTM": 10.5}]
        return []

    with patch(
        "terminal_fmp_insights.FMPClient.get_ratios_ttm",
        autospec=True,
        side_effect=_fake_ratios,
    ) as mock_ratios:
        rows = fetch_fmp_ratios("key", ["aapl", "msft"])

    assert rows == [{"priceToBookRatioTTM": 10.5, "symbol": "AAPL"}]
    assert mock_ratios.call_args_list[0].args[1] == "AAPL"
    assert mock_ratios.call_args_list[1].args[1] == "MSFT"


def test_fetch_fmp_profiles_fail_soft_on_client_error() -> None:
    with patch(
        "terminal_fmp_insights.FMPClient.get_profiles",
        autospec=True,
        side_effect=RuntimeError("down"),
    ):
        rows = fetch_fmp_profiles("key", ["aapl"])

    assert rows == []


def test_terminal_forecast_uses_shared_client_paths() -> None:
    with patch.dict(os.environ, {"FMP_API_KEY": "key"}, clear=False), patch(
        "terminal_forecast.FMPClient.get_company_profile",
        autospec=True,
        return_value={"symbol": "AAPL", "price": 123.45},
    ) as mock_profile, patch(
        "terminal_forecast.FMPClient.get_price_target_consensus",
        autospec=True,
        return_value={"symbol": "AAPL", "targetHigh": 180, "targetLow": 140, "targetConsensus": 160, "targetMedian": 158},
    ) as mock_pt, patch(
        "terminal_forecast.FMPClient.get_price_target_summary",
        autospec=True,
        return_value={"symbol": "AAPL", "lastMonthAvgPriceTarget": 159, "lastMonthCount": 3},
    ) as mock_pt_summary, patch(
        "terminal_forecast.FMPClient.get_grades_consensus",
        autospec=True,
        return_value={"symbol": "AAPL", "strongBuy": 5, "buy": 10, "hold": 3, "sell": 1, "strongSell": 0, "consensus": "Buy"},
    ) as mock_grades_consensus, patch(
        "terminal_forecast.FMPClient.get_analyst_estimates",
        autospec=True,
        return_value=[{"date": "2026-06-30", "epsAvg": 2.5, "epsLow": 2.1, "epsHigh": 2.9, "numAnalystsEps": 14, "revenueAvg": 100.0, "ebitdaAvg": 50.0}],
    ) as mock_estimates, patch(
        "terminal_forecast.FMPClient.get_upgrades_downgrades",
        autospec=True,
        return_value=[{"date": "2026-03-20", "gradingCompany": "Firm", "newGrade": "Buy", "previousGrade": "Hold", "action": "upgrade"}],
    ) as mock_grades:
        result = _fetch_fmp("aapl")

    assert result is not None
    assert result.source == "fmp"
    assert result.price_target is not None
    assert result.price_target.target_mean == 160.0
    assert result.rating is not None
    assert result.rating.consensus_label == "Buy"
    assert len(result.eps_estimates) == 1
    assert len(result.upgrades_downgrades) == 1
    assert mock_profile.call_args.args[1] == "aapl"
    assert mock_pt.call_args.args[1] == "aapl"
    assert mock_pt_summary.call_args.args[1] == "aapl"
    assert mock_grades_consensus.call_args.args[1] == "aapl"
    assert mock_estimates.call_args.args[1] == "aapl"
    assert mock_estimates.call_args.kwargs == {"period": "quarter", "limit": 8}
    assert mock_grades.call_args.args[1] == "aapl"
    assert mock_grades.call_args.kwargs == {}


def test_terminal_forecast_etf_profile_short_circuits_shared_calls() -> None:
    with patch.dict(os.environ, {"FMP_API_KEY": "key"}, clear=False), patch(
        "terminal_forecast.FMPClient.get_company_profile",
        autospec=True,
        return_value={"symbol": "SOXL", "isEtf": True},
    ) as mock_profile, patch(
        "terminal_forecast.FMPClient.get_price_target_consensus",
        autospec=True,
    ) as mock_pt:
        result = _fetch_fmp("SOXL")

    assert result is not None
    assert result.error == "ETF — analyst forecasts not available"
    mock_profile.assert_called_once()
    mock_pt.assert_not_called()


def test_fetch_price_uses_shared_quote_path() -> None:
    with patch(
        "terminal_fmp_technicals.FMPClient.get_index_quote",
        autospec=True,
        return_value={"symbol": "AAPL", "price": "123.45"},
    ) as mock_quote:
        price = _fetch_price("aapl", "key")

    assert price == 123.45
    assert mock_quote.call_args.args[1] == "AAPL"