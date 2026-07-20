from __future__ import annotations

import httpx
import pytest

from terminal_internal_ai import ProducerAIError, ProducerAIInsightsClient


def _response(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "answer": "Inspected answer",
        "model": "gpt-4o",
        "cached": False,
        "context_articles": 3,
        "context_tickers": 2,
        "fmp_tickers": 1,
        "error": "",
    }
    payload.update(overrides)
    return payload


def test_client_posts_to_fixed_private_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/ai-insights"
        assert request.headers["Authorization"] == "Bearer shared-secret"
        assert b"What moved AAPL?" in request.content
        return httpx.Response(200, json=_response())

    client = ProducerAIInsightsClient(
        "http://producer.railway.internal:8080/news-feed.json",
        "shared-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = client.query(question="What moved AAPL?", context_json='{"total_articles":3}')

    assert result.answer == "Inspected answer"
    assert result.context_articles == 3


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/news-feed.json",
        "http://producer.railway.internal.attacker.test/news-feed.json",
        "http://user:secret@localhost/news-feed.json",
    ],
)
def test_client_rejects_non_private_urls(url: str) -> None:
    with pytest.raises(ValueError):
        ProducerAIInsightsClient(url, "token")


def test_client_rejects_http_error_without_leaking_token() -> None:
    client = ProducerAIInsightsClient(
        "http://127.0.0.1:8080/news-feed.json",
        "never-log-this-token",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(503))
        ),
    )

    with pytest.raises(ProducerAIError) as caught:
        client.query(question="question", context_json="{}")

    assert "HTTP 503" in str(caught.value)
    assert "never-log-this-token" not in str(caught.value)
