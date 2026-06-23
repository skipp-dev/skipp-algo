"""GitHub Actions workflow bridge with lightweight in-process caching.

The bridge polls GitHub Actions workflow runs and exposes a compact snapshot for
Prometheus metric export in ``metrics.render_metrics``.

It is optional and env-driven:
- when ``GITHUB_WORKFLOW_MONITOR_TOKEN`` is unset, bridge metrics are emitted as
  disabled and no outbound requests are made.
- errors never bubble into scrape failures; they are converted into status
  gauges via ``snapshot()`` fallback payloads.
"""
from __future__ import annotations

import datetime
import json
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from . import config

_cache_lock = threading.Lock()
_cached_snapshot: dict[str, Any] | None = None
_cached_at_monotonic = 0.0


def _phase_code(status: str, conclusion: str | None) -> int:
    if status == "queued":
        return 1
    if status == "in_progress":
        return 2
    if status != "completed":
        return 0

    match (conclusion or "").lower():
        case "success":
            return 3
        case "failure":
            return 4
        case "cancelled":
            return 5
        case "skipped":
            return 6
        case "neutral":
            return 7
        case "timed_out":
            return 8
        case "action_required":
            return 9
        case "startup_failure":
            return 10
        case "stale":
            return 11
        case _:
            return 0


def _iso_age_seconds(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        epoch = parsed.timestamp()
    except Exception:
        return None
    return max(0.0, time.time() - epoch)


def _duration_seconds(started_at: str | None, updated_at: str | None) -> float | None:
    if not started_at or not updated_at:
        return None
    try:
        start = datetime.datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=datetime.UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=datetime.UTC)
        s_epoch = start.timestamp()
        u_epoch = end.timestamp()
    except Exception:
        return None
    return max(0.0, u_epoch - s_epoch)


def _github_request_json(url: str, token: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "skipp-live-overlay-monitor/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _fetch_snapshot(token: str) -> dict[str, Any]:
    owner, repo = config.github_workflow_repo()
    timeout = config.github_workflow_timeout_secs()
    per_page = config.github_workflow_per_page()
    params = urllib.parse.urlencode({"per_page": per_page})
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/runs?{params}"
    parsed = _github_request_json(url, token, timeout)

    runs_raw = list(parsed.get("workflow_runs") or [])
    configured_workflow_ids = set(config.github_workflow_ids())
    if configured_workflow_ids:
        runs_raw = [
            run
            for run in runs_raw
            if str(run.get("workflow_id", "")) in configured_workflow_ids
        ]

    counts = {
        "seen": 0,
        "success": 0,
        "failed": 0,
        "in_progress": 0,
        "queued": 0,
    }

    latest_age = None
    latest_duration = None
    workflows_latest: dict[str, dict[str, Any]] = {}

    for run in runs_raw:
        counts["seen"] += 1
        status = str(run.get("status", "")).lower()
        conclusion = str(run.get("conclusion", "")).lower() if run.get("conclusion") is not None else None
        if status == "queued":
            counts["queued"] += 1
        elif status == "in_progress":
            counts["in_progress"] += 1
        elif status == "completed" and conclusion == "success":
            counts["success"] += 1
        elif status == "completed":
            counts["failed"] += 1

        age = _iso_age_seconds(run.get("created_at"))
        duration = _duration_seconds(run.get("run_started_at"), run.get("updated_at"))
        if age is not None and (latest_age is None or age < latest_age):
            latest_age = age
            latest_duration = duration

        workflow_id = str(run.get("workflow_id", "unknown"))
        if workflow_id not in workflows_latest:
            workflows_latest[workflow_id] = {
                "id": workflow_id,
                "name": str(run.get("name", "unknown")) or "unknown",
                "event": str(run.get("event", "")).lower() or "unknown",
                # Keep raw GitHub conclusion semantics; queued/in_progress runs
                # have no conclusion yet and should remain "unknown" here.
                "conclusion": conclusion or "unknown",
                "phase_code": _phase_code(status, conclusion),
                "latest_success": 1 if status == "completed" and conclusion == "success" else 0,
                "latest_age_seconds": age,
                "latest_duration_seconds": duration,
            }

    return {
        "enabled": 1,
        "ok": 1,
        "fetched_at_unix": time.time(),
        "counts": counts,
        "latest_run_age_seconds": latest_age,
        "latest_run_duration_seconds": latest_duration,
        "workflows": list(workflows_latest.values()),
    }


def snapshot() -> dict[str, Any]:
    """Return cached GitHub workflow snapshot; never raises."""
    global _cached_snapshot, _cached_at_monotonic

    token = config.github_workflow_token()
    if not token:
        return {
            "enabled": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "counts": {
                "seen": 0,
                "success": 0,
                "failed": 0,
                "in_progress": 0,
                "queued": 0,
            },
            "latest_run_age_seconds": None,
            "latest_run_duration_seconds": None,
            "workflows": [],
            "error": "missing_token",
        }

    ttl = config.github_workflow_poll_ttl_secs()
    with _cache_lock:
        now_mono = time.monotonic()
        if _cached_snapshot is not None and (now_mono - _cached_at_monotonic) < ttl:
            return dict(_cached_snapshot)

        try:
            fresh = _fetch_snapshot(token)
        except Exception as exc:  # pragma: no cover
            fresh = {
                "enabled": 1,
                "ok": 0,
                "fetched_at_unix": time.time(),
                "counts": {
                    "seen": 0,
                    "success": 0,
                    "failed": 0,
                    "in_progress": 0,
                    "queued": 0,
                },
                "latest_run_age_seconds": None,
                "latest_run_duration_seconds": None,
                "workflows": [],
                "error": type(exc).__name__,
            }

        _cached_snapshot = fresh
        _cached_at_monotonic = time.monotonic()
        return dict(fresh)
