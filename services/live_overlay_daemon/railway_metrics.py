"""Railway container-metrics bridge for the live overlay daemon.

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

import json
import logging
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
    timeout: int,
) -> dict[str, Any]:
    """POST a GraphQL request to Railway and return the parsed JSON body."""
    payload = json.dumps({"query": _QUERY, "variables": variables}).encode("utf-8")
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
    """Return the most recent numeric ``value`` from a Railway value series."""
    latest_ts: float | None = None
    latest_value: float | None = None
    for point in values:
        try:
            ts = float(point["ts"])
            value = float(point["value"])
        except (KeyError, TypeError, ValueError):
            continue
        if latest_ts is None or ts >= latest_ts:
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
    return [by_service[key] for key in sorted(by_service)]


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
    return {
        "enabled": True,
        "configured": True,
        "ok": True,
        "fetched_at_unix": time.time(),
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
    base.setdefault("scrape_duration_seconds", None)
    base.setdefault("services", [])
    return base


def snapshot() -> dict[str, Any]:
    """Return a cached Railway metrics snapshot; never raises.

    When the bridge is disabled or misconfigured, returns an ``enabled=False``
    payload. On transient fetch errors, returns the last good cache if present,
    otherwise an ``ok=False`` payload with the error message.
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
    except urllib.error.URLError as exc:
        logger.warning("Railway metrics poll failed (network): %s", exc)
        with _LOCK:
            cached = _CACHE
        return _failed_snapshot("network_error", cached=cached)
    except TimeoutError:
        logger.warning("Railway metrics poll timed out")
        with _LOCK:
            cached = _CACHE
        return _failed_snapshot("timeout", cached=cached)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("Railway metrics poll failed: %s", exc)
        with _LOCK:
            cached = _CACHE
        return _failed_snapshot("fetch_error", cached=cached)

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
