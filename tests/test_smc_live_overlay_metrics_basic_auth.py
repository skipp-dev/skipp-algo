"""Tests for /metrics Basic auth (preferred) vs legacy /{token}/metrics path."""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

_TEST_TOKEN = "test-secret-token"
_TEST_BENTO_KEY = "test-bento-key"


def _client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import services.live_overlay_daemon.feed as feed

    monkeypatch.setattr(feed, "start", lambda: None)
    monkeypatch.setattr(feed, "stop", lambda: None)
    monkeypatch.setattr(feed, "is_ready", lambda: True)
    monkeypatch.setattr(feed, "last_bar_age_secs", lambda: 5.0)
    monkeypatch.setattr(
        feed,
        "worker_liveness",
        lambda: {"live_feed": True, "overlay_refresh": True, "flow_refresh": True},
    )
    monkeypatch.setattr(
        feed,
        "metrics_snapshot",
        lambda: {
            "reconnect_attempts": 0,
            "bento_errors": 0,
            "unexpected_errors": 0,
            "circuit_breakers": 0,
            "partial_restarts": 0,
        },
    )

    import services.live_overlay_daemon.config as config

    monkeypatch.setattr(config, "overlay_secret_token", lambda: _TEST_TOKEN)
    monkeypatch.setattr(config, "databento_api_key", lambda: _TEST_BENTO_KEY)

    import services.live_overlay_daemon.main as main

    main._startup_ts = 100.0
    return TestClient(main.app)


def _basic_header(password: str, username: str = "metrics") -> dict[str, str]:
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def test_metrics_basic_auth_returns_prometheus(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    resp = client.get("/metrics", headers=_basic_header(_TEST_TOKEN))
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "live_overlay_feed_healthy 1" in resp.text


def test_metrics_basic_auth_rejects_missing_header(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    resp = client.get("/metrics")
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Basic"


def test_metrics_basic_auth_rejects_bad_password(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    resp = client.get("/metrics", headers=_basic_header("wrong-token"))
    assert resp.status_code == 401


def test_metrics_basic_auth_accepts_any_username(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    resp = client.get("/metrics", headers=_basic_header(_TEST_TOKEN, username="alloy"))
    assert resp.status_code == 200


def test_metrics_basic_auth_accepts_extra_whitespace_after_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch)
    creds = base64.b64encode(f"metrics:{_TEST_TOKEN}".encode()).decode()
    resp = client.get("/metrics", headers={"Authorization": f"Basic    {creds}"})
    assert resp.status_code == 200


def test_metrics_legacy_path_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    resp = client.get(f"/{_TEST_TOKEN}/metrics")
    assert resp.status_code == 200
    assert "live_overlay_feed_healthy 1" in resp.text


def test_metrics_legacy_path_rejects_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch)
    resp = client.get("/wrong-token/metrics")
    assert resp.status_code == 404
