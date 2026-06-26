"""Tests + guard rails for ``scripts/grafana_alert_rules_upsert.py``.

These tests are the safety net that keeps the Grafana alerting deploy
reproducible from the repo: they fail CI if ``alert-rules.yaml`` becomes
structurally invalid, if the upsert payload/endpoint regresses, or if the
live-news refresh workflow regresses to the ``--newsapi-only`` flag that
previously disabled the FMP / TradingView providers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "grafana_alert_rules_upsert.py"
ALERT_RULES = REPO / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"
NEWSAPI_WORKFLOW = REPO / ".github" / "workflows" / "smc-live-newsapi-refresh.yml"


def _load():
    spec = importlib.util.spec_from_file_location("grafana_alert_rules_upsert", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["grafana_alert_rules_upsert"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


# --------------------------------------------------------------------------- #
# parse_interval_seconds
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "expected"),
    [("1m", 60), ("5m", 300), ("30s", 30), ("1h", 3600), ("90", 90), (120, 120)],
)
def test_parse_interval_seconds_ok(value: Any, expected: int) -> None:
    assert mod.parse_interval_seconds(value) == expected


@pytest.mark.parametrize("value", ["", "abc", "1x", 0, -5, True, None, 1.5])
def test_parse_interval_seconds_rejects_bad(value: Any) -> None:
    with pytest.raises(ValueError):
        mod.parse_interval_seconds(value)


# --------------------------------------------------------------------------- #
# validate_alert_groups against the real repo file
# --------------------------------------------------------------------------- #
def test_repo_alert_rules_are_structurally_valid() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    errors = mod.validate_alert_groups(groups)
    assert errors == [], "alert-rules.yaml structural errors:\n" + "\n".join(errors)


def test_repo_alert_rule_uids_are_globally_unique() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = [r["uid"] for g in groups for r in g["rules"]]
    assert len(uids) == len(set(uids))


def test_validate_flags_duplicate_uid_and_bad_refs() -> None:
    groups = [
        {
            "name": "g1",
            "folder": "F",
            "interval": "1m",
            "rules": [
                {
                    "uid": "dup",
                    "title": "ok rule",
                    "condition": "A",
                    "for": "0s",
                    "data": [{"refId": "A", "datasourceUid": "x", "model": {}}],
                },
                {
                    "uid": "dup",  # duplicate
                    "title": "bad ref",
                    "condition": "Z",  # not among refIds
                    "for": "0s",
                    "data": [{"refId": "A", "datasourceUid": "x", "model": {}}],
                },
            ],
        }
    ]
    errors = mod.validate_alert_groups(groups)
    joined = "\n".join(errors)
    assert "duplicate uid 'dup'" in joined
    assert "condition 'Z'" in joined


def test_validate_flags_missing_fields() -> None:
    errors = mod.validate_alert_groups(
        [{"name": "", "folder": "", "interval": "nope", "rules": []}]
    )
    assert any("missing/empty 'name'" in e for e in errors)
    assert any("'rules' must be a non-empty list" in e for e in errors)


# --------------------------------------------------------------------------- #
# payload construction
# --------------------------------------------------------------------------- #
def test_build_rule_group_payload_shape() -> None:
    group = mod.load_alert_groups(ALERT_RULES)[0]
    payload = mod.build_rule_group_payload(group, "folder-uid-123")
    assert payload["folderUid"] == "folder-uid-123"
    assert payload["title"] == group["name"]
    assert isinstance(payload["interval"], int) and payload["interval"] > 0
    assert payload["rules"], "expected at least one rule"
    rule = payload["rules"][0]
    for key in ("uid", "title", "condition", "data", "for", "folderUID", "ruleGroup", "orgID", "noDataState", "execErrState"):
        assert key in rule, f"missing {key} in provisioned rule"
    assert rule["folderUID"] == "folder-uid-123"
    assert rule["ruleGroup"] == group["name"]
    assert rule["noDataState"] == mod.DEFAULT_NO_DATA_STATE
    assert rule["execErrState"] == mod.DEFAULT_EXEC_ERR_STATE


# --------------------------------------------------------------------------- #
# HTTP layer with mocked urlopen
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_resolve_folder_uid_matches_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    def fake_urlopen(req, timeout=0):
        assert req.get_method() == "GET"
        assert "/api/folders" in req.full_url
        return _FakeResp(json.dumps([{"title": "SMC Live Overlay", "uid": "abc"}]).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.resolve_folder_uid("SMC Live Overlay", "key") == "abc"


def test_resolve_folder_uid_creates_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    calls: list[tuple[str, str]] = []

    def fake_urlopen(req, timeout=0):
        calls.append((req.get_method(), req.full_url))
        if req.get_method() == "GET":
            return _FakeResp(json.dumps([]).encode())
        return _FakeResp(json.dumps({"uid": "new-uid"}).encode())

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod.resolve_folder_uid("New Folder", "key") == "new-uid"
    assert calls[0][0] == "GET"
    assert calls[1][0] == "POST"


def test_upsert_group_uses_rule_group_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout=0):
        method = req.get_method()
        if method == "GET":
            return _FakeResp(json.dumps([{"title": "SMC Live Overlay", "uid": "fuid"}]).encode())
        captured["method"] = method
        captured["url"] = req.full_url
        captured["provenance"] = req.headers.get("X-disable-provenance")
        captured["body"] = json.loads(req.data.decode())
        return _FakeResp(b"")

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    group = mod.load_alert_groups(ALERT_RULES)[0]
    written = mod.upsert_group(group, "key")
    assert written == len(group["rules"])
    assert captured["method"] == "PUT"
    assert f"/api/v1/provisioning/folder/fuid/rule-groups/{group['name']}" in captured["url"]
    assert captured["provenance"] == "true"
    assert captured["body"]["folderUid"] == "fuid"


def test_api_key_prefers_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(mod.ENV_API_KEY, "env-token")
    assert mod._api_key() == "env-token"


def test_main_dry_run_validates_without_network(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*a: object, **k: object) -> None:  # network must not be touched
        raise AssertionError("network call during --dry-run")

    monkeypatch.setattr(mod.urllib.request, "urlopen", boom)
    rc = mod.main(["--dry-run"])
    assert rc == 0
    assert "Validated" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Regression guard: the live-news refresh workflow must keep FMP / TradingView on
# --------------------------------------------------------------------------- #
def test_newsapi_refresh_workflow_keeps_fmp_and_tradingview_enabled() -> None:
    text = NEWSAPI_WORKFLOW.read_text(encoding="utf-8")
    # Inspect only real shell lines (ignore YAML comments, which may mention the
    # historical flag) and reject an *active* ``--newsapi-only`` export argument.
    active_lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert not any("--newsapi-only" in ln for ln in active_lines), (
        "smc-live-newsapi-refresh.yml must not run the export with --newsapi-only "
        "(that disables FMP + TradingView despite active subscriptions)."
    )
    active_text = "\n".join(active_lines)
    # The active export command must enable Benzinga and inject both API keys.
    assert "--skip-benzinga" not in active_text
    assert "FMP_API_KEY" in active_text
    assert "BENZINGA_API_KEY" in active_text


# --------------------------------------------------------------------------- #
# Dashboard-review regression guards
# --------------------------------------------------------------------------- #
def test_alert_workers_degraded_and_overlay_stale_include_job_filter() -> None:
    """All live-overlay alerts must scope to job="live_overlay"."""
    groups = mod.load_alert_groups(ALERT_RULES)
    for group in groups:
        for rule in group["rules"]:
            if rule["uid"] in ("lo-workers-degraded", "lo-overlay-stale"):
                expr = rule["data"][0]["model"]["expr"]
                assert 'job="live_overlay"' in expr, (
                    f"{rule['uid']} is missing job filter: {expr}"
                )


def test_alert_rules_include_tradingview_credential_age() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-tradingview-credential-age-high" in uids
    rule = next(
        r for g in groups for r in g["rules"]
        if r["uid"] == "lo-tradingview-credential-age-high"
    )
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_tradingview_credential_age_hours" in expr
    assert 'job="live_overlay"' in expr


def test_alert_rules_include_ingest_queue_lag() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-ingest-queue-lag-high" in uids
    rule = next(
        r for g in groups for r in g["rules"] if r["uid"] == "lo-ingest-queue-lag-high"
    )
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_feed_ingest_queue_lag_ms_max" in expr
    assert rule["labels"]["severity"] == "warning"


def test_alert_rules_include_daemon_restarts_high() -> None:
    groups = mod.load_alert_groups(ALERT_RULES)
    uids = {r["uid"] for g in groups for r in g["rules"]}
    assert "lo-daemon-restarts-high" in uids
    rule = next(
        r for g in groups for r in g["rules"] if r["uid"] == "lo-daemon-restarts-high"
    )
    expr = rule["data"][0]["model"]["expr"]
    assert "increase(live_overlay_daemon_restarts_total" in expr
    assert "[24h]" in expr
    assert rule["labels"]["severity"] == "high"
