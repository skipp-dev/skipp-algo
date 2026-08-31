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
#: Eigener Zustand fuer die Praesenz-Sonde: andere Kadenz, anderes Ausfallbild.
#: Faellt sie aus, darf das den Haupt-Snapshot NICHT mitreissen -- deshalb
#: getrennte Sperre, getrennter Cache, getrenntes try am Aufrufort.
_presence_lock = threading.Lock()
_presence_cache: dict[str, float | None] | None = None
_presence_at_monotonic = 0.0
_workflow_ids_cache: dict[str, int] | None = None
_workflow_ids_at_monotonic = 0.0
#: Die Namen->ID-Tabelle aendert sich nur, wenn jemand eine Workflow-Datei
#: anlegt, umbenennt oder loescht. Eine Stunde ist reichlich und spart pro
#: Praesenz-Runde die Paginierung ueber /actions/workflows.
_WORKFLOW_IDS_TTL_SECONDS = 3600.0
_cached_snapshot: dict[str, Any] | None = None
_cached_at_monotonic = 0.0

# Conclusions that constitute a workflow-health VERDICT for ``latest_success``.
# A cancelled / skipped / stale / neutral / action_required run says nothing
# about health — the common case is a merge-train concurrency cancel (rapid
# merges cancel older in-flight CI runs), and treating that cancel as
# "not green" flapped the no-green-24h alarm (2026-07-07). Only a genuine
# success or failure finalizes the verdict; non-verdict conclusions are
# skipped so an older CONCLUSIVE run supplies it.
_GREEN_CONCLUSION = "success"
_FAILURE_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
_VERDICT_CONCLUSIONS = frozenset({_GREEN_CONCLUSION}) | _FAILURE_CONCLUSIONS


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
    return age if (age := time.time() - epoch) >= 0.0 else None


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


def _classify_error(exc: Exception) -> str:
    """Map an exception to a small, stable error-code vocabulary."""
    name = type(exc).__name__
    if "Timeout" in name:
        return "timeout"
    if name == "HTTPError":
        return "http_error"
    if name in ("URLError", "ConnectionError", "SSLError", "OSError"):
        return "network_error"
    if "JSON" in name or "json" in name.lower():
        return "json_error"
    return "unknown"


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
    query: dict[str, str] = {"per_page": str(per_page)}
    branch = config.github_workflow_branch()
    if branch:
        # Scope to the default branch so a green feature-branch run cannot mask a
        # red main run (and vice-versa): workflow health tracks main, not PRs.
        # main runs are sparser than all-branch runs, so the same ``per_page``
        # window spans more calendar time. Empty branch (config) disables the
        # filter; github_workflow_per_page documents the page-coverage requirement.
        query["branch"] = branch
    params = urllib.parse.urlencode(query)
    # GitHub returns runs newest-first, so the first page holds the most recent
    # runs; ``per_page`` (default 100) is sized so a monitored workflow's newest
    # verdict stays on the page -- heavy main-push days can otherwise bury it.
    # ``owner``/``repo`` come from config but are percent-encoded defensively in case
    # they ever contain URL-significant characters.
    safe_owner = urllib.parse.quote(owner, safe="")
    safe_repo = urllib.parse.quote(repo, safe="")
    url = f"https://api.github.com/repos/{safe_owner}/{safe_repo}/actions/runs?{params}"
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
        elif status == "completed" and conclusion in _FAILURE_CONCLUSIONS:
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
                # Keep status/conclusion semantics explicit for downstream
                # consumers: `status` is lifecycle state (queued/in_progress/
                # completed), while `conclusion` is only populated by GitHub
                # once a run has completed (success/failure/cancelled/...).
                "status": status or "unknown",
                # Queued/in_progress runs have no conclusion yet and therefore
                # remain "unknown" until GitHub marks completion.
                "conclusion": conclusion or "unknown",
                "phase_code": _phase_code(status, conclusion),
                # Provisional: finalized from the newest COMPLETED run below.
                "latest_success": 0,
                "latest_age_seconds": age,
                "latest_duration_seconds": duration,
            }
        # latest_success reflects the newest run that reached a VERDICT
        # (success or a genuine failure), not merely the newest completed run:
        # a long in-flight run has no verdict yet, and a cancelled/skipped run
        # (merge-train concurrency cancel) is not a health signal either.
        # Counting either as "not green" flapped the no-green-24h alarm
        # (in-flight: smc-library-refresh; cancelled: CI merge train, both
        # 2026-07-07). Runs arrive newest-first, so the first verdict run per
        # workflow wins; non-verdict runs are skipped, older verdicts ignored.
        row = workflows_latest[workflow_id]
        if (
            status == "completed"
            and conclusion in _VERDICT_CONCLUSIONS
            and "latest_success_final" not in row
        ):
            row["latest_success"] = 1 if conclusion == _GREEN_CONCLUSION else 0
            row["latest_success_final"] = True

    # Drop the internal finalization marker before the snapshot is exposed.
    for row in workflows_latest.values():
        row.pop("latest_success_final", None)

    # Praesenz jedes DEKLARIERTEN Workflows. 2026-08-31 umgestellt: frueher
    # gegen die Lauf-Seite dieses Polls geurteilt -- und die deckte an dem Tag
    # neun Stunden ab (am 2026-08-20 fuenf; sie schrumpft mit der Aktivitaet).
    # Ein taeglicher Workflow fehlte darauf zwei Drittel des Tages, "gestoppt"
    # und "lief heute frueh" waren also nicht unterscheidbar. Die Regel darueber
    # laeuft mit `for: 6h` -- sie haette bei gesetzter Erwartungsliste JEDEN TAG
    # fuer JEDEN Daily gefeuert. Die Praesenz kommt jetzt aus einer eigenen
    # Abfrage je Workflow mit eigener, langsamerer Kadenz (presence_snapshot).
    alter = presence_snapshot()
    expected_present = {name: (0 if alter.get(name) is None else 1) for name in alter}

    return {
        "enabled": 1,
        "configured": 1,
        "ok": 1,
        "fetched_at_unix": time.time(),
        "last_success_fetched_at_unix": time.time(),
        "counts": counts,
        "latest_run_age_seconds": latest_age,
        "latest_run_duration_seconds": latest_duration,
        "workflows": list(workflows_latest.values()),
        "expected_present": expected_present,
    }


def _workflow_ids_by_name(token: str, timeout: int) -> dict[str, int]:
    """Anzeigename -> Workflow-ID, ueber alle Seiten, stundenweise gecacht."""
    global _workflow_ids_cache, _workflow_ids_at_monotonic

    now_mono = time.monotonic()
    if (
        _workflow_ids_cache is not None
        and (now_mono - _workflow_ids_at_monotonic) < _WORKFLOW_IDS_TTL_SECONDS
    ):
        return dict(_workflow_ids_cache)

    owner, repo = config.github_workflow_repo()
    safe_owner = urllib.parse.quote(owner, safe="")
    safe_repo = urllib.parse.quote(repo, safe="")
    tabelle: dict[str, int] = {}
    page = 1
    while page <= 10:  # harte Obergrenze: 1000 Workflows sind mehr als real
        url = (
            f"https://api.github.com/repos/{safe_owner}/{safe_repo}/actions/workflows"
            f"?per_page=100&page={page}"
        )
        parsed = _github_request_json(url, token, timeout)
        seite = list(parsed.get("workflows") or [])
        for eintrag in seite:
            name = str(eintrag.get("name") or "").strip()
            wid = eintrag.get("id")
            if name and isinstance(wid, int):
                tabelle.setdefault(name, wid)
        if len(seite) < 100:
            break
        page += 1

    _workflow_ids_cache = dict(tabelle)
    _workflow_ids_at_monotonic = now_mono
    return tabelle


def _presence_ages(token: str) -> dict[str, float | None]:
    """Alter des neuesten Laufs je DEKLARIERTEM Workflow, eigene Abfrage je Name.

    ``None`` heisst "kein Lauf gefunden" -- entweder gibt es den Workflow nicht
    (Name falsch geschrieben, Datei geloescht) oder er hat auf dem beobachteten
    Branch noch nie gelaufen. Beides ist ein Befund, kein fehlendes Datum.

    Bewusst NICHT aus der geteilten Lauf-Seite abgeleitet: die deckt nur wenige
    Stunden ab, und genau daran scheiterte die alte Fassung.
    """
    erwartet = config.github_workflow_expected()
    if not erwartet:
        return {}

    timeout = config.github_workflow_timeout_secs()
    ids = _workflow_ids_by_name(token, timeout)
    owner, repo = config.github_workflow_repo()
    safe_owner = urllib.parse.quote(owner, safe="")
    safe_repo = urllib.parse.quote(repo, safe="")
    branch = config.github_workflow_branch()

    raus: dict[str, float | None] = {}
    for name in erwartet:
        wid = ids.get(name)
        if wid is None:
            raus[name] = None
            continue
        query = "per_page=1"
        if branch:
            query += f"&branch={urllib.parse.quote(branch, safe='')}"
        url = (
            f"https://api.github.com/repos/{safe_owner}/{safe_repo}"
            f"/actions/workflows/{wid}/runs?{query}"
        )
        parsed = _github_request_json(url, token, timeout)
        runs = list(parsed.get("workflow_runs") or [])
        raus[name] = _iso_age_seconds(runs[0].get("created_at")) if runs else None
    return raus


def presence_snapshot() -> dict[str, float | None]:
    """Gecachte Praesenz-Alter. Wirft nicht; bei Fehlschlag der letzte Stand.

    Der zuletzt bekannte Stand ist hier die richtige Degradation: eine leere
    Antwort waere von "alle Workflows verschwunden" nicht zu unterscheiden und
    wuerde einen Alarm ausloesen, den ein API-Schluckauf verursacht hat.
    """
    global _presence_cache, _presence_at_monotonic

    token = config.github_workflow_token()
    if not token:
        return {}
    ttl = config.github_workflow_presence_ttl_secs()
    with _presence_lock:
        now_mono = time.monotonic()
        if _presence_cache is not None and (now_mono - _presence_at_monotonic) < ttl:
            return dict(_presence_cache)
        try:
            frisch = _presence_ages(token)
        except (OSError, ValueError, KeyError, TypeError):
            # Kein blankes `except`: der Repo-Waechter gegen breite Except-
            # Stellen gilt auch hier. Transport, kaputtes JSON, fehlende Felder.
            return dict(_presence_cache) if _presence_cache is not None else {}
        _presence_cache = dict(frisch)
        _presence_at_monotonic = now_mono
        return frisch


def snapshot() -> dict[str, Any]:
    """Return cached GitHub workflow snapshot; never raises."""
    global _cached_snapshot, _cached_at_monotonic

    token = config.github_workflow_token()
    if not token:
        return {
            "enabled": 0,
            "configured": 0,
            "ok": 0,
            "fetched_at_unix": 0.0,
            "scrape_duration_seconds": None,
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
            # No fetch happened, so presence is UNKNOWN, not "missing": emit no
            # series rather than a fabricated 0 that would page a disabled bridge.
            "expected_present": {},
            # Disabled bridge (no token → enabled=0) is NOT an error — the
            # missing-token state is already conveyed by configured=0. Emit
            # error=None so bridge_error_info stays 0, consistent with railway's
            # _disabled_snapshot (was error="missing_token" → a permanent
            # error_info=1 that read as a fault on an intentionally-off bridge).
            "error": None,
            "error_code": None,
            "error_message": "GITHUB_WORKFLOW_MONITOR_TOKEN is not set",
        }

    ttl = config.github_workflow_poll_ttl_secs()
    with _cache_lock:
        now_mono = time.monotonic()
        if _cached_snapshot is not None and (now_mono - _cached_at_monotonic) < ttl:
            return dict(_cached_snapshot)

        started = time.monotonic()
        try:
            fresh = _fetch_snapshot(token)
            fresh["scrape_duration_seconds"] = time.monotonic() - started
            if fresh.get("ok"):
                fresh.setdefault("last_success_fetched_at_unix", fresh.get("fetched_at_unix", 0.0))
        except Exception as exc:  # pragma: no cover
            error_code = _classify_error(exc)
            prev_last_success = (_cached_snapshot or {}).get("last_success_fetched_at_unix", 0.0)
            fresh = {
                "enabled": 1,
                "configured": 1,
                "ok": 0,
                "fetched_at_unix": time.time(),
                "last_success_fetched_at_unix": prev_last_success,
                "scrape_duration_seconds": time.monotonic() - started,
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
                # Scrape failed — presence is UNKNOWN. The keep-last-good path below
                # preserves the previous truthful map; this empty one only takes effect
                # when the very first poll failed, where silence beats a false "missing".
                "expected_present": {},
                "error": type(exc).__name__,
                "error_code": error_code,
                "error_message": str(exc),
            }

        if fresh.get("ok") == 1 or _cached_snapshot is None:
            _cached_snapshot = fresh
        else:
            # Keep last-good DATA but carry the truthful last-attempt STATUS
            # (see uptimerobot_bridge: retaining ok=1/error=none froze
            # bridge_scrape_success/error_info green during persistent
            # failures). A later success replaces the snapshot wholesale.
            _cached_snapshot = {
                **_cached_snapshot,
                "last_attempt_ok": 0,
                "last_attempt_error_code": str(fresh.get("error_code") or "unknown"),
            }
        _cached_at_monotonic = time.monotonic()
        return dict(_cached_snapshot)
