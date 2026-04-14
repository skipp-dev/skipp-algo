from __future__ import annotations

from typing import Any


def build_test_mode_config_overrides() -> dict[str, Any]:
    return {
        "tv_news_enabled": False,
        "fmp_enabled": False,
        "poll_interval_s": 60.0,
    }


def build_test_mode_state_defaults(now: float) -> dict[str, Any]:
    current_now = float(now)
    return {
        "cursor": None,
        "provider_cursors": {},
        "feed": [],
        "live_story_state": {},
        "ticker_catalyst_state": {},
        "ticker_reaction_state": {},
        "ticker_resolution_state": {},
        "ticker_posture_state": {},
        "ticker_attention_state": {},
        "poll_count": 0,
        "last_poll_ts": current_now,
        "last_resync_ts": current_now,
        "auto_refresh": False,
        "use_bg_poller": False,
        "intel_toggle": False,
    }


def extract_feed_tickers(rows: list[dict[str, Any]] | None, *, limit: int = 200) -> list[str]:
    tickers = sorted(
        {
            str(row.get("ticker") or "").strip().upper()
            for row in rows or []
            if str(row.get("ticker") or "").strip().upper() not in {"", "MARKET"}
        }
    )
    if limit <= 0:
        return []
    return tickers[: int(limit)]


def build_alert_rule_payload(
    *,
    ticker: str,
    condition: str,
    threshold: Any,
    category: str,
    webhook_url: str,
    created: float,
) -> dict[str, Any]:
    try:
        normalized_threshold = float(threshold)
    except (TypeError, ValueError):
        normalized_threshold = 0.0

    return {
        "ticker": str(ticker or "*").strip().upper() or "*",
        "condition": str(condition or "").strip(),
        "threshold": normalized_threshold,
        "category": str(category or "").strip().lower(),
        "webhook_url": str(webhook_url or "").strip(),
        "created": float(created),
    }


def merge_alert_log_entries(
    new_entries: list[dict[str, Any]],
    existing_entries: list[dict[str, Any]],
    *,
    max_items: int = 100,
) -> list[dict[str, Any]]:
    if max_items <= 0:
        return []
    merged = list(new_entries) + list(existing_entries)
    return merged[: int(max_items)]