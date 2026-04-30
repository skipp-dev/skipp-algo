from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

from terminal_bitcoin import (
    fetch_btc_news,
    fetch_btc_ohlcv,
    fetch_btc_quote,
    fetch_crypto_listings,
    fetch_crypto_movers,
)
from terminal_fmp_insights import fetch_fmp_profiles, fetch_fmp_quotes, fetch_fmp_ratios
from terminal_fmp_technicals import _fetch_indicator, _fetch_price
from terminal_forecast import _fetch_fmp
from terminal_poller import (
    fetch_defense_watchlist,
    fetch_economic_calendar,
    fetch_industry_performance,
    fetch_sector_performance,
    fetch_ticker_sectors,
)
from terminal_spike_scanner import enrich_with_batch_quote, fetch_gainers, fetch_most_active


def test_spike_scanner_enrich_with_batch_quote_uses_shared_client() -> None:
    client = MagicMock()
    client.get_batch_quotes.return_value = [{"symbol": "NVDA", "volume": 999, "marketCap": 123456}]
    client.get_profiles.return_value = [{"symbol": "NVDA", "averageVolume": 1200, "sector": "Semis"}]

    with patch("terminal_spike_scanner._make_fmp_client", return_value=client):
        rows = enrich_with_batch_quote("key", [{"symbol": "NVDA"}])

    assert rows[0]["volume"] == 999
    assert rows[0]["marketCap"] == 123456
    assert rows[0]["avgVolume"] == 1200
    assert rows[0]["sector"] == "Semis"
    assert client.get_batch_quotes.call_args.args[0] == ["NVDA"]
    assert client.get_profiles.call_args.args[0] == ["NVDA"]


def test_fetch_gainers_uses_shared_client() -> None:
    client = MagicMock()
    client.get_biggest_gainers.return_value = [{"symbol": "AAPL"}]

    with patch("terminal_spike_scanner._make_fmp_client", return_value=client):
        rows = fetch_gainers("key")

    assert rows == [{"symbol": "AAPL"}]
    client.get_biggest_gainers.assert_called_once()


def test_fetch_most_active_fail_soft_on_client_error() -> None:
    client = MagicMock()
    client.get_premarket_movers.side_effect = RuntimeError("down")

    with patch("terminal_spike_scanner._make_fmp_client", return_value=client):
        rows = fetch_most_active("key")

    assert rows == []


def test_fetch_defense_watchlist_uses_shared_client_symbols() -> None:
    client = MagicMock()
    client.get_batch_quotes.return_value = [{"symbol": "LMT"}, {"symbol": "NOC"}]

    with patch("terminal_poller.make_fmp_client", return_value=client):
        rows = fetch_defense_watchlist("key", tickers="LMT, NOC")

    assert [row["symbol"] for row in rows] == ["LMT", "NOC"]
    assert client.get_batch_quotes.call_args.args[0] == ["LMT", "NOC"]


def test_fetch_economic_calendar_uses_shared_client_dates() -> None:
    client = MagicMock()
    client.get_macro_calendar.return_value = [{"event": "CPI"}]

    with patch("terminal_poller._make_fmp_client", return_value=client):
        rows = fetch_economic_calendar("key", "2026-03-24", "2026-03-25")

    assert rows == [{"event": "CPI"}]
    assert client.get_macro_calendar.call_args.args[0] == date(2026, 3, 24)
    assert client.get_macro_calendar.call_args.args[1] == date(2026, 3, 25)


def test_fetch_ticker_sectors_uses_shared_profiles() -> None:
    client = MagicMock()
    client.get_profiles.return_value = [
        {"symbol": "LMT", "sector": "Industrials"},
        {"symbol": "RTX", "sector": "Industrials"},
        {"symbol": "EMPTY", "sector": ""},
    ]

    with patch("terminal_poller._make_fmp_client", return_value=client):
        result = fetch_ticker_sectors("key", ["lmt", "rtx"])

    assert result == {"LMT": "Industrials", "RTX": "Industrials"}
    assert client.get_profiles.call_args.args[0] == ["LMT", "RTX"]


def test_fetch_sector_performance_uses_shared_snapshot_and_aggregates() -> None:
    client = MagicMock()
    client.get_sector_performance_snapshot.return_value = [
        {"sector": "Technology", "averageChange": 1.0},
        {"sector": "Technology", "averageChange": 3.0},
        {"sector": "Energy", "averageChange": -2.0},
    ]

    with patch("terminal_poller._make_fmp_client", return_value=client):
        rows = fetch_sector_performance("key")

    assert {row["sector"]: row["changesPercentage"] for row in rows} == {
        "Technology": 2.0,
        "Energy": -2.0,
    }
    client.get_sector_performance_snapshot.assert_called()


def test_fetch_industry_performance_uses_company_screener_and_sorts() -> None:
    client = MagicMock()
    client.get_company_screener.return_value = [
        {"symbol": "AAA", "marketCap": 10},
        {"symbol": "BBB", "marketCap": 50},
    ]

    with patch("terminal_poller._make_fmp_client", return_value=client):
        rows = fetch_industry_performance("key", industry="Aerospace & Defense", limit=10)

    assert [row["symbol"] for row in rows] == ["BBB", "AAA"]
    assert client.get_company_screener.call_args.kwargs["industry"] == "Aerospace & Defense"
    assert client.get_company_screener.call_args.kwargs["exchange"] == "NYSE,NASDAQ,AMEX"


def test_fetch_ticker_sectors_fail_soft_on_client_error() -> None:
    client = MagicMock()
    client.get_profiles.side_effect = RuntimeError("down")

    with patch("terminal_poller._make_fmp_client", return_value=client):
        result = fetch_ticker_sectors("key", ["LMT"])

    assert result == {}


def test_fetch_fmp_quotes_uses_shared_client() -> None:
    client = MagicMock()
    client.get_batch_quotes.return_value = [{"symbol": "AAPL", "price": 200.0}]

    with patch("terminal_fmp_insights._make_fmp_client", return_value=client):
        rows = fetch_fmp_quotes("key", ["aapl", "msft"])

    assert rows == [{"symbol": "AAPL", "price": 200.0}]
    assert client.get_batch_quotes.call_args.args[0] == ["AAPL", "MSFT"]


def test_fetch_fmp_profiles_uses_shared_client() -> None:
    client = MagicMock()
    client.get_profiles.return_value = [{"symbol": "AAPL", "sector": "Technology"}]

    with patch("terminal_fmp_insights._make_fmp_client", return_value=client):
        rows = fetch_fmp_profiles("key", ["aapl", "msft"])

    assert rows == [{"symbol": "AAPL", "sector": "Technology"}]
    assert client.get_profiles.call_args.args[0] == ["AAPL", "MSFT"]


def test_fetch_fmp_ratios_uses_shared_client_per_symbol() -> None:
    def _fake_ratios(symbol: str) -> list[dict[str, object]]:
        if symbol == "AAPL":
            return [{"priceToBookRatioTTM": 10.5}]
        return []

    client = MagicMock()
    client.get_ratios_ttm.side_effect = _fake_ratios

    with patch("terminal_fmp_insights._make_fmp_client", return_value=client):
        rows = fetch_fmp_ratios("key", ["aapl", "msft"])

    assert rows == [{"priceToBookRatioTTM": 10.5, "symbol": "AAPL"}]
    assert client.get_ratios_ttm.call_args_list[0].args[0] == "AAPL"
    assert client.get_ratios_ttm.call_args_list[1].args[0] == "MSFT"


def test_fetch_fmp_profiles_fail_soft_on_client_error() -> None:
    client = MagicMock()
    client.get_profiles.side_effect = RuntimeError("down")

    with patch("terminal_fmp_insights._make_fmp_client", return_value=client):
        rows = fetch_fmp_profiles("key", ["aapl"])

    assert rows == []


def test_terminal_forecast_uses_shared_client_paths() -> None:
    client = MagicMock()
    client.get_company_profile.return_value = {"symbol": "AAPL", "price": 123.45}
    client.get_price_target_consensus.return_value = {"symbol": "AAPL", "targetHigh": 180, "targetLow": 140, "targetConsensus": 160, "targetMedian": 158}
    client.get_price_target_summary.return_value = {"symbol": "AAPL", "lastMonthAvgPriceTarget": 159, "lastMonthCount": 3}
    client.get_grades_consensus.return_value = {"symbol": "AAPL", "strongBuy": 5, "buy": 10, "hold": 3, "sell": 1, "strongSell": 0, "consensus": "Buy"}
    client.get_analyst_estimates.return_value = [{"date": "2026-06-30", "epsAvg": 2.5, "epsLow": 2.1, "epsHigh": 2.9, "numAnalystsEps": 14, "revenueAvg": 100.0, "ebitdaAvg": 50.0}]
    client.get_upgrades_downgrades.return_value = [{"date": "2026-03-20", "gradingCompany": "Firm", "newGrade": "Buy", "previousGrade": "Hold", "action": "upgrade"}]

    with patch.dict(os.environ, {"FMP_API_KEY": "key"}, clear=False), patch(
        "terminal_forecast._make_fmp_client",
        return_value=client,
    ):
        result = _fetch_fmp("aapl")

    assert result is not None
    assert result.source == "fmp"
    assert result.price_target is not None
    assert result.price_target.target_mean == 160.0
    assert result.rating is not None
    assert result.rating.consensus_label == "Buy"
    assert len(result.eps_estimates) == 1
    assert len(result.upgrades_downgrades) == 1
    assert client.get_company_profile.call_args.args[0] == "aapl"
    assert client.get_price_target_consensus.call_args.args[0] == "aapl"
    assert client.get_price_target_summary.call_args.args[0] == "aapl"
    assert client.get_grades_consensus.call_args.args[0] == "aapl"
    assert client.get_analyst_estimates.call_args.args[0] == "aapl"
    assert client.get_analyst_estimates.call_args.kwargs == {"period": "quarter", "limit": 8}
    assert client.get_upgrades_downgrades.call_args.args[0] == "aapl"
    assert client.get_upgrades_downgrades.call_args.kwargs == {}


def test_terminal_forecast_etf_profile_short_circuits_shared_calls() -> None:
    client = MagicMock()
    client.get_company_profile.return_value = {"symbol": "SOXL", "isEtf": True}

    with patch.dict(os.environ, {"FMP_API_KEY": "key"}, clear=False), patch(
        "terminal_forecast._make_fmp_client",
        return_value=client,
    ):
        result = _fetch_fmp("SOXL")

    assert result is not None
    assert result.error == "ETF — analyst forecasts not available"
    client.get_company_profile.assert_called_once()
    client.get_price_target_consensus.assert_not_called()


def test_fetch_price_uses_shared_quote_path() -> None:
    client = MagicMock()
    client.get_index_quote.return_value = {"symbol": "AAPL", "price": "123.45"}

    with patch("terminal_fmp_technicals._make_fmp_client", return_value=client):
        price = _fetch_price("aapl", "key")

    assert price == 123.45
    assert client.get_index_quote.call_args.args[0] == "AAPL"


def test_fetch_indicator_uses_shared_client_path() -> None:
    client = MagicMock()
    client.get_technical_indicator.return_value = {"rsi": 55.0}

    with patch("terminal_fmp_technicals._make_fmp_client", return_value=client):
        row = _fetch_indicator("aapl", "1day", "rsi", "key", indicator_period=14)

    assert row == {"rsi": 55.0}
    assert client.get_technical_indicator.call_args.args[0] == "AAPL"
    assert client.get_technical_indicator.call_args.args[1] == "1day"
    assert client.get_technical_indicator.call_args.args[2] == "rsi"
    assert client.get_technical_indicator.call_args.kwargs == {"indicator_period": 14}


def test_fetch_btc_quote_uses_shared_quote_path() -> None:
    client = MagicMock()
    client.get_index_quote.return_value = {"symbol": "BTCUSD", "price": 100000.0, "change": 500.0, "changesPercentage": 0.5}

    with patch(
        "terminal_bitcoin._get_cached",
        return_value=None,
    ), patch(
        "terminal_bitcoin._set_cached"
    ), patch(
        "terminal_bitcoin._make_fmp_client",
        return_value=client,
    ):
        quote = fetch_btc_quote()

    assert quote is not None
    assert quote.price == 100000.0
    assert client.get_index_quote.call_args.args[0] == "BTCUSD"


def test_fetch_btc_ohlcv_daily_uses_shared_crypto_history() -> None:
    client = MagicMock()
    client.get_cryptocurrency_historical_price.return_value = [
        {"date": "2026-03-01", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}
    ]

    with patch(
        "terminal_bitcoin._get_cached",
        return_value=None,
    ), patch(
        "terminal_bitcoin._set_cached"
    ), patch(
        "terminal_bitcoin._YF",
        False,
    ), patch(
        "terminal_bitcoin._make_fmp_client",
        return_value=client,
    ):
        rows = fetch_btc_ohlcv(period="5d", interval="1d")

    assert rows == [{"date": "2026-03-01", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10.0}]
    assert client.get_cryptocurrency_historical_price.call_args.args[0] == "BTCUSD"


def test_fetch_crypto_movers_uses_shared_batch_crypto_quotes() -> None:
    client = MagicMock()
    client.get_batch_crypto_quotes.return_value = [
        {"symbol": "BTCUSD", "price": 100.0, "change": 10.0},
        {"symbol": "ETHUSD", "price": 100.0, "change": -5.0},
    ]

    with patch(
        "terminal_bitcoin._get_cached",
        return_value=None,
    ), patch(
        "terminal_bitcoin._set_cached"
    ), patch(
        "terminal_bitcoin._make_fmp_client",
        return_value=client,
    ):
        movers = fetch_crypto_movers()

    assert movers["gainers"][0].symbol == "BTCUSD"
    assert movers["losers"][0].symbol == "ETHUSD"
    client.get_batch_crypto_quotes.assert_called_once()


def test_fetch_crypto_listings_uses_shared_client() -> None:
    client = MagicMock()
    client.get_cryptocurrency_list.return_value = [{"symbol": "BTCUSD", "name": "Bitcoin", "currency": "USD", "exchangeShortName": "CRYPTO"}]

    with patch(
        "terminal_bitcoin._get_cached",
        return_value=None,
    ), patch(
        "terminal_bitcoin._set_cached"
    ), patch(
        "terminal_bitcoin._make_fmp_client",
        return_value=client,
    ):
        rows = fetch_crypto_listings(limit=5)

    assert len(rows) == 1
    assert rows[0].symbol == "BTCUSD"
    client.get_cryptocurrency_list.assert_called_once()


def test_fetch_btc_news_uses_shared_news_path_and_fallback() -> None:
    client = MagicMock()
    client.get_stock_latest_news.side_effect = [
        [],
        [{"title": "Bitcoin rallies", "url": "https://example.test", "site": "Test", "publishedDate": "2026-03-25", "text": "BTC move"}],
    ]

    with patch(
        "terminal_bitcoin._get_cached",
        return_value=None,
    ), patch(
        "terminal_bitcoin._set_cached"
    ), patch(
        "terminal_bitcoin._make_fmp_client",
        return_value=client,
    ):
        rows = fetch_btc_news(limit=1)

    assert len(rows) == 1
    assert rows[0]["title"] == "Bitcoin rallies"
    assert client.get_stock_latest_news.call_args_list[0].kwargs == {"symbol": "BTCUSD", "limit": 1}
    assert client.get_stock_latest_news.call_args_list[1].kwargs == {"limit": 50}


# ``test_fetch_fear_greed_fmp_fallback_uses_shared_client`` removed in P-6
# (2026-04-30): FMP retired ``/stable/fear-and-greed-index`` and the FMP
# fallback branch in ``terminal_bitcoin.fetch_fear_greed`` was deleted.
# alternative.me is the sole F&G source for the crypto tile.
# See docs/reviews/2026-04-24-system-review.md (P-6).

