"""Unit tests for services.live_overlay_daemon.metrics.

Covers:
- Prometheus text formatting basics
- market-aware health status gauges
- non-finite sanitization in metrics rendering
- non-finite rejection in observability primitives
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_compute_news_loader_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid cross-test bleed from compute._load_news_snapshot() TTL globals."""
    import services.live_overlay_daemon.compute as compute_mod

    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})


def test_sanitize_name_rejects_invalid_prometheus_characters() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._sanitize_name("  AAPL/US @NASDAQ  ") == "aapl_us_nasdaq"
    assert metrics_mod._sanitize_name("BTC-USD.PERP") == "btc_usd_perp"
    assert metrics_mod._sanitize_name("__$$$__") == "unknown"


def test_sanitize_name_collapses_runs_of_separators() -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    assert metrics_mod._sanitize_name("A..B---C") == "a_b_c"


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    *,
    feed_ready: bool,
    market_open: bool,
    bar_count: int,
    overlay_symbols: int,
    overlay_age: float,
    workers: dict[str, bool] | None = None,
) -> None:
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
        "news_providers_total": 3.0,
        "news_providers_ok_total": 1.0,
        "news_providers_degraded_total": 1.0,
        "news_providers_unknown_total": 0.0,
        "news_providers_disabled_total": 1.0,
        "news_providers_consumed_total": 2.0,
        "news_health_ok": 0.0,
        "news_health_degraded": 1.0,
        "news_health_unknown": 0.0,
        "news_provider_ok": {"newsapi_ai": 1.0, "tv": 0.0, "benzinga": 0.0},
        "news_provider_degraded": {"newsapi_ai": 0.0, "tv": 1.0, "benzinga": 0.0},
        "news_provider_state_code": {"newsapi_ai": 2.0, "tv": 1.0, "benzinga": 3.0},
        "news_provider_consumed": {"newsapi_ai": 1.0, "tv": 1.0, "benzinga": 0.0},
        "news_provider_info": [
            {"provider": "newsapi_ai", "state": "ok", "reason": "OK", "consumed": "true"},
            {"provider": "tv", "state": "degraded", "reason": "API key missing", "consumed": "true"},
            {"provider": "benzinga", "state": "disabled", "reason": "Provider disabled (not ingested)", "consumed": "false"},
        ],
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
    assert body.count("# TYPE live_overlay_max_stale_seconds gauge") == 1
    assert body.count("live_overlay_max_stale_seconds 300") == 1
    assert "live_overlay_feed_ingest_queue_depth 0.0" in body
    assert "# TYPE live_overlay_feed_ingest_queue_dropped_total counter" in body
    assert "live_overlay_feed_ingest_queue_dropped_total 1.0" in body
    assert "live_overlay_feed_ingest_queue_lag_ms_max 35.0" in body
    assert "live_overlay_provider_news_snapshot_loaded 1.0" in body
    assert "live_overlay_provider_news_providers_degraded_total 1.0" in body
    assert "live_overlay_provider_news_health_degraded 1.0" in body
    assert "live_overlay_provider_news_newsapi_ai_ok 1.0" in body
    assert "live_overlay_provider_news_tv_degraded 1.0" in body
    assert "live_overlay_provider_news_tv_state_code 1.0" in body
    assert "live_overlay_provider_news_providers_disabled_total 1.0" in body
    assert "live_overlay_provider_news_providers_consumed_total 2.0" in body
    assert "live_overlay_provider_news_benzinga_state_code 3.0" in body
    assert "live_overlay_provider_news_benzinga_consumed 0.0" in body
    assert "live_overlay_provider_news_newsapi_ai_consumed 1.0" in body
    assert (
        'live_overlay_provider_news_info{provider="benzinga",state="disabled",'
        'reason="Provider disabled (not ingested)",consumed="false"} 1' in body
    )
    assert (
        'live_overlay_provider_news_info{provider="tv",state="degraded",'
        'reason="API key missing",consumed="true"} 1' in body
    )


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
    assert "live_overlay_hotspot_tf_5m_requests_total 15.0" in body
    assert "live_overlay_hotspot_tf_1h_requests_total 4.0" in body


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
    assert "live_overlay_uptimerobot_monitors_total 4.0" in body
    assert "live_overlay_uptimerobot_monitors_up_total 4.0" in body
    assert "live_overlay_uptimerobot_monitors_response_time_ms_avg 101.5" in body
    assert "live_overlay_uptimerobot_monitor_803343156_up 1.0" in body
    assert "live_overlay_uptimerobot_monitor_803343156_status_code 2.0" in body
    assert "live_overlay_uptimerobot_monitor_803343156_response_time_ms 98.0" in body


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
    assert "live_overlay_uptimerobot_monitors_total 0.0" in body


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
                    "name": "CI",
                    "event": "schedule",
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
    assert "# TYPE live_overlay_github_workflow_runs_seen_total gauge" in body
    assert "live_overlay_github_workflow_runs_seen_total 4.0" in body
    assert "live_overlay_github_workflow_runs_success_total 2.0" in body
    assert "live_overlay_github_workflow_runs_failed_total 1.0" in body
    assert "live_overlay_github_workflow_latest_run_age_seconds 45.5" in body
    assert "live_overlay_github_workflow_latest_run_duration_seconds 120.0" in body
    # Per-workflow series are labelled (id + name + event) so Grafana can name
    # each flow and group a shared status timeline / detail table.
    workflow_labels = 'workflow_id="129428056",workflow="CI",event="schedule"'
    assert f"live_overlay_github_workflow_phase_code{{{workflow_labels}}} 3.0" in body
    assert f"live_overlay_github_workflow_latest_success{{{workflow_labels}}} 1.0" in body
    assert f"live_overlay_github_workflow_latest_age_seconds{{{workflow_labels}}} 45.5" in body
    assert (
        f"live_overlay_github_workflow_latest_duration_seconds{{{workflow_labels}}} 120.0" in body
    )


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


def test_render_metrics_escapes_uptimerobot_error_code_labels(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "ok": 0,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": 'timeout\\\\"quoted',
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_uptimerobot_scrape_error_info{error_code="timeout\\\\\\\\\\"quoted"} 1' in body


def test_render_metrics_escapes_github_workflow_error_code_labels(monkeypatch: pytest.MonkeyPatch) -> None:
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
            "ok": 0,
            "fetched_at_unix": 1_700_000_100.0,
            "error_code": 'http\\\\"401',
            "counts": {"seen": 0, "success": 0, "failed": 0, "in_progress": 0, "queued": 0},
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
        },
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert 'live_overlay_github_workflow_scrape_error_info{error_code="http\\\\\\\\\\"401"} 1' in body


def test_render_metrics_includes_trading_signals_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time as _time

    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    snapshot = {
        "updated_at": "2026-06-23T14:30:00+00:00",
        "updated_epoch": _time.time() - 30.0,
        "poll_interval": 5,
        "poll_duration": 0.4,
        "watched_symbols": ["AAPL", "TSLA", "NVDA"],
        "signal_count": 2,
        "a0_count": 1,
        "a1_count": 1,
        "disabled_reason": None,
        "signals": [
            {
                "symbol": "AAPL",
                "level": "A1",
                "direction": "LONG",
                "confidence_tier": "HIGH",
                "score": 7.5,
                "freshness": 0.9,
                "technical_score": 0.82,
                "change_pct": 1.23,
                "technical_signal": "STRONG_BUY",
                "macd_signal": "BUY",
                "symbol_regime": "TREND_UP",
                "news_category": "earnings",
            },
            {
                "symbol": "TSLA",
                "level": "A0",
                "direction": "SHORT",
                "confidence_tier": "MEDIUM",
                "score": 4.0,
                "freshness": 0.5,
                "technical_score": 0.31,
                "change_pct": -2.0,
                "technical_signal": "SELL",
                "macd_signal": "SELL",
                "symbol_regime": "TREND_DOWN",
                "news_category": "none",
            },
        ],
    }
    monkeypatch.setattr(metrics_mod.compute, "_load_signals_snapshot", lambda: snapshot)

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_trading_signals_loaded 1.0" in body
    assert "live_overlay_trading_signals_active_total 2.0" in body
    assert "live_overlay_trading_signals_a0_total 1.0" in body
    assert "live_overlay_trading_signals_a1_total 1.0" in body
    assert "live_overlay_trading_signals_watched_total 3.0" in body
    assert "live_overlay_trading_signals_snapshot_age_known 1.0" in body
    # Per-signal series are labelled so Grafana can name/group each firing symbol.
    aapl = 'symbol="AAPL",level="A1",direction="LONG",tier="HIGH"'
    assert f"live_overlay_trading_signal_score{{{aapl}}} 7.5" in body
    assert f"live_overlay_trading_signal_freshness{{{aapl}}} 0.9" in body
    assert f"live_overlay_trading_signal_technical_score{{{aapl}}} 0.82" in body
    assert f"live_overlay_trading_signal_change_pct{{{aapl}}} 1.23" in body
    expected_info = (
        "live_overlay_trading_signal_info{"
        + aapl
        + ',technical_signal="STRONG_BUY",macd_signal="BUY",'
        'symbol_regime="TREND_UP",news_category="earnings"} 1'
    )
    assert expected_info in body
    # Highest score sorts first in the capped list.
    assert body.index('live_overlay_trading_signal_score{symbol="AAPL"') < body.index(
        'live_overlay_trading_signal_score{symbol="TSLA"'
    )


def test_render_metrics_includes_tradingview_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    report = {
        "schema_version": "1",
        "overall_severity": "warn",
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "warn",
                "message": "ageing",
                "details": {
                    "validated_at": "2026-06-20T00:00:00+00:00",
                    "age_hours": 60.0,
                    "max_age_hours": 72,
                },
            }
        ],
    }
    monkeypatch.setattr(
        metrics_mod.compute, "_load_tradingview_credential_snapshot", lambda: report
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_tradingview_credential_loaded 1.0" in body
    # severity "warn" is not "error" -> still considered valid.
    assert "live_overlay_tradingview_credential_valid 1.0" in body
    assert "live_overlay_tradingview_credential_age_known 1.0" in body
    assert "live_overlay_tradingview_credential_age_hours 60.000" in body
    assert "live_overlay_tradingview_credential_validated_at_seconds" in body


def test_render_metrics_tradingview_credential_error_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    report = {
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "error",
                "details": {"validated_at": "2026-06-15T00:00:00+00:00", "age_hours": 120.0},
            }
        ],
    }
    monkeypatch.setattr(
        metrics_mod.compute, "_load_tradingview_credential_snapshot", lambda: report
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_tradingview_credential_loaded 1.0" in body
    assert "live_overlay_tradingview_credential_valid 0.0" in body
    assert "live_overlay_tradingview_credential_age_hours 120.000" in body


def test_render_metrics_handles_tradingview_credential_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        metrics_mod.compute, "_load_tradingview_credential_snapshot", lambda: {}
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_tradingview_credential_loaded 0.0" in body
    assert "live_overlay_tradingview_credential_valid 0.0" in body
    assert "live_overlay_tradingview_credential_age_known 0.0" in body
    assert "live_overlay_tradingview_credential_age_hours 0.000" in body


def test_render_metrics_includes_full_credential_health_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    report = {
        "schema_version": "1",
        "overall_severity": "warn",
        "probes": [
            {
                "name": "tv_storage_state_age",
                "severity": "warn",
                "message": "ageing",
                "details": {
                    "validated_at": "2026-06-20T00:00:00+00:00",
                    "age_hours": 60.0,
                    "max_age_hours": 72,
                },
            },
            {
                "name": "github_pat_validity",
                "severity": "ok",
                "message": "PAT valid",
                "details": {"days_left": 45},
            },
            {
                "name": "databento_delivery",
                "severity": "error",
                "message": "stale delivery",
                "details": {"staleness_days": 3.5},
            },
            {
                "name": "fmp_api_key",
                "severity": "ok",
                "message": "OK",
                "details": {},
            },
        ],
    }
    monkeypatch.setattr(
        metrics_mod.compute, "_load_credential_health_snapshot", lambda: report
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_credential_health_loaded 1.0" in body
    assert "live_overlay_credential_health_overall_valid 1.0" in body
    assert 'severity="warn"' in body
    assert "live_overlay_credential_health_tv_storage_state_age_severity_code 1.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_valid 1.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_age_hours 60.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_validated_at_seconds" in body
    assert "live_overlay_credential_health_github_pat_validity_severity_code 2.0" in body
    assert "live_overlay_credential_health_github_pat_validity_valid 1.0" in body
    assert "live_overlay_credential_health_github_pat_validity_days_left 45.0" in body
    assert "live_overlay_credential_health_databento_delivery_severity_code 0.0" in body
    assert "live_overlay_credential_health_databento_delivery_valid 0.0" in body
    assert "live_overlay_credential_health_databento_delivery_staleness_days 3.5" in body
    assert 'live_overlay_credential_health_fmp_api_key_info{severity="ok",message="OK"} 1' in body


def test_render_metrics_credential_health_missing_report_is_zeroed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        metrics_mod.compute, "_load_credential_health_snapshot", lambda: {}
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_credential_health_loaded 0.0" in body
    assert "live_overlay_credential_health_overall_valid 0.0" in body
    assert "live_overlay_credential_health_tv_storage_state_age_severity_code" not in body


def test_render_metrics_handles_trading_signals_snapshot_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.compute, "_load_signals_snapshot", lambda: {})

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_trading_signals_loaded 0.0" in body
    assert "live_overlay_trading_signals_active_total 0.0" in body
    assert "live_overlay_trading_signals_snapshot_age_known 0.0" in body
    # No per-signal series when the snapshot is empty.
    assert "live_overlay_trading_signal_score{" not in body


def test_alert_rules_split_news_snapshot_unavailable_and_stale() -> None:
    """Unavailable snapshot (loaded==0) and stale snapshot (age>3600) must be separate alerts."""
    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    rules_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
    rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    warning_group = next(g for g in rules_doc["groups"] if g.get("name") == "live-overlay-warning")
    uids = {r.get("uid") for r in warning_group["rules"]}
    assert "lo-news-snapshot-unavailable" in uids
    assert "lo-news-snapshot-stale" in uids

    unavailable = next(r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-unavailable")
    assert unavailable["labels"]["severity"] == "high"
    assert "snapshot_loaded" in unavailable["data"][0]["model"]["expr"]
    assert "== bool 0" in unavailable["data"][0]["model"]["expr"]

    stale = next(r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-stale")
    assert "snapshot_age_seconds" in stale["data"][0]["model"]["expr"]
    assert "> bool 3600" in stale["data"][0]["model"]["expr"]


def test_dashboard_service_status_panel_maps_starting_state() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Service Status")
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("0", {}).get("text") == "STARTING"


def test_dashboard_worker_liveness_uses_human_labels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Worker Liveness")
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("0", {}).get("text") == "DEAD"
    assert options.get("1", {}).get("text") == "ALIVE"
    assert "min" not in panel["fieldConfig"]["defaults"]
    assert "max" not in panel["fieldConfig"]["defaults"]


def test_dashboard_has_uptimerobot_state_timeline() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "UptimeRobot Monitor States")
    assert panel["type"] == "state-timeline"
    assert any("live_overlay_uptimerobot_monitor_.*_status_code" in t["expr"] for t in panel["targets"])
    options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert options.get("0", {}).get("text") == "PAUSED"
    assert options.get("8", {}).get("text") == "DOWN"


def test_dashboard_github_workflow_runs_panel_uses_snapshot_counts() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "GitHub Workflow Runs")
    expected_exprs = {
        "seen": "live_overlay_github_workflow_runs_seen_total{job=~\"$job\"}",
        "success": "live_overlay_github_workflow_runs_success_total{job=~\"$job\"}",
        "failed": "live_overlay_github_workflow_runs_failed_total{job=~\"$job\"}",
        "in_progress": "live_overlay_github_workflow_runs_in_progress_total{job=~\"$job\"}",
        "queued": "live_overlay_github_workflow_runs_queued_total{job=~\"$job\"}",
    }
    actual_exprs = {t["legendFormat"]: t["expr"] for t in panel["targets"]}
    assert actual_exprs == expected_exprs
    assert panel["fieldConfig"]["defaults"]["unit"] == "none"
    assert panel["fieldConfig"]["defaults"]["custom"]["axisLabel"] == "runs (snapshot)"


def test_dashboard_has_trading_signals_panels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    by_title = {p.get("title"): p for p in dashboard["panels"]}

    active = by_title["Active Trading Signals"]
    assert active["type"] == "stat"
    assert any(
        "live_overlay_trading_signals_active_total" in t["expr"]
        for t in active["targets"]
    )

    age = by_title["Signals Snapshot Age"]
    assert age["fieldConfig"]["defaults"]["unit"] == "s"
    assert any(
        "live_overlay_trading_signals_snapshot_age_seconds" in t["expr"]
        for t in age["targets"]
    )
    assert any(
        "live_overlay_trading_signals_snapshot_age_known" in t["expr"]
        for t in age["targets"]
    )

    table = by_title["Top Trading Signals — Latest Detail"]
    assert table["type"] == "table"
    exprs = {t["expr"] for t in table["targets"]}
    assert any("live_overlay_trading_signal_score{" in e for e in exprs)
    assert any("live_overlay_trading_signal_technical_score{" in e for e in exprs)
    assert any("live_overlay_trading_signal_change_pct{" in e for e in exprs)
    assert any("live_overlay_trading_signal_freshness{" in e for e in exprs)
    # The numeric series share the same label set so the merge collapses them
    # onto one row per signal; instant queries are required for an at-a-glance
    # snapshot table.
    assert all(t.get("instant") for t in table["targets"])
    assert any(tr["id"] == "merge" for tr in table["transformations"])

    ts_panel = by_title["Signal Score — Active Symbols"]
    assert ts_panel["type"] == "timeseries"
    assert ts_panel["targets"][0]["legendFormat"] == "{{symbol}} {{level}} {{direction}}"


def test_provider_health_snapshot_classifies_state_reason_and_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Disabled providers are excluded from health; degraded reasons are mapped."""
    import services.live_overlay_daemon.compute as compute_mod
    import services.live_overlay_daemon.metrics as metrics_mod

    snapshot = {
        "fetched_at_unix": 0,
        "providers": {
            "newsapi_ai": {"ok": True, "error": None, "raw_count": 12, "new_item_count": 3},
            "benzinga": {"ok": False, "error": "disabled"},
            "fmp_press": {"ok": False, "error": "missing_api_key"},
            "fmp_articles": {"ok": False, "error": "fetch_failed: 403 forbidden no subscription"},
            "tv": {"ok": None},
        },
    }
    snap_path = tmp_path / "smc_live_news_snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(metrics_mod.config, "news_snapshot_path", lambda: snap_path)
    # Deterministic read: provider-health uses the shared compute loader which
    # is TTL-cached process-wide. Reset it so this test does not inherit a
    # prior snapshot from another case (testmon/shard order dependent).
    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})

    health = metrics_mod._provider_health_snapshot()

    assert health["news_providers_total"] == 5.0
    assert health["news_providers_ok_total"] == 1.0
    assert health["news_providers_degraded_total"] == 2.0
    assert health["news_providers_unknown_total"] == 1.0
    assert health["news_providers_disabled_total"] == 1.0
    # disabled provider is not consumed; everything else is.
    assert health["news_providers_consumed_total"] == 4.0
    # benzinga disabled must NOT drag health into degraded by itself,
    # but the missing-key / unknown providers still mark it degraded.
    assert health["news_health_degraded"] == 1.0
    assert health["news_health_ok"] == 0.0

    info = {row["provider"]: row for row in health["news_provider_info"]}
    assert info["benzinga"]["state"] == "disabled"
    assert info["benzinga"]["consumed"] == "false"
    assert info["benzinga"]["reason"] == "Provider disabled (not ingested)"
    assert info["fmp_press"]["state"] == "degraded"
    assert info["fmp_press"]["reason"] == "API key missing"
    assert info["fmp_articles"]["reason"] == "No active subscription"
    assert info["tv"]["state"] == "unknown"
    assert info["newsapi_ai"]["state"] == "ok"
    assert info["newsapi_ai"]["reason"] == "OK"

    assert health["news_provider_state_code"]["benzinga"] == 3.0
    assert health["news_provider_consumed"]["benzinga"] == 0.0
    assert health["news_provider_consumed"]["newsapi_ai"] == 1.0


def test_provider_health_snapshot_all_disabled_except_consumed_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When only one provider is consumed and it is OK, health must be OK."""
    import services.live_overlay_daemon.compute as compute_mod
    import services.live_overlay_daemon.metrics as metrics_mod

    snapshot = {
        "fetched_at_unix": 0,
        "providers": {
            "newsapi_ai": {"ok": True, "error": None},
            "benzinga": {"ok": False, "error": "disabled"},
            "fmp_stock": {"ok": False, "error": "disabled"},
            "tv": {"ok": False, "error": "disabled"},
        },
    }
    snap_path = tmp_path / "smc_live_news_snapshot.json"
    snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    monkeypatch.setattr(metrics_mod.config, "news_snapshot_path", lambda: snap_path)
    # Metrics derive from the shared (TTL-cached) compute loader; reset its
    # cache so the patched snapshot path is read fresh and no URL is used.
    monkeypatch.setattr(compute_mod.config, "news_snapshot_url", lambda: "")
    monkeypatch.setattr(compute_mod, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute_mod, "_news_cache", {})

    health = metrics_mod._provider_health_snapshot()

    assert health["news_providers_consumed_total"] == 1.0
    assert health["news_providers_disabled_total"] == 3.0
    assert health["news_health_ok"] == 1.0
    assert health["news_health_degraded"] == 0.0
    assert health["news_health_unknown"] == 0.0


def test_render_metrics_includes_daily_experiment_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    rollup = {
        "schema_version": 1,
        "scoring_root": "/x/artifacts/ci/measurement_benchmark_rolling/2026-06-21",
        "files_scanned": 1234,
        "per_tf": {
            "5m": {
                "n_events": 200,
                "hit_rate": 0.61,
                "symbols": ["AAPL"],
                "families": {
                    "FVG": {"n_events": 80, "hit_rate": 0.7},
                    "SWEEP": {"n_events": 40, "hit_rate": 0.55},
                },
            },
            "4H": {
                "n_events": 50,
                "hit_rate": 0.48,
                "families": {"BOS": {"n_events": 30, "hit_rate": 0.5}},
            },
        },
        "phase_e2_verdict": {
            "fvg_ttf_5m_vs_baseline": {
                "status": "measured",
                "delta_hr": 0.08,
                "delta_hr_p_value": 0.012,
                "underpowered": False,
                "n_a": 80,
                "n_b": 90,
            },
            "bos_stability_4h_vs_baseline": {
                "status": "insufficient_data",
                "n_a": 5,
                "n_b": 7,
            },
        },
    }
    history = [
        {
            "captured_at": "2026-06-20T13:00:00Z",
            "per_tf": {
                "5m": {
                    "n_events": 180,
                    "hit_rate": 0.58,
                    "families": {"FVG": {"n_events": 70, "hit_rate": 0.66}},
                }
            },
        },
        {
            "captured_at": "2026-06-21T13:00:00Z",
            "per_tf": {
                "5m": {
                    "n_events": 200,
                    "hit_rate": 0.61,
                    "families": {"FVG": {"n_events": 80, "hit_rate": 0.7}},
                }
            },
        },
    ]
    monkeypatch.setattr(
        metrics_mod.compute, "_load_experiment_snapshot", lambda: rollup
    )
    monkeypatch.setattr(
        metrics_mod.compute, "_load_experiment_history", lambda: history
    )

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_experiment_loaded 1.0" in body
    assert "live_overlay_experiment_files_scanned 1234.0" in body
    # The dated scoring_root yields a known run age.
    assert "live_overlay_experiment_snapshot_age_known 1.0" in body
    # Per-timeframe aggregates.
    assert (
        'live_overlay_experiment_tf_hit_rate{timeframe="5m"} 0.61' in body
    )
    assert (
        'live_overlay_experiment_tf_n_events{timeframe="4H"} 50.0' in body
    )
    # Per-family detail.
    assert (
        'live_overlay_experiment_family_hit_rate{timeframe="5m",family="FVG"} 0.7'
        in body
    )
    assert (
        'live_overlay_experiment_family_n_events{timeframe="5m",family="SWEEP"} 40.0'
        in body
    )
    # Phase E2 verdicts mapped to numeric codes; p-value only when measured.
    assert (
        'live_overlay_experiment_verdict_status_code{hypothesis="fvg_5m",status="measured"} 4.0'
        in body
    )
    assert (
        'live_overlay_experiment_verdict_status_code{hypothesis="bos_4h",status="insufficient_data"} 1.0'
        in body
    )
    assert (
        'live_overlay_experiment_verdict_p_value{hypothesis="fvg_5m",status="measured"} 0.012'
        in body
    )
    # p-value is omitted for the insufficient-data verdict (no false 0).
    assert 'live_overlay_experiment_verdict_p_value{hypothesis="bos_4h"' not in body
    # Per-day backfilled history series, one per (run_date, timeframe, family).
    assert (
        'live_overlay_experiment_day_family_hit_rate{run_date="2026-06-20",timeframe="5m",family="FVG"} 0.66'
        in body
    )
    assert (
        'live_overlay_experiment_day_family_hit_rate{run_date="2026-06-21",timeframe="5m",family="FVG"} 0.7'
        in body
    )


def test_render_metrics_handles_daily_experiment_snapshot_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.metrics as metrics_mod

    _patch_common(
        monkeypatch,
        feed_ready=True,
        market_open=True,
        bar_count=10,
        overlay_symbols=5,
        overlay_age=60.0,
    )
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_snapshot", lambda: {})
    monkeypatch.setattr(metrics_mod.compute, "_load_experiment_history", lambda: [])

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_experiment_loaded 0.0" in body
    assert "live_overlay_experiment_snapshot_age_known 0.0" in body
    assert "live_overlay_experiment_files_scanned 0.0" in body
    # No per-family or per-day series when nothing is available.
    assert "live_overlay_experiment_family_hit_rate{" not in body
    assert "live_overlay_experiment_day_family_hit_rate{" not in body


def test_dashboard_has_daily_experiment_panels() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    by_title = {p.get("title"): p for p in dashboard["panels"]}

    age = by_title["Daily Experiment — Snapshot Age"]
    assert age["fieldConfig"]["defaults"]["unit"] == "s"
    assert any(
        "live_overlay_experiment_snapshot_age_seconds" in t["expr"]
        for t in age["targets"]
    )
    assert any(
        "live_overlay_experiment_snapshot_age_known" in t["expr"]
        for t in age["targets"]
    )

    fvg = by_title["FVG 5m Verdict (Phase E2)"]
    assert any(
        'hypothesis="fvg_5m"' in t["expr"]
        and "live_overlay_experiment_verdict_status_code" in t["expr"]
        for t in fvg["targets"]
    )
    fvg_map = fvg["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert fvg_map["4"]["text"] == "measured"

    detail = by_title["Daily Experiment — Latest Per-Family Detail"]
    assert detail["type"] == "table"
    exprs = {t["expr"] for t in detail["targets"]}
    assert any("live_overlay_experiment_family_hit_rate{" in e for e in exprs)
    assert any("live_overlay_experiment_family_n_events{" in e for e in exprs)
    assert all(t.get("instant") for t in detail["targets"])
    assert any(tr["id"] == "merge" for tr in detail["transformations"])

    ts_panel = by_title["Family Hit-Rate Over Time (accumulates daily)"]
    assert ts_panel["type"] == "timeseries"
    assert ts_panel["targets"][0]["legendFormat"] == "{{timeframe}} · {{family}}"

    history = by_title["Per-Day Family Hit-Rate — History (backfilled)"]
    assert history["type"] == "table"
    hist_exprs = {t["expr"] for t in history["targets"]}
    assert any("live_overlay_experiment_day_family_hit_rate{" in e for e in hist_exprs)
    assert any(tr["id"] == "merge" for tr in history["transformations"])


def test_dashboard_railway_panels_query_emitted_metrics() -> None:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))

    emitted = {
        "live_overlay_railway_service_cpu_cores",
        "live_overlay_railway_service_memory_used_ratio",
        "live_overlay_railway_service_disk_gb",
        "live_overlay_railway_service_network_rx_gb",
        "live_overlay_railway_service_network_tx_gb",
        "live_overlay_railway_service_memory_limit_gb",
    }
    expected_titles = {
        "Railway CPU Cores",
        "Railway Memory Used Ratio",
        "Railway Disk Usage (GB)",
        "Railway Network RX (GB)",
        "Railway Network TX (GB)",
        "Railway Memory Limit (GB)",
    }
    by_title = {p["title"]: p for p in dashboard["panels"]}
    missing_titles = expected_titles - by_title.keys()
    assert not missing_titles, f"Missing Railway panels: {missing_titles}"

    queried = set()
    for title in expected_titles:
        panel = by_title[title]
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            metric = expr.split("{")[0].split("(")[-1]
            queried.add(metric)

    missing_metrics = emitted - queried
    assert not missing_metrics, f"Railway panels do not query emitted metrics: {missing_metrics}"

    bad = queried - emitted
    assert not bad, f"Railway panels query non-existent metrics: {bad}"


def test_render_metrics_includes_daemon_restarts_total_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dedicated restart counter is rendered as a counter series."""
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
        obs._counters["live_overlay.daemon.restarts_total"] = 3.0
        obs._counters["live_overlay.daemon.restart_cause.deploy.total"] = 3.0

    body = metrics_mod.render_metrics(startup_ts=100.0)
    assert "# TYPE live_overlay_daemon_restarts_total counter" in body
    assert "live_overlay_daemon_restarts_total 3.0" in body
    assert "# TYPE live_overlay_daemon_restart_cause_deploy_total counter" in body
    assert "live_overlay_daemon_restart_cause_deploy_total 3.0" in body


def test_main_lifespan_increments_restarts_total_counter() -> None:
    """main.py _lifespan increments the dedicated restart counter."""
    import services.live_overlay_daemon.main as main_mod

    source = Path(main_mod.__file__).read_text(encoding="utf-8")
    assert 'observability.metric_counter("live_overlay.daemon.restarts_total")' in source
    assert 'observability.metric_counter(' in source
    assert "restart_cause" in source


def test_dashboard_all_panels_have_datasource() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    expected = {"type": "prometheus", "uid": "grafanacloud-prom"}
    for panel in dashboard["panels"]:
        assert panel.get("datasource") == expected, panel.get("title")
        for target in panel.get("targets", []):
            assert target.get("datasource") == expected, panel.get("title")


def test_dashboard_all_panels_have_stable_id() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    ids = []
    panels = list(dashboard["panels"])
    for panel in dashboard["panels"]:
        panels.extend(panel.get("panels") or [])
    for panel in panels:
        assert "id" in panel, panel.get("title")
        assert isinstance(panel["id"], int), panel.get("title")
        ids.append(panel["id"])
    assert len(ids) == len(set(ids)), "duplicate panel ids"


def test_render_metrics_always_emits_traffic_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Traffic counters must be present even before the first request.

    Grafana panels "Success Rate (%)" and "Market-open Request Health" use
    rate() over live_overlay_smc_live_requests_total / _success_total.  When
    the daemon starts and no request has arrived yet, these counters do not
    exist in the in-process counter dict, so Prometheus returns "No data".
    The renderer must seed them as 0.0 so the series are always scraped.
    """
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

    body = metrics_mod.render_metrics(startup_ts=100.0)

    assert "live_overlay_smc_live_requests_total 0.0" in body
    assert "live_overlay_smc_live_success_total 0.0" in body
    assert "live_overlay_smc_live_errors_total 0.0" in body
    assert "live_overlay_smc_live_auth_denied 0.0" in body
    assert "live_overlay_smc_live_bad_tf_total 0.0" in body
    assert "live_overlay_smc_live_cache_miss_total 0.0" in body
    assert "live_overlay_smc_live_stale_served_total 0.0" in body


def test_dashboard_job_variable_allows_multi_and_all() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dashboard_path = repo_root / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
    dashboard = json.loads(dashboard_path.read_text(encoding="utf-8"))
    job_var = next(v for v in dashboard["templating"]["list"] if v["name"] == "job")
    assert job_var["multi"] is True
    assert job_var["includeAll"] is True
