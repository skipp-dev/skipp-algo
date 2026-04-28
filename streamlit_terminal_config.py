from __future__ import annotations

from typing import Any


def collect_tv_news_symbols(cfg: Any, feed: list[dict[str, Any]] | None = None) -> list[str]:
    if not bool(getattr(cfg, "tv_news_enabled", True)):
        return []

    configured = [
        str(symbol).strip().upper()
        for symbol in str(getattr(cfg, "tv_news_symbols", "") or "").split(",")
        if str(symbol).strip()
    ]
    dynamic: list[str] = []
    for row in feed or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker and ticker != "MARKET":
            dynamic.append(ticker)

    merged: list[str] = []
    seen: set[str] = set()
    raw_max_symbols = getattr(cfg, "tv_news_max_symbols", 25)
    max_symbols = max(1, int(25 if raw_max_symbols in {None, ""} else raw_max_symbols))
    for ticker in [*configured, *dynamic]:
        if ticker in seen:
            continue
        seen.add(ticker)
        merged.append(ticker)
        if len(merged) >= max_symbols:
            break
    return merged


def has_live_news_provider(cfg: Any, feed: list[dict[str, Any]] | None = None) -> bool:
    if str(getattr(cfg, "benzinga_api_key", "") or "").strip():
        return True
    if bool(getattr(cfg, "fmp_enabled", False)) and str(getattr(cfg, "fmp_api_key", "") or "").strip():
        return True
    return bool(collect_tv_news_symbols(cfg, feed))


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

    raw_tv_news_max_symbols = getattr(cfg, "tv_news_max_symbols", 25)
    tv_news_max_symbols = int(25 if raw_tv_news_max_symbols in {None, ""} else raw_tv_news_max_symbols)
    if tv_news_max_symbols < 1:
        problems.append("tv_news_max_symbols must be greater than or equal to 1")

    if bool(getattr(cfg, "fmp_enabled", False)) and not str(getattr(cfg, "fmp_api_key", "") or "").strip():
        problems.append("fmp_api_key must be set when fmp_enabled is true")

    return problems
