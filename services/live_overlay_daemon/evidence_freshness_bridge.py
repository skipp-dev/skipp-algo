"""Evidence-freshness bridge — serves the ADR-0023 evidence chain's output age.

Consumer half of the monitoring layer added after the 2026-06/07 blind-spot
(see ``scripts/build_evidence_freshness_snapshot.py`` for the why). The producer
writes a compact snapshot; this bridge fetches it (runtime URL, local-file
fallback) and normalizes it into the fields ``metrics.render_metrics`` turns
into Prometheus gauges. It never raises — a missing / unreadable snapshot yields
``loaded=0``; the separate ``Evidence snapshot unloadable`` alert catches that
case. A loaded snapshot without a ``generated_at_unix`` timestamp exports
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
from datetime import UTC, date, datetime
from typing import Any

from . import config

_cache_lock = threading.Lock()
_cached: dict[str, Any] | None = None
_cached_at_monotonic = 0.0


def _midnight_epoch(date_str: str) -> float | None:
    """UTC-midnight epoch for a ``YYYY-MM-DD`` string, or ``None`` if unparseable."""
    try:
        d = date.fromisoformat(str(date_str))
    except (TypeError, ValueError):
        return None
    return datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()


def age_seconds_from_date(date_str: str, *, now: float | None = None) -> float | None:
    """Seconds between UTC-midnight of ``date_str`` and ``now`` (never negative)."""
    epoch = _midnight_epoch(date_str)
    if epoch is None:
        return None
    return max(0.0, (time.time() if now is None else now) - epoch)


def _empty(loaded: float, error: str) -> dict[str, Any]:
    return {
        "loaded": loaded,
        "generated_at_unix": 0.0,
        "ledger": {"newest_date": "", "plane": "", "rows": 0, "candidate_pass": 0},
        "audit_branch": {"last_commit_date": ""},
        "samples": {"target": 0, "per_family": {}},
        "fills": {
            "filled_cumulative": 0,
            "closed_cumulative": 0,
            "submit_failed_cumulative": 0,
            "target": 0,
            "newest_incubation_date": "",
        },
        "wsh": {"newest_date": "", "status": ""},
        "submitter": {"submit_code_behind_commits": 0, "known": 0},
        "error": error,
    }


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize a parsed snapshot into a fixed shape; tolerate missing keys."""
    ledger = raw.get("ledger") if isinstance(raw.get("ledger"), dict) else {}
    audit = raw.get("audit_branch") if isinstance(raw.get("audit_branch"), dict) else {}
    samples = raw.get("samples") if isinstance(raw.get("samples"), dict) else {}
    fills = raw.get("fills") if isinstance(raw.get("fills"), dict) else {}
    wsh = raw.get("wsh") if isinstance(raw.get("wsh"), dict) else {}
    submitter = raw.get("submitter") if isinstance(raw.get("submitter"), dict) else {}

    def _num(value: Any) -> float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0

    per_family_raw = samples.get("per_family") if isinstance(samples.get("per_family"), dict) else {}
    per_family = {
        str(fam): {
            "usable": _num(v.get("usable")) if isinstance(v, dict) else 0.0,
            "classification": str(v.get("classification", "") or "") if isinstance(v, dict) else "",
        }
        for fam, v in per_family_raw.items()
    }

    return {
        "loaded": 1.0,
        "generated_at_unix": _num(raw.get("generated_at_unix")),
        "ledger": {
            "newest_date": str(ledger.get("newest_date", "") or ""),
            "plane": str(ledger.get("plane", "") or ""),
            "rows": _num(ledger.get("rows")),
            "candidate_pass": _num(ledger.get("candidate_pass")),
        },
        "audit_branch": {"last_commit_date": str(audit.get("last_commit_date", "") or "")},
        "samples": {"target": _num(samples.get("target")), "per_family": per_family},
        "fills": {
            "filled_cumulative": _num(fills.get("filled_cumulative")),
            "closed_cumulative": _num(fills.get("closed_cumulative")),
            "submit_failed_cumulative": _num(fills.get("submit_failed_cumulative")),
            "target": _num(fills.get("target")),
            "newest_incubation_date": str(fills.get("newest_incubation_date", "") or ""),
        },
        "wsh": {
            "newest_date": str(wsh.get("newest_date", "") or ""),
            "status": str(wsh.get("status", "") or ""),
        },
        "submitter": {
            "submit_code_behind_commits": _num(submitter.get("submit_code_behind_commits")),
            "known": _num(submitter.get("known")),
        },
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
    headers = {"Accept": "application/json", "User-Agent": "skipp-evidence-freshness/1.0"}
    # GitHub's Contents API returns a base64 metadata envelope for the default
    # Accept; ask for the raw file instead (same fix the news/experiment
    # bridges already carry — compute._is_github_contents_api_url). Without
    # this, the documented Contents-API URL decodes to an EMPTY snapshot with
    # loaded=1, keeping the stale alert silently green (post-review finding 1).
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
    url = config.evidence_freshness_snapshot_url()
    if url:
        body = _fetch_url(url, config.evidence_freshness_snapshot_url_token())
        if body is not None:
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                return _coerce(_decode_github_envelope(parsed) or parsed)

    path = config.evidence_freshness_snapshot_path()
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
    """Return the cached evidence-freshness snapshot; never raises."""
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
