"""Truth-audit fixes for the terminal LLM-context / TV-headline parsers.

N1: the FMP/AI insight context builders read a per-article ``sentiment`` from a
key the feed never emits — the canonical feed dict carries ``sentiment_label``
(and ``sentiment_score``), so the categorical bull/bear label used to be dropped
before it reached the model. N3: the TradingView headline parser read the flash
flag as snake_case ``is_flash`` against a camelCase payload (every sibling field —
``isExclusive``/``relatedSymbols``/``storyPath`` — is camelCase), so it always
resolved to the ``False`` default.
"""
from __future__ import annotations


def test_assemble_context_reads_sentiment_label() -> None:
    from terminal_fmp_insights import assemble_context

    # A unique token in sentiment_label surfaces in the context ONLY if the
    # builder reads sentiment_label (nothing else echoes it).
    feed = [{"headline": "h", "ticker": "AAPL", "news_score": 0.9, "sentiment_label": "zzbull42"}]
    ctx = assemble_context(feed, max_articles=1)
    assert "zzbull42" in ctx


def test_parse_items_reads_camelcase_isflash_with_snakecase_fallback() -> None:
    from terminal_tradingview_news import _parse_items

    camel = _parse_items({"items": [{"id": "1", "title": "t", "isFlash": True}]})
    assert camel and camel[0].is_flash is True

    # snake_case is still honored (robust fallback — cannot regress if a payload
    # ever used the old key).
    snake = _parse_items({"items": [{"id": "2", "title": "t", "is_flash": True}]})
    assert snake and snake[0].is_flash is True

    # absent → False
    none = _parse_items({"items": [{"id": "3", "title": "t"}]})
    assert none and none[0].is_flash is False
