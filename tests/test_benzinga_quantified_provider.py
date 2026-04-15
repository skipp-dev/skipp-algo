"""Tests for WP-NW6: Benzinga quantified news provider integration."""
from __future__ import annotations

from newsstack_fmp.normalize import normalize_benzinga_quantified


class TestNormalizeBenzingaQuantified:
    def test_normalizes_basic_item(self) -> None:
        raw = {
            "title": "AAPL Surges After Earnings Beat",
            "stocks": [{"name": "AAPL"}],
            "created": "2025-01-15T10:00:00Z",
            "url": "https://example.com/article",
            "overall_sentiment_signal": "Bullish",
            "overall_average_signal": "0.6",
        }
        item = normalize_benzinga_quantified(raw)
        assert item.headline == "AAPL Surges After Earnings Beat"
        assert "AAPL" in item.tickers
        assert item.provider == "benzinga_quantified"

    def test_empty_item(self) -> None:
        item = normalize_benzinga_quantified({})
        assert item.headline == ""
        assert item.tickers == []
        assert item.provider == "benzinga_quantified"

    def test_missing_stocks(self) -> None:
        raw = {
            "title": "Market summary",
            "created": "2025-01-15T10:00:00Z",
        }
        item = normalize_benzinga_quantified(raw)
        assert item.tickers == []

    def test_preserves_price_context(self) -> None:
        raw = {
            "title": "AAPL up 3%",
            "stocks": [{"name": "AAPL"}],
            "created": "2025-01-15T10:00:00Z",
            "overall_sentiment_signal": "Bullish",
            "overall_average_signal": "0.8",
        }
        item = normalize_benzinga_quantified(raw)
        assert item.raw["overall_sentiment_signal"] == "Bullish"


class TestProviderInBus:
    def test_benzinga_quantified_in_provider_order(self) -> None:
        from scripts.smc_live_news_bus import PROVIDER_ORDER
        assert "benzinga_quantified" in PROVIDER_ORDER
