"""Railway API bridge: container metrics, and volume-backup health (bottom of file).

Polls the Railway public GraphQL API for per-service container resource usage
(CPU, memory, disk, network) and exposes it as a cached snapshot that
``metrics.py`` renders into Prometheus exposition text. Grafana Alloy already
scrapes the daemon ``/metrics`` endpoint, so no additional scrape job is
required.

Design mirrors :mod:`uptimerobot_bridge`:

* A lazily-refreshed in-process cache with a TTL avoids hammering the Railway
  API on every Prometheus scrape.
* :func:`snapshot` never raises; on any failure it returns the last good cache
  (if still useful) or an ``ok=False`` payload so the daemon keeps serving
  ``/metrics``.
* All configuration is read lazily via :mod:`config` so tests can patch the
  environment.
"""

from __future__ import annotations

import calendar
import json
import logging
import math
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from . import config

logger = logging.getLogger(__name__)

_GRAPHQL_ENDPOINT = "https://backboard.railway.com/graphql/v2"
_USER_AGENT = "skipp-live-overlay-daemon/railway-metrics"

# Railway measurement enum -> snapshot field name (native units preserved).
_MEASUREMENTS: dict[str, str] = {
    "CPU_USAGE": "cpu_cores",
    "MEMORY_USAGE_GB": "memory_gb",
    "MEMORY_LIMIT_GB": "memory_limit_gb",
    "DISK_USAGE_GB": "disk_gb",
    "NETWORK_RX_GB": "network_rx_gb",
    "NETWORK_TX_GB": "network_tx_gb",
}

_QUERY = (
    "query Metrics($projectId: String!, $environmentId: String!, "
    "$startDate: DateTime!, $measurements: [MetricMeasurement!]!, "
    "$sampleRateSeconds: Int) {"
    " metrics(projectId: $projectId, environmentId: $environmentId, "
    "startDate: $startDate, measurements: $measurements, "
    "groupBy: [SERVICE_ID], sampleRateSeconds: $sampleRateSeconds) {"
    " measurement tags { serviceId } values { ts value } } }"
)

_LOCK = threading.Lock()
_CACHE: dict[str, Any] | None = None
_CACHE_EXPIRES_AT: float = 0.0


def _iso_utc(epoch_seconds: float) -> str:
    """Format an epoch timestamp as an RFC3339/ISO-8601 UTC string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def _post_graphql(
    token: str,
    variables: dict[str, Any],
    timeout: int, query: str = _QUERY,  # one egress site, two queries — see _VOLUME_BACKUP_QUERY
) -> dict[str, Any]:
    """POST a GraphQL request to Railway and return the parsed JSON body."""
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        _GRAPHQL_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": _USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def _latest_value(values: list[dict[str, Any]]) -> float | None:
    """Return the newest finite ``value`` from a Railway series (order-independent)."""
    latest_ts: float | None = None
    latest_value: float | None = None
    for point in values:
        try:
            ts = float(point["ts"])
            value = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        # ``json.loads`` accepts the non-standard NaN/Infinity tokens, so a
        # still-aggregating or corrupt Railway sample can carry a non-finite
        # value. Skip it like any other invalid point so the last *finite*
        # reading wins instead of poisoning the Prometheus gauge with ``nan``.
        if not math.isfinite(ts) or not math.isfinite(value):
            continue
        # Running max of (ts, value): order-independent (Railway's response
        # order is not guaranteed) and breaks equal-ts ties deterministically.
        if latest_ts is None or (ts, value) > (latest_ts, latest_value):
            latest_ts = ts
            latest_value = value
    return latest_value


def _build_services(
    results: list[dict[str, Any]],
    service_names: dict[str, str],
) -> list[dict[str, Any]]:
    """Collapse Railway metric series into one record per service."""
    by_service: dict[str, dict[str, Any]] = {}
    for result in results:
        measurement = result.get("measurement")
        field = _MEASUREMENTS.get(measurement)
        if field is None:
            continue
        service_id = (result.get("tags") or {}).get("serviceId")
        if not service_id:
            continue
        latest = _latest_value(result.get("values") or [])
        if latest is None:
            continue
        record = by_service.setdefault(
            service_id,
            {
                "service_id": service_id,
                "service": service_names.get(service_id, service_id),
            },
        )
        record[field] = latest
    # Sort by str(id): a schema-violating response or hand-built cache can mix
    # str and int serviceIds, and a bare ``sorted`` would then raise a TypeError
    # that ``snapshot`` does not catch. ``metrics`` renders the id via ``str``.
    return [by_service[key] for key in sorted(by_service, key=str)]


def _fetch() -> dict[str, Any]:
    """Fetch the current Railway metrics snapshot (raises on hard failure)."""
    token = config.railway_api_token()
    project_id = config.railway_project_id()
    environment_id = config.railway_environment_id()
    timeout = config.railway_metrics_timeout_secs()
    window = config.railway_metrics_window_secs()
    sample_rate = config.railway_metrics_sample_secs()
    service_names = config.railway_service_names()

    start_date = _iso_utc(time.time() - window)
    variables = {
        "projectId": project_id,
        "environmentId": environment_id,
        "startDate": start_date,
        "measurements": list(_MEASUREMENTS),
        "sampleRateSeconds": sample_rate,
    }
    body = _post_graphql(token, variables, timeout)
    if body.get("errors"):
        message = json.dumps(body["errors"])[:300]
        raise RuntimeError(f"Railway GraphQL errors: {message}")
    results = ((body.get("data") or {}).get("metrics")) or []
    services = _build_services(results, service_names)
    now = time.time()
    return {
        "enabled": True,
        "configured": True,
        "ok": True,
        "fetched_at_unix": now,
        "last_success_fetched_at_unix": now,
        "scrape_duration_seconds": None,
        "error": None,
        "services": services,
    }


def _disabled_snapshot() -> dict[str, Any]:
    return {
        "enabled": False,
        "configured": False,
        "ok": False,
        "fetched_at_unix": 0.0,
        "scrape_duration_seconds": None,
        "error": None,
        "services": [],
    }


def _misconfigured_snapshot() -> dict[str, Any]:
    """Enabled by intent but missing required configuration."""
    return {
        "enabled": True,
        "configured": False,
        "ok": False,
        "fetched_at_unix": 0.0,
        "scrape_duration_seconds": None,
        "error": "missing_configuration",
        "services": [],
    }


def _failed_snapshot(
    error: str,
    *,
    cached: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve cached resource data but mark the scrape as failed.

    Stable error codes keep Grafana value mappings and alerts reliable even
    when the underlying exception message varies.
    """
    base = dict(cached) if cached else {}
    base.update(
        {
            "enabled": True,
            "configured": True,
            "ok": False,
            "error": error,
        }
    )
    base.setdefault("fetched_at_unix", 0.0)
    # A failed scrape must never fabricate a success time: fall back to 0.0
    # ("never succeeded"), not to fetched_at_unix (the failed-attempt time).
    base.setdefault("last_success_fetched_at_unix", 0.0)
    base.setdefault("scrape_duration_seconds", None)
    base.setdefault("services", [])
    return base


def snapshot() -> dict[str, Any]:
    """Return a cached Railway metrics snapshot; never raises.

    When the bridge is disabled, returns an ``enabled=False`` payload; when
    enabled but missing required config, returns ``enabled=True, configured=False``
    (the misconfigured-vs-disabled distinction the metrics deliberately expose).
    On transient fetch errors, returns the last good cache if present, otherwise
    an ``ok=False`` payload carrying a stable error *code* (not the raw message).
    """
    global _CACHE, _CACHE_EXPIRES_AT

    if not config.railway_metrics_enabled():
        return _disabled_snapshot()
    if not (config.railway_api_token() and config.railway_project_id() and config.railway_environment_id()):
        logger.warning(
            "Railway metrics enabled but RAILWAY_API_TOKEN / RAILWAY_PROJECT_ID / "
            "RAILWAY_ENVIRONMENT_ID is missing; skipping poll",
        )
        return _misconfigured_snapshot()

    now = time.monotonic()
    with _LOCK:
        if _CACHE is not None and now < _CACHE_EXPIRES_AT:
            return _CACHE

    started = time.monotonic()
    try:
        fresh = _fetch()
        fresh["scrape_duration_seconds"] = time.monotonic() - started
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        error = _classify_fetch_error(exc)
        logger.warning("Railway metrics poll failed (%s): %s", error, exc)
        with _LOCK:
            cached = _CACHE
        failed = _failed_snapshot(error, cached=cached)
        failed["scrape_duration_seconds"] = time.monotonic() - started
        # Failure backoff: cache the (truthful, ok=0) failed snapshot for one
        # TTL so a hanging Railway API costs at most one fetch timeout per TTL
        # instead of one per scrape — inline fetch latency here counts against
        # Alloy's scrape_timeout for the whole /metrics exposition.
        with _LOCK:
            _CACHE = failed
            _CACHE_EXPIRES_AT = time.monotonic() + config.railway_metrics_poll_ttl_secs()
        return failed

    ttl = config.railway_metrics_poll_ttl_secs()
    with _LOCK:
        _CACHE = fresh
        _CACHE_EXPIRES_AT = time.monotonic() + ttl
    return fresh


def reset_cache() -> None:
    """Clear the in-process cache (used by tests)."""
    global _CACHE, _CACHE_EXPIRES_AT
    with _LOCK:
        _CACHE = None
        _CACHE_EXPIRES_AT = 0.0


def _classify_fetch_error(exc: Exception) -> str:
    """Map Railway fetch exceptions to stable bridge error codes."""
    reason = getattr(exc, "reason", None)
    names = [type(exc).__name__]
    if reason is not None:
        names.append(type(reason).__name__)
    if any("Timeout" in name for name in names):
        return "timeout"
    if isinstance(exc, urllib.error.URLError):
        return "network_error"
    return "fetch_error"


# ---------------------------------------------------------------------------
# Volume backups
#
# Railway takes native volume backups on a schedule, and can restore one or
# roll a volume back to a point in time. Both are worthless if nobody notices
# that the schedule was never switched on, or that it silently stopped: the
# customer plane's licence database ran unbacked-up by the platform until
# 2026-08-13 without a single signal saying so.
#
# This half of the bridge answers three separate questions, deliberately kept
# apart so none of them can be answered by accident:
#
#   * is a schedule configured at all         -> schedule_count
#   * has it actually produced anything       -> backup_count, age_known
#   * how old is the newest one               -> age_seconds
#
# ``age_known`` is the important one. Without it "no backup has ever been
# taken" would render as age 0 — the youngest possible backup — and a volume
# that has never been backed up would look healthier than one backed up an
# hour ago.
# ---------------------------------------------------------------------------

_VOLUME_BACKUP_QUERY = (
    "query VolumeBackups($volumeInstanceId: String!) {"
    " volumeInstanceBackupScheduleList(volumeInstanceId: $volumeInstanceId) {"
    " id kind retentionSeconds }"
    " volumeInstanceBackupList(volumeInstanceId: $volumeInstanceId) {"
    " id name createdAt } }"
)

_BACKUP_LOCK = threading.Lock()
_BACKUP_CACHE: dict[str, Any] | None = None
_BACKUP_CACHE_EXPIRES_AT: float = 0.0


def _parse_iso_utc(value: Any) -> float | None:
    """Parse Railway's RFC3339 timestamps to epoch seconds; None when unusable.

    Railway sends ``2026-08-13T10:57:00.302Z``. Fractional seconds are dropped
    (irrelevant at the age scale this feeds) and a missing/garbled value returns
    None so the caller can report *unknown* rather than a fabricated age.
    """
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1]
    text = text.split(".", 1)[0].split("+", 1)[0]
    try:
        parsed = time.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return float(calendar.timegm(parsed))


def _summarise_volume(name: str, instance_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Collapse one instance's GraphQL payload into flat, renderable numbers."""
    data = body.get("data") or {}
    schedules = data.get("volumeInstanceBackupScheduleList") or []
    backups = data.get("volumeInstanceBackupList") or []
    retentions = [
        float(entry["retentionSeconds"])
        for entry in schedules
        if isinstance(entry, dict) and isinstance(entry.get("retentionSeconds"), (int, float))
    ]
    timestamps = [
        stamp
        for stamp in (_parse_iso_utc(entry.get("createdAt")) for entry in backups if isinstance(entry, dict))
        if stamp is not None
    ]
    newest = max(timestamps) if timestamps else None
    return {
        "name": name,
        "instance_id": instance_id,
        "schedule_count": float(len(schedules)),
        "schedule_kinds": ",".join(
            sorted(str(entry.get("kind", "")) for entry in schedules if isinstance(entry, dict))
        ),
        "retention_seconds": min(retentions) if retentions else None,
        "backup_count": float(len(backups)),
        # A backup whose createdAt will not parse is counted (backup_count) but
        # cannot date the volume: age stays unknown rather than silently older.
        "newest_created_at_unix": newest,
    }


def _fetch_volume_backups() -> dict[str, Any]:
    """Query every configured volume instance once. Raises on any failure."""
    token = config.railway_api_token()
    timeout = config.railway_volume_backup_timeout_secs()
    volumes = []
    for name, instance_id in sorted(config.railway_volume_backup_instances().items()):
        body = _post_graphql(
            token,
            {"volumeInstanceId": instance_id},
            timeout,
            query=_VOLUME_BACKUP_QUERY,
        )
        if body.get("errors"):
            message = json.dumps(body["errors"])[:300]
            raise RuntimeError(f"Railway GraphQL errors for {name}: {message}")
        volumes.append(_summarise_volume(name, instance_id, body))
    now = time.time()
    return {
        "enabled": True,
        "configured": True,
        "ok": True,
        "fetched_at_unix": now,
        "last_success_fetched_at_unix": now,
        "scrape_duration_seconds": None,
        "error": None,
        "volumes": volumes,
    }


def volume_backup_snapshot() -> dict[str, Any]:
    """Return a cached volume-backup snapshot; never raises.

    Mirrors :func:`snapshot`: disabled when nothing is configured, and on a
    failed poll it keeps the last good ``volumes`` payload while telling the
    truth about the attempt (``ok=0`` plus a stable error code), so a Railway
    outage cannot freeze the bridge green.
    """
    global _BACKUP_CACHE, _BACKUP_CACHE_EXPIRES_AT

    if not config.railway_volume_backup_enabled():
        return {
            "enabled": False,
            "configured": False,
            "ok": False,
            "fetched_at_unix": 0.0,
            "last_success_fetched_at_unix": 0.0,
            "scrape_duration_seconds": None,
            "error": None,
            "volumes": [],
        }

    now = time.monotonic()
    with _BACKUP_LOCK:
        if _BACKUP_CACHE is not None and now < _BACKUP_CACHE_EXPIRES_AT:
            return _BACKUP_CACHE

    started = time.monotonic()
    try:
        fresh = _fetch_volume_backups()
        fresh["scrape_duration_seconds"] = time.monotonic() - started
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        error = _classify_fetch_error(exc)
        logger.warning("Railway volume-backup poll failed (%s): %s", error, exc)
        with _BACKUP_LOCK:
            cached = _BACKUP_CACHE
        fresh = dict(cached) if cached else {}
        fresh.update({"enabled": True, "configured": True, "ok": False, "error": error})
        fresh.setdefault("fetched_at_unix", 0.0)
        fresh.setdefault("last_success_fetched_at_unix", 0.0)
        fresh.setdefault("volumes", [])
        fresh["scrape_duration_seconds"] = time.monotonic() - started

    with _BACKUP_LOCK:
        _BACKUP_CACHE = fresh
        _BACKUP_CACHE_EXPIRES_AT = time.monotonic() + config.railway_volume_backup_poll_ttl_secs()
    return fresh


def reset_volume_backup_cache() -> None:
    """Clear the volume-backup cache (used by tests)."""
    global _BACKUP_CACHE, _BACKUP_CACHE_EXPIRES_AT
    with _BACKUP_LOCK:
        _BACKUP_CACHE = None
        _BACKUP_CACHE_EXPIRES_AT = 0.0
