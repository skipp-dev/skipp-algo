"""Unit tests for the Railway container-metrics bridge."""

from __future__ import annotations

import importlib
import json
from typing import Any
from unittest.mock import patch

import pytest

from services.live_overlay_daemon import config, railway_metrics


@pytest.fixture(autouse=True)
def _reset_bridge_cache() -> None:
    railway_metrics.reset_cache()
    yield
    railway_metrics.reset_cache()


def _fake_response(body: bytes) -> object:
    class _Response:
        def read(self) -> bytes:
            return body

        def __enter__(self) -> object:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


def _metrics_body() -> bytes:
    payload = {
        "data": {
            "metrics": [
                {
                    "measurement": "CPU_USAGE",
                    "tags": {"serviceId": "svc-a"},
                    "values": [
                        {"ts": 1000, "value": 0.10},
                        {"ts": 2000, "value": 0.25},
                    ],
                },
                {
                    "measurement": "MEMORY_USAGE_GB",
                    "tags": {"serviceId": "svc-a"},
                    "values": [{"ts": 2000, "value": 0.50}],
                },
                {
                    "measurement": "MEMORY_LIMIT_GB",
                    "tags": {"serviceId": "svc-a"},
                    "values": [{"ts": 2000, "value": 1.00}],
                },
                {
                    "measurement": "CPU_USAGE",
                    "tags": {"serviceId": "svc-b"},
                    "values": [{"ts": 2000, "value": 0.05}],
                },
            ]
        }
    }
    return json.dumps(payload).encode("utf-8")


def test_latest_value_picks_most_recent() -> None:
    values = [{"ts": 1, "value": 10}, {"ts": 3, "value": 30}, {"ts": 2, "value": 20}]
    assert railway_metrics._latest_value(values) == 30.0


def test_latest_value_skips_invalid_points() -> None:
    values = [{"ts": "bad", "value": 5}, {"value": 7}, {"ts": 2, "value": "9"}]
    assert railway_metrics._latest_value(values) == 9.0


def test_latest_value_empty_returns_none() -> None:
    assert railway_metrics._latest_value([]) is None


def test_build_services_collapses_series_per_service() -> None:
    results = json.loads(_metrics_body().decode())["data"]["metrics"]
    services = railway_metrics._build_services(results, {"svc-a": "alpha"})

    by_id = {s["service_id"]: s for s in services}
    assert set(by_id) == {"svc-a", "svc-b"}
    assert by_id["svc-a"]["service"] == "alpha"
    assert by_id["svc-a"]["cpu_cores"] == 0.25
    assert by_id["svc-a"]["memory_gb"] == 0.50
    assert by_id["svc-a"]["memory_limit_gb"] == 1.00
    # svc-b has no friendly name -> falls back to the id.
    assert by_id["svc-b"]["service"] == "svc-b"
    assert by_id["svc-b"]["cpu_cores"] == 0.05


def test_snapshot_disabled_when_flag_off() -> None:
    with patch.object(railway_metrics.config, "railway_metrics_enabled", return_value=False):
        result = railway_metrics.snapshot()
    assert result["enabled"] is False
    assert result["ok"] is False
    assert result["services"] == []


def test_snapshot_enabled_but_missing_config_reports_failed_not_disabled() -> None:
    """Missing credentials must report enabled intent, not look disabled."""
    with (
        patch.object(railway_metrics.config, "railway_metrics_enabled", return_value=True),
        patch.object(railway_metrics.config, "railway_api_token", return_value=""),
        patch.object(railway_metrics.config, "railway_project_id", return_value=""),
        patch.object(railway_metrics.config, "railway_environment_id", return_value=""),
    ):
        result = railway_metrics.snapshot()
    assert result["enabled"] is True
    assert result["configured"] is False
    assert result["ok"] is False
    assert result["error"] == "missing_configuration"


def _patch_enabled_config() -> list[Any]:
    return [
        patch.object(railway_metrics.config, "railway_metrics_enabled", return_value=True),
        patch.object(railway_metrics.config, "railway_api_token", return_value="tok"),
        patch.object(railway_metrics.config, "railway_project_id", return_value="proj"),
        patch.object(railway_metrics.config, "railway_environment_id", return_value="env"),
        patch.object(railway_metrics.config, "railway_metrics_timeout_secs", return_value=5),
        patch.object(railway_metrics.config, "railway_metrics_window_secs", return_value=600),
        patch.object(railway_metrics.config, "railway_metrics_sample_secs", return_value=60),
        patch.object(railway_metrics.config, "railway_metrics_poll_ttl_secs", return_value=60),
        patch.object(railway_metrics.config, "railway_service_names", return_value={"svc-a": "alpha"}),
    ]


def test_snapshot_fetches_and_parses() -> None:
    patches = _patch_enabled_config()
    for p in patches:
        p.start()
    try:
        with patch.object(
            railway_metrics.urllib.request,
            "urlopen",
            return_value=_fake_response(_metrics_body()),
        ) as mock_urlopen:
            result = railway_metrics.snapshot()
    finally:
        for p in patches:
            p.stop()

    assert result["enabled"] is True
    assert result["ok"] is True
    assert {s["service_id"] for s in result["services"]} == {"svc-a", "svc-b"}
    mock_urlopen.assert_called_once()


def test_snapshot_returns_last_good_cache_on_error() -> None:
    patches = _patch_enabled_config()
    for p in patches:
        p.start()
    try:
        with patch.object(
            railway_metrics.urllib.request,
            "urlopen",
            return_value=_fake_response(_metrics_body()),
        ):
            good = railway_metrics.snapshot()
        assert good["ok"] is True

        # Expire the cache then make the next fetch fail; keep cached services
        # but mark the scrape as failed with a stable error code.
        railway_metrics._CACHE_EXPIRES_AT = 0.0
        with patch.object(
            railway_metrics.urllib.request,
            "urlopen",
            side_effect=OSError("boom"),
        ):
            result = railway_metrics.snapshot()
    finally:
        for p in patches:
            p.stop()

    assert result["ok"] is False
    assert result["enabled"] is True
    assert result["configured"] is True
    assert result["error"] == "fetch_error"
    assert result["services"] == good["services"]


def test_snapshot_graphql_errors_treated_as_failure() -> None:
    patches = _patch_enabled_config()
    for p in patches:
        p.start()
    try:
        body = json.dumps({"errors": [{"message": "nope"}]}).encode()
        with patch.object(
            railway_metrics.urllib.request,
            "urlopen",
            return_value=_fake_response(body),
        ):
            result = railway_metrics.snapshot()
    finally:
        for p in patches:
            p.stop()

    assert result["enabled"] is True
    assert result["configured"] is True
    assert result["ok"] is False
    assert result["error"] == "fetch_error"


def test_render_metrics_includes_railway_gauges() -> None:
    from services.live_overlay_daemon import metrics

    snapshot = {
        "enabled": True,
        "ok": True,
        "fetched_at_unix": 1_000_000.0,
        "error": None,
        "services": [
            {
                "service_id": "svc-a",
                "service": "alpha",
                "cpu_cores": 0.25,
                "memory_gb": 0.50,
                "memory_limit_gb": 1.00,
            }
        ],
    }
    with patch.object(metrics.railway_metrics, "snapshot", return_value=snapshot):
        text = metrics.render_metrics(startup_ts=1_000_000.0)

    assert "live_overlay_railway_metrics_enabled 1" in text
    assert 'live_overlay_railway_service_cpu_cores{service="alpha",service_id="svc-a"} 0.25' in text
    assert 'live_overlay_railway_service_memory_gb{service="alpha",service_id="svc-a"} 0.5' in text
    assert 'live_overlay_railway_service_memory_used_ratio{service="alpha",service_id="svc-a"} 0.5' in text


def test_render_metrics_railway_disabled_emits_zero_gauge() -> None:
    from services.live_overlay_daemon import metrics

    snapshot = {
        "enabled": False,
        "ok": False,
        "fetched_at_unix": 0.0,
        "error": None,
        "services": [],
    }
    with patch.object(metrics.railway_metrics, "snapshot", return_value=snapshot):
        text = metrics.render_metrics(startup_ts=1_000_000.0)

    assert "live_overlay_railway_metrics_enabled 0" in text
    assert "live_overlay_railway_service_cpu_cores{" not in text


def test_railway_metrics_enabled_when_credentials_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge auto-enables when all Railway credentials are configured."""
    monkeypatch.delenv("ENABLE_RAILWAY_METRICS", raising=False)
    monkeypatch.setenv("RAILWAY_API_TOKEN", "token")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "project")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env")
    importlib.reload(config)
    assert config.railway_metrics_enabled() is True


def test_railway_metrics_disabled_when_no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge stays disabled when no credentials are configured."""
    monkeypatch.delenv("ENABLE_RAILWAY_METRICS", raising=False)
    monkeypatch.setenv("RAILWAY_API_TOKEN", "")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "")
    importlib.reload(config)
    assert config.railway_metrics_enabled() is False


def test_render_metrics_emits_configured_and_success_gauges() -> None:
    from services.live_overlay_daemon import metrics

    snapshot = {
        "enabled": True,
        "ok": True,
        "fetched_at_unix": 1_000_000.0,
        "error": None,
        "services": [],
    }
    with patch.object(metrics.railway_metrics, "snapshot", return_value=snapshot):
        text = metrics.render_metrics(startup_ts=1_000_000.0)

    assert "live_overlay_railway_metrics_configured 1" in text
    assert "live_overlay_railway_metrics_scrape_success 1" in text
    assert "live_overlay_railway_metrics_enabled 1" in text


def test_render_metrics_scrape_error_still_exposes_configured() -> None:
    from services.live_overlay_daemon import metrics

    snapshot = {
        "enabled": True,
        "ok": False,
        "fetched_at_unix": 0.0,
        "error": " GraphQL error",
        "services": [],
    }
    with patch.object(metrics.railway_metrics, "snapshot", return_value=snapshot):
        text = metrics.render_metrics(startup_ts=1_000_000.0)

    assert "live_overlay_railway_metrics_configured 1" in text
    assert "live_overlay_railway_metrics_scrape_success 0" in text
    assert "live_overlay_railway_metrics_enabled 0" in text
    assert "live_overlay_railway_metrics_error_info" in text


@pytest.mark.parametrize(
    ("snapshot", "enabled", "configured", "success", "error"),
    [
        ({"enabled": False, "configured": False, "ok": False, "error": None}, 0, 0, 0, "none"),
        ({"enabled": True, "configured": False, "ok": False, "error": "missing_configuration"}, 1, 0, 0, "missing_configuration"),
        ({"enabled": True, "configured": True, "ok": False, "error": "fetch_error"}, 1, 1, 0, "fetch_error"),
        ({"enabled": True, "configured": True, "ok": True, "error": None}, 1, 1, 1, "none"),
    ],
)
def test_render_metrics_exports_railway_bridge_truth_table(
    snapshot: dict[str, Any],
    enabled: int,
    configured: int,
    success: int,
    error: str,
) -> None:
    from services.live_overlay_daemon import metrics

    snapshot = {
        "fetched_at_unix": 0.0,
        "scrape_duration_seconds": None,
        "services": [],
        **snapshot,
    }
    with patch.object(metrics.railway_metrics, "snapshot", return_value=snapshot):
        text = metrics.render_metrics(startup_ts=1_000_000.0)

    assert f'live_overlay_bridge_enabled{{bridge="railway_metrics"}} {enabled}' in text
    assert f'live_overlay_bridge_configured{{bridge="railway_metrics"}} {configured}' in text
    assert f'live_overlay_bridge_scrape_success{{bridge="railway_metrics"}} {success}' in text
    assert f'live_overlay_bridge_error_info{{bridge="railway_metrics",error="{error}"}}' in text


def test_fetch_sets_last_success_fetched_at_unix(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful Railway poll must record when the last success happened."""
    monkeypatch.setenv("ENABLE_RAILWAY_METRICS", "1")
    monkeypatch.setenv("RAILWAY_API_TOKEN", "token")
    monkeypatch.setenv("RAILWAY_PROJECT_ID", "project")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_ID", "env")
    importlib.reload(config)

    body = _metrics_body()
    with patch.object(railway_metrics, "_post_graphql", return_value=json.loads(body)):
        result = railway_metrics.snapshot()

    assert result["ok"] is True
    assert result["last_success_fetched_at_unix"] == result["fetched_at_unix"]
    assert result["last_success_fetched_at_unix"] > 0


def test_failed_snapshot_preserves_last_success_from_cache() -> None:
    """A failed Railway poll must not reset last_success to the failed poll time."""
    previous = {
        "enabled": True,
        "configured": True,
        "ok": True,
        "fetched_at_unix": 1_000_000.0,
        "last_success_fetched_at_unix": 1_000_000.0,
        "services": [],
    }
    failed = railway_metrics._failed_snapshot("network_error", cached=previous)
    assert failed["ok"] is False
    assert failed["fetched_at_unix"] == 1_000_000.0
    assert failed["last_success_fetched_at_unix"] == 1_000_000.0


def test_render_metrics_uses_last_success_for_bridge_age() -> None:
    """Railway bridge last_success_age_seconds must use last_success_fetched_at_unix."""
    from services.live_overlay_daemon import metrics

    snapshot = {
        "enabled": True,
        "ok": False,
        "fetched_at_unix": 1_300.0,
        "last_success_fetched_at_unix": 1_000.0,
        "error": "network_error",
        "services": [],
    }
    with patch.object(metrics.railway_metrics, "snapshot", return_value=snapshot):
        with patch("services.live_overlay_daemon.metrics.time.time", return_value=1_300.0):
            text = metrics.render_metrics(startup_ts=1_300.0)

    assert 'live_overlay_bridge_last_success_age_seconds{bridge="railway_metrics"} 300' in text
