from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import HTTPError

import pytest

from scripts import check_pre_a0_mlflow_health as health


class _Response:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def _version_payload(review_after: str = "2026-08-17T08:53:15Z") -> dict[str, object]:
    return {
        "model_version": {
            "version": "1",
            "status": "READY",
            "run_id": "run-1",
            "tags": [
                {"key": "pre_a0.artifact_id", "value": health.DEFAULT_ARTIFACT_ID},
                {"key": "pre_a0.bundle_id", "value": "bundle-1"},
                {"key": "pre_a0.gate.offline_evaluated", "value": "true"},
                {"key": "pre_a0.gate.shadow_evaluated", "value": "false"},
                {"key": "pre_a0.review_after", "value": review_after},
                {"key": "pre_a0.runtime_contract", "value": "local-json-v1"},
                {"key": "pre_a0.promotion_status", "value": "candidate"},
            ],
        }
    }


class _TextResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


def _fake_urlopen(version_payload: dict[str, object], deployed: bytes | None = None):
    def fake(request, timeout):
        assert timeout == 15
        if request.full_url.endswith("/health"):
            return _Response({})
        if request.full_url.endswith("/version"):
            # Only reached when check_health got a declared version to compare.
            if deployed is None:
                raise HTTPError(request.full_url, 404, "not found", {}, None)
            return _TextResponse(deployed)
        if "registered-models/alias" in request.full_url:
            if request.get_header("Authorization") is None:
                raise HTTPError(request.full_url, 401, "unauthorized", {}, None)
            return _Response(version_payload)
        if "/runs/get" in request.full_url:
            return _Response({"run": {"info": {"status": "FINISHED"}}})
        raise AssertionError(request.full_url)

    return fake


def test_probe_verifies_auth_identity_run_and_expiry_without_exposing_password(monkeypatch) -> None:
    monkeypatch.setattr(health, "urlopen", _fake_urlopen(_version_payload()))
    rc, report = health.check_health(
        tracking_uri="https://mlflow.example.test",
        username="monitor",
        password="do-not-echo",
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert rc == 0
    assert report["overall"] == "healthy"
    assert report["unauthenticated_alias_http_status"] == 401
    assert report["shadow_gate"] == "false"
    assert "do-not-echo" not in json.dumps(report)


def test_probe_warns_before_expiry(monkeypatch) -> None:
    monkeypatch.setattr(health, "urlopen", _fake_urlopen(_version_payload("2026-07-25T00:00:00Z")))
    rc, report = health.check_health(
        tracking_uri="https://mlflow.example.test",
        username="monitor",
        password="secret",
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert rc == 2
    assert report["warnings"] == ["model_expiry_window"]


def test_probe_fails_closed_on_identity_mismatch(monkeypatch) -> None:
    payload = _version_payload()
    payload["model_version"]["tags"][0]["value"] = "wrong"  # type: ignore[index]
    monkeypatch.setattr(health, "urlopen", _fake_urlopen(payload))
    rc, report = health.check_health(
        tracking_uri="https://mlflow.example.test",
        username="monitor",
        password="secret",
        now=datetime(2026, 7, 18, tzinfo=UTC),
    )
    assert rc == 1
    assert "tag_mismatch:pre_a0.artifact_id" in report["critical"]


@pytest.mark.parametrize(
    "value",
    ("http://mlflow.example.test", "https://user:secret@mlflow.example.test", "https://mlflow.example.test/path"),
)
def test_tracking_uri_rejects_unsafe_shapes(value: str) -> None:
    with pytest.raises(ValueError):
        health._tracking_uri(value)


def _deployed_probe(monkeypatch, *, deployed: bytes | None, declared: str):
    monkeypatch.setattr(health, "urlopen", _fake_urlopen(_version_payload(), deployed=deployed))
    return health.check_health(
        tracking_uri="https://mlflow.example.test",
        username="monitor",
        password="secret",
        now=datetime(2026, 7, 18, tzinfo=UTC),
        declared_mlflow_version=declared,
    )


def test_deployed_version_mismatch_is_critical(monkeypatch) -> None:
    """The Doppelgaenger tripwire: deployed 3.14.0 vs declared 3.15.1 pages.

    Measured live 2026-08-18: three Dependabot bumps to the service
    requirements never reached the redeploy-driven container and nothing
    noticed. A mismatch must be critical, not a warning.
    """
    rc, report = _deployed_probe(monkeypatch, deployed=b"3.14.0", declared="3.15.1")
    assert rc == 1
    assert "deployed_version_mismatch" in report["critical"]
    assert report["deployed_mlflow_version"] == "3.14.0"
    assert report["declared_mlflow_version"] == "3.15.1"


def test_deployed_version_match_stays_healthy(monkeypatch) -> None:
    rc, report = _deployed_probe(monkeypatch, deployed=b"3.15.1", declared="3.15.1")
    assert rc == 0
    assert report["overall"] == "healthy"


def test_unreadable_deployed_version_is_a_visible_warning(monkeypatch) -> None:
    # /version 404s (deployed=None) — the probe must degrade to a WARNING the
    # hourly cron surfaces, never to a silent pass and never to a false
    # mismatch page.
    rc, report = _deployed_probe(monkeypatch, deployed=None, declared="3.15.1")
    assert rc == 2
    assert "deployed_version_unavailable" in report["warnings"]
    rc_garbage, report_garbage = _deployed_probe(
        monkeypatch, deployed=b"<html>proxy error</html>", declared="3.15.1"
    )
    assert rc_garbage == 2
    assert "deployed_version_unavailable" in report_garbage["warnings"]


def test_declared_pin_parses_from_the_real_service_requirements() -> None:
    """Binds the default path to the actual repo file: exists + parseable."""
    declared = health.declared_mlflow_pin(health.DEFAULT_DECLARED_REQUIREMENTS)
    assert declared.count(".") >= 1


def test_declared_pin_fails_loud_without_a_pin(tmp_path) -> None:
    orphan = tmp_path / "requirements.txt"
    orphan.write_text("boto3==1.0.0\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        health.declared_mlflow_pin(orphan)
