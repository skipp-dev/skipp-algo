"""Pure helpers for rendering provider / feed status diagnostics.

Every function here is free of Streamlit imports and can be tested
in regular pytest.  ``streamlit_terminal.py`` calls these from inside
``st.sidebar`` blocks to render operator-facing status widgets.
"""
from __future__ import annotations

import time
from typing import Any


# ── Provider key detection ──────────────────────────────────────────────────

def api_key_status(
    *,
    benzinga_key: str,
    databento_available: bool,
    openai_key: str,
) -> list[dict[str, Any]]:
    """Return per-provider status dicts suitable for sidebar rendering.

    Each dict has ``name``, ``configured`` (bool), ``icon``, ``message``.
    """
    results: list[dict[str, Any]] = []

    results.append({
        "name": "News API",
        "configured": bool(benzinga_key),
        "icon": "✅" if benzinga_key else "❌",
        "message": "configured" if benzinga_key else "No BENZINGA_API_KEY found",
    })
    results.append({
        "name": "Databento",
        "configured": databento_available,
        "icon": "✅" if databento_available else "—",
        "message": "configured" if databento_available else "not configured (quote enrichment disabled)",
    })
    results.append({
        "name": "OpenAI",
        "configured": bool(openai_key),
        "icon": "✅" if openai_key else "—",
        "message": "configured" if openai_key else "not configured (AI Insights disabled)",
    })
    return results


# ── Feed staleness diagnostics ──────────────────────────────────────────────

def feed_staleness_diagnostic(
    staleness_minutes: float | None,
    is_market_hours: bool,
) -> dict[str, Any]:
    """Classify feed staleness into a severity + label for the sidebar.

    Returns ``{"severity": "ok"|"warn"|"stale", "label": str}``.
    """
    if staleness_minutes is None:
        return {"severity": "ok", "label": ""}

    label = f"Feed age: {staleness_minutes:.0f}m"
    if is_market_hours:
        if staleness_minutes > 2:
            return {"severity": "warn", "label": label}
        return {"severity": "ok", "label": label}
    else:
        suffix = " (off-hours)"
        if staleness_minutes > 15:
            return {"severity": "warn", "label": label + suffix}
        return {"severity": "ok", "label": label + suffix}


def cursor_diagnostic(cursor: Any) -> str:
    """Format cursor value into a human-readable age string."""
    if not cursor:
        return "Cursor: (initial)"
    try:
        cursor_ago = (time.time() - float(cursor)) / 60
        return f"Cursor: {cursor_ago:.0f}m ago"
    except (ValueError, TypeError):
        return f"Cursor: {str(cursor)[:20]}"


# ── Poll status formatting ─────────────────────────────────────────────────

def poll_failure_count(attempts: int, successes: int) -> int | None:
    """Return number of poll failures, or None if no failures."""
    if attempts > successes:
        return attempts - successes
    return None


def format_poll_ago(last_poll_ts: float, last_duration_s: float = 0.0) -> str:
    """Human-readable 'last poll X seconds ago' string."""
    if not last_poll_ts:
        return ""
    ago = time.time() - last_poll_ts
    dur_txt = f" ({last_duration_s:.1f}s)" if last_duration_s > 0 else ""
    return f"Last poll: {ago:.0f}s ago{dur_txt}"


# ── Provider health one-liners ──────────────────────────────────────────────

PROVIDER_STATUS_ICONS = {
    "up": "✅",
    "degraded": "⚡",
    "down": "🔴",
    "unknown": "❓",
}


def format_provider_status_line(
    name: str,
    availability: str,
    reason: str,
    avg_latency_ms: float = 0.0,
) -> str:
    """Single-line operator-facing summary for a provider."""
    icon = PROVIDER_STATUS_ICONS.get(availability, "❓")
    lat = f" avg={avg_latency_ms:.0f}ms" if avg_latency_ms > 0 else ""
    return f"{icon} {name}: {availability}{lat} — {reason}"


# ── Degraded-mode reason builder ────────────────────────────────────────────

def degraded_mode_reasons(
    *,
    provider_statuses: list[dict[str, Any]] | None = None,
    feed_staleness_min: float | None = None,
    consecutive_empty_polls: int = 0,
    bg_poller_last_failure: dict[str, Any] | None = None,
    is_market_hours: bool = True,
) -> list[str]:
    """Collect all active degraded-mode reasons for operator display.

    Returns a list of short, human-readable reason strings.  An empty
    list means the system is healthy.
    """
    reasons: list[str] = []

    # Provider-level issues
    for ps in provider_statuses or []:
        avail = ps.get("availability", "unknown")
        if avail in ("degraded", "down"):
            reasons.append(
                f"{ps.get('name', '?')} is {avail}: {ps.get('reason', 'unknown')}"
            )

    # Feed staleness
    if feed_staleness_min is not None and is_market_hours and feed_staleness_min > 5:
        reasons.append(f"Feed stale ({feed_staleness_min:.0f}m without new data)")

    # Empty poll streak
    if consecutive_empty_polls >= 3:
        reasons.append(
            f"{consecutive_empty_polls} consecutive empty polls — cursor may be stuck"
        )

    # Background poller failure
    if bg_poller_last_failure:
        err = bg_poller_last_failure.get("last_poll_error", "")
        if err:
            reasons.append(f"Background poller error: {err[:120]}")

    return reasons
