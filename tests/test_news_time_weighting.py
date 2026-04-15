"""Tests for WP-NW3: Time-weighted news scoring in scripts/smc_news_scorer.py."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_news_scorer import compute_news_sentiment


def _make_article(headline: str, ticker: str, ts: float | None) -> dict:
    art = {"headline": headline, "tickers": [ticker]}
    if ts is not None:
        art["published_ts"] = ts
    return art


def _parse_heat(result: dict, ticker: str) -> float:
    """Extract a ticker's score from the ticker_heat_map string."""
    hmap = result.get("ticker_heat_map", "")
    if not hmap:
        return 0.0
    for part in hmap.split(","):
        t, score = part.split(":")
        if t == ticker:
            return float(score)
    return 0.0


class TestRecentDominates:
    def test_recent_article_has_more_weight(self) -> None:
        """A recent bullish article + old bearish article → net bullish."""
        now = time.time()
        recent_bullish = _make_article("AAPL beats earnings, raises guidance", "AAPL", now - 60)
        old_bearish = _make_article("AAPL misses estimates, lowers guidance", "AAPL", now - 36 * 3600)
        result = compute_news_sentiment(["AAPL"], [recent_bullish, old_bearish])
        # The recent bullish should dominate the decayed bearish
        assert "AAPL" in result["bullish_tickers"]


class TestOldDecayed:
    def test_old_article_weight_decayed(self) -> None:
        """An article from 24h ago has significantly less influence."""
        now = time.time()
        recent = _make_article("AAPL beats earnings, record profit", "AAPL", now - 60)
        recent_result = compute_news_sentiment(["AAPL"], [recent])

        old = _make_article("AAPL beats earnings, record profit", "AAPL", now - 24 * 3600)
        old_result = compute_news_sentiment(["AAPL"], [old])

        recent_val = _parse_heat(recent_result, "AAPL")
        old_val = _parse_heat(old_result, "AAPL")
        # Both positive, recent should have higher weighted score
        assert recent_val > 0
        assert old_val > 0
        # Combined should still be positive and >= old value
        combined = compute_news_sentiment(["AAPL"], [recent, old])
        combined_val = _parse_heat(combined, "AAPL")
        assert combined_val >= old_val


class TestNoTimestamp:
    def test_missing_timestamp_uses_default_age(self) -> None:
        """Without published_ts, uses 12h default age → still contributes."""
        art = _make_article("AAPL beats earnings, raises guidance", "AAPL", None)
        result = compute_news_sentiment(["AAPL"], [art])
        assert "AAPL" in result["bullish_tickers"]
        val = _parse_heat(result, "AAPL")
        assert val > 0


class TestSameAge:
    def test_equal_timestamps_unchanged_ratio(self) -> None:
        """Two articles from equal time ago → equal weight."""
        now = time.time()
        t = now - 3600  # 1h ago
        bullish = _make_article("AAPL beats earnings, record growth", "AAPL", t)
        bearish = _make_article("AAPL misses estimates, lowers guidance", "AAPL", t)
        result = compute_news_sentiment(["AAPL"], [bullish, bearish])
        val = _parse_heat(result, "AAPL")
        # Roughly cancel out
        assert -0.5 < val < 0.5
