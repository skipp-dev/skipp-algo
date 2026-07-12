"""Thin, fail-soft Composio REST client for skipp-algo ops automations.

Consumers:

* ``scripts/credential_health_notify.py``            — #1 credential -> Slack DM
* ``scripts/ops_digest.py``                          — #4 daily Outlook digest
* ``services/live_overlay_daemon/grafana_composio_fanout.py`` — #3 Grafana fan-out

Transport — the **Composio REST API over pure stdlib ``urllib``**, no SDK
dependency. This keeps the module importable everywhere (the live-overlay
daemon runs from the hash-locked terminal image; the CI runners install no
extra packages) and avoids pulling Composio's heavy transitive tree
(openai/pandas/pyarrow) into any image. Verified live 2026-07-11:
``POST {base}/api/v3/tools/execute/{slug}`` with an ``x-api-key`` header and a
``{"user_id", "arguments", "connected_account_id"?}`` body returns
``{"data": ..., "successful": bool, "error": null|{...}}``.

Design contract — **ops notification is best-effort and MUST never raise into
the caller**. A missing environment-specific project key or provider/network hiccup
degrades to a *logged no-op / failed DeliveryResult*; it must never crash a
credential health check, a nightly digest cron, or the live-overlay daemon.

Config (env):
    COMPOSIO_ENVIRONMENT                       ``prod`` or ``dev``
    COMPOSIO_<ENV>_API_KEY                     project-specific ak_… key
    COMPOSIO_<ENV>_USER_ID                     project entity ID
    COMPOSIO_<TOOLKIT>_<ACCESS>_ACCOUNT_ID     mandatory read/write account pin
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://backend.composio.dev"
_TIMEOUT = 20.0
_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "configs" / "composio_tools.json"

# Tool slugs kept as module constants so a Composio-side rename is a one-line
# change here rather than a scattered string edit across three call sites.
SLACK_OPEN_DM = "SLACK_OPEN_DM"
SLACK_SEND_MESSAGE = "SLACK_SEND_MESSAGE"
GITHUB_CREATE_ISSUE = "GITHUB_CREATE_AN_ISSUE"
OUTLOOK_SEND_EMAIL = "OUTLOOK_SEND_EMAIL"
OUTLOOK_CREATE_EVENT = "OUTLOOK_CALENDAR_CREATE_EVENT"
NOTION_CREATE_PAGE = "NOTION_CREATE_NOTION_PAGE"
NOTION_APPEND_TEXT = "NOTION_APPEND_TEXT_BLOCKS"


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of an attempted Composio delivery.

    ``skipped`` distinguishes "not configured, did not attempt" from a genuine
    delivery failure so callers can stay quiet on the former and warn on the
    latter.
    """

    ok: bool
    skipped: bool
    detail: str
    data: dict[str, Any] | None = None

    @property
    def delivered(self) -> bool:
        """True only when a real send both attempted and succeeded."""
        return self.ok and not self.skipped


def is_configured() -> bool:
    """Whether a live Composio delivery could be attempted at all."""
    return bool(_api_key())


@lru_cache(maxsize=1)
def tool_registry() -> dict[str, dict[str, Any]]:
    """Return the reviewed allow-list of pinned Composio tools."""
    with _REGISTRY_PATH.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload["tools"]


def _environment() -> str:
    value = os.getenv("COMPOSIO_ENVIRONMENT", "prod").strip().lower()
    return value if value in {"prod", "dev"} else "prod"


def _api_key() -> str:
    """Select a project key explicitly by environment; never cross environments."""
    name = f"COMPOSIO_{_environment().upper()}_API_KEY"
    return os.getenv(name, "").strip()


def _base_url() -> str:
    return os.getenv("COMPOSIO_BASE_URL", _DEFAULT_BASE_URL).strip().rstrip("/") or _DEFAULT_BASE_URL


def _account_for_toolkit(toolkit: str, access: str) -> str | None:
    """Resolve a read/write-specific account; implicit account selection is forbidden."""
    value = os.getenv(f"COMPOSIO_{toolkit.upper()}_{access.upper()}_ACCOUNT_ID", "").strip()
    return value or None


def _error_message(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message") or error)
    return str(error) if error else "unknown error"


def _interpret(slug: str, payload: Any) -> DeliveryResult:
    """Normalize a parsed Composio REST response into a :class:`DeliveryResult`."""
    if isinstance(payload, dict):
        successful = payload.get("successful", payload.get("success", True))
        error = payload.get("error")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        if error or successful is False:
            return DeliveryResult(
                ok=False,
                skipped=False,
                detail=f"{slug} reported failure: {_error_message(error)}",
                data=data,
            )
        return DeliveryResult(ok=True, skipped=False, detail=f"{slug} delivered", data=data)
    return DeliveryResult(ok=True, skipped=False, detail=f"{slug} delivered (opaque response)")


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Extract Composio's structured error message from an HTTPError body."""
    try:
        parsed = json.loads(exc.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        return str(exc.reason)
    error = parsed.get("error") if isinstance(parsed, dict) else None
    return _error_message(error) if error else str(exc.reason)


def execute_tool(
    slug: str,
    arguments: dict[str, Any],
    *,
    toolkit: str | None = None,
    access: str | None = None,
    connected_account_id: str | None = None,
    opener: Any = None,
) -> DeliveryResult:
    """Execute one Composio tool over REST, fail-soft.

    Returns ``skipped=True`` when unconfigured (no API key) and never raises; a
    provider/network/HTTP error is captured and returned as a failed — but
    non-fatal — :class:`DeliveryResult`. ``opener`` is injectable for tests.
    """
    spec = tool_registry().get(slug)
    if spec is None:
        return DeliveryResult(ok=False, skipped=True, detail=f"tool {slug} is not allow-listed")
    expected_toolkit = str(spec["toolkit"])
    expected_access = str(spec["access"])
    if toolkit and toolkit != expected_toolkit:
        return DeliveryResult(ok=False, skipped=True, detail=f"toolkit mismatch for {slug}")
    if access and access != expected_access:
        return DeliveryResult(ok=False, skipped=True, detail=f"access mismatch for {slug}")

    api_key = _api_key()
    if not api_key:
        name = f"COMPOSIO_{_environment().upper()}_API_KEY"
        logger.info("composio_ops: %s unset — skipping %s (no-op)", name, slug)
        return DeliveryResult(ok=False, skipped=True, detail=f"{name} unset")

    user_name = f"COMPOSIO_{_environment().upper()}_USER_ID"
    user_id = os.getenv(user_name, "").strip()
    if not user_id:
        return DeliveryResult(ok=False, skipped=True, detail=f"{user_name} unset")
    account = connected_account_id or _account_for_toolkit(expected_toolkit, expected_access)
    if not account:
        env_name = f"COMPOSIO_{expected_toolkit.upper()}_{expected_access.upper()}_ACCOUNT_ID"
        return DeliveryResult(ok=False, skipped=True, detail=f"{env_name} unset")

    missing = [name for name in spec.get("required", []) if name not in arguments]
    if missing:
        return DeliveryResult(ok=False, skipped=True, detail=f"{slug} missing arguments: {', '.join(missing)}")
    body: dict[str, Any] = {
        "user_id": user_id,
        "arguments": arguments,
        "connected_account_id": account,
        "version": spec["version"],
    }

    request = urllib.request.Request(
        f"{_base_url()}/api/v3/tools/execute/{slug}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "skipp-algo-composio-ops/1",
        },
    )
    _opener = opener or urllib.request.build_opener()
    try:
        with _opener.open(request, timeout=_TIMEOUT) as resp:  # nosec B310 - literal Composio API host
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc)
        logger.warning("composio_ops: %s HTTP %s — %s", slug, exc.code, detail)
        return DeliveryResult(ok=False, skipped=False, detail=f"{slug} HTTP {exc.code}: {detail}")
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.warning("composio_ops: %s transport error — %s", slug, exc)
        return DeliveryResult(ok=False, skipped=False, detail=f"{slug} transport error: {exc}")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return DeliveryResult(ok=False, skipped=False, detail=f"{slug} returned a non-JSON response")
    return _interpret(slug, payload)


# -- High-level helpers -----------------------------------------------------


def send_slack_channel_message(channel: str, markdown_text: str, *, thread_ts: str | None = None) -> DeliveryResult:
    """Post a Markdown message to a Slack channel (or DM channel id)."""
    if not channel:
        return DeliveryResult(ok=False, skipped=True, detail="no Slack channel configured")
    arguments = {"channel": channel, "markdown_text": markdown_text}
    if thread_ts:
        arguments["thread_ts"] = thread_ts
    return execute_tool(
        SLACK_SEND_MESSAGE,
        arguments,
        toolkit="slack",
    )


def _extract_dm_channel_id(data: dict[str, Any] | None) -> str | None:
    """Pull the ``channel.id`` out of a SLACK_OPEN_DM response, defensively."""
    if not isinstance(data, dict):
        return None
    channel = data.get("channel")
    if isinstance(channel, dict):
        cid = channel.get("id")
        if isinstance(cid, str) and cid:
            return cid
    cid = data.get("channel_id")
    if not cid:
        cid = data.get("id")
    return cid if isinstance(cid, str) and cid else None


def send_slack_dm(slack_user_id: str, markdown_text: str) -> DeliveryResult:
    """Open (or reuse) a DM to a Slack user id and post a Markdown message."""
    if not slack_user_id:
        return DeliveryResult(ok=False, skipped=True, detail="no Slack user id configured")
    opened = execute_tool(SLACK_OPEN_DM, {"users": slack_user_id}, toolkit="slack")
    if not opened.delivered:
        return opened
    channel_id = _extract_dm_channel_id(opened.data)
    if not channel_id:
        return DeliveryResult(ok=False, skipped=False, detail="SLACK_OPEN_DM returned no usable channel id")
    return send_slack_channel_message(channel_id, markdown_text)


def notify_slack(markdown_text: str) -> DeliveryResult:
    """Route an operator alert to Slack.

    Prefers a DM to ``SLACK_ALERT_USER_ID`` (a Slack member id, e.g. ``U0…``);
    falls back to a channel post to ``SLACK_ALERT_CHANNEL``. Returns
    ``skipped=True`` when neither is configured.
    """
    user = os.getenv("SLACK_ALERT_USER_ID", "").strip()
    if user:
        return send_slack_dm(user, markdown_text)
    channel = os.getenv("SLACK_ALERT_CHANNEL", "").strip()
    if channel:
        return send_slack_channel_message(channel, markdown_text)
    return DeliveryResult(
        ok=False,
        skipped=True,
        detail="neither SLACK_ALERT_USER_ID nor SLACK_ALERT_CHANNEL configured",
    )


def create_github_issue(
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> DeliveryResult:
    """Create a GitHub issue via Composio (used only where ``gh`` is absent)."""
    arguments: dict[str, Any] = {"owner": owner, "repo": repo, "title": title, "body": body}
    if labels:
        arguments["labels"] = list(labels)
    return execute_tool(GITHUB_CREATE_ISSUE, arguments, toolkit="github")


def list_github_issues(owner: str, repo: str, *, state: str = "open") -> DeliveryResult:
    """List repository issues through the read-only GitHub connection."""
    return execute_tool(
        "GITHUB_LIST_REPOSITORY_ISSUES",
        {"owner": owner, "repo": repo, "state": state, "per_page": 100},
        toolkit="github",
    )


def comment_github_issue(owner: str, repo: str, issue_number: int, body: str) -> DeliveryResult:
    """Append an incident lifecycle event to an existing issue."""
    return execute_tool(
        "GITHUB_CREATE_AN_ISSUE_COMMENT",
        {"owner": owner, "repo": repo, "issue_number": issue_number, "body": body},
        toolkit="github",
    )


def close_github_issue(owner: str, repo: str, issue_number: int) -> DeliveryResult:
    """Close an incident issue after a resolved event."""
    return execute_tool(
        "GITHUB_CLOSE_ISSUE",
        {"owner": owner, "repo": repo, "issue_number": issue_number},
        toolkit="github",
    )


def send_outlook_email(to: str, subject: str, html_body: str) -> DeliveryResult:
    """Send an HTML email via the connected Outlook account."""
    if not to:
        return DeliveryResult(ok=False, skipped=True, detail="no Outlook recipient configured")
    return execute_tool(
        OUTLOOK_SEND_EMAIL,
        {"to": to, "subject": subject, "body": html_body, "is_html": True},
        toolkit="outlook",
    )


def create_outlook_event(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    *,
    time_zone: str = "Europe/Berlin",
    body: str = "",
    transaction_id: str | None = None,
) -> DeliveryResult:
    """Create an idempotent operator calendar event."""
    arguments: dict[str, Any] = {
        "subject": subject,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "time_zone": time_zone,
        "body": body,
        "is_html": False,
    }
    if transaction_id:
        arguments["transaction_id"] = transaction_id
    return execute_tool(OUTLOOK_CREATE_EVENT, arguments, toolkit="outlook")


def create_notion_page(parent_id: str, title: str, *, markdown: str = "") -> DeliveryResult:
    """Create a research digest page below the configured parent."""
    arguments = {"parent_id": parent_id, "title": title}
    if markdown:
        arguments["markdown"] = markdown
    return execute_tool(
        NOTION_CREATE_PAGE,
        arguments,
        toolkit="notion",
    )


def append_notion_text(block_id: str, children: list[dict[str, Any]]) -> DeliveryResult:
    """Append reviewed text blocks to a Notion page."""
    return execute_tool(
        NOTION_APPEND_TEXT,
        {"block_id": block_id, "children": children},
        toolkit="notion",
    )
