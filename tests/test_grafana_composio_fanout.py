"""Unit tests for the Grafana -> Composio fan-out router (use case #3)."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts.composio_ops import DeliveryResult
from services.live_overlay_daemon import grafana_composio_fanout as gf


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(gf.router)
    return TestClient(app)


def test_build_slack_message():
    payload = {
        "status": "firing",
        "title": "High latency",
        "externalURL": "http://grafana.local",
        "alerts": [
            {
                "labels": {"alertname": "lo-latency", "severity": "critical"},
                "annotations": {"summary": "p95 over budget"},
            }
        ],
    }
    msg = gf.build_slack_message(payload)
    assert "firing" in msg
    assert "lo-latency" in msg and "critical" in msg and "p95 over budget" in msg
    assert "http://grafana.local" in msg


def test_fan_out_routes_slack_and_optin_issue(monkeypatch):
    issues: list[str] = []
    monkeypatch.setattr(gf.composio_ops, "notify_slack", lambda m: DeliveryResult(True, False, "ok"))

    def fake_issue(owner: str, repo: str, title: str, body: str, labels: Any = None) -> DeliveryResult:
        issues.append(title)
        return DeliveryResult(True, False, "ok")

    monkeypatch.setattr(gf.composio_ops, "create_github_issue", fake_issue)
    payload = {"status": "firing", "alerts": [{"labels": {"alertname": "A", "composio_issue": "true"}}]}
    results = gf.fan_out(payload)
    assert results["slack"]["delivered"] is True
    assert results["github_issues"] and "A" in issues[0]


def test_fan_out_no_issue_without_optin(monkeypatch):
    monkeypatch.setattr(gf.composio_ops, "notify_slack", lambda m: DeliveryResult(True, True, "skip"))
    monkeypatch.setattr(
        gf.composio_ops,
        "create_github_issue",
        lambda *a, **k: pytest.fail("issue should not be created without opt-in"),
    )
    results = gf.fan_out({"status": "firing", "alerts": [{"labels": {"alertname": "A"}}]})
    assert "github_issues" not in results


def test_endpoint_503_without_token(monkeypatch):
    monkeypatch.delenv("GRAFANA_WEBHOOK_TOKEN", raising=False)
    resp = _client().post("/anything/grafana-webhook", json={"status": "firing"})
    assert resp.status_code == 503


def test_endpoint_401_on_bad_token(monkeypatch):
    monkeypatch.setenv("GRAFANA_WEBHOOK_TOKEN", "secret")
    resp = _client().post("/wrong/grafana-webhook", json={"status": "firing"})
    assert resp.status_code == 401


def test_endpoint_200_ok(monkeypatch):
    monkeypatch.setenv("GRAFANA_WEBHOOK_TOKEN", "secret")
    monkeypatch.setattr(gf.composio_ops, "notify_slack", lambda m: DeliveryResult(True, True, "skip"))
    resp = _client().post("/secret/grafana-webhook", json={"status": "firing", "alerts": []})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
