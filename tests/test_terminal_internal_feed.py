from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from open_prep import realtime_signals as rs
from terminal_background_poller import BackgroundPoller
from terminal_internal_feed import ProducerFeedClient, ProducerFeedError


def _candidate(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "ticker": "AAPL",
        "headline": "Apple raises guidance after strong demand",
        "snippet": "Revenue is expected to exceed prior guidance.",
        "news_provider": "benzinga_rest",
        "news_source": "Benzinga",
        "news_url": "https://example.test/apple-guidance",
        "category": "guidance",
        "impact": 0.9,
        "clarity": 0.8,
        "novelty_cluster_count": 1,
        "polarity": 1.0,
        "news_score": 0.91,
        "published_ts": time.time() - 30.0,
        "updated_ts": time.time() - 10.0,
        "warn_flags": [],
    }
    base.update(overrides)
    return base


def _payload(items: list[dict[str, object]] | None = None) -> dict[str, object]:
    values = items if items is not None else [_candidate()]
    return {
        "schema_version": 1,
        "generated_ts": time.time(),
        "source": "smc-signals-producer",
        "status": "ready",
        "item_count": len(values),
        "items": values,
    }


def test_client_reads_private_snapshot_and_emits_only_changes() -> None:
    original_candidate = _candidate()
    state = {"payload": _payload([original_candidate])}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer shared-secret"
        return httpx.Response(200, json=state["payload"])

    client = ProducerFeedClient(
        "http://smc-signals-producer.railway.internal:8080",
        "shared-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    first, cursor = client.fetch()
    second, _ = client.fetch()
    assert cursor
    assert len(first) == 1
    assert first[0].ticker == "AAPL"
    assert first[0].provider == "benzinga_rest"
    assert first[0].news_score == 0.91
    assert first[0].sentiment_label == "bullish"
    assert second == []

    updated_candidate = dict(original_candidate)
    updated_candidate["news_score"] = 0.95
    state["payload"] = _payload([updated_candidate])
    changed, _ = client.fetch()
    assert len(changed) == 1
    assert changed[0].item_id == first[0].item_id
    assert changed[0].news_score == 0.95


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/news-feed.json",
        "http://smc-signals-producer.railway.internal.attacker.test/news-feed",
        "http://user:secret@localhost/news-feed",
        "http://localhost/other",
    ],
)
def test_client_rejects_non_private_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError):
        ProducerFeedClient(url, "token")


def test_client_rejects_stale_snapshot_without_leaking_token() -> None:
    payload = _payload()
    payload["generated_ts"] = time.time() - 601.0
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    client = ProducerFeedClient(
        "http://127.0.0.1:8080/news-feed",
        "never-log-this-token",
        max_age_s=300.0,
        client=httpx.Client(transport=transport),
    )

    with pytest.raises(ProducerFeedError, match="stale") as caught:
        client.fetch()
    assert "never-log-this-token" not in str(caught.value)


def test_background_poller_prefers_producer_over_direct_adapters() -> None:
    producer = MagicMock()
    producer.fetch.return_value = ([], str(time.time()))
    cfg = SimpleNamespace(
        poll_interval_s=0.02,
        page_size=10,
        channels="",
        topics="",
        producer_feed_url="",
        producer_feed_token="",
    )
    poller = BackgroundPoller(
        cfg,
        MagicMock(),
        MagicMock(),
        MagicMock(),
        producer_feed_client=producer,
    )

    with patch("terminal_poller.poll_and_classify_live_bus") as direct_poll:
        poller.start()
        time.sleep(0.08)
        poller.stop_and_join(timeout=1.0)

    assert producer.fetch.called
    direct_poll.assert_not_called()
    assert poller.snapshot()["provider_cursors"].get("producer")


def test_background_poller_allows_direct_fallback_with_partial_producer_config() -> None:
    cfg = SimpleNamespace(
        producer_feed_url="http://producer.railway.internal:8080/news-feed.json",
        producer_feed_token="",
    )

    poller = BackgroundPoller(cfg, MagicMock(), MagicMock(), MagicMock())

    assert poller is not None


def test_producer_endpoint_is_fail_closed_and_serves_ready_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIGNALS_INTERNAL_TOKEN", "shared-secret")
    poller = rs.AsyncNewsstackPoller()
    with poller._lock:
        poller._feed_items = [_candidate()]
        poller.last_success_at = time.time()
    engine = SimpleNamespace(_async_newsstack=poller)
    server = rs._start_telemetry_server(
        rs.ScoreTelemetry(), port=0, host="127.0.0.1", engine=engine
    )
    assert server is not None
    endpoint = f"http://127.0.0.1:{server.server_port}/news-feed.json"

    try:
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(endpoint, timeout=2.0)
        assert missing.value.code == 401

        request = urllib.request.Request(
            endpoint,
            headers={"Authorization": "Bearer shared-secret"},
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            payload = json.load(response)
        assert payload["schema_version"] == 1
        assert payload["status"] == "ready"
        assert payload["item_count"] == 1
        assert payload["items"][0]["ticker"] == "AAPL"

        monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN")
        with pytest.raises(urllib.error.HTTPError) as unconfigured:
            urllib.request.urlopen(request, timeout=2.0)
        assert unconfigured.value.code == 503
    finally:
        server.shutdown()
        server.server_close()
