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
    monkeypatch.setattr(feed, "backpressure_snapshot", lambda: {
        "ingest_queue_depth": 0.0,
        "ingest_queue_depth_max": 3.0,
        "ingest_queue_dropped_total": 1.0,
        "ingest_queue_lag_ms_last": 7.5,
        "ingest_queue_lag_ms_max": 35.0,
    })
    monkeypatch.setattr(metrics_mod, "_provider_health_snapshot", lambda: {
        "news_snapshot_loaded": 1.0,
        "news_snapshot_age_seconds": 42.0,
        "news_providers_total": 2.0,
        "news_providers_ok_total": 1.0,
        "news_providers_degraded_total": 1.0,
        "news_providers_unknown_total": 0.0,
        "news_health_ok": 0.0,
        "news_health_degraded": 1.0,
        "news_health_unknown": 0.0,
        "news_provider_ok": {"newsapi_ai": 1.0, "tv": 0.0},
        "news_provider_degraded": {"newsapi_ai": 0.0, "tv": 1.0},
        "news_provider_state_code": {"newsapi_ai": 2.0, "tv": 1.0},
    })

    monkeypatch.setattr(cache, "overlay_symbol_count", lambda: overlay_symbols)
    monkeypatch.setattr(cache, "bar_symbol_count", lambda: max(overlay_symbols, 1))
    monkeypatch.setattr(cache, "total_bar_count", lambda: bar_count)
    monkeypatch.setattr(cache, "overlay_age_secs", lambda: overlay_age)

    monkeypatch.setattr(config, "max_stale_secs", lambda: 300)
    monkeypatch.setattr(metrics_mod, "is_us_regular_session_open", lambda: market_open)
    monkeypatch.setattr(metrics_mod, "is_europe_regular_session_open", lambda: False)
    monkeypatch.setattr(metrics_mod, "is_asia_regular_session_open", lambda: False)


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
    assert "live_overlay_feed_ingest_queue_depth 0.0" in body
    assert "live_overlay_feed_ingest_queue_lag_ms_max 35.0" in body
    assert "live_overlay_provider_news_snapshot_loaded 1.0" in body
    assert "live_overlay_provider_news_providers_degraded_total 1.0" in body
    assert "live_overlay_provider_news_health_degraded 1.0" in body
    assert "live_overlay_provider_news_newsapi_ai_ok 1.0" in body
    assert "live_overlay_provider_news_tv_degraded 1.0" in body
    assert "live_overlay_provider_news_tv_state_code 1.0" in body


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
    assert "live_overlay_market_us_open 1" in body
    assert "live_overlay_market_europe_open 0" in body
    assert "live_overlay_market_asia_open 0" in body


def test_render_metrics_region_open_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=False,
        bar_count=10,
        overlay_symbols=3,
        overlay_age=30.0,
    )
    monkeypatch.setattr(metrics_mod, "is_europe_regular_session_open", lambda: True)
    monkeypatch.setattr(metrics_mod, "is_asia_regular_session_open", lambda: False)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_market_us_open 0" in body
    assert "live_overlay_market_europe_open 1" in body
    assert "live_overlay_market_asia_open 0" in body


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


def test_render_metrics_emits_latency_quantile_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
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
        obs._counters["live_overlay.smc_live_latency.count"] = 100.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_100"] = 90.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_250"] = 98.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_500"] = 100.0
        obs._counters["live_overlay.smc_live_latency.bucket_le_inf"] = 100.0

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_smc_live_latency_p95_ms" in body
    assert "live_overlay_smc_live_latency_p99_ms" in body


def test_render_metrics_emits_hotspot_gauges(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.request_hotspots,
        "snapshot",
        lambda top_n=5: {
            "symbol_count": 3,
            "tf_count": 2,
            "top_symbols": [("NVDA", 12), ("AAPL", 7)],
            "top_tfs": [("5m", 15), ("1H", 4)],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_hotspot_symbols_tracked 3.0" in body
    assert "live_overlay_hotspot_timeframes_tracked 2.0" in body
    assert "live_overlay_hotspot_symbol_nvda_requests_total 12.0" in body
    assert "live_overlay_hotspot_symbol_aapl_requests_total 7.0" in body
    assert "live_overlay_hotspot_tf__5m_requests_total 15.0" in body
    assert "live_overlay_hotspot_tf__1h_requests_total 4.0" in body


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


def test_observability_histogram_respects_explicit_empty_buckets() -> None:
    import services.live_overlay_daemon.observability as obs

    with obs._counter_lock:
        for key in list(obs._counters):
            if key.startswith("live_overlay.test_latency_empty"):
                obs._counters.pop(key, None)

    obs.metric_histogram_ms("live_overlay.test_latency_empty", 42.0, buckets_ms=())

    with obs._counter_lock:
        assert obs._counters["live_overlay.test_latency_empty.count"] == 1.0
        assert obs._counters["live_overlay.test_latency_empty.sum_ms"] == 42.0
        assert obs._counters["live_overlay.test_latency_empty.bucket_le_inf"] == 1.0
        assert "live_overlay.test_latency_empty.bucket_le_10" not in obs._counters
        assert "live_overlay.test_latency_empty.bucket_le_50" not in obs._counters


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


def test_render_metrics_includes_uptimerobot_bridge_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_000.0,
            "counts": {"total": 4, "up": 4, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": 101.5,
            "monitors": [
                {
                    "id": "803343156",
                    "up": 1,
                    "status_code": 2,
                    "response_time_ms": 98.0,
                }
            ],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_uptimerobot_bridge_enabled 1" in body
    assert "live_overlay_uptimerobot_scrape_success 1" in body
    assert "live_overlay_uptimerobot_monitors_total_total 4.0" in body
    assert "live_overlay_uptimerobot_monitors_up_total 4.0" in body
    assert "live_overlay_uptimerobot_monitors_response_time_ms_avg 101.5" in body
    assert "live_overlay_uptimerobot_monitor__803343156_up 1.0" in body
    assert "live_overlay_uptimerobot_monitor__803343156_status_code 2.0" in body
    assert "live_overlay_uptimerobot_monitor__803343156_response_time_ms 98.0" in body


def test_render_metrics_handles_uptimerobot_bridge_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.uptimerobot_bridge,
        "snapshot",
        lambda: {
            "enabled": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_uptimerobot_bridge_enabled 0" in body
    assert "live_overlay_uptimerobot_scrape_success 0" in body
    assert "live_overlay_uptimerobot_monitors_total_total 0.0" in body


def test_render_metrics_includes_github_workflow_bridge_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 1,
            "ok": 1,
            "fetched_at_unix": 1_700_000_100.0,
            "counts": {
                "seen": 4,
                "success": 2,
                "failed": 1,
                "in_progress": 1,
                "queued": 0,
            },
            "latest_run_age_seconds": 45.5,
            "latest_run_duration_seconds": 120.0,
            "workflows": [
                {
                    "id": "129428056",
                    "phase_code": 3,
                    "latest_success": 1,
                    "latest_age_seconds": 45.5,
                    "latest_duration_seconds": 120.0,
                }
            ],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_github_workflow_bridge_enabled 1" in body
    assert "live_overlay_github_workflow_scrape_success 1" in body
    assert "live_overlay_github_workflow_runs_seen_total 4.0" in body
    assert "live_overlay_github_workflow_runs_success_total 2.0" in body
    assert "live_overlay_github_workflow_runs_failed_total 1.0" in body
    assert "live_overlay_github_workflow_latest_run_age_seconds 45.5" in body
    assert "live_overlay_github_workflow_latest_run_duration_seconds 120.0" in body
    assert "live_overlay_github_workflow__129428056_phase_code 3.0" in body
    assert "live_overlay_github_workflow__129428056_latest_success 1.0" in body
    assert "live_overlay_github_workflow__129428056_latest_age_seconds 45.5" in body
    assert "live_overlay_github_workflow__129428056_latest_duration_seconds 120.0" in body


def test_render_metrics_handles_github_workflow_bridge_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(
        metrics_mod.github_workflow_bridge,
        "snapshot",
        lambda: {
            "enabled": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "counts": {
                "seen": 0,
                "success": 0,
                "failed": 0,
                "in_progress": 0,
                "queued": 0,
            },
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_github_workflow_bridge_enabled 0" in body
    assert "live_overlay_github_workflow_scrape_success 0" in body
    assert "live_overlay_github_workflow_runs_seen_total 0.0" in body


def test_sanitize_name_rejects_invalid_prometheus_characters() -> None:
    """_sanitize_name must replace characters outside the strict [a-z0-9_] allow-list with underscores."""
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._sanitize_name("AAPL") == "aapl"
    assert metrics_mod._sanitize_name("AAPL/USD") == "aapl_usd"
    assert metrics_mod._sanitize_name("SPX:500") == "spx_500"
    assert metrics_mod._sanitize_name(" bitcoin ") == "bitcoin"
    assert metrics_mod._sanitize_name("tf-1m") == "tf_1m"
    assert metrics_mod._sanitize_name("tf 1m") == "tf_1m"
    assert metrics_mod._sanitize_name("provider@news") == "provider_news"
    assert metrics_mod._sanitize_name("123provider") == "_123provider"
    assert metrics_mod._sanitize_name("") == "_"
