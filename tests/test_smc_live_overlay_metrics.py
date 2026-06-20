"""Unit tests for services.live_overlay_daemon.metrics.

Covers:
- Prometheus text formatting basics
- market-aware health status gauges
- non-finite sanitization in metrics rendering
- non-finite rejection in observability primitives
"""
from __future__ import annotations

import math

import pytest


def _patch_common(monkeypatch: pytest.MonkeyPatch, *, feed_ready: bool, market_open: bool, bar_count: int, overlay_symbols: int, overlay_age: float, workers: dict[str, bool] | None = None) -> None:
    import services.live_overlay_daemon.cache as cache
    import services.live_overlay_daemon.config as config
    import services.live_overlay_daemon.feed as feed
    import services.live_overlay_daemon.metrics as metrics_mod

    monkeypatch.setattr(feed, "is_ready", lambda: feed_ready)
    monkeypatch.setattr(feed, "last_bar_age_secs", lambda: 5.0)
    monkeypatch.setattr(feed, "worker_liveness", lambda: workers or {
        "live_feed": True,
        "overlay_refresh": True,
        "flow_refresh": True,
    })
    monkeypatch.setattr(feed, "metrics_snapshot", lambda: {
        "reconnect_attempts": 2,
        "bento_errors": 1,
        "unexpected_errors": 0,
        "circuit_breakers": 0,
        "partial_restarts": 0,
    })

    monkeypatch.setattr(cache, "overlay_symbol_count", lambda: overlay_symbols)
    monkeypatch.setattr(cache, "bar_symbol_count", lambda: max(overlay_symbols, 1))
    monkeypatch.setattr(cache, "total_bar_count", lambda: bar_count)
    monkeypatch.setattr(cache, "overlay_age_secs", lambda: overlay_age)

    monkeypatch.setattr(config, "max_stale_secs", lambda: 300)
    monkeypatch.setattr(metrics_mod, "is_us_regular_session_open", lambda: market_open)


def test_render_metrics_prometheus_format_and_trailing_newline(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()
        obs._counters["live_overlay.health_requests.total"] = 3.0

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert body.endswith("\n")
    assert "# TYPE live_overlay_health_requests_total counter" in body
    assert "live_overlay_health_requests_total 3.0" in body
    assert "# TYPE live_overlay_uptime_seconds gauge" in body
    assert "# TYPE live_overlay_max_stale_seconds gauge" in body
    assert "live_overlay_max_stale_seconds 300" in body


def test_render_metrics_health_status_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=3,
        overlay_age=30.0,
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_overlay_fresh 1" in body
    assert "live_overlay_health_status_ok 1" in body
    assert "live_overlay_health_status_starting 0" in body
    assert "live_overlay_health_status_idle_market_closed 0" in body


def test_render_metrics_health_status_idle_market_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=False,
        market_open=False,
        bar_count=0,
        overlay_symbols=0,
        overlay_age=float("inf"),
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_health_status_ok 0" in body
    assert "live_overlay_health_status_starting 0" in body
    assert "live_overlay_health_status_idle_market_closed 1" in body


def test_render_metrics_health_status_starting(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=False,
        market_open=True,
        bar_count=0,
        overlay_symbols=0,
        overlay_age=float("inf"),
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "live_overlay_health_status_ok 0" in body
    assert "live_overlay_health_status_starting 1" in body
    assert "live_overlay_health_status_idle_market_closed 0" in body


def test_render_metrics_sanitizes_non_finite_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod
    import services.live_overlay_daemon.observability as obs

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )

    with obs._counter_lock:
        obs._counters.clear()
        obs._counters["live_overlay.bad_inf"] = float("inf")
        obs._counters["live_overlay.bad_nan"] = float("nan")

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_bad_inf nan" in body
    assert "live_overlay_bad_nan nan" in body


def test_observability_rejects_non_finite_values() -> None:
    import services.live_overlay_daemon.observability as obs

    with pytest.raises(ValueError):
        obs.metric_counter("live_overlay.test_counter", float("inf"))
    with pytest.raises(ValueError):
        obs.metric_gauge("live_overlay.test_gauge", float("nan"))
    with pytest.raises(ValueError):
        obs.metric_timing_ms("live_overlay.test_timing", float("-inf"))


def test_observability_counter_accepts_finite_values() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        obs._counters.pop("live_overlay.test_counter_ok", None)

    total = obs.metric_counter("live_overlay.test_counter_ok", 1.5)
    assert math.isfinite(total)
    assert total == 1.5


def test_observability_histogram_ms_emits_bucket_count_and_sum() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        obs._counters.pop("live_overlay.test_latency.count", None)
        obs._counters.pop("live_overlay.test_latency.sum_ms", None)
        obs._counters.pop("live_overlay.test_latency.bucket_le_10", None)
        obs._counters.pop("live_overlay.test_latency.bucket_le_50", None)
        obs._counters.pop("live_overlay.test_latency.bucket_le_inf", None)

    obs.metric_histogram_ms("live_overlay.test_latency", 42.0, buckets_ms=(10.0, 50.0))

    with obs._counter_lock:
        assert obs._counters["live_overlay.test_latency.count"] == 1.0
        assert obs._counters["live_overlay.test_latency.sum_ms"] == 42.0
        assert "live_overlay.test_latency.bucket_le_10" not in obs._counters
        assert obs._counters["live_overlay.test_latency.bucket_le_50"] == 1.0
        assert obs._counters["live_overlay.test_latency.bucket_le_inf"] == 1.0


def test_observability_histogram_bucket_suffix_avoids_scientific_notation() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        obs._counters.pop("live_overlay.test_latency_scientific.bucket_le_1000000", None)
        obs._counters.pop("live_overlay.test_latency_scientific.bucket_le_inf", None)

    obs.metric_histogram_ms(
        "live_overlay.test_latency_scientific",
        1000.0,
        buckets_ms=(1_000_000.0,),
    )

    with obs._counter_lock:
        assert obs._counters["live_overlay.test_latency_scientific.bucket_le_1000000"] == 1.0
        assert obs._counters["live_overlay.test_latency_scientific.bucket_le_inf"] == 1.0
