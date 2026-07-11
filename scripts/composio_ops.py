"""Thin, fail-soft Composio client for skipp-algo ops automations.

Consumers:

* ``scripts/credential_health_notify.py``            — #1 credential -> Slack DM
* ``scripts/ops_digest.py``                          — #4 daily Outlook digest
* ``services/live_overlay_daemon/grafana_composio_fanout.py`` — #3 Grafana fan-out

Design contract — **ops notification is best-effort and MUST never raise into
the caller**. A missing ``COMPOSIO_API_KEY``, an uninstalled ``composio`` SDK,
or a provider hiccup degrades to a *logged no-op*; it must not crash a
credential health check, a nightly digest cron, or the live-overlay daemon.

Every public helper therefore returns a :class:`DeliveryResult` instead of
raising. ``skipped=True`` means "not attempted" (unconfigured), ``ok=False``
with ``skipped=False`` means "attempted and failed" — the caller can log the
difference but should treat neither as fatal.

Auth model: the Composio Python SDK talks to the Composio backend with an API
key (``COMPOSIO_API_KEY``); the individual toolkit accounts (Slack, GitHub,
Outlook) are authorized once in the Composio dashboard and referenced per call
by ``user_id`` (``COMPOSIO_USER_ID``, default ``"default"``) and optionally by a
per-toolkit ``connected_account_id`` (``COMPOSIO_<TOOLKIT>_ACCOUNT_ID``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

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


def _account_for_toolkit(toolkit: str | None) -> str | None:
    """Optional per-toolkit connected-account override from the environment."""
    if not toolkit:
        return None
    value = os.getenv(f"COMPOSIO_{toolkit.upper()}_ACCOUNT_ID", "").strip()
    return value or None


def _interpret(slug: str, response: Any) -> DeliveryResult:
    """Normalize a raw SDK response into a :class:`DeliveryResult`."""
    payload: Any = response
    if hasattr(response, "model_dump"):
        payload = response.model_dump()

    if isinstance(payload, dict):
        successful = payload.get("successful", payload.get("success", True))
        error = payload.get("error")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else None
        if error or successful is False:
            return DeliveryResult(
                ok=False,
                skipped=False,
                detail=f"{slug} reported failure: {error or 'unknown error'}",
                data=data,
            )
        return DeliveryResult(ok=True, skipped=False, detail=f"{slug} delivered", data=data)

    # Non-dict truthy response — treat as success but keep the shape opaque.
    return DeliveryResult(ok=True, skipped=False, detail=f"{slug} delivered (opaque response)")


def execute_tool(
    slug: str,
    arguments: dict[str, Any],
    *,
    toolkit: str | None = None,
    connected_account_id: str | None = None,
) -> DeliveryResult:
    """Execute one Composio tool, fail-soft.

    Returns ``skipped=True`` when unconfigured (no API key / SDK) and never
    raises; a provider/network error is captured and returned as a failed —
    but non-fatal — :class:`DeliveryResult`.
    """
    api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
    if not api_key:
        logger.info("composio_ops: COMPOSIO_API_KEY unset — skipping %s (no-op)", slug)
        return DeliveryResult(ok=False, skipped=True, detail="COMPOSIO_API_KEY unset")

    try:
        from composio import Composio
    except ImportError as exc:
        logger.warning(
            "composio_ops: composio SDK not importable (%s) — skipping %s (no-op)", exc, slug
        )
        return DeliveryResult(ok=False, skipped=True, detail=f"composio SDK not installed: {exc}")

    user_id = os.getenv("COMPOSIO_USER_ID", "default").strip() or "default"
    account = connected_account_id or _account_for_toolkit(toolkit)
    kwargs: dict[str, Any] = {"user_id": user_id, "arguments": arguments}
    if account:
        kwargs["connected_account_id"] = account

    try:
        response = Composio(api_key=api_key).tools.execute(slug, **kwargs)
    except Exception as exc:
        # Fail-soft notifier: the SDK surfaces many provider/network/auth error
        # types; none may propagate into a health check, digest cron, or daemon.
        logger.warning("composio_ops: %s raised %s: %s", slug, type(exc).__name__, exc)
        return DeliveryResult(
            ok=False, skipped=False, detail=f"{slug} raised {type(exc).__name__}: {exc}"
        )

    return _interpret(slug, response)


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
    cid = data.get("channel_id") or data.get("id")
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
