"""Tests for WP-NW4: Category, count, and breaking-news fields."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_news_scorer import compute_news_sentiment


def _art(headline: str, ticker: str, ts: float | None = None) -> dict:
    a = {"headline": headline, "tickers": [ticker]}
    if ts is not None:
        a["published_ts"] = ts
    return a


class TestCategoryMapFormat:
    def test_category_map_contains_ticker(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["AAPL"],
            [_art("AAPL beats earnings, record profit", "AAPL", now - 60)],
        )
        cmap = result["news_category_map"]
        assert "AAPL:" in cmap

    def test_multiple_tickers(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["AAPL", "MSFT"],
            [
                _art("AAPL beats earnings", "AAPL", now - 60),
                _art("MSFT FDA approval", "MSFT", now - 120),
            ],
        )
        cmap = result["news_category_map"]
        assert "AAPL:" in cmap
        assert "MSFT:" in cmap


class TestCountMap:
    def test_count_map_format(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["AAPL", "MSFT"],
            [
                _art("AAPL earnings up", "AAPL", now - 60),
                _art("AAPL guidance raised", "AAPL", now - 120),
                _art("MSFT update", "MSFT", now - 180),
            ],
        )
        cmap = result["news_count_map"]
        # AAPL should have count 2, MSFT count 1
        assert "AAPL:2" in cmap
        assert "MSFT:1" in cmap


class TestBreakingDetection:
    def test_halt_triggers_breaking(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["KODK"],
            [_art("KODK stock halted pending investigation", "KODK", now - 60)],
        )
        assert "KODK" in result["breaking_tickers"]

    def test_no_breaking_for_normal_news(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["AAPL"],
            [_art("AAPL corporate update", "AAPL", now - 60)],
        )
        assert len(result["breaking_tickers"]) == 0


class TestMostMentioned:
    def test_most_mentioned_ticker(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["AAPL", "MSFT"],
            [
                _art("AAPL earnings up", "AAPL", now - 60),
                _art("AAPL guidance raised", "AAPL", now - 120),
                _art("AAPL record quarter", "AAPL", now - 180),
                _art("MSFT update", "MSFT", now - 200),
            ],
        )
        assert result["most_mentioned_ticker"] == "AAPL"


class TestHighImpactCount:
    def test_high_impact_threshold(self) -> None:
        """Ticker with many articles should appear in high-impact count."""
        now = time.time()
        articles = [_art(f"AAPL news {i}", "AAPL", now - i * 60) for i in range(6)]
        result = compute_news_sentiment(["AAPL"], articles)
        assert result["high_impact_news_count"] >= 1

    def test_low_article_count_excluded(self) -> None:
        now = time.time()
        result = compute_news_sentiment(
            ["AAPL"],
            [_art("AAPL update", "AAPL", now - 60)],
        )
        assert result["high_impact_news_count"] == 0


class TestEmptyArticles:
    def test_empty_list(self) -> None:
        result = compute_news_sentiment([], [])
        assert result["news_category_map"] == ""
        assert result["news_count_map"] == ""
        assert result["breaking_tickers"] == []
        assert result["high_impact_news_count"] == 0
        assert result["most_mentioned_ticker"] == ""
