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
the caller**. A missing ``COMPOSIO_API_KEY`` or a provider/network hiccup
degrades to a *logged no-op / failed DeliveryResult*; it must never crash a
credential health check, a nightly digest cron, or the live-overlay daemon.

Config (env):
    COMPOSIO_API_KEY               required to attempt a live call (the ak_… key)
    COMPOSIO_USER_ID               entity the connected accounts belong to (default "default")
    COMPOSIO_BASE_URL              override the API host (default backend.composio.dev)
    COMPOSIO_<TOOLKIT>_ACCOUNT_ID  optional connected-account pin per toolkit
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://backend.composio.dev"
_TIMEOUT = 20.0

# Tool slugs kept as module constants so a Composio-side rename is a one-line
# change here rather than a scattered string edit across three call sites.
SLACK_OPEN_DM = "SLACK_OPEN_DM"
SLACK_SEND_MESSAGE = "SLACK_SEND_MESSAGE"
GITHUB_CREATE_ISSUE = "GITHUB_CREATE_AN_ISSUE"
OUTLOOK_SEND_EMAIL = "OUTLOOK_SEND_EMAIL"


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
    return bool(os.getenv("COMPOSIO_API_KEY", "").strip())


def _base_url() -> str:
    return os.getenv("COMPOSIO_BASE_URL", _DEFAULT_BASE_URL).strip().rstrip("/") or _DEFAULT_BASE_URL


def _account_for_toolkit(toolkit: str | None) -> str | None:
    """Optional per-toolkit connected-account override from the environment."""
    if not toolkit:
        return None
    value = os.getenv(f"COMPOSIO_{toolkit.upper()}_ACCOUNT_ID", "").strip()
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
    connected_account_id: str | None = None,
    opener: Any = None,
) -> DeliveryResult:
    """Execute one Composio tool over REST, fail-soft.

    Returns ``skipped=True`` when unconfigured (no API key) and never raises; a
    provider/network/HTTP error is captured and returned as a failed — but
    non-fatal — :class:`DeliveryResult`. ``opener`` is injectable for tests.
    """
    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        logger.info("composio_ops: COMPOSIO_API_KEY unset — skipping %s (no-op)", slug)
        return DeliveryResult(ok=False, skipped=True, detail="COMPOSIO_API_KEY unset")

    user_id = os.getenv("COMPOSIO_USER_ID", "default").strip() or "default"
    account = connected_account_id or _account_for_toolkit(toolkit)
    body: dict[str, Any] = {"user_id": user_id, "arguments": arguments}
    if account:
        body["connected_account_id"] = account

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


def send_slack_channel_message(channel: str, markdown_text: str) -> DeliveryResult:
    """Post a Markdown message to a Slack channel (or DM channel id)."""
    if not channel:
        return DeliveryResult(ok=False, skipped=True, detail="no Slack channel configured")
    return execute_tool(
        SLACK_SEND_MESSAGE,
        {"channel": channel, "markdown_text": markdown_text},
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
        return DeliveryResult(
            ok=False, skipped=False, detail="SLACK_OPEN_DM returned no usable channel id"
        )
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


def send_outlook_email(to: str, subject: str, html_body: str) -> DeliveryResult:
    """Send an HTML email via the connected Outlook account."""
    if not to:
        return DeliveryResult(ok=False, skipped=True, detail="no Outlook recipient configured")
    return execute_tool(
        OUTLOOK_SEND_EMAIL,
        {"to": to, "subject": subject, "body": html_body, "is_html": True},
        toolkit="outlook",
    )
