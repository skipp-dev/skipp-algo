from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.publish_overlay_dashboard import (
    _get_token,
    _load_dashboard,
    _post,
    _prepare_legacy_payload,
    _prepare_payload,
    main,
)


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

    monkeypatch.setattr("scripts.publish_overlay_dashboard.shutil.which", lambda _name: "/usr/bin/security")
    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "kc-token"


def test_get_token_keychain_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    def _fake_run(*_args, **_kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=["security"])

    monkeypatch.setattr("scripts.publish_overlay_dashboard.shutil.which", lambda _name: "/usr/bin/security")
    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(SystemExit, match="Could not obtain Grafana API token"):
        _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN")


def test_prepare_payload_wraps_classic_dashboard_into_apis_v1() -> None:
    data = {"uid": "smc-live-overlay-v1", "title": "SMC", "schemaVersion": 39, "panels": [{"type": "stat"}]}

    payload = _prepare_payload(data, "sync from test", "cfpozahbhfzswc")

    assert payload["apiVersion"] == "dashboard.grafana.app/v1"
    assert payload["kind"] == "Dashboard"
    assert payload["metadata"]["name"] == "smc-live-overlay-v1"
    assert payload["metadata"]["annotations"]["grafana.app/message"] == "sync from test"
    assert payload["metadata"]["annotations"]["grafana.app/folder"] == "cfpozahbhfzswc"
    # Classic model is carried unchanged inside spec (no v2alpha elements rewrite).
    assert payload["spec"] is data
    assert payload["spec"]["panels"] == [{"type": "stat"}]


@pytest.mark.parametrize("folder", ["", "   ", "\t", None])
def test_prepare_payload_omits_folder_annotation_when_blank(folder: str | None) -> None:
    payload = _prepare_payload({"uid": "u1", "panels": []}, "msg", folder)

    assert "grafana.app/folder" not in payload["metadata"]["annotations"]
    assert payload["metadata"]["annotations"] == {"grafana.app/message": "msg"}


def test_prepare_payload_strips_folder_whitespace() -> None:
    payload = _prepare_payload({"uid": "u1", "panels": []}, "msg", "  cfpozahbhfzswc  ")

    assert payload["metadata"]["annotations"]["grafana.app/folder"] == "cfpozahbhfzswc"


def test_prepare_payload_accepts_v2_input_and_uses_metadata_name() -> None:
    data = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": "smc-live-overlay-v1"},
        "spec": {"panels": []},
    }

    payload = _prepare_payload(data, "msg", None)

    assert payload["apiVersion"] == "dashboard.grafana.app/v1"
    assert payload["metadata"]["name"] == "smc-live-overlay-v1"
    assert payload["spec"] == {"panels": []}


def test_prepare_payload_missing_uid_raises() -> None:
    with pytest.raises(SystemExit, match="missing a uid"):
        _prepare_payload({"title": "no uid", "panels": []}, "msg", None)


@pytest.mark.parametrize("bad_annotations", [None, [], "x", 42])
def test_prepare_payload_normalizes_non_dict_annotations(bad_annotations: object) -> None:
    # Source metadata may carry "annotations" as null or a non-mapping value;
    # _prepare_payload must normalize it instead of raising a TypeError.
    data = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {"name": "smc-live-overlay-v1", "annotations": bad_annotations},
        "spec": {"elements": {}},
    }

    payload = _prepare_payload(data, "sync from test")

    assert payload["metadata"]["annotations"] == {"grafana.app/message": "sync from test"}


def test_prepare_payload_preserves_existing_annotation_keys() -> None:
    data = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": {
            "name": "smc-live-overlay-v1",
            "annotations": {"grafana.app/folder": "ops"},
        },
        "spec": {"elements": {}},
    }

    payload = _prepare_payload(data, "sync from test")

    assert payload["metadata"]["annotations"] == {
        "grafana.app/folder": "ops",
        "grafana.app/message": "sync from test",
    }


@pytest.mark.parametrize("bad_metadata", [None, [], "x", 42])
def test_prepare_payload_normalizes_non_dict_metadata(bad_metadata: object) -> None:
    data = {
        "apiVersion": "dashboard.grafana.app/v2",
        "kind": "Dashboard",
        "metadata": bad_metadata,
        "spec": {"elements": {}},
    }

    payload = _prepare_payload(data, "sync from test")

    assert payload["metadata"] == {
        "annotations": {"grafana.app/message": "sync from test"},
    }


def test_get_token_custom_env_then_default_then_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTOM_GRAFANA_TOKEN", raising=False)
    monkeypatch.setenv("GRAFANA_API_TOKEN", "default-token")
    monkeypatch.setenv("GRAFANA_TOKEN", "fallback-token")

    assert _get_token(None, "svc", "CUSTOM_GRAFANA_TOKEN") == "default-token"


def test_prepare_legacy_payload_wraps_payload_with_message() -> None:
    dashboard = {
        "title": "legacy-dashboard",
        "panels": [],
    }

    wrapped = _prepare_legacy_payload(dashboard, "from test")
    assert wrapped["dashboard"] is dashboard
    assert wrapped["overwrite"] is True
    assert wrapped["message"] == "from test"


def test_load_dashboard_accepts_legacy_v1_shape(tmp_path: Path) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps({"title": "legacy", "panels": []}), encoding="utf-8")

    loaded = _load_dashboard(path)
    assert loaded["title"] == "legacy"
    assert loaded["panels"] == []


def test_main_dry_run_prints_summary_only_by_default(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text(
        '{"uid":"smc-live-overlay-v1","schemaVersion":39,"panels":[{"type":"stat"}]}',
        encoding="utf-8",
    )

    rc = main([str(path), "--dry-run"])
    out = capsys.readouterr().out

    create_ep = (
        '"endpoint_create": "https://bronzeporridge977.grafana.net'
        '/apis/dashboard.grafana.app/v1/namespaces/default/dashboards"'
    )
    assert rc == 0
    assert "Dry-run: no network request sent." in out
    assert '"api_surface": "dashboard.grafana.app/v1"' in out
    assert '"namespace": "default"' in out
    assert '"uid": "smc-live-overlay-v1"' in out
    assert create_ep in out
    assert '"endpoint_legacy_fallback": "https://bronzeporridge977.grafana.net/api/dashboards/db"' in out
    assert '"spec_panels": 1' in out
    assert '"spec": {' not in out


def test_main_dry_run_full_prints_payload(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text('{"uid":"u1","schemaVersion":39,"panels":[]}', encoding="utf-8")

    rc = main([str(path), "--dry-run", "--dry-run-full"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Payload:" in out
    assert '"spec": {' in out
    assert '"apiVersion": "dashboard.grafana.app/v1"' in out


def test_main_dry_run_custom_namespace_overrides_default(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    path = tmp_path / "dashboard.json"
    path.write_text('{"uid":"u1","panels":[]}', encoding="utf-8")

    rc = main([str(path), "--dry-run", "--namespace", "stacks-12345"])
    out = capsys.readouterr().out

    assert rc == 0
    assert '"namespace": "stacks-12345"' in out
    assert "namespaces/stacks-12345/dashboards" in out


def _apis_payload() -> dict:
    return {
        "apiVersion": "dashboard.grafana.app/v1",
        "kind": "Dashboard",
        "metadata": {"name": "u1", "annotations": {"grafana.app/message": "m"}},
        "spec": {"panels": []},
    }


def test_post_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request_json(url, _token, *, method, payload=None):
        calls.append((method, url))
        if method == "GET":
            return 404, {}
        return 201, {"metadata": {"name": "u1", "resourceVersion": "5"}}

    monkeypatch.setattr("scripts.publish_overlay_dashboard._request_json", fake_request_json)
    body, endpoint = _post("h", "t", _apis_payload(), namespace="default", uid="u1", message="m")

    assert calls[0][0] == "GET"
    assert calls[1][0] == "POST"
    assert calls[1][1].endswith("/dashboards")
    # Create reports the collection endpoint (POST), not the per-uid path.
    assert endpoint.startswith("POST ")
    assert endpoint.endswith("/dashboards")
    assert body["metadata"]["resourceVersion"] == "5"


def test_post_updates_with_resource_version_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_request_json(url, _token, *, method, payload=None):
        if method == "GET":
            return 200, {"metadata": {"resourceVersion": "42"}}
        seen.update(method=method, url=url, payload=payload)
        return 200, {"metadata": {"name": "u1", "resourceVersion": "43"}}

    monkeypatch.setattr("scripts.publish_overlay_dashboard._request_json", fake_request_json)
    _body, endpoint = _post("h", "t", _apis_payload(), namespace="default", uid="u1", message="m")

    assert seen["method"] == "PUT"
    assert seen["url"].endswith("/dashboards/u1")
    assert seen["payload"]["metadata"]["resourceVersion"] == "42"
    # Update reports the per-uid endpoint (PUT).
    assert endpoint.startswith("PUT ")
    assert endpoint.endswith("/dashboards/u1")


def test_post_raises_on_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_json(_url, _token, *, method, payload=None):
        if method == "GET":
            return 200, {"metadata": {"resourceVersion": "42"}}
        return 409, {"message": "conflict"}

    monkeypatch.setattr("scripts.publish_overlay_dashboard._request_json", fake_request_json)
    with pytest.raises(SystemExit, match="409 conflict"):
        _post("h", "t", _apis_payload(), namespace="default", uid="u1", message="m")


def test_post_falls_back_to_legacy_on_apis_404(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request_json(url, _token, *, method, payload=None):
        calls.append((method, url))
        if method == "GET":
            return 404, {}
        if "/apis/" in url:
            return 404, {}
        return 200, {"metadata": {"name": "u1"}}

    monkeypatch.setattr("scripts.publish_overlay_dashboard._request_json", fake_request_json)
    _body, endpoint = _post("h", "t", _apis_payload(), namespace="default", uid="u1", message="m")

    assert endpoint == "POST https://h/api/dashboards/db"
    assert calls[-1][1].endswith("/api/dashboards/db")


def test_post_raises_on_404_when_app_platform_base_is_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """404 from PUT/POST while the App Platform base is reachable must raise, not fall back."""

    def fake_request_json(url, _token, *, method, payload=None):
        if method == "GET" and url.endswith("/dashboards/u1"):
            return 200, {"metadata": {"name": "u1", "resourceVersion": "42"}}
        if method == "GET" and url.endswith("/v1"):
            # Probe: API group base is reachable (e.g. wrong namespace, not absent platform).
            return 200, {}
        # PUT to collection/{uid} returns 404 (wrong namespace).
        return 404, {"message": "not found"}

    monkeypatch.setattr("scripts.publish_overlay_dashboard._request_json", fake_request_json)
    with pytest.raises(SystemExit, match="API-group base is reachable"):
        _post("h", "t", _apis_payload(), namespace="wrong-ns", uid="u1", message="m")


def test_get_resource_version_raises_on_200_without_resource_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 response without metadata.resourceVersion must raise SystemExit (not return None)."""
    from scripts.publish_overlay_dashboard import _get_resource_version

    def fake_request_json(url, _token, *, method, payload=None):
        return 200, {"metadata": {"name": "u1"}}  # missing resourceVersion

    monkeypatch.setattr("scripts.publish_overlay_dashboard._request_json", fake_request_json)
    with pytest.raises(SystemExit, match="resourceVersion"):
        _get_resource_version("h", "t", "default", "u1")
