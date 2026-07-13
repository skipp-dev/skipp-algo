"""Grafana alert webhook -> Composio fan-out (use case #3).

Grafana can POST a contact-point webhook on alert transitions. This router
receives that payload and fans it out through Composio to channels Grafana
does not natively combine well: an operator Slack ping *and* (opt-in per alert)
a GitHub issue — one webhook, context-aware routing.

Mounting: ``main.py`` includes this router unconditionally. The endpoint is a
no-op (HTTP 503) until ``GRAFANA_WEBHOOK_TOKEN`` is set, and every delivery is
fail-soft via ``composio_ops`` (no prod project key -> logged skip), so the
daemon boots and serves overlays exactly as before when Composio is not wired.

Routing rules:
* **Always** — a Slack message summarizing the firing/resolved alerts
  (DM to ``SLACK_ALERT_USER_ID`` or post to ``SLACK_ALERT_CHANNEL``).
* **Opt-in** — a GitHub issue is created only for a *firing* alert that carries
  the label ``composio_issue: "true"``, so routine alerts never spam issues.

Security: the webhook path embeds a shared secret (``GRAFANA_WEBHOOK_TOKEN``),
mirroring the daemon's existing URL-token model; a mismatch is HTTP 401.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request
from starlette.concurrency import run_in_threadpool

try:  # scripts/ is on PYTHONPATH in the daemon image; keep import robust in tests
    import composio_ops
except ImportError:  # imported as a package (pytest pythonpath=".")
    from scripts import composio_ops

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_ISSUE_REPO = "skipp-dev/skipp-algo"


def _alerts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = payload.get("alerts")
    return [a for a in alerts if isinstance(a, dict)] if isinstance(alerts, list) else []


def build_slack_message(payload: dict[str, Any]) -> str:
    """Render a compact Slack Markdown summary of a Grafana webhook payload."""
    status = str(payload.get("status", "unknown"))
    emoji = "🔴" if status == "firing" else ("✅" if status == "resolved" else "⚪")
    title = payload.get("title") or payload.get("message") or "Grafana alert"
    lines = [f"{emoji} *Grafana: {status}* — {title}"]

    for alert in _alerts(payload):
        labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
        annotations = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}
        name = labels.get("alertname", "?")
        severity = labels.get("severity", "")
        summary = annotations.get("summary") or annotations.get("description") or ""
        sev_tag = f" `{severity}`" if severity else ""
        lines.append(f"• *{name}*{sev_tag} — {summary}".rstrip(" —"))

    external = payload.get("externalURL")
    if isinstance(external, str) and external:
        lines.append(f"\n<{external}|Open Grafana>")
    return "\n".join(lines)


def _issue_body(alert: dict[str, Any], payload: dict[str, Any]) -> str:
    labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
    annotations = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}
    parts = [
        f"Auto-filed from a Grafana webhook fan-out (status: {payload.get('status')}).",
        "",
        f"**Alert:** {labels.get('alertname', '?')}",
        f"**Severity:** {labels.get('severity', 'n/a')}",
        f"**Summary:** {annotations.get('summary', '')}",
        f"**Description:** {annotations.get('description', '')}",
    ]
    generator = alert.get("generatorURL")
    if isinstance(generator, str) and generator:
        parts.append(f"**Source:** {generator}")
    return "\n".join(parts)


def _issue_rows(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize the common Composio/GitHub list-response wrappers."""
    if not isinstance(data, dict):
        return []
    for key in ("items", "issues", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _find_incident(owner: str, repo: str, title: str) -> int | None:
    result = composio_ops.list_github_issues(owner, repo, state="open")
    if not result.delivered:
        return None
    for issue in _issue_rows(result.data):
        if issue.get("title") == title and isinstance(issue.get("number"), int):
            return int(issue["number"])
    return None


def fan_out(payload: dict[str, Any]) -> dict[str, Any]:
    """Deliver a parsed Grafana payload to Slack (+ opt-in GitHub issues).

    Synchronous and fail-soft: returns a per-channel result summary and never
    raises. Runs off the event loop via ``run_in_threadpool`` at the call site.
    """
    results: dict[str, Any] = {}

    slack = composio_ops.notify_slack(build_slack_message(payload))
    results["slack"] = {"delivered": slack.delivered, "skipped": slack.skipped, "detail": slack.detail}

    repo = os.getenv("GITHUB_ISSUE_REPO", _DEFAULT_ISSUE_REPO).strip() or _DEFAULT_ISSUE_REPO
    owner, _, name = repo.partition("/")
    issues: list[dict[str, Any]] = []
    for alert in _alerts(payload):
        labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
        if str(labels.get("composio_issue", "")).lower() != "true":
            continue
        alertname = str(labels.get("alertname", "grafana-alert"))
        title = f"[grafana] {alertname} firing"
        if owner and name:
            existing = _find_incident(owner, name, title)
            if str(payload.get("status")) == "resolved":
                if existing is None:
                    continue
                comment = composio_ops.comment_github_issue(
                    owner, name, existing, "Resolved by Grafana.\n\n" + _issue_body(alert, payload)
                )
                closed = composio_ops.close_github_issue(owner, name, existing)
                res = closed if not closed.delivered else comment
            elif existing is not None:
                res = composio_ops.comment_github_issue(
                    owner, name, existing, "Still firing.\n\n" + _issue_body(alert, payload)
                )
            else:
                res = composio_ops.create_github_issue(
                    owner,
                    name,
                    title=title,
                    body=_issue_body(alert, payload),
                    labels=["grafana-alert", "automated"],
                )
            issues.append(
                {"alert": alertname, "delivered": res.delivered, "skipped": res.skipped, "detail": res.detail}
            )
    if issues:
        results["github_issues"] = issues
    return results


@router.api_route("/{token}/grafana-webhook", methods=["POST"], include_in_schema=False)
async def grafana_webhook(request: Request, token: str = Path(...)) -> dict[str, Any]:
    expected = os.getenv("GRAFANA_WEBHOOK_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Grafana webhook fan-out not configured")
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid webhook token")

    try:
        payload = await request.json()
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="webhook body must be a JSON object")

    results = await run_in_threadpool(fan_out, payload)
    logger.info("grafana_composio_fanout: fanned out Grafana webhook -> %s", results)
    return {"ok": True, "results": results}
