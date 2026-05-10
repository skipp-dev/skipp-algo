from __future__ import annotations

import io
import json
import urllib.error
from contextlib import contextmanager
from unittest.mock import patch

import terminal_tradingview_news as ttvn
from terminal_tradingview_news import TVHeadline, _health, fetch_tv_headlines, health_status


def _reset_health_state() -> None:
    with _health._lock:
        _health.consecutive_failures = 0
        _health.last_success_ts = 0.0
        _health.last_failure_ts = 0.0
        _health.last_error = ""
        _health.total_requests = 0
        _health.total_failures = 0


def test_tvheadline_recency_unknown_when_published_missing() -> None:
    h = TVHeadline(
        id="h1",
        title="Headline",
        provider="tradingview",
        source="TradingView",
        published=0.0,
        urgency=2,
        tickers=["AAPL"],
        story_url="https://example.com/story",
    )

    feed = h.to_feed_dict()
    assert feed["recency_bucket"] == "UNKNOWN"
    assert feed["age_minutes"] is None
    assert feed["is_actionable"] is False


def test_health_failure_counter_increments_and_success_resets_streak() -> None:
    _reset_health_state()

    _health.record_failure("timeout")
    _health.record_failure("timeout")

    degraded = health_status()
    assert degraded["status"] == "degraded"
    assert degraded["consecutive_failures"] == 2
    assert degraded["total_requests"] == 2
    assert degraded["total_failures"] == 2

    _health.record_success()
    healthy = health_status()
    assert healthy["status"] == "healthy"
    assert healthy["consecutive_failures"] == 0
    assert healthy["total_requests"] == 3
    assert healthy["total_failures"] == 2

    _reset_health_state()


def test_health_three_consecutive_failures_mark_down_and_unhealthy() -> None:
    _reset_health_state()

    _health.record_failure("timeout")
    _health.record_failure("http 503")
    _health.record_failure("url error")

    st = health_status()
    assert st["consecutive_failures"] == 3
    assert st["status"] == "down"
    assert _health.is_healthy is False

    _reset_health_state()


# ── Single-source health accounting (audit 2026-05-10) ───────────


def _clear_tv_cache() -> None:
    with ttvn._cache_lock:
        ttvn._cache.clear()


@contextmanager
def _mock_urlopen_success(payload: dict | None = None):
    if payload is None:
        payload = {"items": []}
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return body

    with patch.object(ttvn, "urlopen", return_value=_Resp()):
        yield


@contextmanager
def _mock_urlopen_http_error(code: int = 500):
    def _raise(*_a, **_kw):
        raise urllib.error.HTTPError(
            url="http://x", code=code, msg="boom",
            hdrs=None, fp=io.BytesIO(b""),
        )

    with patch.object(ttvn, "urlopen", side_effect=_raise):
        yield


def test_one_successful_fetch_increments_total_requests_by_one() -> None:
    _reset_health_state()
    _clear_tv_cache()

    before = health_status()
    with _mock_urlopen_success({"items": []}):
        fetch_tv_headlines("AAPL")
    after = health_status()

    assert after["total_requests"] - before["total_requests"] == 1
    assert after["total_failures"] - before["total_failures"] == 0
    assert after["consecutive_failures"] == 0

    _reset_health_state()
    _clear_tv_cache()


def test_one_failed_fetch_increments_failures_by_one() -> None:
    _reset_health_state()
    _clear_tv_cache()

    before = health_status()
    with _mock_urlopen_http_error(503):
        result = fetch_tv_headlines("AAPL")
    after = health_status()

    assert result == []
    assert after["total_requests"] - before["total_requests"] == 1
    assert after["total_failures"] - before["total_failures"] == 1
    assert after["consecutive_failures"] == 1

    _reset_health_state()
    _clear_tv_cache()


def test_consecutive_failures_resets_on_successful_fetch() -> None:
    _reset_health_state()
    _clear_tv_cache()

    with _mock_urlopen_http_error(500):
        fetch_tv_headlines("AAPL")
    assert health_status()["consecutive_failures"] == 1

    _clear_tv_cache()  # bypass cached empty list so a real fetch happens
    with _mock_urlopen_success({"items": []}):
        fetch_tv_headlines("AAPL")

    final = health_status()
    assert final["consecutive_failures"] == 0
    assert final["total_requests"] == 2
    assert final["total_failures"] == 1

    _reset_health_state()
    _clear_tv_cache()
