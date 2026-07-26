"""Provider API-usage snapshot bridge (daemon side).

Fetches the monthly provider-usage snapshot written by the ingest layer
(``newsstack_fmp/provider_usage.py``) — over https when
``PROVIDER_USAGE_SNAPSHOT_URL`` is set, else from the local path — and exposes
the CURRENT month's per-provider byte / call / record totals for Prometheus.

Why: REST providers (FMP first) meter monthly DATA VOLUME. We had no telemetry
until an FMP "90% of bandwidth used" email; this surfaces our own consumption
so the quota becomes visible and alertable. Never raises — a missing or
unreadable snapshot yields a loaded=0 payload, like the other bridges.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Any

from . import config

_cache_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at_monotonic = 0.0


def _empty(loaded: float, error: str) -> dict[str, Any]:
    return {
        "loaded": loaded,
        "error": error,
        "current_month": "",
        "updated_at": "",
        "snapshot_age_seconds": None,
        "providers": {},
    }


def _age_seconds(updated_at: str, *, now: float | None = None) -> float | None:
    if not updated_at:
        return None
    try:
        import datetime

        parsed = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        epoch = parsed.timestamp()
    except Exception:
        return None
    return age if (age := (time.time() if now is None else now) - epoch) >= 0.0 else None


def _coerce(parsed: dict[str, Any]) -> dict[str, Any]:
    """Reduce the raw snapshot to the current month's per-provider totals."""
    months = parsed.get("months")
    if not isinstance(months, dict) or not months:
        return _empty(0.0, "no_months")
    current = str(parsed.get("current_month") or "")
    if current not in months:
        # Fall back to the lexically newest month present (YYYY-MM sorts).
        current = sorted(months)[-1]
    month_slot = months.get(current) or {}
    providers: dict[str, dict[str, float]] = {}
    if isinstance(month_slot, dict):
        for name, vals in month_slot.items():
            if not isinstance(vals, dict):
                continue
            try:
                providers[str(name)] = {
                    "calls": float(vals.get("calls", 0) or 0),
                    "bytes": float(vals.get("bytes", 0) or 0),
                    "records": float(vals.get("records", 0) or 0),
                    "rate_limit_hits": float(vals.get("rate_limit_hits", 0) or 0),
                }
            except (TypeError, ValueError):
                continue
    updated_at = str(parsed.get("updated_at") or "")
    return {
        "loaded": 1.0,
        "error": "",
        "current_month": current,
        "updated_at": updated_at,
        "snapshot_age_seconds": _age_seconds(updated_at),
        "providers": providers,
    }


def _fetch_url(url: str, token: str, timeout: float = 10.0) -> str | None:
    if not url.lower().startswith("https://"):
        return None
    headers = {"User-Agent": "skipp-live-overlay/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None

def _load_raw() -> dict[str, Any]:
    """Fetch + parse the snapshot (URL first, local fallback); never raises."""
    url = config.provider_usage_snapshot_url()
    if url:
        body = _fetch_url(url, config.provider_usage_snapshot_url_token())
        if body is not None:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return _coerce(_decode_github_envelope(parsed) or parsed)

    path = config.provider_usage_snapshot_path()
    if not path.exists():
        return _empty(0.0, "missing_snapshot")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty(0.0, "unreadable_snapshot")
    if not isinstance(parsed, dict):
        return _empty(0.0, "malformed_snapshot")
    return _coerce(parsed)


def snapshot() -> dict[str, Any]:
    """Return the cached provider-usage snapshot; never raises.

    ``snapshot_age_seconds`` is recomputed from ``updated_at`` on every call, so
    the producer-heartbeat age reflects true wall-clock age even while the
    payload is TTL-cached (matching the sweep-trap / evidence-freshness bridges,
    which recompute age live on each scrape instead of freezing it at load).
    A failed reload continues to preserve the last successfully loaded payload.
    """
    global _cached, _cached_at_monotonic
    ttl = config.experiment_cache_ttl_secs()
    with _cache_lock:
        now_mono = time.monotonic()
        if _cached is not None and (now_mono - _cached_at_monotonic) < ttl:
            snap = dict(_cached)
        else:
            fresh = _load_raw()
            if fresh.get("loaded") == 1.0 or _cached is None:
                _cached = fresh
            _cached_at_monotonic = time.monotonic()
            snap = dict(_cached)
    snap["snapshot_age_seconds"] = _age_seconds(str(snap.get("updated_at") or ""))
    return snap


def _decode_github_envelope(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Decode a GitHub Contents API base64 response when raw media is ignored."""
    import base64

    if str(parsed.get("encoding", "")).lower() != "base64" or "content" not in parsed:
        return None
    try:
        decoded = json.loads(base64.b64decode(str(parsed["content"])).decode("utf-8"))
    except (ValueError, TypeError):
        return None
    return decoded if isinstance(decoded, dict) else None
