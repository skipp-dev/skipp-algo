"""Tests for WP-NW1: Fine-grained polarity scoring in newsstack_fmp/scoring.py."""
from __future__ import annotations

from newsstack_fmp.scoring import classify_and_score


class TestStrongPositive:
    def test_multiple_positive_keywords_high_impact(self) -> None:
        """Several strong positive keywords → polarity well above 0.5."""
        r = classify_and_score(
            {"headline": "AAPL beats earnings, raises guidance, record revenue", "tickers": ["AAPL"]},
            cluster_count=1,
        )
        assert r.polarity > 0.5

    def test_strong_positive_with_snippet(self) -> None:
        r = classify_and_score(
            {
                "headline": "AAPL earnings report",
                "snippet": "Apple beats expectations, raises guidance, and reports record profit.",
                "tickers": ["AAPL"],
            },
            cluster_count=1,
        )
        assert r.polarity > 0.3


class TestWeakPositive:
    def test_single_positive_keyword_low_impact(self) -> None:
        """Single mild positive keyword + low-impact category → low polarity."""
        r = classify_and_score(
            {"headline": "AAPL mentioned in positive article", "tickers": ["AAPL"]},
            cluster_count=1,
        )
        assert 0.0 < r.polarity <= 0.4


class TestMixedSignals:
    def test_beats_but_lowers(self) -> None:
        """Positive and negative keywords cancel out → polarity near zero."""
        r = classify_and_score(
            {"headline": "AAPL beats earnings but lowers guidance", "tickers": ["AAPL"]},
            cluster_count=1,
        )
        assert -0.3 < r.polarity < 0.3


class TestStrongNegative:
    def test_multiple_negative_keywords(self) -> None:
        """Multiple negative keywords → polarity negative."""
        r = classify_and_score(
            {"headline": "AAPL halted, plunge, decline feared, loss widens", "tickers": ["AAPL"]},
            cluster_count=1,
        )
        assert r.polarity < -0.3

    def test_halt_high_impact(self) -> None:
        r = classify_and_score(
            {"headline": "KODK halted, warning, downgrade, drops", "tickers": ["KODK"]},
            cluster_count=1,
        )
        assert r.polarity < -0.4


class TestNoKeywords:
    def test_neutral_headline(self) -> None:
        """No positive or negative keywords → polarity exactly 0.0."""
        r = classify_and_score(
            {"headline": "AAPL to present at conference", "tickers": ["AAPL"]},
            cluster_count=1,
        )
        assert r.polarity == 0.0


class TestContinuousScale:
    def test_polarity_bounded(self) -> None:
        """Verify polarity stays within [-1.0, +1.0]."""
        for headline in [
            "Record growth surge jumps soars beats rally profit strong exceeds",
            "Halted plunge bankruptcy delist decline loss slumps tumbles drops warning",
            "Neutral corporate update",
        ]:
            r = classify_and_score(
                {"headline": headline, "tickers": ["X"]},
                cluster_count=1,
            )
            assert -1.0 <= r.polarity <= 1.0

    def test_differentiation(self) -> None:
        """Weak vs. strong signals yield different polarity magnitudes."""
        weak = classify_and_score(
            {"headline": "Company gains momentum", "tickers": ["X"]},
            cluster_count=1,
        )
        strong = classify_and_score(
            {"headline": "Company beats earnings, raises guidance, record growth, profit surge", "tickers": ["X"]},
            cluster_count=1,
        )
        assert strong.polarity > weak.polarity
