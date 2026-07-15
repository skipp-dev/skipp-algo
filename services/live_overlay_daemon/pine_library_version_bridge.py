"""Pine-library version bridge — serves Repo↔TradingView pin drift.

Consumer half of the monitoring layer added after the 2026-07-13 incident chain
(#3599/#3603): the ``import preuss_steffen/<lib>/<N>`` pins in the repo drifted
from the real published TradingView version (micro_profiles ``/1`` vs a live
``/152`` for ~4 months) with NOTHING alerting — CE10272 on every modern ``mp.*``
symbol. The producer (``scripts/build_pine_library_version_snapshot.ts``) probes
each library's published version via the pine-facade ``filter=published`` listing
and writes a compact snapshot; this bridge fetches it (runtime URL, local-file
fallback) and normalizes it into the fields ``metrics.render_metrics`` turns into
Prometheus gauges. It never raises — a missing / unreadable snapshot yields
``loaded=0``; the separate ``Pine-library snapshot unloadable`` alert catches
that case. A loaded snapshot without a ``generated_at_unix`` timestamp exports
``snapshot_age_known=0`` and ``snapshot_age_seconds=0`` so the stale alert must
gate on ``snapshot_age_known`` to avoid reading zero as fresh.
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


def _empty(loaded: float, error: str) -> dict[str, Any]:
    return {
        "loaded": loaded,
        "generated_at_unix": 0.0,
        "any_drift": 0.0,
        "libraries_probed": 0.0,
        "libraries_drifted": 0.0,
        "facade_error": "",
        "libraries": [],
        "error": error,
    }


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parsed snapshot into a fixed shape; tolerate missing keys."""
    libraries_raw = raw.get("libraries") if isinstance(raw.get("libraries"), list) else []
    libraries: list[dict[str, Any]] = []
    for lib in libraries_raw:
        if not isinstance(lib, dict):
            continue
        tv_version_known = bool(lib.get("tvVersionKnown"))
        consumers_raw = lib.get("consumers") if isinstance(lib.get("consumers"), list) else []
        consumers = [
            {
                "file": str(c.get("file", "") or ""),
                "pinned_version": _num(c.get("pinnedVersion")),
                "drift": 1.0 if bool(c.get("drift")) else 0.0,
            }
            for c in consumers_raw
            if isinstance(c, dict)
        ]
        libraries.append(
            {
                "name": str(lib.get("name", "") or ""),
                # tv_version is only meaningful when known; carry the raw number
                # so the gauge can emit it, gated by tv_version_known.
                "tv_version": _num(lib.get("tvVersion")),
                "tv_version_known": 1.0 if tv_version_known else 0.0,
                "consumers": consumers,
                "any_consumer_drift": 1.0 if bool(lib.get("anyConsumerDrift")) else 0.0,
            }
        )

    return {
        "loaded": 1.0,
        "generated_at_unix": _num(raw.get("generated_at_unix")),
        "any_drift": 1.0 if bool(raw.get("anyDrift")) else 0.0,
        "libraries_probed": _num(raw.get("librariesProbed")),
        "libraries_drifted": _num(raw.get("librariesDrifted")),
        "facade_error": str(raw.get("facadeError", "") or ""),
        "libraries": libraries,
        "error": "",
    }


def _is_github_contents_api_url(url: str) -> bool:
    """True when ``url`` is a GitHub Contents API endpoint (mirrors compute)."""
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
    headers = {"Accept": "application/json", "User-Agent": "skipp-pine-library-version/1.0"}
    # GitHub's Contents API returns a base64 metadata envelope for the default
    # Accept; ask for the raw file instead (same fix the evidence-freshness /
    # provider-usage bridges carry). Without this the documented Contents-API
    # URL decodes to an EMPTY snapshot with loaded=1, keeping the stale alert
    # silently green.
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
    """Decode a GitHub Contents API base64 envelope to the inner JSON dict.

    Belt-and-suspenders: even if the raw-Accept upgrade above is stripped by a
    proxy or a stale token, recognise ``{content, encoding: "base64"}`` and
    decode it rather than silently treating the envelope as an empty snapshot.
    Returns ``None`` when *parsed* is not such an envelope.
    """
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
    url = config.pine_library_versions_snapshot_url()
    if url:
        body = _fetch_url(url, config.pine_library_versions_snapshot_url_token())
        if body is not None:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return _coerce(_decode_github_envelope(parsed) or parsed)

    path = config.pine_library_versions_snapshot_path()
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
    """Return the cached Pine-library version snapshot; never raises."""
    global _cached, _cached_at_monotonic
    ttl = config.experiment_cache_ttl_secs()
    with _cache_lock:
        now_mono = time.monotonic()
        if _cached is not None and (now_mono - _cached_at_monotonic) < ttl:
            return dict(_cached)
        fresh = _load_raw()
        _cached = fresh
        _cached_at_monotonic = time.monotonic()
        return dict(fresh)
