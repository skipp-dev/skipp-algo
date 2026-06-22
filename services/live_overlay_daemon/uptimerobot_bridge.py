"""UptimeRobot API bridge with lightweight in-process caching.

This module fetches monitor state from UptimeRobot and provides a cached
snapshot that can be exported as Prometheus gauges in ``metrics.render_metrics``.

The bridge is optional and fully env-driven:
- when ``UPTIMEROBOT_API_KEY`` is unset, bridge metrics are emitted as disabled
  and no outbound HTTP request is made.
- failures keep serving the previous good cache when available; otherwise they
    are converted into status gauges. Scraping never raises.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from . import config

_API_URL = "https://api.uptimerobot.com/v2/getMonitors"

_cache_lock = threading.Lock()
_cached_snapshot: dict[str, Any] | None = None
_cached_at_monotonic = 0.0


def _status_bucket(status_code: int) -> str:
    if status_code == 2:
        return "up"
    if status_code in (8, 9):
        return "down"
    if status_code == 0:
        return "paused"
    return "unknown"


def _to_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _extract_response_time_ms(raw_monitor: dict[str, Any]) -> float | None:
    response_times = raw_monitor.get("response_times")
    if isinstance(response_times, list) and response_times:
        candidate = response_times[0]
        if isinstance(candidate, dict):
            return _to_float(candidate.get("value"))
    return _to_float(raw_monitor.get("average_response_time"))


def _fetch_snapshot(api_key: str) -> dict[str, Any]:
    payload: dict[str, str] = {
        "api_key": api_key,
        "format": "json",
        "logs": "0",
        "response_times": "1",
        "response_times_limit": "1",
    }
    monitor_ids = config.uptimerobot_monitor_ids()
    if monitor_ids:
        payload["monitors"] = "-".join(monitor_ids)

    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(
        _API_URL,
        data=encoded,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    timeout = config.uptimerobot_timeout_secs()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")

    parsed = json.loads(body)
    if str(parsed.get("stat", "")).lower() != "ok":
        raise RuntimeError(f"uptimerobot_api_stat={parsed.get('stat', 'unknown')}")

    monitors: list[dict[str, Any]] = []
    counts = {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0}
    response_times: list[float] = []

    for monitor in parsed.get("monitors") or []:
        monitor_id = str(monitor.get("id", "unknown")).strip() or "unknown"
        name = str(monitor.get("friendly_name", "unknown")).strip() or "unknown"
        try:
            status_code = int(monitor.get("status", 1))
        except (TypeError, ValueError):
            status_code = 1
        bucket = _status_bucket(status_code)
        response_time_ms = _extract_response_time_ms(monitor)
        if response_time_ms is not None:
            response_times.append(response_time_ms)

        counts["total"] += 1
        counts[bucket] += 1
        monitors.append(
            {
                "id": monitor_id,
                "name": name,
                "status_code": status_code,
                "status_bucket": bucket,
                "up": 1 if status_code == 2 else 0,
                "response_time_ms": response_time_ms,
            }
        )

    avg_response_time_ms = sum(response_times) / len(response_times) if response_times else None
    return {
        "enabled": 1,
        "ok": 1,
        "fetched_at_unix": time.time(),
        "counts": counts,
        "avg_response_time_ms": avg_response_time_ms,
        "monitors": monitors,
    }


def snapshot() -> dict[str, Any]:
    """Return cached UptimeRobot snapshot; never raises."""
    global _cached_snapshot, _cached_at_monotonic

    api_key = config.uptimerobot_api_key()
    if not api_key:
        return {
            "enabled": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
            "error": "missing_api_key",
        }

    ttl = config.uptimerobot_poll_ttl_secs()
    now_mono = time.monotonic()
    with _cache_lock:
        if _cached_snapshot is not None and (now_mono - _cached_at_monotonic) < ttl:
            return dict(_cached_snapshot)

    try:
        fresh = _fetch_snapshot(api_key)
    except Exception as exc:  # pragma: no cover - exercised via tests using monkeypatch
        with _cache_lock:
            if _cached_snapshot is not None and int(_cached_snapshot.get("ok", 0) or 0) == 1:
                fallback = dict(_cached_snapshot)
                fallback["error"] = type(exc).__name__
                fallback["cache_fallback"] = 1
                _cached_snapshot = fallback
                _cached_at_monotonic = now_mono
                return dict(fallback)

        fresh = {
            "enabled": 1,
            "ok": 0,
            "fetched_at_unix": time.time(),
            "counts": {"total": 0, "up": 0, "down": 0, "paused": 0, "unknown": 0},
            "avg_response_time_ms": None,
            "monitors": [],
            "error": type(exc).__name__,
        }

    with _cache_lock:
        _cached_snapshot = fresh
        _cached_at_monotonic = now_mono
    return dict(fresh)
