"""Sweep-trap shadow bridge — serves the WS4a shadow-eval's Brier-delta + verdict.

Consumer half of the sweep-trap shadow monitoring: the daily
``scripts/eval_sweep_trap_shadow.py`` writes a compact snapshot
(``artifacts/monitoring/sweep_trap_shadow.json``); this bridge fetches it
(runtime URL, local-file fallback, TTL-cached) and normalizes it into the fields
``metrics.render_metrics`` turns into Prometheus gauges. It never raises — a
missing/unreadable snapshot yields ``loaded=0`` and the snapshot-age gauge stops
advancing, which the ``Sweep-trap shadow stale`` alert catches.

The sweep-trap detector stays in shadow (no score-budget weight); these gauges
exist so the Brier-delta + sample accrual toward the promotion decision are
visible in Grafana instead of buried in a committed JSONL ledger.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from . import config

_cache_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at_monotonic = 0.0

_VERDICT_CODE = {"INCONCLUSIVE": 0, "SHADOW": 1, "PROMOTABLE": 2}


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _empty(loaded: float, error: str) -> dict[str, Any]:
    return {
        "loaded": loaded,
        "generated_at_unix": 0.0,
        "date": "",
        "n_samples": 0.0,
        "min_samples": 0.0,
        "brier_delta": 0.0,
        "lift": 0.0,
        "verdict": "",
        "verdict_code": 0.0,
        "error": error,
    }


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    verdict = str(raw.get("verdict", "") or "")
    # Trust the producer's verdict_code but fall back to the name mapping.
    code = raw.get("verdict_code")
    verdict_code = _num(code) if isinstance(code, (int, float)) and not isinstance(code, bool) else float(
        _VERDICT_CODE.get(verdict, 0)
    )
    return {
        "loaded": 1.0,
        "generated_at_unix": _num(raw.get("generated_at")),
        "date": str(raw.get("date", "") or ""),
        "n_samples": _num(raw.get("n_samples")),
        "min_samples": _num(raw.get("min_samples")),
        "brier_delta": _num(raw.get("brier_delta")),
        "lift": _num(raw.get("lift")),
        "verdict": verdict,
        "verdict_code": verdict_code,
        "error": "",
    }


def _is_github_contents_api_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.netloc.lower() == "api.github.com"
        and "/repos/" in parsed.path.lower()
        and "/contents/" in parsed.path.lower()
    )


def _fetch_url(url: str, token: str, timeout: float = 10.0) -> str | None:
    if not url.lower().startswith("https://"):
        return None
    headers = {"Accept": "application/json", "User-Agent": "skipp-sweep-trap-shadow/1.0"}
    if _is_github_contents_api_url(url):
        headers["Accept"] = "application/vnd.github.raw+json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception:
        return None


def _decode_github_envelope(parsed: dict[str, Any]) -> dict[str, Any] | None:
    if str(parsed.get("encoding", "")).lower() != "base64" or "content" not in parsed:
        return None
    try:
        inner = base64.b64decode(str(parsed["content"])).decode("utf-8")
        decoded = json.loads(inner)
    except (ValueError, TypeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _load_raw() -> dict[str, Any]:
    """Fetch + parse the snapshot (URL first, local fallback); never raises."""
    url = config.sweep_trap_shadow_snapshot_url()
    if url:
        body = _fetch_url(url, config.sweep_trap_shadow_snapshot_url_token())
        if body is not None:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return _coerce(_decode_github_envelope(parsed) or parsed)

    path = config.sweep_trap_shadow_snapshot_path()
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
    """Return the cached sweep-trap shadow snapshot; never raises."""
    global _cached, _cached_at_monotonic
    ttl = config.sweep_trap_shadow_cache_ttl_secs()
    with _cache_lock:
        now_mono = time.monotonic()
        if _cached is not None and (now_mono - _cached_at_monotonic) < ttl:
            return _cached
        loaded = _load_raw()
        _cached = loaded
        _cached_at_monotonic = now_mono
        return loaded


def _reset_cache_for_tests() -> None:
    global _cached, _cached_at_monotonic
    with _cache_lock:
        _cached = None
        _cached_at_monotonic = 0.0
