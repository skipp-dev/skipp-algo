from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def get_provider_status_notice(
    meta: Mapping[str, Any] | None,
    *,
    provider_key: str,
    provider_name: str,
) -> tuple[str, str] | None:
    """Build a user-facing status notice for a newsstack provider.

    Returns ``(severity, message)`` where severity is one of
    ``caption``, ``info``, or ``warning``. ``None`` is returned when the
    requested provider has no exported status metadata.
    """
    if not isinstance(meta, Mapping):
        return None
    providers = meta.get("providers")
    if not isinstance(providers, Mapping):
        return None
    provider_meta = providers.get(provider_key)
    if not isinstance(provider_meta, Mapping):
        return None

    provider_status = str(provider_meta.get("provider_status") or "").strip()
    status_detail = str(provider_meta.get("status_detail") or "").strip()
    if not provider_status:
        return None

    if provider_status == "ok":
        severity = "caption"
    elif provider_status == "ok_no_recent_matches":
        severity = "info"
    else:
        severity = "warning"

    message = f"{provider_name}: {provider_status}"
    if status_detail:
        message = f"{message} - {status_detail}"
    return severity, message


def _format_cursor_epoch(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "empty"
    try:
        epoch = float(text)
    except ValueError:
        return text
    if epoch <= 0.0:
        return "empty"
    iso_text = datetime.fromtimestamp(epoch, tz=UTC).isoformat().replace("+00:00", "Z")
    return f"{iso_text} ({text})"


def get_provider_cursor_caption(
    meta: Mapping[str, Any] | None,
    *,
    provider_key: str,
    provider_name: str,
) -> str | None:
    if provider_key != "newsapi_ai":
        return None
    if not isinstance(meta, Mapping):
        return None
    cursor = meta.get("cursor")
    if not isinstance(cursor, Mapping):
        return None

    epoch_value = cursor.get("newsapi_ai_last_seen_epoch")
    uri_value = str(cursor.get("newsapi_ai_last_seen_news_uri") or "").strip() or "empty"
    if epoch_value in (None, "") and uri_value == "empty":
        return None
    return f"{provider_name} cursor: epoch={_format_cursor_epoch(epoch_value)} - uri={uri_value}"