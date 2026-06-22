"""Lightweight Prometheus text-format renderer.

Exposes all in-process counters from observability._counters plus feed health
counters, overlay state gauges, and timing metrics without pulling in the
heavyweight prometheus_client dependency.

Single-worker deployment (uvicorn --workers 1) guarantees these in-process
values are consistent and complete.
"""
from __future__ import annotations

import json
import math
import re
import time

from . import (
    cache,
    config,
    feed,
    github_workflow_bridge,
    observability,
    request_hotspots,
    uptimerobot_bridge,
)
from .market_hours import (
    compute_daemon_health_status,
    is_asia_regular_session_open,
    is_europe_regular_session_open,
    is_us_regular_session_open,
)

_PROM_NAME_CHARS_RE = re.compile(r"[^a-z0-9_]")


def _sanitize_name(name: str) -> str:
    """Convert metric fragments to a strict Prometheus-safe ASCII allow-list.

    This project embeds user-derived fragments (symbol, timeframe, provider)
    into metric names, so we enforce a conservative allow-list of
    ``[a-z0-9_]`` rather than Prometheus' broader grammar. The fragment is
    lower-cased, whitespace is stripped, every character outside the
    allow-list is replaced with an underscore, and a leading digit is
    prefixed with an underscore. Empty or fully-invalid fragments fall back
    to ``_``.
    """
    cleaned = _PROM_NAME_CHARS_RE.sub("_", str(name).lower().strip())
    if cleaned and cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned or "_"


def _prom_numeric_value(raw: object) -> float:
    """Coerce metric value to a Prometheus-safe finite number (fallback: NaN)."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float("nan")
    return value if math.isfinite(value) else float("nan")


def _parse_bucket_upper_bound(suffix: str) -> float | None:
    if suffix == "inf":
        return float("inf")
    try:
        return float(suffix.replace("_", "."))
    except ValueError:
        return None


def _estimate_histogram_quantile_ms(
    counters: dict[str, float],
    *,
    base_name: str,
    quantile: float,
) -> float | None:
    """Estimate a latency quantile from cumulative bucket counters.

    The in-process histogram stores counters as flattened names like
    ``{base_name}.bucket_le_100``. This function computes an approximate
    quantile using linear interpolation across cumulative buckets.
    """
    if not 0.0 < quantile <= 1.0:
        return None

    total_raw = counters.get(f"{base_name}.count")
    if total_raw is None:
        return None
    total = _prom_numeric_value(total_raw)
    if not math.isfinite(total) or total <= 0:
        return None

    prefix = f"{base_name}.bucket_le_"
    bucket_points: list[tuple[float, float]] = []
    for key, value in counters.items():
        if not key.startswith(prefix):
            continue
        suffix = key[len(prefix):]
        upper = _parse_bucket_upper_bound(suffix)
        if upper is None:
            continue
        cumulative = _prom_numeric_value(value)
        if not math.isfinite(cumulative):
            continue
        bucket_points.append((upper, cumulative))

    if not bucket_points:
        return None

    bucket_points.sort(key=lambda x: x[0])
    target = quantile * total
    prev_upper = 0.0
    prev_cumulative = 0.0

    for upper, cumulative in bucket_points:
        if cumulative >= target:
            if upper == float("inf"):
                return prev_upper
            span = cumulative - prev_cumulative
            if span <= 0:
                return upper
            position = (target - prev_cumulative) / span
            return prev_upper + (upper - prev_upper) * max(0.0, min(1.0, position))
        if upper != float("inf"):
            prev_upper = upper
        prev_cumulative = cumulative

    return prev_upper


# Provider health state codes exposed via live_overlay_provider_news_*_state_code
# and the live_overlay_provider_news_info{state=...} label.
_PROVIDER_STATE_LABELS = {0: "unknown", 1: "degraded", 2: "ok", 3: "disabled"}

# Map the raw snapshot "error" reason onto a human-readable message that the
# dashboard surfaces directly to operators.
_PROVIDER_REASON_MESSAGES = {
    "disabled": "Provider disabled (not ingested)",
    "missing_api_key": "API key missing",
    "no_api_key": "API key missing",
    "no_subscription": "No active subscription",
    "subscription_required": "No active subscription",
    "no_symbols": "No symbols configured",
    "fetch_failed": "Fetch failed",
}


def _truncate_reason(text: str, *, limit: int = 120) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def _provider_reason_message(status: object, error: str) -> str:
    """Translate a provider ``ok``/``error`` pair into an operator message."""
    if status is True:
        return "OK"
    if not error:
        return "Unknown (no detail reported)"
    key = error.strip().lower()
    if key in _PROVIDER_REASON_MESSAGES:
        return _PROVIDER_REASON_MESSAGES[key]
    if "api" in key and "key" in key:
        return "API key missing"
    if "subscription" in key or "not subscribed" in key or "402" in key or "403" in key:
        return "No active subscription"
    if "401" in key or "unauthorized" in key or "forbidden" in key:
        return "Authentication failed"
    if "429" in key or "rate limit" in key or "ratelimit" in key:
        return "Rate limited"
    return _truncate_reason(error)


def _escape_label_value(value: object) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
    )


def _provider_health_snapshot() -> dict[str, object]:
    """Derive provider-health gauges from the configured news snapshot file."""
    path = config.news_snapshot_path()
    snapshot_loaded = 0.0
    snapshot_age_seconds = 0.0
    providers_obj: object = {}

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                providers_obj = raw.get("providers") or {}
                snapshot_loaded = 1.0
                # Use fetched_at_unix when present (live producer snapshots).
                # Seed files omit this key and report age 0 (never stale).
                fetched_at = raw.get("fetched_at_unix")
                if fetched_at is not None and math.isfinite(float(fetched_at)) and float(fetched_at) > 0:
                    snapshot_age_seconds = max(0.0, time.time() - float(fetched_at))
        except Exception:
            providers_obj = {}

    providers = providers_obj if isinstance(providers_obj, dict) else {}

    ok = 0
    degraded = 0
    unknown = 0
    disabled = 0
    consumed_total = 0
    provider_ok: dict[str, float] = {}
    provider_degraded: dict[str, float] = {}
    provider_state_code: dict[str, float] = {}
    provider_consumed: dict[str, float] = {}
    provider_info: list[dict[str, str]] = []

    for provider_name, state in providers.items():
        state_obj = state if isinstance(state, dict) else {}
        status = state_obj.get("ok")
        error_raw = state_obj.get("error")
        error = "" if error_raw in (None, "") else str(error_raw).strip()
        pname = _sanitize_name(str(provider_name).lower())

        # A provider is "disabled" (not ingested) when it was excluded from the
        # producer run. Such providers must not count as degraded or drag the
        # aggregate health down -- they simply are not consumed right now.
        is_disabled = status is not True and error.lower() == "disabled"
        consumed = not is_disabled
        if consumed:
            consumed_total += 1

        if status is True:
            state_code = 2.0
            ok += 1
            provider_ok[pname] = 1.0
            provider_degraded[pname] = 0.0
        elif is_disabled:
            state_code = 3.0
            disabled += 1
            provider_ok[pname] = 0.0
            provider_degraded[pname] = 0.0
        elif status is False:
            state_code = 1.0
            degraded += 1
            provider_ok[pname] = 0.0
            provider_degraded[pname] = 1.0
        else:
            state_code = 0.0
            unknown += 1
            provider_ok[pname] = 0.0
            provider_degraded[pname] = 0.0

        provider_state_code[pname] = state_code
        provider_consumed[pname] = 1.0 if consumed else 0.0
        provider_info.append(
            {
                "provider": pname,
                "state": _PROVIDER_STATE_LABELS[int(state_code)],
                "reason": _provider_reason_message(status, error),
                "consumed": "true" if consumed else "false",
            }
        )

    total = len(providers)
    # Health reflects only providers that are actually consumed/ingested;
    # disabled (not-ingested) providers are excluded so they never raise alarms.
    health_ok = (
        1.0 if consumed_total > 0 and degraded == 0 and unknown == 0 else 0.0
    )
    health_degraded = 1.0 if degraded > 0 else 0.0
    health_unknown = 1.0 if consumed_total == 0 or unknown > 0 else 0.0

    return {
        "news_snapshot_loaded": snapshot_loaded,
        "news_snapshot_age_seconds": snapshot_age_seconds,
        "news_providers_total": float(total),
        "news_providers_ok_total": float(ok),
        "news_providers_degraded_total": float(degraded),
        "news_providers_unknown_total": float(unknown),
        "news_providers_disabled_total": float(disabled),
        "news_providers_consumed_total": float(consumed_total),
        "news_health_ok": health_ok,
        "news_health_degraded": health_degraded,
        "news_health_unknown": health_unknown,
        "news_provider_ok": provider_ok,
        "news_provider_degraded": provider_degraded,
        "news_provider_state_code": provider_state_code,
        "news_provider_consumed": provider_consumed,
        "news_provider_info": provider_info,
    }


def render_metrics(startup_ts: float) -> str:
    """Return Prometheus text-format exposition of all daemon metrics."""
    lines: list[str] = []

    # --- Counters from observability ---
    with observability._counter_lock:
        counters = dict(observability._counters)

    for name, value in sorted(counters.items()):
        prom_name = _sanitize_name(name)
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    hotspot = request_hotspots.snapshot(top_n=5)
    lines.append("# TYPE live_overlay_hotspot_symbols_tracked gauge")
    lines.append(
        f"live_overlay_hotspot_symbols_tracked {_prom_numeric_value(hotspot.get('symbol_count', 0))}"
    )
    lines.append("# TYPE live_overlay_hotspot_timeframes_tracked gauge")
    lines.append(
        f"live_overlay_hotspot_timeframes_tracked {_prom_numeric_value(hotspot.get('tf_count', 0))}"
    )

    for symbol, count in hotspot.get("top_symbols") or []:
        sym = _sanitize_name(str(symbol).lower())
        lines.append(f"# TYPE live_overlay_hotspot_symbol_{sym}_requests_total gauge")
        lines.append(
            f"live_overlay_hotspot_symbol_{sym}_requests_total {_prom_numeric_value(count)}"
        )

    for tf, count in hotspot.get("top_tfs") or []:
        tf_name = _sanitize_name(str(tf).lower())
        lines.append(f"# TYPE live_overlay_hotspot_tf_{tf_name}_requests_total gauge")
        lines.append(
            f"live_overlay_hotspot_tf_{tf_name}_requests_total {_prom_numeric_value(count)}"
        )

    latency_p95_ms = _estimate_histogram_quantile_ms(
        counters,
        base_name="live_overlay.smc_live_latency",
        quantile=0.95,
    )
    if latency_p95_ms is not None:
        lines.append("# TYPE live_overlay_smc_live_latency_p95_ms gauge")
        lines.append(f"live_overlay_smc_live_latency_p95_ms {latency_p95_ms:.3f}")

    latency_p99_ms = _estimate_histogram_quantile_ms(
        counters,
        base_name="live_overlay.smc_live_latency",
        quantile=0.99,
    )
    if latency_p99_ms is not None:
        lines.append("# TYPE live_overlay_smc_live_latency_p99_ms gauge")
        lines.append(f"live_overlay_smc_live_latency_p99_ms {latency_p99_ms:.3f}")

    # --- Feed counters ---
    feed_metrics = feed.metrics_snapshot()
    for name, value in sorted(feed_metrics.items()):
        prom_name = f"live_overlay_feed_{_sanitize_name(name)}"
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    backpressure = feed.backpressure_snapshot()
    for key in (
        "ingest_queue_depth",
        "ingest_queue_depth_max",
        "ingest_queue_dropped_total",
        "ingest_queue_lag_ms_last",
        "ingest_queue_lag_ms_max",
    ):
        prom_name = f"live_overlay_feed_{_sanitize_name(key)}"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(backpressure.get(key, 0.0))}")

    provider_health = _provider_health_snapshot()
    for key in (
        "news_snapshot_loaded",
        "news_snapshot_age_seconds",
        "news_providers_total",
        "news_providers_ok_total",
        "news_providers_degraded_total",
        "news_providers_unknown_total",
        "news_providers_disabled_total",
        "news_providers_consumed_total",
        "news_health_ok",
        "news_health_degraded",
        "news_health_unknown",
    ):
        prom_name = f"live_overlay_provider_{_sanitize_name(key)}"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(
            f"{prom_name} {_prom_numeric_value(provider_health.get(key, 0.0))}"
        )

    for provider_name, value in sorted(
        (provider_health.get("news_provider_ok") or {}).items()
    ):
        prom_name = f"live_overlay_provider_news_{provider_name}_ok"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    for provider_name, value in sorted(
        (provider_health.get("news_provider_degraded") or {}).items()
    ):
        prom_name = f"live_overlay_provider_news_{provider_name}_degraded"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    for provider_name, value in sorted(
        (provider_health.get("news_provider_state_code") or {}).items()
    ):
        prom_name = f"live_overlay_provider_news_{provider_name}_state_code"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    for provider_name, value in sorted(
        (provider_health.get("news_provider_consumed") or {}).items()
    ):
        prom_name = f"live_overlay_provider_news_{provider_name}_consumed"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    # Labeled info metric: one series per provider carrying the human-readable
    # degraded reason, lifecycle state and whether the provider is consumed.
    info_rows = provider_health.get("news_provider_info") or []
    if info_rows:
        lines.append("# TYPE live_overlay_provider_news_info gauge")
        for row in info_rows:
            labels = (
                f'provider="{_escape_label_value(row.get("provider", ""))}",'
                f'state="{_escape_label_value(row.get("state", ""))}",'
                f'reason="{_escape_label_value(row.get("reason", ""))}",'
                f'consumed="{_escape_label_value(row.get("consumed", ""))}"'
            )
            lines.append(f"live_overlay_provider_news_info{{{labels}}} 1")

    # --- Gauges: overlay health state ---
    uptime = time.monotonic() - startup_ts if startup_ts > 0 else 0
    lines.append("# TYPE live_overlay_uptime_seconds gauge")
    lines.append(f"live_overlay_uptime_seconds {uptime:.1f}")

    overlay_symbols = cache.overlay_symbol_count()
    lines.append("# TYPE live_overlay_overlay_symbols gauge")
    lines.append(f"live_overlay_overlay_symbols {overlay_symbols}")

    bar_symbols = cache.bar_symbol_count()
    lines.append("# TYPE live_overlay_bar_symbols gauge")
    lines.append(f"live_overlay_bar_symbols {bar_symbols}")

    bar_count = cache.total_bar_count()
    lines.append("# TYPE live_overlay_bar_count gauge")
    lines.append(f"live_overlay_bar_count {bar_count}")

    overlay_age = cache.overlay_age_secs()
    if overlay_age != float("inf"):
        lines.append("# TYPE live_overlay_overlay_age_seconds gauge")
        lines.append(f"live_overlay_overlay_age_seconds {overlay_age:.1f}")

    bar_age = feed.last_bar_age_secs()
    if bar_age is not None:
        lines.append("# TYPE live_overlay_last_bar_age_seconds gauge")
        lines.append(f"live_overlay_last_bar_age_seconds {bar_age:.1f}")

    feed_healthy = 1 if feed.is_ready() else 0
    lines.append("# TYPE live_overlay_feed_healthy gauge")
    lines.append(f"live_overlay_feed_healthy {feed_healthy}")

    workers = feed.worker_liveness()
    workers_healthy = 1 if all(workers.values()) else 0
    lines.append("# TYPE live_overlay_workers_healthy gauge")
    lines.append(f"live_overlay_workers_healthy {workers_healthy}")

    # Market/session-aware daemon health state mirrors /health status logic.
    # US session gates feed/traffic/health (feed is US equities); the headline
    # display gauge widens to "any major session" so the dashboard does not show
    # MARKET CLOSED while European exchanges trade ahead of the US open.
    us_open = is_us_regular_session_open()
    eu_open = is_europe_regular_session_open()
    asia_open = is_asia_regular_session_open()
    market_open = us_open or eu_open
    max_stale = config.max_stale_secs()
    overlay_fresh = (
        overlay_symbols > 0
        and overlay_age != float("inf")
        and overlay_age <= max_stale
    )
    lines.append("# TYPE live_overlay_overlay_fresh gauge")
    lines.append(f"live_overlay_overlay_fresh {1 if overlay_fresh else 0}")
    status = compute_daemon_health_status(
        feed_healthy=bool(feed_healthy),
        workers_healthy=bool(workers_healthy),
        overlay_fresh=overlay_fresh,
        market_open=us_open,
        bar_count=bar_count,
    )

    lines.append("# TYPE live_overlay_market_open gauge")
    lines.append(f"live_overlay_market_open {1 if market_open else 0}")
    lines.append("# TYPE live_overlay_market_us_open gauge")
    lines.append(f"live_overlay_market_us_open {1 if us_open else 0}")
    lines.append("# TYPE live_overlay_market_europe_open gauge")
    lines.append(f"live_overlay_market_europe_open {1 if eu_open else 0}")
    lines.append("# TYPE live_overlay_market_asia_open gauge")
    lines.append(f"live_overlay_market_asia_open {1 if asia_open else 0}")
    lines.append("# TYPE live_overlay_max_stale_seconds gauge")
    lines.append(f"live_overlay_max_stale_seconds {max_stale}")
    lines.append("# TYPE live_overlay_health_status_ok gauge")
    lines.append(f"live_overlay_health_status_ok {1 if status == 'ok' else 0}")
    lines.append("# TYPE live_overlay_health_status_starting gauge")
    lines.append(f"live_overlay_health_status_starting {1 if status == 'starting' else 0}")
    lines.append("# TYPE live_overlay_health_status_idle_market_closed gauge")
    lines.append(f"live_overlay_health_status_idle_market_closed {1 if status == 'idle_market_closed' else 0}")

    for worker_name, alive in workers.items():
        prom_worker = _sanitize_name(worker_name)
        lines.append(f"# TYPE live_overlay_worker_{prom_worker}_alive gauge")
        lines.append(f"live_overlay_worker_{prom_worker}_alive {1 if alive else 0}")

    # --- Optional UptimeRobot bridge ---
    uptime_snapshot = uptimerobot_bridge.snapshot()
    enabled = int(uptime_snapshot.get("enabled", 0) or 0)
    ok = int(uptime_snapshot.get("ok", 0) or 0)
    fetched_at_unix = _prom_numeric_value(uptime_snapshot.get("fetched_at_unix", 0.0))
    snapshot_age = max(0.0, time.time() - fetched_at_unix) if math.isfinite(fetched_at_unix) and fetched_at_unix > 0 else 0.0

    lines.append("# TYPE live_overlay_uptimerobot_bridge_enabled gauge")
    lines.append(f"live_overlay_uptimerobot_bridge_enabled {enabled}")
    lines.append("# TYPE live_overlay_uptimerobot_scrape_success gauge")
    lines.append(f"live_overlay_uptimerobot_scrape_success {ok}")
    lines.append("# TYPE live_overlay_uptimerobot_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_uptimerobot_snapshot_age_seconds {snapshot_age:.1f}")

    counts = dict(uptime_snapshot.get("counts") or {})
    for key in ("total", "up", "down", "paused", "unknown"):
        suffix = "_total" if key != "total" else ""
        prom_name = f"live_overlay_uptimerobot_monitors_{key}{suffix}"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(
            f"{prom_name} {_prom_numeric_value(counts.get(key, 0))}"
        )

    avg_response_time_ms = uptime_snapshot.get("avg_response_time_ms")
    if avg_response_time_ms is not None:
        lines.append("# TYPE live_overlay_uptimerobot_monitors_response_time_ms_avg gauge")
        lines.append(
            f"live_overlay_uptimerobot_monitors_response_time_ms_avg {_prom_numeric_value(avg_response_time_ms)}"
        )

    for monitor in uptime_snapshot.get("monitors") or []:
        monitor_id = _sanitize_name(str(monitor.get("id", "unknown")))
        monitor_prefix = f"live_overlay_uptimerobot_monitor_{monitor_id}"
        lines.append(f"# TYPE {monitor_prefix}_up gauge")
        lines.append(f"{monitor_prefix}_up {_prom_numeric_value(monitor.get('up', 0))}")
        lines.append(f"# TYPE {monitor_prefix}_status_code gauge")
        lines.append(
            f"{monitor_prefix}_status_code {_prom_numeric_value(monitor.get('status_code', 1))}"
        )
        response_time_ms = monitor.get("response_time_ms")
        if response_time_ms is not None:
            lines.append(f"# TYPE {monitor_prefix}_response_time_ms gauge")
            lines.append(f"{monitor_prefix}_response_time_ms {_prom_numeric_value(response_time_ms)}")

    # --- Optional GitHub workflow bridge ---
    workflow_snapshot = github_workflow_bridge.snapshot()
    wf_enabled = int(workflow_snapshot.get("enabled", 0) or 0)
    wf_ok = int(workflow_snapshot.get("ok", 0) or 0)
    wf_fetched_at_unix = _prom_numeric_value(workflow_snapshot.get("fetched_at_unix", 0.0))
    wf_snapshot_age = max(0.0, time.time() - wf_fetched_at_unix) if math.isfinite(wf_fetched_at_unix) and wf_fetched_at_unix > 0 else 0.0

    lines.append("# TYPE live_overlay_github_workflow_bridge_enabled gauge")
    lines.append(f"live_overlay_github_workflow_bridge_enabled {wf_enabled}")
    lines.append("# TYPE live_overlay_github_workflow_scrape_success gauge")
    lines.append(f"live_overlay_github_workflow_scrape_success {wf_ok}")
    lines.append("# TYPE live_overlay_github_workflow_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_github_workflow_snapshot_age_seconds {wf_snapshot_age:.1f}")

    workflow_counts = dict(workflow_snapshot.get("counts") or {})
    for key in ("seen", "success", "failed", "in_progress", "queued"):
        lines.append(f"# TYPE live_overlay_github_workflow_runs_{key}_total gauge")
        lines.append(
            f"live_overlay_github_workflow_runs_{key}_total {_prom_numeric_value(workflow_counts.get(key, 0))}"
        )

    latest_run_age = workflow_snapshot.get("latest_run_age_seconds")
    if latest_run_age is not None:
        lines.append("# TYPE live_overlay_github_workflow_latest_run_age_seconds gauge")
        lines.append(
            f"live_overlay_github_workflow_latest_run_age_seconds {_prom_numeric_value(latest_run_age)}"
        )

    latest_run_duration = workflow_snapshot.get("latest_run_duration_seconds")
    if latest_run_duration is not None:
        lines.append("# TYPE live_overlay_github_workflow_latest_run_duration_seconds gauge")
        lines.append(
            "live_overlay_github_workflow_latest_run_duration_seconds "
            f"{_prom_numeric_value(latest_run_duration)}"
        )

    for workflow in workflow_snapshot.get("workflows") or []:
        workflow_id = _sanitize_name(str(workflow.get("id", "unknown")))
        workflow_prefix = f"live_overlay_github_workflow_{workflow_id}"
        lines.append(f"# TYPE {workflow_prefix}_phase_code gauge")
        lines.append(
            f"{workflow_prefix}_phase_code {_prom_numeric_value(workflow.get('phase_code', 0))}"
        )
        lines.append(f"# TYPE {workflow_prefix}_latest_success gauge")
        lines.append(
            f"{workflow_prefix}_latest_success {_prom_numeric_value(workflow.get('latest_success', 0))}"
        )

        workflow_age = workflow.get("latest_age_seconds")
        if workflow_age is not None:
            lines.append(f"# TYPE {workflow_prefix}_latest_age_seconds gauge")
            lines.append(f"{workflow_prefix}_latest_age_seconds {_prom_numeric_value(workflow_age)}")

        workflow_duration = workflow.get("latest_duration_seconds")
        if workflow_duration is not None:
            lines.append(f"# TYPE {workflow_prefix}_latest_duration_seconds gauge")
            lines.append(
                f"{workflow_prefix}_latest_duration_seconds {_prom_numeric_value(workflow_duration)}"
            )

    lines.append("")  # trailing newline
    return "\n".join(lines)
