from __future__ import annotations

from typing import Any


def has_live_news_provider(cfg: Any, feed: list[dict[str, Any]] | None = None) -> bool:
    if str(getattr(cfg, "benzinga_api_key", "") or "").strip():
        return True
    return bool(getattr(cfg, "fmp_enabled", False)) and bool(
        str(getattr(cfg, "fmp_api_key", "") or "").strip()
    )


def validate_terminal_config(cfg: Any) -> list[str]:
    problems: list[str] = []

    if not str(getattr(cfg, "jsonl_path", "") or "").strip():
        problems.append("jsonl_path must not be empty")
    if not str(getattr(cfg, "sqlite_path", "") or "").strip():
        problems.append("sqlite_path must not be empty")

    poll_interval_s = float(getattr(cfg, "poll_interval_s", 10.0) or 0.0)
    if poll_interval_s <= 0:
        problems.append("poll_interval_s must be greater than 0")

    feed_max_age_s = float(getattr(cfg, "feed_max_age_s", 14400.0) or 0.0)
    if feed_max_age_s < 0:
        problems.append("feed_max_age_s must be greater than or equal to 0")

    if bool(getattr(cfg, "fmp_enabled", False)) and not str(getattr(cfg, "fmp_api_key", "") or "").strip():
        problems.append("fmp_api_key must be set when fmp_enabled is true")

    return problems
