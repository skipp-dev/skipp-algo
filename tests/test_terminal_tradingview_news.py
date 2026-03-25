from __future__ import annotations

from terminal_tradingview_news import TVHeadline, _health, health_status


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
