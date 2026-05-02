from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from scripts.smc_newsapi_ai import (
    TARGET_KEYWORDS_PER_REQUEST,
    NewsApiAiProviderError,
    extract_newsapi_feed_article_cursor_uri,
    fetch_newsapi_article_records,
    fetch_newsapi_articles,
    fetch_newsapi_event_records,
    fetch_newsapi_feed_article_probe,
    fetch_newsapi_feed_article_records,
    fetch_newsapi_records,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any] | str, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = payload if isinstance(payload, str) else str(payload)

    def json(self) -> dict[str, Any] | str:
        return self._payload


class _FakeClient:
    def __init__(self, payloads: list[dict[str, Any] | str], *, status_codes: list[int] | None = None) -> None:
        self._payloads = payloads
        self._status_codes = status_codes or [200] * len(payloads)
        self.calls: list[list[tuple[str, str]]] = []
        self.urls: list[str] = []

    def get(self, url: str, params: list[tuple[str, str]]) -> _FakeResponse:
        self.urls.append(url)
        self.calls.append(params)
        index = len(self.calls) - 1
        return _FakeResponse(self._payloads[index], status_code=self._status_codes[index])

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


def test_fetch_newsapi_articles_chunks_keywords_into_balanced_requests() -> None:
    symbols = [f"SYM{index:03d}" for index in range(TARGET_KEYWORDS_PER_REQUEST + 1)]
    client = _FakeClient([
        {"articles": {"results": []}},
        {"articles": {"results": []}},
    ])

    fetch_newsapi_articles("test-key", symbols, client=client)

    assert len(client.calls) == 2
    assert sum(1 for key, _ in client.calls[0] if key == "keyword") == TARGET_KEYWORDS_PER_REQUEST
    assert sum(1 for key, _ in client.calls[1] if key == "keyword") == 1
    assert ("articlesCount", "50") in client.calls[0]
    assert ("articlesCount", "50") in client.calls[1]


def test_fetch_newsapi_articles_ignores_short_symbols() -> None:
    client = _FakeClient([
        {"articles": {"results": [{"uri": "uri-1", "title": "AAPL rises while AI demand remains strong"}]}}
    ])

    articles = fetch_newsapi_articles("test-key", ["AI", "AAPL"], client=client)

    assert articles == [{"headline": "AAPL rises while AI demand remains strong", "tickers": ["AAPL"]}]


def test_fetch_newsapi_article_records_preserve_metadata() -> None:
    client = _FakeClient([
        {
            "articles": {
                "results": [
                    {
                        "uri": "uri-1",
                        "url": "https://example.test/aapl",
                        "title": "AAPL jumps after earnings beat",
                        "body": "Apple reported stronger iPhone demand.",
                        "dateTime": "2026-04-08T10:15:00Z",
                        "source": {"title": "Reuters"},
                    }
                ]
            }
        }
    ])

    articles = fetch_newsapi_article_records("test-key", ["AAPL"], client=client)

    assert articles == [
        {
            "id": "uri-1",
            "uri": "uri-1",
            "url": "https://example.test/aapl",
            "title": "AAPL jumps after earnings beat",
            "headline": "AAPL jumps after earnings beat",
            "body": "Apple reported stronger iPhone demand.",
            "content": "Apple reported stronger iPhone demand.",
            "published": "2026-04-08T10:15:00Z",
            "date": "2026-04-08T10:15:00Z",
            "source": "Reuters",
            "tickers": ["AAPL"],
            "sentiment": None,
            "social_score": None,
            "concepts": None,
            "categories": None,
            "image": None,
            "newsapi_fetch_mode": "search_articles",
        }
    ]


def test_fetch_newsapi_article_records_filter_ambiguous_tickers_without_market_context() -> None:
    client = _FakeClient([
        {
            "articles": {
                "results": [
                    {
                        "uri": "uri-cat-noise",
                        "title": "7 cat breeds that struggle with being left alone",
                        "dateTime": "2026-04-08T10:15:00Z",
                    },
                    {
                        "uri": "uri-lin-noise",
                        "title": "Ayush Shetty stuns world No.7 Lin Shi Feng",
                        "dateTime": "2026-04-08T10:16:00Z",
                    },
                    {
                        "uri": "uri-cat-stock",
                        "title": "CAT stock rallies after Caterpillar earnings beat",
                        "dateTime": "2026-04-08T10:17:00Z",
                    },
                    {
                        "uri": "uri-lin-stock",
                        "title": "NYSE:LIN rises as Linde lifts guidance",
                        "dateTime": "2026-04-08T10:18:00Z",
                    },
                ]
            }
        }
    ])

    articles = fetch_newsapi_article_records("test-key", ["CAT", "LIN"], client=client)

    assert [article["id"] for article in articles] == ["uri-cat-stock", "uri-lin-stock"]
    assert articles[0]["tickers"] == ["CAT"]
    assert articles[1]["tickers"] == ["LIN"]


def test_fetch_newsapi_article_records_require_market_context_for_untrusted_three_letter_symbols() -> None:
    client = _FakeClient([
        {
            "articles": {
                "results": [
                    {
                        "uri": "uri-aca-noise",
                        "title": "ACA Stress Test: Four Key Takeaways from This Year's Open Enrollment",
                        "dateTime": "2026-04-08T10:15:00Z",
                        "source": {"title": "CNN"},
                    },
                    {
                        "uri": "uri-acu-noise",
                        "title": "RR manager Bhinder breaches ACU protocol, BCCI to examine the matter",
                        "dateTime": "2026-04-08T10:16:00Z",
                        "source": {"title": "ThePrint"},
                    },
                    {
                        "uri": "uri-xom-finance",
                        "title": "XOM rises after crude rebound",
                        "dateTime": "2026-04-08T10:17:00Z",
                        "source": {"title": "Reuters"},
                    },
                    {
                        "uri": "uri-aca-market",
                        "title": "NYSE:ACA gains after outlook update",
                        "dateTime": "2026-04-08T10:18:00Z",
                        "source": {"title": "Reuters"},
                    },
                ]
            }
        }
    ])

    articles = fetch_newsapi_article_records("test-key", ["ACA", "ACU", "XOM"], client=client)

    assert [article["id"] for article in articles] == ["uri-xom-finance", "uri-aca-market"]
    assert articles[0]["tickers"] == ["XOM"]
    assert articles[1]["tickers"] == ["ACA"]


def test_fetch_newsapi_article_records_balance_symbol_coverage_across_chunks() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-meta-1",
                            "title": "META extends gains after model launch",
                            "dateTime": "2026-04-08T10:15:00Z",
                        }
                    ]
                }
            },
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-aapl-1",
                            "title": "AAPL rises as iPhone demand improves",
                            "dateTime": "2026-04-08T10:16:00Z",
                        },
                        {
                            "uri": "uri-msft-1",
                            "title": "MSFT rallies after Azure growth accelerates",
                            "dateTime": "2026-04-08T10:17:00Z",
                        },
                    ]
                }
            },
        ]
    )

    articles = fetch_newsapi_article_records(
        "test-key",
        ["META", "AMZN", "JPM", "JNJ", "XOM", "PG", "AAPL", "MSFT"],
        client=client,
    )

    assert len(client.calls) == 2
    assert [article["id"] for article in articles] == ["uri-meta-1", "uri-aapl-1", "uri-msft-1"]
    assert articles[1]["tickers"] == ["AAPL"]
    assert articles[2]["tickers"] == ["MSFT"]


def test_fetch_newsapi_event_records_preserve_metadata() -> None:
    client = _FakeClient([
        {
            "events": {
                "results": [
                    {
                        "uri": "event-1",
                        "title": {"eng": "AAPL unveils new AI-capable devices"},
                        "summary": {"eng": "Apple event coverage intensifies after product launch."},
                        "eventDate": "2026-04-08",
                        "totalArticleCount": 14,
                    }
                ]
            }
        }
    ])

    events = fetch_newsapi_event_records("test-key", ["AAPL"], client=client)

    assert events == [
        {
            "id": "event-1",
            "uri": "event-1",
            "url": None,
            "title": "AAPL unveils new AI-capable devices",
            "headline": "AAPL unveils new AI-capable devices",
            "body": "Apple event coverage intensifies after product launch.",
            "content": "Apple event coverage intensifies after product launch.",
            "summary": "Apple event coverage intensifies after product launch.",
            "published": "2026-04-08",
            "date": "2026-04-08",
            "source": "Event Registry",
            "tickers": ["AAPL"],
            "kind": "event",
            "event_article_count": 14,
            "sentiment": None,
            "social_score": None,
            "concepts": None,
            "categories": None,
            "location": None,
            "stories": None,
            "newsapi_fetch_mode": "search_events",
        }
    ]


def test_fetch_newsapi_event_records_filter_ambiguous_tickers_without_market_context() -> None:
    client = _FakeClient([
        {
            "events": {
                "results": [
                    {
                        "uri": "event-cat-noise",
                        "title": {"eng": "Cat rescue story trends across Europe"},
                        "summary": {"eng": "Animal shelters report rising adoption interest."},
                        "eventDate": "2026-04-08",
                    },
                    {
                        "uri": "event-lin-stock",
                        "title": {"eng": "LIN stock gains after industrial gas outlook improves"},
                        "summary": {"eng": "Market coverage remains focused on Linde shares."},
                        "eventDate": "2026-04-08",
                    },
                ]
            }
        }
    ])

    events = fetch_newsapi_event_records("test-key", ["CAT", "LIN"], client=client)

    assert [event["id"] for event in events] == ["event-lin-stock"]
    assert events[0]["tickers"] == ["LIN"]


def test_fetch_newsapi_records_include_articles_and_events() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {"uri": "uri-1", "title": "AAPL beats estimates after product refresh"},
                    ]
                }
            },
            {
                "events": {
                    "results": [
                        {
                            "uri": "event-1",
                            "title": {"eng": "AAPL suppliers rally after launch event"},
                            "summary": {"eng": "Event coverage remains heavily focused on AAPL."},
                            "eventDate": "2026-04-08",
                        }
                    ]
                }
            },
        ]
    )

    records = fetch_newsapi_records("test-key", ["AAPL"], client=client)

    assert [record["id"] for record in records] == ["uri-1", "event-1"]
    assert records[0]["tickers"] == ["AAPL"]
    assert records[1]["kind"] == "event"


def test_fetch_newsapi_feed_article_records_uses_minute_stream() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-feed-1",
                            "url": "https://example.test/feed/aapl",
                            "title": "AAPL extends gains in live wire",
                            "body": "Fresh wire mentions AAPL in the title.",
                            "dateTime": "2026-04-08T10:16:00Z",
                            "source": {"title": "Reuters"},
                        }
                    ]
                }
            }
        ]
    )

    records = fetch_newsapi_feed_article_records(
        "test-key",
        ["AAPL"],
        article_feed_after_epoch=datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp(),
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    assert client.urls == ["https://eventregistry.org/api/v1/minuteStreamArticles"]
    assert ("recentActivityArticlesUpdatesAfterTm", "2026-04-08T10:15:00") in client.calls[0]
    assert records[0]["id"] == "uri-feed-1"
    assert records[0]["tickers"] == ["AAPL"]
    assert records[0]["newsapi_fetch_mode"] == "feed_articles"


def test_fetch_newsapi_feed_article_records_filter_named_entity_false_positives() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-feed-adam-noise",
                            "title": "Adam Cole Not Traveling With AEW As Return Timeline Remains Unclear",
                            "dateTime": "2026-04-08T10:16:00Z",
                            "source": {"title": "Ringside News"},
                        },
                        {
                            "uri": "uri-feed-aapl-1",
                            "title": "AAPL extends gains in live wire",
                            "dateTime": "2026-04-08T10:17:00Z",
                            "source": {"title": "Reuters"},
                        },
                        {
                            "uri": "uri-feed-adam-market",
                            "title": "NASDAQ:ADAM rallies after phase 2 data",
                            "dateTime": "2026-04-08T10:18:00Z",
                            "source": {"title": "Reuters"},
                        },
                    ]
                }
            }
        ]
    )

    records = fetch_newsapi_feed_article_records(
        "test-key",
        ["ADAM", "AAPL"],
        article_feed_after_epoch=datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp(),
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    assert [record["id"] for record in records] == ["uri-feed-aapl-1", "uri-feed-adam-market"]
    assert records[0]["tickers"] == ["AAPL"]
    assert records[1]["tickers"] == ["ADAM"]


def test_fetch_newsapi_feed_article_records_balance_symbol_coverage_across_chunks() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-feed-meta-1",
                            "title": "META surges in fresh stream update",
                            "dateTime": "2026-04-08T10:16:00Z",
                        }
                    ]
                }
            },
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-feed-aapl-1",
                            "title": "AAPL follows through in live wire",
                            "dateTime": "2026-04-08T10:17:00Z",
                        }
                    ]
                }
            },
        ]
    )

    records = fetch_newsapi_feed_article_records(
        "test-key",
        ["META", "AMZN", "JPM", "JNJ", "XOM", "PG", "AAPL", "MSFT"],
        article_feed_after_epoch=datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp(),
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    assert len(client.calls) == 2
    assert ("recentActivityArticlesMaxArticleCount", "50") in client.calls[0]
    assert ("recentActivityArticlesMaxArticleCount", "50") in client.calls[1]
    assert [record["id"] for record in records] == ["uri-feed-meta-1", "uri-feed-aapl-1"]


def test_fetch_newsapi_records_prefers_feed_for_recent_cursor() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-feed-1",
                            "title": "AAPL breaks higher in fresh update",
                            "dateTime": "2026-04-08T10:16:00Z",
                        }
                    ]
                }
            },
            {"events": {"results": []}},
        ]
    )

    records = fetch_newsapi_records(
        "test-key",
        ["AAPL"],
        prefer_article_feed=True,
        article_feed_after_epoch=datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp(),
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    assert client.urls[0] == "https://eventregistry.org/api/v1/minuteStreamArticles"
    assert client.urls[1] == "https://eventregistry.org/api/v1/event/getEvents"
    assert records[0]["id"] == "uri-feed-1"


def test_fetch_newsapi_feed_article_records_uses_uri_cursor_when_available() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-feed-2",
                            "title": "AAPL extends follow-through in stream update",
                            "dateTime": "2026-04-08T10:17:00Z",
                        }
                    ]
                }
            }
        ]
    )

    records = fetch_newsapi_feed_article_records(
        "test-key",
        ["AAPL"],
        article_feed_after_epoch=datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp(),
        article_feed_after_uri="uri-feed-1",
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    assert ("recentActivityArticlesNewsUpdatesAfterUri", "uri-feed-1") in client.calls[0]
    assert all(key != "recentActivityArticlesUpdatesAfterTm" for key, _ in client.calls[0])
    assert extract_newsapi_feed_article_cursor_uri(records) == "uri-feed-2"


def test_fetch_newsapi_feed_article_probe_reports_raw_and_matched_counts() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-raw-1",
                            "title": "Macro wire without tracked symbol in title",
                            "dateTime": "2026-04-08T10:16:00Z",
                        },
                        {
                            "uri": "uri-raw-2",
                            "title": "AAPL spikes after fresh stream mention",
                            "dateTime": "2026-04-08T10:17:00Z",
                        },
                    ]
                }
            }
        ]
    )

    probe = fetch_newsapi_feed_article_probe(
        "test-key",
        ["AAPL"],
        article_feed_after_epoch=datetime(2026, 4, 8, 10, 15, tzinfo=UTC).timestamp(),
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    diagnostics = probe["diagnostics"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["cursor_mode"] == "timestamp"
    assert diagnostics[0]["raw_result_count"] == 2
    assert diagnostics[0]["matched_result_count"] == 1
    assert diagnostics[0]["accepted_record_count"] == 1
    assert diagnostics[0]["sample_raw_uris"] == ["uri-raw-1", "uri-raw-2"]
    assert diagnostics[0]["sample_matched_uris"] == ["uri-raw-2"]
    assert [record["id"] for record in probe["records"]] == ["uri-raw-2"]


def test_fetch_newsapi_records_falls_back_to_search_for_old_cursor() -> None:
    client = _FakeClient(
        [
            {
                "articles": {
                    "results": [
                        {
                            "uri": "uri-search-1",
                            "title": "AAPL remains in focus after earlier move",
                            "dateTime": "2026-04-08T10:16:00Z",
                        }
                    ]
                }
            },
            {"events": {"results": []}},
        ]
    )

    records = fetch_newsapi_records(
        "test-key",
        ["AAPL"],
        prefer_article_feed=True,
        article_feed_after_epoch=datetime(2026, 4, 8, 1, 0, tzinfo=UTC).timestamp(),
        client=client,
        current_time=datetime(2026, 4, 8, 10, 20, tzinfo=UTC),
    )

    assert client.urls[0] == "https://eventregistry.org/api/v1/article/getArticles"
    assert client.urls[1] == "https://eventregistry.org/api/v1/event/getEvents"
    assert records[0]["id"] == "uri-search-1"


def test_fetch_newsapi_article_records_raises_quota_exhausted_error() -> None:
    client = _FakeClient(
        ["You have used all available tokens for unsubscribed users. In order to continue using Event Registry please subscribe to a paid plan."],
        status_codes=[403],
    )

    with __import__("pytest").raises(NewsApiAiProviderError) as exc_info:
        fetch_newsapi_article_records("test-key", ["AAPL"], client=client)

    assert exc_info.value.provider_status == "quota_exhausted"
    assert exc_info.value.error_code == "quota_exhausted"
