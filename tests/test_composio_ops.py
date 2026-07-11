"""Unit tests for ``scripts/composio_ops.py`` — the fail-soft Composio client.

No network: the ``composio`` SDK is replaced by an in-process fake so we can
assert the wrapper's contract (skip-when-unconfigured, never-raise, response
interpretation, DM channel resolution) without a real API key.
"""

from __future__ import annotations

import sys
import types
from typing import Any

from scripts import composio_ops


def _install_fake_composio(monkeypatch, execute_impl) -> None:
    module = types.ModuleType("composio")

    class _Tools:
        def execute(self, slug: str, **kwargs: Any) -> Any:
            return execute_impl(slug, kwargs)

    class Composio:  # mirrors the real class name
        def __init__(self, api_key: str | None = None) -> None:
            self.api_key = api_key
            self.tools = _Tools()

    module.Composio = Composio  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "composio", module)


def test_skips_without_api_key(monkeypatch):
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    result = composio_ops.execute_tool("SLACK_SEND_MESSAGE", {"channel": "x"})
    assert result.skipped and not result.ok and not result.delivered


def test_skips_when_sdk_missing(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    monkeypatch.setitem(sys.modules, "composio", None)  # forces ImportError
    result = composio_ops.execute_tool("SLACK_SEND_MESSAGE", {})
    assert result.skipped and "not installed" in result.detail


def test_success_passes_arguments_and_user_id(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    seen: dict[str, Any] = {}

    def impl(slug, kwargs):
        seen["slug"] = slug
        seen["kwargs"] = kwargs
        return {"successful": True, "data": {"ok": 1}}

    _install_fake_composio(monkeypatch, impl)
    result = composio_ops.execute_tool("SLACK_OPEN_DM", {"users": "U1"}, toolkit="slack")
    assert result.delivered
    assert seen["slug"] == "SLACK_OPEN_DM"
    assert seen["kwargs"]["arguments"] == {"users": "U1"}
    assert seen["kwargs"]["user_id"] == "default"
    assert "connected_account_id" not in seen["kwargs"]


def test_connected_account_from_env(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    monkeypatch.setenv("COMPOSIO_SLACK_ACCOUNT_ID", "acc_1")
    seen: dict[str, Any] = {}
    _install_fake_composio(monkeypatch, lambda s, k: seen.update(k) or {"successful": True})
    composio_ops.execute_tool("SLACK_SEND_MESSAGE", {}, toolkit="slack")
    assert seen["connected_account_id"] == "acc_1"


def test_reports_provider_failure(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    _install_fake_composio(
        monkeypatch, lambda s, k: {"successful": False, "error": "channel_not_found"}
    )
    result = composio_ops.execute_tool("SLACK_SEND_MESSAGE", {})
    assert not result.ok and not result.skipped and "channel_not_found" in result.detail


def test_swallows_sdk_exception(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")

    def boom(slug, kwargs):
        raise RuntimeError("network down")

    _install_fake_composio(monkeypatch, boom)
    result = composio_ops.execute_tool("X", {})
    assert not result.ok and not result.skipped and "network down" in result.detail


def test_notify_slack_prefers_dm(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    monkeypatch.setenv("SLACK_ALERT_USER_ID", "U9")
    monkeypatch.delenv("SLACK_ALERT_CHANNEL", raising=False)
    seq: list[str] = []

    def impl(slug, kwargs):
        seq.append(slug)
        if slug == "SLACK_OPEN_DM":
            return {"successful": True, "data": {"channel": {"id": "D9"}}}
        return {"successful": True, "data": {}}

    _install_fake_composio(monkeypatch, impl)
    result = composio_ops.notify_slack("hi")
    assert result.delivered
    assert seq == ["SLACK_OPEN_DM", "SLACK_SEND_MESSAGE"]


def test_notify_slack_channel_fallback(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    monkeypatch.delenv("SLACK_ALERT_USER_ID", raising=False)
    monkeypatch.setenv("SLACK_ALERT_CHANNEL", "ops-alerts")
    seen: dict[str, Any] = {}
    _install_fake_composio(monkeypatch, lambda s, k: seen.update({"slug": s, **k}) or {"successful": True})
    result = composio_ops.notify_slack("hi")
    assert result.delivered
    assert seen["slug"] == "SLACK_SEND_MESSAGE"
    assert seen["arguments"]["channel"] == "ops-alerts"


def test_notify_slack_skips_unconfigured(monkeypatch):
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    monkeypatch.delenv("SLACK_ALERT_USER_ID", raising=False)
    monkeypatch.delenv("SLACK_ALERT_CHANNEL", raising=False)
    result = composio_ops.notify_slack("hi")
    assert result.skipped


def test_is_configured(monkeypatch):
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    assert composio_ops.is_configured() is False
    monkeypatch.setenv("COMPOSIO_API_KEY", "k")
    assert composio_ops.is_configured() is True
