"""Allow-listed, read-only Slack ChatOps endpoint for Composio triggers."""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi import Path as ApiPath
from starlette.concurrency import run_in_threadpool

try:
    import composio_ops
except ImportError:
    from scripts import composio_ops

router = APIRouter()
_ROOT = Path(__file__).resolve().parents[2]
_STATUS_FILES = (
    _ROOT / "artifacts" / "ci" / "workflow_freshness.json",
    _ROOT / "artifacts" / "ci" / "credential_health.json",
    _ROOT / "artifacts" / "monitoring" / "evidence_freshness.json",
)


def _allowed(value: str, env_name: str) -> bool:
    allowed = {item.strip() for item in os.getenv(env_name, "").split(",") if item.strip()}
    return bool(allowed) and value in allowed


def _event(payload: dict[str, Any]) -> dict[str, Any]:
    candidate = payload.get("data")
    if candidate is None:
        candidate = payload.get("event")
    if candidate is None:
        candidate = payload
    if isinstance(candidate, dict) and isinstance(candidate.get("event"), dict):
        candidate = candidate["event"]
    return candidate if isinstance(candidate, dict) else {}


def _read_status() -> str:
    lines = ["*skipp-algo status*"]
    found = False
    for path in _STATUS_FILES:
        if not path.is_file():
            continue
        found = True
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            lines.append(f"• `{path.name}`: unreadable")
            continue
        status = payload.get("overall")
        if status is None:
            status = payload.get("overall_severity")
        if status is None:
            status = payload.get("status")
        if status is None:
            status = "available"
        lines.append(f"• `{path.name}`: *{status}*")
    if not found:
        lines.append("• No local status snapshots are mounted; inspect GitHub Actions.")
    return "\n".join(lines)


def _incident_summary() -> str:
    repo = os.getenv("GITHUB_ISSUE_REPO", "skipp-dev/skipp-algo")
    owner, _, name = repo.partition("/")
    result = composio_ops.list_github_issues(owner, name, state="open")
    if not result.delivered:
        return f"Could not read incidents: {result.detail}"
    rows: list[dict[str, Any]] = []
    if result.data:
        for key in ("items", "issues", "data"):
            if isinstance(result.data.get(key), list):
                rows = [item for item in result.data[key] if isinstance(item, dict)]
                break
    incidents = [row for row in rows if str(row.get("title", "")).startswith("[grafana]")]
    if not incidents:
        return "No open Grafana incident issues."
    lines = ["*Open Grafana incidents*"]
    for row in incidents[:10]:
        lines.append(f"• #{row.get('number', '?')} {row.get('title', 'untitled')}")
    return "\n".join(lines)


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    event = _event(payload)
    user_value = event.get("user")
    if user_value is None:
        user_value = event.get("user_id")
    channel_value = event.get("channel")
    if channel_value is None:
        channel_value = event.get("channel_id")
    timestamp_value = event.get("ts")
    if timestamp_value is None:
        timestamp_value = event.get("timestamp")
    user = str(user_value) if user_value is not None else ""
    channel = str(channel_value) if channel_value is not None else ""
    text_value = event.get("text")
    text = str(text_value).strip() if text_value is not None else ""
    timestamp = str(timestamp_value) if timestamp_value is not None else ""
    if event.get("bot_id") or not text:
        return {"ok": True, "ignored": "bot-or-empty"}
    if not _allowed(user, "COMPOSIO_CHATOPS_ALLOWED_USERS"):
        raise HTTPException(status_code=403, detail="Slack user is not allow-listed")
    if not _allowed(channel, "COMPOSIO_CHATOPS_ALLOWED_CHANNELS"):
        raise HTTPException(status_code=403, detail="Slack channel is not allow-listed")

    command = text.lower().removeprefix("@skipp ").removeprefix("skipp ").strip()
    if command in {"help", ""}:
        reply = "Commands: `status`, `incidents`, `help`. All commands are read-only."
    elif command == "status":
        reply = _read_status()
    elif command == "incidents":
        reply = _incident_summary()
    else:
        reply = "Unknown command. Use `skipp help`."
    thread_ts = timestamp if timestamp else None
    delivery = composio_ops.send_slack_channel_message(channel, reply[:3900], thread_ts=thread_ts)
    return {"ok": delivery.delivered, "detail": delivery.detail}


@router.api_route("/{token}/composio-chatops", methods=["POST"], include_in_schema=False)
async def webhook(request: Request, token: str = ApiPath(...)) -> dict[str, Any]:
    expected = os.getenv("COMPOSIO_CHATOPS_WEBHOOK_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Composio ChatOps is not configured")
    if not hmac.compare_digest(token.encode(), expected.encode()):  # bytes: a non-ASCII path token would make the str form raise
        raise HTTPException(status_code=401, detail="invalid webhook token")
    try:
        payload = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="webhook body must be an object")
    return await run_in_threadpool(handle, payload)
