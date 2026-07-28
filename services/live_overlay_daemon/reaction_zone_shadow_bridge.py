"""Reaction-zone shadow bridge — serves the reaction-zone follow-through study's
per-direction best-variant lift + promotion verdict.

Consumer half of the reaction-zone shadow monitoring, mirroring the sweep-trap
shadow bridge exactly: the daily ``scripts/eval_reaction_zone_shadow.py`` writes a
compact snapshot (``artifacts/monitoring/reaction_zone_shadow.json``) and the
``sweep-trap-shadow-daily`` workflow publishes it to the rolling
``bot/live-sweep-trap-shadow`` branch alongside ``sweep_trap_shadow.json``. This
bridge fetches it (runtime URL, local-file fallback, TTL-cached) and normalizes it
into the fields ``metrics.render_metrics`` turns into Prometheus gauges. It never
raises — a missing/unreadable snapshot yields ``loaded=0`` with
``age_known=0``/``stale=0`` (the age gauge drops to 0, it does not keep climbing),
which the dedicated ``lo-reaction-zone-shadow-age-unknown`` alert catches; the stale
alert only covers snapshots whose age is KNOWN (updated_at parses to a real epoch).

The reaction-zone study is OBSERVE-ONLY (it changes no score); these gauges exist so
the per-direction lift + promotion-candidate accrual is visible in Grafana instead of
buried in a committed JSONL ledger. Nothing here feeds a trade/signal path.

Schema note: the reaction snapshot stamps its freshness as an ISO-8601 ``updated_at``
string (from the workflow's ``--now-iso``), not a unix ``generated_at`` float like the
sweep-trap snapshot, so this bridge parses it to an epoch for the staleness gate.
"""

from __future__ import annotations

import base64
import datetime
import json
import math
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
_CODE_VERDICT = {0: "INCONCLUSIVE", 1: "SHADOW", 2: "PROMOTABLE"}
_DIRECTIONS = ("bull", "bear")


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def _parse_iso_to_unix(value: Any) -> float:
    """Parse an ISO-8601 ``updated_at`` string to a unix epoch; 0.0 if unparsable.

    Returns 0.0 (age-unknown) for None/""/malformed timestamps so the staleness
    gate treats an undated snapshot exactly like the no-data seed, never as fresh.
    """
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    epoch = parsed.timestamp()
    return epoch if math.isfinite(epoch) and epoch > 0.0 else 0.0


def _empty(loaded: float, error: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "loaded": loaded,
        "generated_at_unix": 0.0,
        "date": "",
        "n_samples": 0.0,
        "min_samples": 0.0,
        "lift_promote_threshold": 0.0,
        "verdict": "",
        "verdict_code": 0.0,
        "error": error,
    }
    for direction in _DIRECTIONS:
        out[f"{direction}_best_variant"] = ""
        out[f"{direction}_best_lift"] = 0.0
        out[f"{direction}_best_verdict"] = ""
        out[f"{direction}_best_verdict_code"] = 0.0
    return out


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    by_direction = raw.get("by_direction")
    by_direction = by_direction if isinstance(by_direction, dict) else {}
    cfg = raw.get("config")
    cfg = cfg if isinstance(cfg, dict) else {}
    updated_at = raw.get("updated_at")

    out: dict[str, Any] = {
        "loaded": 1.0,
        "generated_at_unix": _parse_iso_to_unix(updated_at),
        "date": str(updated_at)[:10] if isinstance(updated_at, str) and updated_at else "",
        "n_samples": _num(raw.get("n_reaction_samples")),
        "min_samples": _num(cfg.get("min_samples")),
        "lift_promote_threshold": _num(cfg.get("lift_promote_threshold")),
        "error": "",
    }

    # Overall verdict = the strongest cell across BOTH directions × ALL variants,
    # so "is anything a promotion candidate" is a single number; per-direction we
    # also surface the highest-lift variant and its own verdict for the table.
    overall_code = 0
    for direction in _DIRECTIONS:
        dir_block = by_direction.get(direction)
        dir_block = dir_block if isinstance(dir_block, dict) else {}
        variants = dir_block.get("variants")
        variants = variants if isinstance(variants, dict) else {}
        best_name = dir_block.get("best_variant")
        best_name = best_name if isinstance(best_name, str) else ""
        best_metrics = variants.get(best_name) if best_name else None
        best_metrics = best_metrics if isinstance(best_metrics, dict) else {}
        best_verdict = str(best_metrics.get("verdict", "") or "")
        out[f"{direction}_best_variant"] = best_name
        out[f"{direction}_best_lift"] = _num(best_metrics.get("lift"))
        out[f"{direction}_best_verdict"] = best_verdict
        out[f"{direction}_best_verdict_code"] = float(_VERDICT_CODE.get(best_verdict, 0))
        for variant_metrics in variants.values():
            if isinstance(variant_metrics, dict):
                code = _VERDICT_CODE.get(str(variant_metrics.get("verdict", "") or ""), 0)
                overall_code = max(overall_code, code)

    out["verdict_code"] = float(overall_code)
    out["verdict"] = _CODE_VERDICT.get(overall_code, "")
    return out


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
    headers = {"Accept": "application/json", "User-Agent": "skipp-reaction-zone-shadow/1.0"}
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
    url = config.reaction_zone_shadow_snapshot_url()
    if url:
        body = _fetch_url(url, config.reaction_zone_shadow_snapshot_url_token())
        if body is not None:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return _coerce(_decode_github_envelope(parsed) or parsed)

    path = config.reaction_zone_shadow_snapshot_path()
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
    """Return the cached reaction-zone shadow snapshot; never raises.

    A failed load keeps the last good snapshot so a transient outage does not
    immediately flip the dashboard to loaded=0.
    """
    global _cached, _cached_at_monotonic
    ttl = config.reaction_zone_shadow_cache_ttl_secs()
    with _cache_lock:
        now_mono = time.monotonic()
        if _cached is not None and (now_mono - _cached_at_monotonic) < ttl:
            return dict(_cached)  # defensive copy — matches the other bridges' contract
        loaded = _load_raw()
        if loaded.get("loaded") == 1.0 or _cached is None:
            _cached = loaded
        _cached_at_monotonic = now_mono
        return dict(_cached)


def _reset_cache_for_tests() -> None:
    global _cached, _cached_at_monotonic
    with _cache_lock:
        _cached = None
        _cached_at_monotonic = 0.0
