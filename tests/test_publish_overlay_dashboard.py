from __future__ import annotations

import subprocess

import pytest

from scripts.publish_overlay_dashboard import _get_token, _prepare_payload


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


def test_get_token_keychain_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    def _fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=["security"])

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(SystemExit, match="Could not obtain Grafana API token"):
        _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN")


def test_prepare_payload_wraps_v2_dashboard_for_legacy_endpoint() -> None:
    data = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": "smc-live-overlay-v1", "labels": {"team": "ops"}},
        "spec": {"elements": {}},
    }

    payload = _prepare_payload(data, "sync from test")

    assert payload["dashboard"] is data
    assert payload["overwrite"] is True
    assert payload["message"] == "sync from test"
