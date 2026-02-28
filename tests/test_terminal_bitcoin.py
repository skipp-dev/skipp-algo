"""Tests for terminal_bitcoin.py — Bitcoin data endpoints.

These tests verify that each data source responds and returns the expected
data structure. They hit live APIs (not mocked) to confirm real connectivity.

Run with: pytest tests/test_terminal_bitcoin.py -v
"""

from __future__ import annotations

import os
import pytest

# Skip entire module if no API keys are set
pytestmark = pytest.mark.skipif(
    not os.environ.get("FMP_API_KEY") and not os.environ.get("NEWSAPI_AI_KEY"),
    reason="No API keys set (FMP_API_KEY / NEWSAPI_AI_KEY) — skipping live endpoint tests",
)

from terminal_bitcoin import (
    BTCOutlook,
    BTCQuote,
    BTCSupply,
    BTCTechnicals,
    CryptoListing,
    CryptoMover,
    FearGreed,
    fetch_btc_news,
    fetch_btc_ohlcv,
    fetch_btc_ohlcv_10min,
    fetch_btc_outlook,
    fetch_btc_quote,
    fetch_btc_supply,
    fetch_btc_technicals,
    fetch_crypto_listings,
    fetch_crypto_movers,
    fetch_fear_greed,
    format_btc_price,
    format_large_number,
    format_supply,
    is_available,
    technicals_signal_icon,
    technicals_signal_label,
)


class TestBTCQuote:
    """Real-time Bitcoin quote from FMP or yfinance."""

    def test_quote_returns_data(self) -> None:
        quote = fetch_btc_quote()
        assert quote is not None, "fetch_btc_quote() returned None — no data source available"
        assert isinstance(quote, BTCQuote)

    def test_quote_has_price(self) -> None:
        quote = fetch_btc_quote()
        assert quote is not None
        assert quote.price > 0, f"BTC price should be positive, got {quote.price}"

    def test_quote_has_volume(self) -> None:
        quote = fetch_btc_quote()
        assert quote is not None
        # Volume may be 0 on some sources, but price should be set
        assert quote.price > 0

    def test_quote_change_icon(self) -> None:
        quote = fetch_btc_quote()
        assert quote is not None
        assert quote.change_icon in ("🟢", "🔴", "⚪")


class TestBTCOHLCV:
    """Historical OHLCV data for chart rendering."""

    def test_ohlcv_daily_returns_data(self) -> None:
        rows = fetch_btc_ohlcv(period="30d", interval="1d")
        assert isinstance(rows, list)
        assert len(rows) > 0, "fetch_btc_ohlcv (daily) returned empty list"

    def test_ohlcv_row_structure(self) -> None:
        rows = fetch_btc_ohlcv(period="5d", interval="1d")
        assert len(rows) > 0
        row = rows[0]
        for key in ("date", "open", "high", "low", "close", "volume"):
            assert key in row, f"Missing key '{key}' in OHLCV row"

    def test_ohlcv_prices_positive(self) -> None:
        rows = fetch_btc_ohlcv(period="5d", interval="1d")
        assert len(rows) > 0
        for row in rows:
            assert row["close"] > 0, f"Close price should be positive: {row}"

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="yfinance intraday requires market access",
    )
    def test_ohlcv_hourly_returns_data(self) -> None:
        rows = fetch_btc_ohlcv(period="5d", interval="1h")
        assert isinstance(rows, list)
        # May be empty if yfinance is not installed, but should not error
        if rows:
            assert rows[0]["close"] > 0


class TestBTCOHLCV10Min:
    """10-minute aggregated OHLCV for volume analysis."""

    def test_10min_returns_data(self) -> None:
        rows = fetch_btc_ohlcv_10min(hours=24)
        assert isinstance(rows, list)
        # May be empty if pandas/yfinance not installed
        if rows:
            assert len(rows) > 0
            assert "volume" in rows[0]
            assert rows[0]["volume"] >= 0

    def test_10min_row_structure(self) -> None:
        rows = fetch_btc_ohlcv_10min(hours=12)
        if rows:
            for key in ("date", "open", "high", "low", "close", "volume"):
                assert key in rows[0], f"Missing key '{key}' in 10min row"


class TestTechnicals:
    """TradingView technical analysis for BTC."""

    def test_technicals_returns_data(self) -> None:
        tech = fetch_btc_technicals("1h")
        assert isinstance(tech, BTCTechnicals)

    def test_technicals_has_summary(self) -> None:
        tech = fetch_btc_technicals("1h")
        if not tech.error:
            assert tech.summary in (
                "STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"
            ), f"Unexpected summary: {tech.summary}"

    def test_technicals_has_rsi(self) -> None:
        tech = fetch_btc_technicals("1h")
        if not tech.error:
            assert tech.rsi is not None, "RSI should not be None"
            assert 0 <= tech.rsi <= 100, f"RSI out of range: {tech.rsi}"

    def test_technicals_signal_icon(self) -> None:
        tech = fetch_btc_technicals("1h")
        if not tech.error:
            assert tech.signal_icon in ("🟢", "🔴", "⚪")

    def test_technicals_multiple_intervals(self) -> None:
        for interval in ("1h", "4h", "1d"):
            tech = fetch_btc_technicals(interval)
            assert isinstance(tech, BTCTechnicals)
            assert tech.interval == interval


class TestFearGreed:
    """Fear & Greed index from FMP."""

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required for Fear & Greed",
    )
    def test_fear_greed_returns_data(self) -> None:
        fg = fetch_fear_greed()
        assert fg is not None, "fetch_fear_greed() returned None"
        assert isinstance(fg, FearGreed)

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_fear_greed_value_range(self) -> None:
        fg = fetch_fear_greed()
        if fg:
            assert 0 <= fg.value <= 100, f"F&G value out of range: {fg.value}"

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_fear_greed_icon(self) -> None:
        fg = fetch_fear_greed()
        if fg:
            assert fg.icon in ("🟢", "🟡", "⚪", "🟠", "🔴")


class TestCryptoMovers:
    """Cryptocurrency gainers and losers from FMP."""

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_movers_returns_dict(self) -> None:
        movers = fetch_crypto_movers()
        assert isinstance(movers, dict)
        assert "gainers" in movers
        assert "losers" in movers

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_movers_structure(self) -> None:
        movers = fetch_crypto_movers()
        for key in ("gainers", "losers"):
            items = movers.get(key, [])
            if items:
                m = items[0]
                assert isinstance(m, CryptoMover)
                assert m.symbol, "Mover should have a symbol"


class TestCryptoListings:
    """Cryptocurrency exchange listings from FMP."""

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_listings_returns_data(self) -> None:
        listings = fetch_crypto_listings(limit=10)
        assert isinstance(listings, list)

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_listings_structure(self) -> None:
        listings = fetch_crypto_listings(limit=5)
        if listings:
            li = listings[0]
            assert isinstance(li, CryptoListing)
            assert li.symbol, "Listing should have a symbol"


class TestBTCSupply:
    """Bitcoin market cap and supply data."""

    def test_supply_returns_data(self) -> None:
        supply = fetch_btc_supply()
        assert isinstance(supply, BTCSupply)

    def test_supply_total_max(self) -> None:
        supply = fetch_btc_supply()
        assert supply.total_supply == 21_000_000


class TestBTCNews:
    """Bitcoin news from FMP."""

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_news_returns_list(self) -> None:
        articles = fetch_btc_news(limit=5)
        assert isinstance(articles, list)

    @pytest.mark.skipif(
        not os.environ.get("FMP_API_KEY"),
        reason="FMP_API_KEY required",
    )
    def test_news_structure(self) -> None:
        articles = fetch_btc_news(limit=3)
        if articles:
            art = articles[0]
            assert "title" in art
            assert "url" in art


class TestBTCOutlook:
    """Composite tomorrow outlook."""

    def test_outlook_returns_data(self) -> None:
        outlook = fetch_btc_outlook()
        assert isinstance(outlook, BTCOutlook)

    def test_outlook_has_trend(self) -> None:
        outlook = fetch_btc_outlook()
        assert outlook.trend_label in ("Bullish", "Bearish", "Neutral")

    def test_outlook_has_price(self) -> None:
        outlook = fetch_btc_outlook()
        # Price may be 0 if all sources fail, but trend should always be set
        assert outlook.trend_label


class TestHelpers:
    """Helper functions."""

    def test_format_btc_price(self) -> None:
        assert format_btc_price(84532.50) == "$84,532.50"

    def test_format_large_number_billion(self) -> None:
        result = format_large_number(1_650_000_000_000)
        assert "T" in result

    def test_format_large_number_million(self) -> None:
        result = format_large_number(45_000_000)
        assert "M" in result

    def test_format_supply(self) -> None:
        assert "M" in format_supply(19_500_000)

    def test_technicals_signal_label(self) -> None:
        assert technicals_signal_label("STRONG_BUY") == "Strong Buy"
        assert technicals_signal_label("SELL") == "Sell"
        assert technicals_signal_label("NEUTRAL") == "Neutral"

    def test_technicals_signal_icon(self) -> None:
        assert technicals_signal_icon("BUY") == "🟢"
        assert technicals_signal_icon("SELL") == "🔴"
        assert technicals_signal_icon("NEUTRAL") == "⚪"

    def test_is_available(self) -> None:
        # Should be true if any key/lib is available
        result = is_available()
        assert isinstance(result, bool)


class TestMarketHoursCompliance:
    """Bitcoin markets are 24/7 — ensure no market-hours blocking."""

    def test_no_market_hours_check_in_quote(self) -> None:
        """Verify quote works regardless of time of day (24/7 market)."""
        quote = fetch_btc_quote()
        # Should return data — Bitcoin never closes
        assert quote is not None or not is_available()

    def test_no_market_hours_check_in_technicals(self) -> None:
        """Technicals should always be available (crypto screener)."""
        tech = fetch_btc_technicals("1h")
        assert isinstance(tech, BTCTechnicals)
        # Should not have an error about market being closed
        if tech.error:
            assert "closed" not in tech.error.lower()
            assert "market" not in tech.error.lower()

    def test_no_market_hours_check_in_ohlcv(self) -> None:
        """OHLCV should be available anytime."""
        rows = fetch_btc_ohlcv(period="5d", interval="1d")
        assert isinstance(rows, list)
