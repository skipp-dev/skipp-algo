"""Truth-audit fixes for the terminal LLM-context builder.

N1: the FMP/AI insight context builders read a per-article ``sentiment`` from a
key the feed never emits — the canonical feed dict carries ``sentiment_label``
(and ``sentiment_score``), so the categorical bull/bear label used to be dropped
before it reached the model.
"""
from __future__ import annotations


def test_assemble_context_reads_sentiment_label() -> None:
    from terminal_fmp_insights import assemble_context

    # A unique token in sentiment_label surfaces in the context ONLY if the
    # builder reads sentiment_label (nothing else echoes it).
    feed = [{"headline": "h", "ticker": "AAPL", "news_score": 0.9, "sentiment_label": "zzbull42"}]
    ctx = assemble_context(feed, max_articles=1)
    assert "zzbull42" in ctx
