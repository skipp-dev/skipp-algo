from __future__ import annotations

from typing import Any

from scripts.smc_newsapi_ai import fetch_newsapi_articles


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = payloads
        self.calls: list[list[tuple[str, str]]] = []

    def get(self, url: str, params: list[tuple[str, str]]) -> _FakeResponse:
        self.calls.append(params)
        index = len(self.calls) - 1
        return _FakeResponse(self._payloads[index])

    def close(self) -> None:
        return None


def test_fetch_newsapi_articles_matches_symbols_and_deduplicates() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {"uri": "uri-1", "title": "AAPL jumps after earnings beat"},
                        {"uri": "uri-2", "title": "MSFT rallies as cloud growth accelerates"},
                        {"uri": "uri-1", "title": "AAPL jumps after earnings beat"},
                        {"uri": "uri-3", "title": "Broad market update without ticker keyword"},
                    ]
                }
            }
        ]
    )

    articles = fetch_newsapi_articles("test-key", ["AAPL", "MSFT"], client=client)

    assert articles == [
        {"headline": "AAPL jumps after earnings beat", "tickers": ["AAPL"]},
        {"headline": "MSFT rallies as cloud growth accelerates", "tickers": ["MSFT"]},
    ]


def test_fetch_newsapi_articles_chunks_keywords_at_sixty_items() -> None:
    symbols = [f"SYM{index:03d}" for index in range(61)]
    client = _FakeClient([
        {"articles": {"results": []}},
        {"articles": {"results": []}},
    ])

    fetch_newsapi_articles("test-key", symbols, client=client)

    assert len(client.calls) == 2
    assert sum(1 for key, _ in client.calls[0] if key == "keyword") == 60
    assert sum(1 for key, _ in client.calls[1] if key == "keyword") == 1


def test_fetch_newsapi_articles_ignores_short_symbols() -> None:
    client = _FakeClient([
        {"articles": {"results": [{"uri": "uri-1", "title": "AAPL rises while AI demand remains strong"}]}}
    ])

    articles = fetch_newsapi_articles("test-key", ["AI", "AAPL"], client=client)

    assert articles == [{"headline": "AAPL rises while AI demand remains strong", "tickers": ["AAPL"]}]