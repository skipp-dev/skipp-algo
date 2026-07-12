from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from scripts import composio_calendar_sync, composio_ops, notion_research_digest
from services.live_overlay_daemon import composio_chatops

ROOT = Path(__file__).resolve().parents[1]


def test_every_tool_is_versioned_and_access_scoped():
    registry = composio_ops.tool_registry()
    assert registry
    for spec in registry.values():
        assert spec["version"].startswith("2026")
        assert spec["access"] in {"read", "write"}


def test_composio_workflows_are_pinned():
    """Keep composio-canary and composio-publish out of the orphan inventory."""
    canary = (ROOT / ".github/workflows/composio-canary.yml").read_text(encoding="utf-8")
    publish = (ROOT / ".github/workflows/composio-publish.yml").read_text(encoding="utf-8")
    assert "composio_contract_check.py" in canary
    assert "composio_canary.py" in canary
    assert "notion_research_digest.py" in publish
    assert "composio_calendar_sync.py" in publish


def test_calendar_sync_is_idempotently_keyed(tmp_path, monkeypatch):
    path = tmp_path / "events.json"
    path.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "subject": "Review",
                        "start": "2026-07-13T10:00:00Z",
                        "end": "2026-07-13T10:30:00Z",
                    }
                ]
            }
        )
    )
    calls = []

    def create(*args, **kwargs):
        calls.append((args, kwargs))
        return composio_ops.DeliveryResult(True, False, "ok")

    monkeypatch.setattr(composio_calendar_sync.composio_ops, "create_outlook_event", create)
    report = composio_calendar_sync.sync(path, now=datetime(2026, 7, 12, tzinfo=UTC))
    assert report["ok"] and len(calls) == 1
    assert calls[0][1]["transaction_id"].startswith("skipp-")


def test_notion_digest_is_repo_evidence():
    title, markdown = notion_research_digest.render()
    assert "skipp-algo research digest" in title
    assert "Recent promotion decisions" in markdown
    assert "Not a trading instruction" in markdown


def test_chatops_is_allowlisted_and_replies_in_thread(monkeypatch):
    monkeypatch.setenv("COMPOSIO_CHATOPS_ALLOWED_USERS", "U1")
    monkeypatch.setenv("COMPOSIO_CHATOPS_ALLOWED_CHANNELS", "C1")
    calls = []

    def send(channel, text, *, thread_ts=None):
        calls.append((channel, text, thread_ts))
        return composio_ops.DeliveryResult(True, False, "ok")

    monkeypatch.setattr(composio_chatops.composio_ops, "send_slack_channel_message", send)
    result = composio_chatops.handle({"event": {"user": "U1", "channel": "C1", "text": "skipp help", "ts": "1.2"}})
    assert result["ok"]
    assert calls == [("C1", "Commands: `status`, `incidents`, `help`. All commands are read-only.", "1.2")]


def test_chatops_rejects_unknown_user(monkeypatch):
    monkeypatch.setenv("COMPOSIO_CHATOPS_ALLOWED_USERS", "U1")
    monkeypatch.setenv("COMPOSIO_CHATOPS_ALLOWED_CHANNELS", "C1")
    try:
        composio_chatops.handle({"event": {"user": "U2", "channel": "C1", "text": "skipp status"}})
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("unknown user was accepted")
