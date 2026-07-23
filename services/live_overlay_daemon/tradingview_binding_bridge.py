"""Load measured TradingView saved-source hashes and dropdown assignments."""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.request
from typing import Any

from . import config

_lock = threading.Lock()
_cache: dict[str, Any] = {"snapshot": None, "at": 0.0}


def _empty(error: str) -> dict[str, Any]:
    return {"loaded": 0.0, "generated_at_unix": 0.0, "ok": 0.0, "mismatches": 0.0,
            "failed_consumers": 0.0, "checked_bindings": 0.0, "consumers": [],
            "binding_drift": 0.0,
            "binding_check_known": 0.0, "binding_expected_consumers": 0.0,
            "binding_checked_consumers": 0.0,
            "source_check_known": 0.0, "source_drift": 0.0, "source_expected": 0.0,
            "source_checked": 0.0, "source_drifted": 0.0, "source_failed_consumers": 0.0,
            "source_consumers": [], "error": error}


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    bindings = raw.get("bindings") if isinstance(raw.get("bindings"), dict) else {}
    sources = raw.get("sources") if isinstance(raw.get("sources"), dict) else None
    consumers_raw = bindings.get("consumers") if isinstance(bindings.get("consumers"), list) else []
    consumers = []
    for item in consumers_raw:
        if not isinstance(item, dict):
            continue
        mismatches = item.get("mismatches") if isinstance(item.get("mismatches"), list) else []
        consumers.append({
            "script_name": str(item.get("scriptName", "") or "unknown"),
            "checked": _num(item.get("checked")),
            "mismatches": float(len(mismatches)),
            "ok": 1.0 if bool(item.get("ok")) else 0.0,
        })
    source_consumers = []
    for item in (sources.get("consumers") if sources and isinstance(sources.get("consumers"), list) else []):
        if not isinstance(item, dict):
            continue
        source_consumers.append({
            "script_name": str(item.get("scriptName", "") or "unknown"),
            "matches": 1.0 if bool(item.get("matches")) else 0.0,
        })
    # Binding coverage. ``mismatches``/``failed`` alone cannot distinguish "every
    # dropdown verified and correct" from "nothing was verified at all": a run
    # that opened no consumer reports both as 0. Measured 2026-07-23 in
    # production -- expectedConsumers=7, checkedConsumers=0, snapshot ok=false,
    # and live_overlay_tv_binding_drift still read 0 (green, no alert). The
    # coverage terms below close that, mirroring the saved-source half.
    binding_expected = _num(bindings.get("expectedConsumers"))
    binding_checked = _num(bindings.get("checkedConsumers"))
    source_expected = _num(sources.get("expected")) if sources else 0.0
    source_checked = _num(sources.get("checked")) if sources else 0.0
    source_drifted = _num(sources.get("drifted")) if sources else 0.0
    source_failed = float(len(sources.get("failed") or [])) if sources else 0.0
    return {
        "loaded": 1.0,
        "generated_at_unix": _num(raw.get("generated_at_unix")),
        "ok": 1.0 if bool(raw.get("ok")) else 0.0,
        "mismatches": _num(bindings.get("mismatches")),
        "failed_consumers": float(len(bindings.get("failed") or [])),
        "checked_bindings": _num(bindings.get("checkedBindings")),
        "consumers": consumers,
        "binding_drift": 1.0 if (
            _num(bindings.get("mismatches")) > 0
            or len(bindings.get("failed") or []) > 0
            or binding_checked != binding_expected
        ) else 0.0,
        "binding_check_known": 1.0 if binding_expected > 0 else 0.0,
        "binding_expected_consumers": binding_expected,
        "binding_checked_consumers": binding_checked,
        "source_check_known": 1.0 if sources is not None and source_expected > 0 else 0.0,
        "source_drift": 1.0 if source_drifted > 0 or source_failed > 0 or source_checked != source_expected else 0.0,
        "source_expected": source_expected,
        "source_checked": source_checked,
        "source_drifted": source_drifted,
        "source_failed_consumers": source_failed,
        "source_consumers": source_consumers,
        "error": "",
    }


def _load() -> dict[str, Any]:
    body: str | None = None
    url = config.tradingview_bindings_snapshot_url()
    if url.lower().startswith("https://"):
        headers = {"Accept": "application/vnd.github.raw+json", "User-Agent": "skipp-tv-bindings/1.0"}
        token = config.tradingview_bindings_snapshot_url_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
                body = response.read().decode("utf-8")
        except Exception:
            body = None
    if body is None:
        path = config.tradingview_bindings_snapshot_path()
        if not path.exists():
            return _empty("missing_snapshot")
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            return _empty("unreadable_snapshot")
    try:
        parsed = json.loads(body)
    except ValueError:
        return _empty("malformed_snapshot")
    if isinstance(parsed, dict) and str(parsed.get("encoding", "")).lower() == "base64":
        try:
            parsed = json.loads(base64.b64decode(str(parsed["content"])).decode("utf-8"))
        except (KeyError, TypeError, ValueError):
            return _empty("malformed_snapshot")
    return _coerce(parsed) if isinstance(parsed, dict) else _empty("malformed_snapshot")


def snapshot() -> dict[str, Any]:
    """Return a TTL-cached snapshot without raising."""
    with _lock:
        now = time.monotonic()
        if _cache["snapshot"] is None or now - float(_cache["at"]) >= config.experiment_cache_ttl_secs():
            fresh = _load()
            # Keep last-good on transient failures (sibling-bridge contract):
            # a failed reload must not evict a previously loaded snapshot for
            # a full TTL — staleness stays visible via the age gauges, which
            # recompute from the retained generated_at_unix every scrape.
            if fresh.get("loaded") == 1.0 or _cache["snapshot"] is None:
                _cache["snapshot"] = fresh
            _cache["at"] = now
        return dict(_cache["snapshot"])
