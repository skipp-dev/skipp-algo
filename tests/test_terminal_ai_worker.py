from __future__ import annotations

from unittest.mock import MagicMock

from terminal_internal_ai import ProducerAIResponse
from terminal_tabs import tab_fmp_ai


def test_worker_adds_databento_context_and_uses_private_producer(monkeypatch) -> None:
    monkeypatch.setattr(
        tab_fmp_ai,
        "fetch_databento_quote_map",
        lambda symbols: {symbols[0]: {"close": 213.4, "volume": 123_456}},
    )
    producer_ai = MagicMock()
    producer_ai.query.return_value = ProducerAIResponse(
        answer="inspected answer",
        model="gpt-4o",
        cached=False,
        context_articles=1,
        context_tickers=1,
        fmp_tickers=0,
    )

    result = tab_fmp_ai._analysis_worker_inner(
        feed=[
            {
                "headline": "Apple raises guidance",
                "ticker": "AAPL",
                "news_score": 0.9,
                "sentiment_label": "bullish",
            }
        ],
        question="What changed?",
        fmp_key="",
        producer_ai=producer_ai,
        benzinga_key="",
        macro=None,
        cached={},
        technicals_available=False,
        finnhub_available=False,
        forecast_available=False,
        poller_available=False,
        databento_available=True,
    )

    assert result["result_dict"]["answer"] == "inspected answer"
    assert '"databento_quotes"' in result["context_json"]
    producer_ai.query.assert_called_once()
