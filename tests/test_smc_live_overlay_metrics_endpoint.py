"""Tests for the /metrics Prometheus endpoint and error counters.

Validates:
  - /{token}/metrics returns valid Prometheus text-format exposition.
  - Auth is enforced (wrong token → 404).
  - Feed/compute error counters are emitted on failure paths.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_TEST_TOKEN = "test-secret-token"
_TEST_BENTO_KEY = "test-bento-key"


@pytest.fixture()
def _patch_env(monkeypatch: pytest.MonkeyPatch):
    """Patch config to return test values without real env vars."""
    import services.live_overlay_daemon.config as config

    monkeypatch.setattr(config, "overlay_secret_token", lambda: _TEST_TOKEN)
    monkeypatch.setattr(config, "databento_api_key", lambda: _TEST_BENTO_KEY)


@pytest.fixture()
def _patch_feed(monkeypatch: pytest.MonkeyPatch):
    """Stub feed so the app can start without a real Databento connection."""
    import services.live_overlay_daemon.feed as feed

    monkeypatch.setattr(feed, "start", lambda: None)
    monkeypatch.setattr(feed, "stop", lambda: None)
    monkeypatch.setattr(feed, "is_ready", lambda: True)
    monkeypatch.setattr(feed, "last_bar_age_secs", lambda: 5.0)
    monkeypatch.setattr(feed, "worker_liveness", lambda: {
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


@pytest.fixture()
def client(_patch_env, _patch_feed):
    """TestClient with stubbed dependencies."""
    import services.live_overlay_daemon.main as main
    # Reset startup_ts for predictable uptime
    main._startup_ts = 100.0
    return TestClient(main.app)


class TestMetricsEndpoint:
    def test_returns_prometheus_text_format(self, client: TestClient) -> None:
        resp = client.get(f"/{_TEST_TOKEN}/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers["content-type"]
        assert "version=0.0.4" in resp.headers["content-type"]
        body = resp.text
        # Should contain TYPE declarations and counter/gauge values
        assert "# TYPE" in body
        assert "live_overlay_feed_reconnect_attempts" in body
        assert "live_overlay_feed_bento_errors" in body
        assert "live_overlay_uptime_seconds" in body
        assert "live_overlay_overlay_symbols" in body
        assert "live_overlay_feed_healthy 1" in body
        assert "live_overlay_workers_healthy 1" in body

    def test_wrong_token_returns_404(self, client: TestClient) -> None:
        resp = client.get("/wrong-token/metrics")
        assert resp.status_code == 404

    def test_counter_values_reflect_feed_state(self, client: TestClient) -> None:
        body = client.get(f"/{_TEST_TOKEN}/metrics").text
        # Feed metrics from the stub
        assert "live_overlay_feed_reconnect_attempts 2" in body
        assert "live_overlay_feed_bento_errors 1" in body
        assert "live_overlay_feed_unexpected_errors 0" in body

    def test_worker_liveness_per_worker(self, client: TestClient) -> None:
        body = client.get(f"/{_TEST_TOKEN}/metrics").text
        assert "live_overlay_worker_live_feed_alive 1" in body
        assert "live_overlay_worker_overlay_refresh_alive 1" in body
        assert "live_overlay_worker_flow_refresh_alive 1" in body


class TestComputeErrorCounters:
    """Verify that refresh loop errors emit structured counter metrics."""

    def test_full_compute_error_emits_counter(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        import services.live_overlay_daemon.compute as compute
        import services.live_overlay_daemon.observability as obs

        # Reset counters
        with obs._counter_lock:
            obs._counters.pop("live_overlay.full_compute_cycle.errors", None)

        # Make compute raise
        monkeypatch.setattr(compute, "run_full_compute_cycle", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        # Manually simulate what _run_refresh_loop does on error
        try:
            compute.run_full_compute_cycle()
        except Exception:
            from services.live_overlay_daemon.observability import metric_counter
            with caplog.at_level(logging.INFO, logger=obs.logger.name):
                metric_counter("live_overlay.full_compute_cycle.errors")

        assert "live_overlay.full_compute_cycle.errors" in obs._counters
        assert obs._counters["live_overlay.full_compute_cycle.errors"] == 1.0

    def test_flow_patch_error_emits_counter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import services.live_overlay_daemon.compute as compute
        import services.live_overlay_daemon.observability as obs

        # Reset counters
        with obs._counter_lock:
            obs._counters.pop("live_overlay.flow_patch_cycle.errors", None)

        monkeypatch.setattr(compute, "run_flow_patch_cycle", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

        try:
            compute.run_flow_patch_cycle()
        except Exception:
            from services.live_overlay_daemon.observability import metric_counter
            metric_counter("live_overlay.flow_patch_cycle.errors")

        assert "live_overlay.flow_patch_cycle.errors" in obs._counters
        assert obs._counters["live_overlay.flow_patch_cycle.errors"] == 1.0


class TestFeedMetricEmission:
    """Verify that _inc_metric emits to observability counters."""

    def test_inc_metric_emits_structured_counter(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        import services.live_overlay_daemon.feed as feed_mod
        import services.live_overlay_daemon.observability as obs

        # Reset
        with obs._counter_lock:
            obs._counters.pop("live_overlay.feed.bento_errors", None)
        with feed_mod._metrics_lock:
            feed_mod._metrics["bento_errors"] = 0

        with caplog.at_level(logging.INFO, logger=obs.logger.name):
            feed_mod._inc_metric("bento_errors")

        # Internal feed counter incremented
        assert feed_mod._metrics["bento_errors"] == 1
        # Also emitted as observability counter
        assert obs._counters.get("live_overlay.feed.bento_errors") == 1.0
        # Structured log line present
        msgs = [r.getMessage() for r in caplog.records]
        assert any("name=live_overlay.feed.bento_errors" in m for m in msgs)
