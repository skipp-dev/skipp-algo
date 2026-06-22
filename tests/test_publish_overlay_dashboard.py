from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.publish_overlay_dashboard import _get_token, _prepare_legacy_payload, _prepare_payload, main


def test_get_token_prefers_cli_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAFANA_API_TOKEN", "env-token")
    assert _get_token("cli-token", "svc", "GRAFANA_API_TOKEN") == "cli-token"


def test_get_token_reads_primary_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTOM_GRAFANA_TOKEN", "primary-token")
    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "primary-token"


def test_get_token_reads_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.setenv("GRAFANA_TOKEN", "fallback-token")
    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "fallback-token"


def test_get_token_no_keychain_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    with pytest.raises(SystemExit, match="keychain lookup disabled"):
        _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN", no_keychain=True)


def test_get_token_keychain_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    def _fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="kc-token\n")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "kc-token"


def test_get_token_keychain_success_sets_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    captured: dict[str, object] = {}

    def _fake_run(*_args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="kc-token\n")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "kc-token"
    assert captured.get("timeout") == 10


def test_get_token_keychain_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    def _fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=["security"])

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(SystemExit, match="Could not obtain Grafana API token"):
        _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN")


def test_get_token_keychain_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    def _fake_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=["security"], timeout=10)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(SystemExit, match="Could not obtain Grafana API token"):
        _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN")


def test_prepare_payload_keeps_v2_shape_for_api_v1_endpoint() -> None:
    data = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": "smc-live-overlay-v1", "labels": {"team": "ops"}},
        "spec": {"elements": {}},
    }

    payload = _prepare_payload(data, "sync from test")

    assert payload["apiVersion"] == "dashboard.grafana.app/v2"
    assert payload["kind"] == "Dashboard"
    assert payload["metadata"]["name"] == "smc-live-overlay-v1"
    assert payload["metadata"]["labels"] == {"team": "ops"}
    assert payload["metadata"]["annotations"]["grafana.app/message"] == "sync from test"
    assert payload["spec"] == {"elements": {}}


def test_get_token_custom_env_then_default_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.setenv("GRAFANA_API_TOKEN", "default-token")
    monkeypatch.setenv("GRAFANA_TOKEN", "fallback-token")

    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "default-token"


def test_prepare_legacy_payload_rejects_v2_dashboard_shape() -> None:
    payload = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {
            "name": "smc-live-overlay-v1",
            "annotations": {"grafana.app/message": "from test"},
        },
        "spec": {"elements": {}},
    }

    with pytest.raises(SystemExit, match="fallback /api/dashboards/db endpoint is incompatible"):
        _prepare_legacy_payload(payload)


def test_prepare_legacy_payload_wraps_legacy_shape_with_message() -> None:
    payload = {
        "title": "smc-live-overlay-v1",
        "panels": [],
        "metadata": {
            "annotations": {"grafana.app/message": "from test"},
        },
    }

    wrapped = _prepare_legacy_payload(payload)
    assert wrapped["dashboard"] is payload
    assert wrapped["overwrite"] is True
    assert wrapped["message"] == "from test"


def test_main_dry_run_prints_summary_only_by_default(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GRAFANA_API_TOKEN", "env-token")
    path = tmp_path / "dashboard.json"
    path.write_text(
        '{"apiVersion":"dashboard.grafana.app/v2","kind":"Dashboard","metadata":{"name":"smc-live-overlay-v1"},"spec":{"elements":{}}}',
        encoding="utf-8",
    )

    rc = main([str(path), "--dry-run"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Dry-run: no network request sent." in out
    assert '"endpoint_primary": "https://bronzeporridge977.grafana.net/api/v1/dashboards"' in out
    assert '"endpoint_fallback": "https://bronzeporridge977.grafana.net/api/dashboards/db"' in out
    assert '"spec_elements": 0' in out
    assert '"spec": {' not in out


def test_main_dry_run_full_prints_payload(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("GRAFANA_API_TOKEN", "env-token")
    path = tmp_path / "dashboard.json"
    path.write_text(
        '{"apiVersion":"dashboard.grafana.app/v2","kind":"Dashboard","metadata":{"name":"smc-live-overlay-v1"},"spec":{"elements":{}}}',
        encoding="utf-8",
    )

    rc = main([str(path), "--dry-run", "--dry-run-full"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Payload:" in out
    assert '"spec": {' in out
