from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from terminal_news_routing import NewsSourceUnavailableError, poll_news_sources


def test_producer_primary_success_does_not_call_direct() -> None:
    producer = MagicMock()
    producer.fetch.return_value = ([], "producer-cursor")
    direct = MagicMock()

    result = poll_news_sources(
        producer_feed=producer,
        direct_poll=direct,
        direct_available=True,
        direct_primary=False,
    )

    assert result.source == "producer"
    assert result.items == []
    direct.assert_not_called()


def test_producer_failure_falls_back_to_direct() -> None:
    producer = MagicMock()
    producer.fetch.side_effect = RuntimeError("secret must not escape")
    direct = MagicMock(return_value=(["item"], {"fmp": "cursor"}, {"fmp": 1}))

    result = poll_news_sources(
        producer_feed=producer,
        direct_poll=direct,
        direct_available=True,
        direct_primary=False,
    )

    assert result.source == "direct"
    assert result.fallback_from == "producer"
    assert result.items == ["item"]


def test_direct_primary_success_does_not_call_producer() -> None:
    producer = MagicMock()
    direct = MagicMock(return_value=([], {}, {}))

    result = poll_news_sources(
        producer_feed=producer,
        direct_poll=direct,
        direct_available=True,
        direct_primary=True,
    )

    assert result.source == "direct"
    producer.fetch.assert_not_called()


def test_direct_failure_falls_back_to_producer() -> None:
    producer = MagicMock()
    producer.fetch.return_value = (["item"], "producer-cursor")
    direct = MagicMock(side_effect=OSError("credential material"))

    result = poll_news_sources(
        producer_feed=producer,
        direct_poll=direct,
        direct_available=True,
        direct_primary=True,
    )

    assert result.source == "producer"
    assert result.fallback_from == "direct"


def test_all_failures_are_reported_without_exception_text() -> None:
    producer = MagicMock()
    producer.fetch.side_effect = RuntimeError("producer-secret")
    direct = MagicMock(side_effect=OSError("direct-secret"))

    with pytest.raises(NewsSourceUnavailableError) as caught:
        poll_news_sources(
            producer_feed=producer,
            direct_poll=direct,
            direct_available=True,
            direct_primary=False,
        )

    message = str(caught.value)
    assert "RuntimeError" in message
    assert "OSError" in message
    assert "producer-secret" not in message
    assert "direct-secret" not in message
