"""Observability contract tests for live_overlay_daemon.

These tests pin that metrics/traces/audit-events are emitted as structured logs
and can be asserted via caplog.
"""
from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException


def _sample_bar() -> dict[str, float]:
    return {
        "open": 100.0,
        "high": 101.0,
        "low": 99.5,
        "close": 100.5,
        "volume": 1_000.0,
    }


def test_full_compute_cycle_emits_trace_metric_and_audit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import services.live_overlay_daemon.compute as compute
    import services.live_overlay_daemon.observability as obs

    monkeypatch.setattr(compute.cache, "get_all_symbols_snapshot", lambda: {"AAPL": [_sample_bar()]})
    monkeypatch.setattr(compute.config, "max_stale_secs", lambda: 3600)
    monkeypatch.setattr(compute, "_get_global_news_fields", lambda: {"tone": "NEUTRAL", "global_heat": 0.0})
    monkeypatch.setattr(compute, "build_payload", lambda *args, **kwargs: {"symbol": "AAPL"})
    monkeypatch.setattr(compute.cache, "set_overlay", lambda _payloads: None)

    with caplog.at_level(logging.INFO, logger=obs.logger.name):
        n = compute.run_full_compute_cycle()

    assert n == 1
    msgs = [r.getMessage() for r in caplog.records]
    assert any("trace name=live_overlay.full_compute_cycle phase=start" in m for m in msgs)
    assert any("metric kind=gauge name=live_overlay.overlay_symbols value=1" in m for m in msgs)
    assert any("audit event=live_overlay_full_compute_cycle outcome=ok" in m for m in msgs)


def test_flow_patch_cycle_emits_trace_metric_and_audit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import services.live_overlay_daemon.compute as compute
    import services.live_overlay_daemon.observability as obs

    monkeypatch.setattr(compute.cache, "get_all_symbols_snapshot", lambda: {"AAPL": [_sample_bar()]})
    monkeypatch.setattr(compute.cache, "get_vix", lambda: 18.12345)
    monkeypatch.setattr(compute.cache, "patch_overlay", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.INFO, logger=obs.logger.name):
        n = compute.run_flow_patch_cycle()

    assert n == 1
    msgs = [r.getMessage() for r in caplog.records]
    assert any("trace name=live_overlay.flow_patch_cycle phase=start" in m for m in msgs)
    assert any("metric kind=gauge name=live_overlay.flow_patch_symbols value=1" in m for m in msgs)
    assert any("audit event=live_overlay_flow_patch_cycle outcome=ok" in m for m in msgs)


def test_smc_live_auth_denied_emits_metric_and_audit(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import services.live_overlay_daemon.main as main_mod
    import services.live_overlay_daemon.observability as obs

    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: "secret-token")

    with caplog.at_level(logging.INFO, logger=obs.logger.name), pytest.raises(HTTPException) as exc_info:
        main_mod.smc_live(token="wrong", symbol="AAPL", tf="5m")

    assert exc_info.value.status_code == 404
    msgs = [r.getMessage() for r in caplog.records]
    assert any("metric kind=counter name=live_overlay.smc_live_auth.denied" in m for m in msgs)
    assert any("audit event=smc_live_auth outcome=denied" in m for m in msgs)


def test_structured_log_fields_escape_whitespace_and_newlines() -> None:
    import services.live_overlay_daemon.observability as obs

    assert obs._kv({"symbol": "BAD TICK\nNEXT", "tf": "5m"}) == "symbol=BAD\\sTICK\\nNEXT tf=5m"


def test_smc_live_cache_miss_counts_stale_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.main as main_mod
    import services.live_overlay_daemon.observability as obs

    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: "secret-token")
    monkeypatch.setattr(main_mod.cache, "get_overlay", lambda _sym: None)

    with obs._counter_lock:
        obs._counters.pop("live_overlay.smc_live_stale_served.total", None)

    payload = main_mod.smc_live(token="secret-token", symbol="AAPL", tf="5m")

    assert payload.status_code == 200
    with obs._counter_lock:
        assert obs._counters.get("live_overlay.smc_live_stale_served.total") == 1.0


def test_smc_live_records_latency_histogram_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.live_overlay_daemon.main as main_mod
    import services.live_overlay_daemon.observability as obs

    monkeypatch.setattr(main_mod.config, "overlay_secret_token", lambda: "secret-token")
    monkeypatch.setattr(main_mod.cache, "overlay_age_secs", lambda: 1.0)
    monkeypatch.setattr(main_mod.config, "max_stale_secs", lambda: 3600)
    monkeypatch.setattr(
        main_mod.cache,
        "get_overlay",
        lambda _sym: {
            "schema": "smc-live-overlay/1",
            "symbol": "AAPL",
            "asof_ts": 1,
            "stale": False,
            "news_strength": None,
            "news_bias": None,
            "flow_rel_vol": 1.0,
            "flow_delta_proxy_pct": 0.0,
            "squeeze_on": 0,
            "ats_state": "neutral",
            "ats_zscore": 0.0,
            "vix_level": 20.0,
            "tone": "NEUTRAL",
            "global_heat": 0.0,
            "event_window_state": "normal",
            "event_risk_level": "low",
            "next_event_name": None,
            "next_event_time": None,
            "market_event_blocked": False,
            "symbol_event_blocked": False,
            "event_provider_status": "unavailable",
        },
    )

    with obs._counter_lock:
        obs._counters.pop("live_overlay.smc_live_latency.count", None)
        obs._counters.pop("live_overlay.smc_live_latency.sum_ms", None)
        obs._counters.pop("live_overlay.smc_live_latency.bucket_le_inf", None)

    response = main_mod.smc_live(token="secret-token", symbol="AAPL", tf="5m")
    assert response.status_code == 200

    with obs._counter_lock:
        assert obs._counters.get("live_overlay.smc_live_latency.count") == 1.0
        assert obs._counters.get("live_overlay.smc_live_latency.bucket_le_inf") == 1.0
        assert obs._counters.get("live_overlay.smc_live_latency.sum_ms", 0.0) >= 0.0
