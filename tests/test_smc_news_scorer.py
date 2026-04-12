"""Tests for scripts/smc_news_scorer.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_news_scorer import compute_news_sentiment


class TestEmptyArticles:

    def test_empty_articles(self) -> None:
        result = compute_news_sentiment(["AAPL", "TSLA"], [])
        assert result["bullish_tickers"] == []
        assert result["bearish_tickers"] == []
        assert result["neutral_tickers"] == []
        assert result["news_heat_global"] == 0.0
        assert result["ticker_heat_map"] == ""


class TestBullishTicker:

    def test_bullish_ticker(self) -> None:
        articles = [
            {"headline": "AAPL beats earnings, raises guidance, strong growth", "tickers": ["AAPL"]},
        ]
        result = compute_news_sentiment(["AAPL", "MSFT"], articles)
        assert "AAPL" in result["bullish_tickers"]
        assert result["neutral_tickers"] == []


class TestBearishTicker:

    def test_bearish_ticker(self) -> None:
        articles = [
            {"headline": "TSLA misses estimates, negative outlook, loss widens", "tickers": ["TSLA"]},
        ]
        result = compute_news_sentiment(["TSLA", "GOOG"], articles)
        assert "TSLA" in result["bearish_tickers"]
        assert result["neutral_tickers"] == []


class TestTickerHeatMapFormat:

    def test_ticker_heat_map_format(self) -> None:
        articles = [
            {"headline": "AAPL strong growth beats", "tickers": ["AAPL"]},
        ]
        result = compute_news_sentiment(["AAPL", "MSFT"], articles)
        hmap = result["ticker_heat_map"]
        # Format: "TICKER:SCORE,TICKER:SCORE"
        parts = hmap.split(",")
        assert len(parts) == 1
        for part in parts:
            ticker, score = part.split(":")
            assert ticker == "AAPL"
            float(score)  # must be parseable


class TestGlobalHeatCalculation:

    def test_global_heat_calculation(self) -> None:
        articles = [
            {"headline": "AAPL beats earnings, strong growth", "tickers": ["AAPL"]},
            {"headline": "TSLA misses estimates, weak outlook", "tickers": ["TSLA"]},
        ]
        result = compute_news_sentiment(["AAPL", "TSLA"], articles)
        # One positive, one negative → global heat near zero
        assert -0.6 <= result["news_heat_global"] <= 0.6

    def test_global_heat_all_bullish(self) -> None:
        articles = [
            {"headline": "AAPL beats, strong growth", "tickers": ["AAPL"]},
            {"headline": "TSLA beats, record profit", "tickers": ["TSLA"]},
        ]
        result = compute_news_sentiment(["AAPL", "TSLA"], articles)
        assert result["news_heat_global"] > 0


class TestUnknownTickerIgnored:

    def test_unknown_ticker_ignored(self) -> None:
        articles = [
            {"headline": "XYZ beats earnings, strong upgrade", "tickers": ["XYZ"]},
        ]
        result = compute_news_sentiment(["AAPL"], articles)
        assert "XYZ" not in result["bullish_tickers"]
        assert "XYZ" not in result["bearish_tickers"]
        assert "XYZ" not in result["neutral_tickers"]
        assert result["neutral_tickers"] == []
        assert result["ticker_heat_map"] == ""


class TestReturnShape:

    def test_return_keys(self) -> None:
        result = compute_news_sentiment(["A"], [])
        assert set(result.keys()) == {
            "bullish_tickers", "bearish_tickers", "neutral_tickers",
            "news_heat_global", "ticker_heat_map",
        }


class TestDiagnostics:

    def test_include_diagnostics_reports_payload_distribution(self) -> None:
        articles = [
            {"headline": "AAPL beats earnings, strong growth", "tickers": ["AAPL"]},
            {"headline": "TSLA misses estimates, weak outlook", "tickers": ["TSLA"]},
            {"headline": "", "tickers": ["AAPL"]},
        ]

        result = compute_news_sentiment(["AAPL", "TSLA"], articles, include_diagnostics=True)

        diagnostics = result["diagnostics"]
        assert diagnostics["article_count"] == 3
        assert diagnostics["matched_article_count"] == 3
        assert diagnostics["empty_headline_count"] == 1
        assert diagnostics["recognized_ticker_mentions"] == 3
        assert diagnostics["unique_recognized_ticker_count"] == 2
        assert diagnostics["polarity_distribution"] == {
            "positive": 1,
            "negative": 1,
            "neutral": 1,
        }
