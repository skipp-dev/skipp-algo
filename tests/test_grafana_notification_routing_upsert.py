"""Tests + guard rails for ``scripts/grafana_notification_routing_upsert.py``.

Keeps the Grafana *routing* (contact points + notification policy) reproducible
from the repo the same way ``test_grafana_alert_rules_upsert.py`` does for the
rules: fail CI if ``notification-routing.yaml`` becomes structurally invalid, if
the Slack contact point / severity route silently drifts, if a secret would be
committed instead of referenced via ``${...}``, or if the upsert
payload/endpoint regresses.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "grafana_notification_routing_upsert.py"
ROUTING = REPO / "services" / "live_overlay_daemon" / "infra" / "grafana" / "notification-routing.yaml"
WORKFLOW = REPO / ".github" / "workflows" / "live-overlay-notification-routing-publish.yml"


def _load():
    spec = importlib.util.spec_from_file_location("grafana_notification_routing_upsert", SCRIPT)
    assert spec and spec.loader
    modu = importlib.util.module_from_spec(spec)
    sys.modules["grafana_notification_routing_upsert"] = modu
    spec.loader.exec_module(modu)
    return modu


mod = _load()


# --------------------------------------------------------------------------- #
# The committed routing file
# --------------------------------------------------------------------------- #
def test_repo_routing_is_structurally_valid() -> None:
    doc = mod.load_routing(ROUTING)
    assert mod.validate_routing(doc) == []


def test_repo_routing_pins_slack_contact_point_and_severity_route() -> None:
    """Drift guard: the intent (Slack + credential-covering severities) is pinned
    so a silent edit that drops the route or the contact point fails CI."""
    doc = mod.load_routing(ROUTING)
    cps = {c["name"]: c for c in doc["contactPoints"]}
    assert "slack-smc-alerts" in cps
    assert cps["slack-smc-alerts"]["type"] == "slack"

    policy = doc["policy"]
    assert policy["receiver"] == "slack-smc-alerts"  # catch-all root, nothing dropped
    matchers = [m for r in policy["routes"] for m in r["object_matchers"]]
    sev = next(m for m in matchers if m[0] == "severity")
    assert sev[1] == "=~"
    # critical|warning|high must ALL be covered (5 of the credential alerts are high).
    for level in ("critical", "warning", "high"):
        assert level in sev[2]


def test_repo_routing_commits_no_secret_only_a_placeholder() -> None:
    """The webhook must never be committed — only the ${SLACK_WEBHOOK_URL} ref."""
    text = ROUTING.read_text(encoding="utf-8")
    assert "hooks.slack.com" not in text
    assert "${SLACK_WEBHOOK_URL}" in text
    assert mod.find_placeholders(mod.load_routing(ROUTING)) == {"SLACK_WEBHOOK_URL"}


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_flags_missing_contact_points() -> None:
    errs = mod.validate_routing({"policy": {"receiver": "x", "routes": []}})
    assert any("contactPoints" in e for e in errs)


def test_validate_flags_dangling_receiver() -> None:
    doc = {
        "contactPoints": [{"name": "slack", "type": "slack", "settings": {"url": "x"}}],
        "policy": {"receiver": "ghost", "routes": []},
    }
    errs = mod.validate_routing(doc)
    assert any("ghost" in e and "not a defined contact point" in e for e in errs)


def test_validate_flags_bad_matcher_operator() -> None:
    doc = {
        "contactPoints": [{"name": "s", "type": "slack", "settings": {"url": "x"}}],
        "policy": {
            "receiver": "s",
            "routes": [{"receiver": "s", "object_matchers": [["severity", "BADOP", "critical"]]}],
        },
    }
    errs = mod.validate_routing(doc)
    assert any("BADOP" in e for e in errs)


# --------------------------------------------------------------------------- #
# Placeholder resolution (secret injection at apply time)
# --------------------------------------------------------------------------- #
def test_resolve_placeholders_substitutes_from_env() -> None:
    out = mod.resolve_placeholders({"url": "${SLACK_WEBHOOK_URL}"}, {"SLACK_WEBHOOK_URL": "https://x"})
    assert out == {"url": "https://x"}


def test_resolve_placeholders_fails_loud_when_unset() -> None:
    with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL"):
        mod.resolve_placeholders({"url": "${SLACK_WEBHOOK_URL}"}, {})


# --------------------------------------------------------------------------- #
# Payload shapes
# --------------------------------------------------------------------------- #
def test_build_contact_point_body_shape() -> None:
    body = mod.build_contact_point_body(
        {"name": "slack-smc-alerts", "type": "slack", "settings": {"url": "https://x"}}
    )
    assert body == {
        "name": "slack-smc-alerts",
        "type": "slack",
        "settings": {"url": "https://x"},
        "disableResolveMessage": False,
    }


def test_build_policy_body_shape() -> None:
    body = mod.build_policy_body(
        {
            "receiver": "slack-smc-alerts",
            "group_by": ["grafana_folder", "alertname"],
            "routes": [
                {"receiver": "slack-smc-alerts", "object_matchers": [["severity", "=~", "critical|warning|high"]]}
            ],
        }
    )
    assert body["receiver"] == "slack-smc-alerts"
    assert body["group_by"] == ["grafana_folder", "alertname"]
    assert body["routes"][0]["object_matchers"] == [["severity", "=~", "critical|warning|high"]]
    assert body["routes"][0]["continue"] is False


# --------------------------------------------------------------------------- #
# HTTP layer (mocked)
# --------------------------------------------------------------------------- #
def test_upsert_contact_point_creates_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        calls.append((method, path))
        if method == "GET":
            return []  # no existing contact points
        return None

    monkeypatch.setattr(mod, "_request", fake_request)
    action = mod.upsert_contact_point({"name": "slack-smc-alerts", "type": "slack", "settings": {"url": "x"}}, "k")
    assert action == "create"
    assert ("POST", "/api/v1/provisioning/contact-points") in calls


def test_upsert_contact_point_updates_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        calls.append((method, path))
        if method == "GET":
            return [{"name": "slack-smc-alerts", "uid": "abc123"}]
        return None

    monkeypatch.setattr(mod, "_request", fake_request)
    action = mod.upsert_contact_point({"name": "slack-smc-alerts", "type": "slack", "settings": {"url": "x"}}, "k")
    assert action == "update"
    assert ("PUT", "/api/v1/provisioning/contact-points/abc123") in calls


def test_put_policy_hits_policies_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_request(method: str, path: str, key: str, payload: Any = None, extra_headers: Any = None):
        seen["method"], seen["path"], seen["payload"], seen["headers"] = method, path, payload, extra_headers
        return None

    monkeypatch.setattr(mod, "_request", fake_request)
    mod.put_policy({"receiver": "slack-smc-alerts"}, "k")
    assert seen["method"] == "PUT"
    assert seen["path"] == "/api/v1/provisioning/policies"
    assert seen["headers"] == {"X-Disable-Provenance": "true"}


# --------------------------------------------------------------------------- #
# Deploy workflow wiring
# --------------------------------------------------------------------------- #
def test_workflow_deploys_routing_with_secret() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/grafana_notification_routing_upsert.py" in text
    # Secret plumbing: the webhook comes from a GitHub secret, the token reuses
    # the existing GRAFANA_API_TOKEN mapped to GRAFANA_API_KEY.
    assert "SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}" in text
    assert "GRAFANA_API_KEY: ${{ secrets.GRAFANA_API_TOKEN }}" in text
    # Push trigger must watch the routing file so a change actually deploys.
    assert "services/live_overlay_daemon/infra/grafana/notification-routing.yaml" in text
    # Dry-run preflight (validates without the secret) must run.
    assert "--dry-run" in text
