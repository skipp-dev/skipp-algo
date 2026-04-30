"""Pure alert helpers extracted from streamlit_terminal.py.

These helpers keep alert-rule evaluation and webhook URL validation free of
Streamlit/session-state side effects so they can be covered with regular tests.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
import urllib.parse
from collections.abc import Callable
from typing import Any

from terminal_attention_state import (
    effective_attention_active,
    effective_attention_dispatchable,
    effective_attention_reason,
    effective_attention_score,
    effective_attention_state,
)
from terminal_catalyst_state import effective_catalyst_sentiment
from terminal_posture_state import effective_posture_action
from terminal_reaction_state import effective_reaction_state
from terminal_resolution_state import effective_resolution_state
from terminal_ui_helpers import match_alert_rule

_ALLOWED_WEBHOOK_SCHEMES = frozenset({"https"})

logger = logging.getLogger(__name__)
# Fallback ticker extraction: matches `$AAPL` style cashtags (1-5 upper-case letters).
_TICKER_DOLLAR_RE = re.compile(r"\$([A-Z]{1,5})\b")


def _get_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _ip_is_private_or_local(ip: Any) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_webhook_url(
    url: str,
    *,
    resolver: Callable[..., Any] | None = None,
) -> tuple[bool, str]:
    """Best-effort SSRF guard shared by Streamlit alert rules and webhooks."""
    normalized_url = str(url or "").strip()
    if not normalized_url:
        return True, ""

    try:
        parsed = urllib.parse.urlparse(normalized_url)
    except Exception:
        return False, "invalid_url"

    if parsed.scheme not in {"https", "http"}:
        return False, "unsupported_scheme"

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "missing_host"
    if host in {"localhost", "localhost.localdomain", "0.0.0.0"} or host.endswith(".local"):  # noqa: S104 -- "0.0.0.0" is a deny-listed URL host literal, not a bind address
        return False, "local_host"
    if parsed.username or parsed.password:
        return False, "credentials_not_allowed"

    try:
        if _ip_is_private_or_local(ipaddress.ip_address(host)):
            return False, "private_or_local_ip"
    except ValueError:
        lookup = resolver or socket.getaddrinfo
        try:
            infos = lookup(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            for info in infos:
                resolved_ip = ipaddress.ip_address(info[4][0])
                if _ip_is_private_or_local(resolved_ip):
                    return False, "resolved_to_private_or_local_ip"
        except Exception:
            pass

    if parsed.scheme not in _ALLOWED_WEBHOOK_SCHEMES:
        return False, "insecure_scheme"

    return True, ""


def evaluate_alert_rules(
    items: list[Any],
    rules: list[dict[str, Any]],
    *,
    webhook_budget: int,
    now: float | None = None,
    webhook_validator: Callable[[str], tuple[bool, str]] | None = None,
) -> dict[str, Any]:
    """Evaluate alert rules without mutating Streamlit session state."""
    if not rules:
        return {
            "alert_log_entries": [],
            "pending_webhooks": [],
        }

    event_ts = float(now) if now is not None else time.time()
    remaining_budget = max(int(webhook_budget), 0)
    seen_pairs: set[tuple[str, int]] = set()
    alert_log_entries: list[dict[str, Any]] = []
    pending_webhooks: list[tuple[str, dict[str, Any]]] = []
    validate_webhook = webhook_validator or validate_webhook_url
    webhook_validation_cache: dict[str, tuple[bool, str]] = {}

    for item in items:
        if not effective_attention_active(item):
            continue

        ticker = str(_get_field(item, "ticker", "") or "").strip().upper()
        if not ticker:
            headline = str(_get_field(item, "headline", "") or "")
            m = _TICKER_DOLLAR_RE.search(headline)
            if m:
                ticker = m.group(1)
            else:
                logger.debug(
                    "alert: no ticker for item, skipping (headline=%r)", headline[:60]
                )
                # Skip untickered items entirely so wildcard rules
                # (ticker="*") cannot fire alerts/webhooks for them.
                continue
        effective_score = effective_attention_score(item)
        effective_sentiment = effective_catalyst_sentiment(item)
        attention_state = effective_attention_state(item)
        attention_dispatchable = effective_attention_dispatchable(item)
        story_key = str(_get_field(item, "story_key", "") or "").strip()
        item_id = str(_get_field(item, "item_id", "") or "").strip()

        for rule_idx, rule in enumerate(rules):
            if str(rule.get("ticker") or "").strip().upper() not in {"*", ticker}:
                continue

            pair_key = (story_key or item_id, rule_idx)
            if pair_key in seen_pairs:
                continue

            if not match_alert_rule(
                rule,
                ticker=ticker,
                news_score=effective_score,
                sentiment_label=effective_sentiment,
                materiality=str(_get_field(item, "materiality", "") or ""),
                category=str(_get_field(item, "category", "") or ""),
            ):
                continue

            seen_pairs.add(pair_key)
            log_entry = {
                "ts": event_ts,
                "ticker": ticker,
                "headline": str(_get_field(item, "headline", "") or "")[:120],
                "rule": str(rule.get("condition") or ""),
                "score": effective_score,
                "story_score": _get_field(item, "news_score", 0.0),
                "sentiment": effective_sentiment,
                "item_id": item_id,
                "story_key": story_key,
                "story_update_kind": _get_field(item, "story_update_kind", None),
                "attention_state": attention_state,
                "attention_score": effective_score,
                "attention_dispatchable": attention_dispatchable,
                "attention_reason": str(_get_field(item, "attention_reason", "") or "") or effective_attention_reason(item),
                "posture_state": _get_field(item, "posture_state", None),
                "posture_action": effective_posture_action(item),
                "reaction_state": effective_reaction_state(item),
                "resolution_state": effective_resolution_state(item),
            }
            alert_log_entries.insert(0, log_entry)

            webhook_url = str(rule.get("webhook_url") or "").strip()
            if webhook_url and remaining_budget > 0:
                validation = webhook_validation_cache.get(webhook_url)
                if validation is None:
                    validation = validate_webhook(webhook_url)
                    webhook_validation_cache[webhook_url] = validation
                if not validation[0]:
                    continue
                remaining_budget -= 1
                pending_webhooks.append((webhook_url, log_entry))

    return {
        "alert_log_entries": alert_log_entries,
        "pending_webhooks": pending_webhooks,
    }
