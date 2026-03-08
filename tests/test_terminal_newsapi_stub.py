"""Tests for terminal_newsapi.py stub completeness after decommission."""
from __future__ import annotations

import unittest

from terminal_newsapi import (
    NLPSentiment,
    fetch_breaking_events,
    fetch_event_clusters,
    fetch_nlp_sentiment,
    fetch_social_ranked_articles,
    fetch_trending_concepts,
    newsapi_available,
)


class TestNewsApiStubCompleteness(unittest.TestCase):
    """Verify all stubs return safe defaults and NLPSentiment has all fields."""

    def test_newsapi_available_returns_false(self):
        self.assertFalse(newsapi_available())

    def test_fetch_functions_return_empty(self):
        self.assertEqual(fetch_breaking_events(), [])
        self.assertEqual(fetch_event_clusters(), [])
        self.assertEqual(fetch_nlp_sentiment(), {})
        self.assertEqual(fetch_trending_concepts(), [])
        self.assertEqual(fetch_social_ranked_articles(), [])

    def test_nlp_sentiment_has_all_required_fields(self):
        """Callers may access .symbol, .label, .nlp_score, .icon — all must exist."""
        s = NLPSentiment()
        self.assertEqual(s.symbol, "")
        self.assertEqual(s.label, "neutral")
        self.assertAlmostEqual(s.nlp_score, 0.0)
        self.assertEqual(s.article_count, 0)
        self.assertAlmostEqual(s.agreement, 0.0)
        self.assertEqual(s.icon, "")

    def test_nlp_sentiment_construct_with_kwargs(self):
        s = NLPSentiment(symbol="AAPL", nlp_score=0.5, label="positive")
        self.assertEqual(s.symbol, "AAPL")
        self.assertAlmostEqual(s.nlp_score, 0.5)
        self.assertEqual(s.label, "positive")


if __name__ == "__main__":
    unittest.main()
