"""Lightweight Prometheus text-format renderer.

Exposes all in-process counters from observability._counters plus feed health
counters, overlay state gauges, and timing metrics without pulling in the
heavyweight prometheus_client dependency.

Single-worker deployment (uvicorn --workers 1) guarantees these in-process
values are consistent and complete.
"""
from __future__ import annotations

import datetime
import math
import re
import time
from collections.abc import Mapping

from . import (
    cache,
    compute,
    config,
    feed,
    github_workflow_bridge,
    observability,
    railway_metrics,
    request_hotspots,
    uptimerobot_bridge,
)
from .market_hours import (
    compute_daemon_health_status,
    is_asia_regular_session_open,
    is_europe_regular_session_open,
    is_us_regular_session_open,
)


def _sanitize_name(name: str) -> str:
    """Normalize metric/path fragments to a Prometheus-safe token.

    Rules:
    - lowercase
    - trim surrounding whitespace
    - map dots/dashes to underscores
    - collapse all remaining non [a-z0-9_] chars to underscores
    - collapse repeated underscores and trim edge underscores
    - fallback to ``unknown`` when nothing remains
    """
    token = str(name).strip().lower().replace(".", "_").replace("-", "_")
    token = re.sub(r"[^a-z0-9_]", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    return token or "unknown"


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
# NOTE: the per-provider metric names (live_overlay_provider_news_<provider>_state_code)
# are intentionally dynamic. The Grafana dashboards select them with a
# ``__name__=~"live_overlay_provider_news_.*_state_code"`` regex matcher rather than a
# fixed metric name, so adding a provider needs no dashboard change. Cardinality stays
# bounded by the small, static provider set.
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


def _workflow_labels(workflow: Mapping[str, object]) -> str:
    """Render the ``workflow_id``/``workflow``/``event`` label set for a flow.

    The workflow name and trigger event are surfaced as labels (rather than
    baked into the metric name) so Grafana can name each flow and group a
    single shared status timeline / detail table by workflow.
    """
    return (
        f'workflow_id="{_escape_label_value(workflow.get("id", "unknown"))}",'
        f'workflow="{_escape_label_value(workflow.get("name", "unknown") or "unknown")}",'
        f'event="{_escape_label_value(workflow.get("event", "unknown") or "unknown")}"'
    )


# Cap the number of per-signal series emitted so a busy session cannot blow up
# Prometheus cardinality; the strongest-scoring signals are kept.
_SIGNAL_SERIES_CAP = 50


def _signal_labels(sig: Mapping[str, object]) -> str:
    """Render the ``symbol``/``level``/``direction``/``tier`` label set.

    Surfacing the breakout level (A0 pre-breakout / A1 breakout), trade
    direction and confidence tier as labels lets Grafana name, colour and
    group each firing symbol instead of baking identity into the metric name.
    """
    return (
        f'symbol="{_escape_label_value(sig.get("symbol", "") or "unknown")}",'
        f'level="{_escape_label_value(sig.get("level", "") or "unknown")}",'
        f'direction="{_escape_label_value(sig.get("direction", "") or "unknown")}",'
        f'tier="{_escape_label_value(sig.get("confidence_tier", "") or "unknown")}"'
    )


def _trading_signals_snapshot() -> dict[str, object]:
    """Derive trading-signal gauges from the realtime-engine snapshot.

    Reads through :func:`compute._load_signals_snapshot` so the gauges reflect
    whatever source the daemon serves (the runtime ``SIGNALS_SNAPSHOT_URL`` when
    configured, otherwise the local ``latest_realtime_signals.json``). Returns
    aggregate counts, the snapshot age (when known) and a cardinality-capped,
    score-sorted list of the active signals.
    """
    raw = compute._load_signals_snapshot()
    loaded = 0.0
    age_seconds = 0.0
    age_known = 0.0
    max_age_seconds = float(config.signals_max_age_secs())
    stale = 0.0
    signals_obj: object = []
    counts = {"active": 0, "a0": 0, "a1": 0, "watched": 0}

    if isinstance(raw, dict) and raw:
        loaded = 1.0
        signals_obj = raw.get("signals") or []
        counts["active"] = int(raw.get("signal_count", 0) or 0)
        counts["a0"] = int(raw.get("a0_count", 0) or 0)
        counts["a1"] = int(raw.get("a1_count", 0) or 0)
        watched = raw.get("watched_symbols") or []
        counts["watched"] = len(watched) if isinstance(watched, (list, tuple)) else 0
        updated_epoch = raw.get("updated_epoch")
        epoch_float = 0.0
        if isinstance(updated_epoch, (int, float, str)):
            try:
                epoch_float = float(updated_epoch)
            except (TypeError, ValueError):
                epoch_float = 0.0
        if math.isfinite(epoch_float) and epoch_float > 0:
            age_known = 1.0
            age_seconds = max(0.0, time.time() - epoch_float)
            stale = 1.0 if age_seconds > max_age_seconds else 0.0

    signals_list = signals_obj if isinstance(signals_obj, list) else []
    normalized = [item for item in signals_list if isinstance(item, dict)]

    def _score_key(sig: dict[str, object]) -> float:
        value = sig.get("score")
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    normalized.sort(key=_score_key, reverse=True)

    return {
        "loaded": loaded,
        "age_seconds": age_seconds,
        "age_known": age_known,
        "max_age_seconds": max_age_seconds,
        "stale": stale,
        "counts": counts,
        "signals": normalized[:_SIGNAL_SERIES_CAP],
    }


def _tradingview_credential_snapshot() -> dict[str, float]:
    """Derive TradingView credential-age gauges from the credential report.

    Reads through :func:`compute._load_tradingview_credential_snapshot` (local
    ``credential_health.json`` or the runtime
    ``TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL``) and extracts the
    ``tv_storage_state_age`` probe written by
    ``scripts/credential_health_check.py``. Surfaces the storage-state age in
    hours versus the 72h policy TTL so Grafana can alert before the cached
    TradingView login expires. Returns ``loaded=0`` when no report/probe is
    available; ``valid`` is 1.0 while the probe severity is not ``error``.
    """
    raw = compute._load_tradingview_credential_snapshot()
    loaded = 0.0
    age_hours = 0.0
    age_known = 0.0
    valid = 0.0
    validated_at_seconds = 0.0

    probe: dict[str, object] | None = None
    if isinstance(raw, dict) and raw:
        probes = raw.get("probes")
        if isinstance(probes, (list, tuple)):
            for item in probes:
                if isinstance(item, dict) and item.get("name") == "tv_storage_state_age":
                    probe = item
                    break

    if probe is not None:
        loaded = 1.0
        severity = str(probe.get("severity", "") or "")
        valid = 0.0 if severity == "error" else 1.0
        details = probe.get("details")
        if isinstance(details, dict):
            age_raw = details.get("age_hours")
            if isinstance(age_raw, (int, float)) and not isinstance(age_raw, bool):
                age_float = float(age_raw)
                if math.isfinite(age_float):
                    age_known = 1.0
                    age_hours = max(0.0, age_float)
            validated_at = details.get("validated_at")
            if isinstance(validated_at, str) and validated_at:
                try:
                    parsed = datetime.datetime.fromisoformat(
                        validated_at.replace("Z", "+00:00")
                    )
                    validated_at_seconds = parsed.timestamp()
                except ValueError:
                    validated_at_seconds = 0.0

    return {
        "loaded": loaded,
        "age_hours": age_hours,
        "age_known": age_known,
        "valid": valid,
        "validated_at_seconds": validated_at_seconds,
    }


# Stable numeric code per credential-health probe severity so Grafana can colour
# states consistently. Higher is healthier.
_CREDENTIAL_SEVERITY_CODES: Mapping[str, int] = {
    "error": 0,
    "warn": 1,
    "ok": 2,
}


def _credential_health_snapshot() -> dict[str, object]:
    """Derive credential-health gauges from the daily credential report.

    Reads through :func:`compute._load_credential_health_snapshot` (local
    ``credential_health.json`` or the runtime
    ``TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL``) and exposes every probe written by
    ``scripts/credential_health_check.py``. For each probe we emit:

    * ``live_overlay_credential_health_<probe>_severity_code`` — 0=error,
      1=warn, 2=ok.
    * ``live_overlay_credential_health_<probe>_valid`` — 1 unless severity is
      ``error``.
    * ``live_overlay_credential_health_<probe>_info`` — labelled gauge carrying
      the raw severity and message as metadata.
    * Numeric detail gauges when the probe exposes a known scalar:
      ``age_hours`` for ``tv_storage_state_age``,
      ``days_left`` for ``github_pat_validity``,
      ``staleness_days`` for ``databento_delivery``.

    The legacy ``live_overlay_tradingview_credential_*`` gauges remain so
    existing dashboards and alerts keep working.
    """
    raw = compute._load_credential_health_snapshot()
    snapshot: dict[str, object] = {
        "loaded": 0.0,
        "overall_severity": "unknown",
        "overall_valid": 0.0,
        "probes": [],
    }

    if not isinstance(raw, dict) or not raw:
        return snapshot

    snapshot["loaded"] = 1.0
    overall = str(raw.get("overall_severity", "") or "unknown").lower()
    snapshot["overall_severity"] = overall
    snapshot["overall_valid"] = 0.0 if overall == "error" else 1.0

    probes = raw.get("probes")
    probe_rows: list[dict[str, object]] = []
    if isinstance(probes, (list, tuple)):
        for item in probes:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "unknown")
            severity = str(item.get("severity", "") or "unknown").lower()
            message = str(item.get("message", "") or "")
            details = item.get("details")
            details_dict = details if isinstance(details, dict) else {}

            code = _CREDENTIAL_SEVERITY_CODES.get(severity, 0)
            valid = 0.0 if severity == "error" else 1.0

            numeric: dict[str, float] = {}
            if name == "tv_storage_state_age":
                age_raw = details_dict.get("age_hours")
                if isinstance(age_raw, (int, float)) and not isinstance(age_raw, bool):
                    age_float = float(age_raw)
                    if math.isfinite(age_float):
                        numeric["age_hours"] = max(0.0, age_float)
                validated_at = details_dict.get("validated_at")
                if isinstance(validated_at, str) and validated_at:
                    try:
                        parsed = datetime.datetime.fromisoformat(
                            validated_at.replace("Z", "+00:00")
                        )
                        numeric["validated_at_seconds"] = parsed.timestamp()
                    except ValueError:
                        numeric["validated_at_seconds"] = float("nan")
            elif name == "github_pat_validity":
                days_left = details_dict.get("days_left")
                if isinstance(days_left, (int, float)) and not isinstance(days_left, bool):
                    numeric["days_left"] = float(days_left)
            elif name == "databento_delivery":
                staleness = details_dict.get("staleness_days")
                if isinstance(staleness, (int, float)) and not isinstance(staleness, bool):
                    numeric["staleness_days"] = float(staleness)

            probe_rows.append(
                {
                    "name": _sanitize_name(name),
                    "severity": severity,
                    "code": float(code),
                    "valid": valid,
                    "message": message,
                    "numeric": numeric,
                }
            )

    snapshot["probes"] = probe_rows
    return snapshot


# ---------------------------------------------------------------------------
# Daily experiment (Plan 2.8 per-TF family rollup + per-day history) helpers
# ---------------------------------------------------------------------------
# The rolling measurement benchmark scores SMC setup families (BOS / OB / FVG /
# SWEEP) per timeframe once per day. We surface the latest rollup (current-day
# stats + Phase E2 verdicts) plus the retained per-day history so Grafana can
# render both a live "today" view and a backfilled per-day timeline.

# Stable numeric code per Phase E2 verdict status so a Grafana stat panel can
# colour it (higher == more conclusive / healthier evidence).
_EXPERIMENT_VERDICT_STATUS_CODES: Mapping[str, int] = {
    "missing": 0,
    "insufficient_data": 1,
    "degenerate_aliased_input": 2,
    "measured_underpowered": 3,
    "measured": 4,
}

# Map the rollup's verdict keys to short hypothesis labels for the dashboard.
_EXPERIMENT_VERDICT_KEYS: Mapping[str, str] = {
    "fvg_ttf_5m_vs_baseline": "fvg_5m",
    "bos_stability_4h_vs_baseline": "bos_4h",
}


def _experiment_tf_labels(timeframe: str) -> str:
    """Render the ``timeframe`` label for a per-TF experiment series."""
    return f'timeframe="{_escape_label_value(timeframe or "unknown")}"'


def _experiment_family_labels(timeframe: str, family: str) -> str:
    """Render the ``timeframe``/``family`` label set for a per-family series."""
    return (
        f'timeframe="{_escape_label_value(timeframe or "unknown")}",'
        f'family="{_escape_label_value(family or "unknown")}"'
    )


def _experiment_day_labels(run_date: str, timeframe: str, family: str) -> str:
    """Render the ``run_date``/``timeframe``/``family`` label set (history)."""
    return (
        f'run_date="{_escape_label_value(run_date or "unknown")}",'
        f'timeframe="{_escape_label_value(timeframe or "unknown")}",'
        f'family="{_escape_label_value(family or "unknown")}"'
    )


def _experiment_verdict_labels(hypothesis: str, status: str) -> str:
    """Render the ``hypothesis``/``status`` label set for a verdict series."""
    return (
        f'hypothesis="{_escape_label_value(hypothesis or "unknown")}",'
        f'status="{_escape_label_value(status or "unknown")}"'
    )


def _experiment_date_from_root(scoring_root: object) -> str:
    """Extract a ``YYYY-MM-DD`` run date from a rollup ``scoring_root`` path."""
    if not isinstance(scoring_root, str) or not scoring_root:
        return ""
    tail = scoring_root.rstrip("/").rsplit("/", 1)[-1]
    if len(tail) == 10 and tail[4] == "-" and tail[7] == "-":
        try:
            datetime.datetime.strptime(tail, "%Y-%m-%d")
        except ValueError:
            return ""
        return tail
    return ""


def _experiment_run_age(run_date: str) -> tuple[float, float]:
    """Return ``(age_known, age_seconds)`` from a ``YYYY-MM-DD`` run date.

    Daily granularity: age is measured from midnight UTC of the run date. When
    the date cannot be parsed ``age_known`` is ``0`` so the panel shows N/A
    rather than a misleading ``0``.
    """
    if not run_date:
        return 0.0, 0.0
    try:
        parsed = datetime.datetime.strptime(run_date, "%Y-%m-%d").replace(
            tzinfo=datetime.UTC
        )
    except ValueError:
        return 0.0, 0.0
    age = time.time() - parsed.timestamp()
    return 1.0, max(0.0, age)


def _experiment_per_tf_rows(per_tf: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Flatten a rollup/history ``per_tf`` mapping into TF and family rows.

    Returns ``(tf_rows, family_rows)`` where each TF row carries
    ``timeframe``/``n_events``/``hit_rate`` and each family row additionally
    carries ``family``. Malformed entries are skipped.
    """
    tf_rows: list[dict[str, object]] = []
    family_rows: list[dict[str, object]] = []
    if not isinstance(per_tf, dict):
        return tf_rows, family_rows
    for timeframe, payload in per_tf.items():
        if not isinstance(payload, dict):
            continue
        tf_rows.append(
            {
                "timeframe": str(timeframe),
                "n_events": payload.get("n_events", 0),
                "hit_rate": payload.get("hit_rate", 0),
            }
        )
        families = payload.get("families")
        if not isinstance(families, dict):
            continue
        for family, fam_payload in families.items():
            if not isinstance(fam_payload, dict):
                continue
            family_rows.append(
                {
                    "timeframe": str(timeframe),
                    "family": str(family),
                    "n_events": fam_payload.get("n_events", 0),
                    "hit_rate": fam_payload.get("hit_rate", 0),
                }
            )
    return tf_rows, family_rows


def _experiment_snapshot() -> dict[str, object]:
    """Derive daily-experiment gauges from the latest Plan 2.8 family rollup.

    Reads through :func:`compute._load_experiment_snapshot` so the gauges
    reflect whatever source the daemon serves (the runtime
    ``EXPERIMENT_SNAPSHOT_URL`` when configured, otherwise the local rollup).
    Returns the load flag, run date + age, files scanned, flattened per-TF and
    per-family rows and the Phase E2 verdicts.
    """
    raw = compute._load_experiment_snapshot()
    loaded = 0.0
    run_date = ""
    age_known = 0.0
    age_seconds = 0.0
    files_scanned = 0.0
    tf_rows: list[dict[str, object]] = []
    family_rows: list[dict[str, object]] = []
    verdicts: list[dict[str, object]] = []

    if isinstance(raw, dict) and raw:
        loaded = 1.0
        run_date = _experiment_date_from_root(raw.get("scoring_root"))
        age_known, age_seconds = _experiment_run_age(run_date)
        files_value = raw.get("files_scanned", 0)
        if isinstance(files_value, (int, float)) and not isinstance(files_value, bool):
            files_scanned = float(files_value)
        tf_rows, family_rows = _experiment_per_tf_rows(raw.get("per_tf"))

        phase_e2 = raw.get("phase_e2_verdict")
        if isinstance(phase_e2, dict):
            for key, hypothesis in _EXPERIMENT_VERDICT_KEYS.items():
                verdict = phase_e2.get(key)
                if not isinstance(verdict, dict):
                    continue
                status = str(verdict.get("status", "missing"))
                p_value = verdict.get("delta_hr_p_value")
                verdicts.append(
                    {
                        "hypothesis": hypothesis,
                        "status": status,
                        "status_code": _EXPERIMENT_VERDICT_STATUS_CODES.get(status, 0),
                        "delta_hr": verdict.get("delta_hr", 0),
                        "p_value": (
                            p_value
                            if isinstance(p_value, (int, float)) and not isinstance(p_value, bool)
                            else None
                        ),
                        "underpowered": 1.0 if verdict.get("underpowered") else 0.0,
                        "n_a": verdict.get("n_a", 0),
                        "n_b": verdict.get("n_b", 0),
                    }
                )

    return {
        "loaded": loaded,
        "run_date": run_date,
        "age_known": age_known,
        "age_seconds": age_seconds,
        "files_scanned": files_scanned,
        "tf_rows": tf_rows,
        "family_rows": family_rows,
        "verdicts": verdicts,
    }


def _experiment_history() -> list[dict[str, object]]:
    """Flatten the per-day Plan 2.8 history into per-(day, TF, family) rows.

    Reads through :func:`compute._load_experiment_history` (already capped and
    chronologically ordered). Each returned row carries ``run_date``,
    ``timeframe``, ``family``, ``hit_rate`` and ``n_events`` so Grafana can
    render the retained window as an immediate per-day timeline without waiting
    for Prometheus to accumulate samples.
    """
    rows: list[dict[str, object]] = []
    for snapshot in compute._load_experiment_history():
        if not isinstance(snapshot, dict):
            continue
        captured_at = snapshot.get("captured_at")
        run_date = str(captured_at)[:10] if isinstance(captured_at, str) else ""
        if not run_date:
            continue
        _tf_rows, family_rows = _experiment_per_tf_rows(snapshot.get("per_tf"))
        for family_row in family_rows:
            rows.append(
                {
                    "run_date": run_date,
                    "timeframe": family_row["timeframe"],
                    "family": family_row["family"],
                    "hit_rate": family_row["hit_rate"],
                    "n_events": family_row["n_events"],
                }
            )
    return rows


def _snapshot_timestamp(raw: dict[str, object]) -> float | None:
    """Best-effort unix timestamp for a news snapshot.

    Prefers ``fetched_at_unix`` (written by the live producer) then the
    ISO-8601 ``generated_at`` string. Returns ``None`` when neither is usable
    so callers can flag the snapshot age as unknown rather than reporting a
    misleading 0.
    """
    fetched_at = raw.get("fetched_at_unix")
    fetched_at_float = 0.0
    if isinstance(fetched_at, (int, float, str)):
        try:
            fetched_at_float = float(fetched_at)
        except (TypeError, ValueError):
            fetched_at_float = 0.0
    if math.isfinite(fetched_at_float) and fetched_at_float > 0:
        return fetched_at_float

    generated_at = raw.get("generated_at")
    if isinstance(generated_at, str) and generated_at.strip():
        text = generated_at.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.UTC)
        return parsed.timestamp()
    return None


def _provider_health_snapshot() -> dict[str, object]:
    """Derive provider-health gauges from the current news snapshot.

    Reads through the shared :func:`compute._load_news_snapshot` loader so the
    gauges reflect whatever source the daemon actually serves (the runtime
    ``NEWS_SNAPSHOT_URL`` when configured, otherwise the local file / baked
    seed).
    """
    raw = compute._load_news_snapshot()
    snapshot_loaded = 0.0
    snapshot_age_seconds = 0.0
    snapshot_age_known = 0.0
    providers_obj: object = {}

    if isinstance(raw, dict) and raw:
        providers_obj = raw.get("providers") or {}
        snapshot_loaded = 1.0
        # Prefer fetched_at_unix (live producer); fall back to the ISO-8601
        # generated_at string. When neither is present (e.g. the static seed)
        # the age is unknown and flagged as such instead of reporting a
        # misleading 0 that masquerades as a fresh snapshot.
        snapshot_ts = _snapshot_timestamp(raw)
        if snapshot_ts is not None:
            snapshot_age_known = 1.0
            snapshot_age_seconds = max(0.0, time.time() - snapshot_ts)

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
        "news_snapshot_age_known": snapshot_age_known,
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


def _collect_process_metrics(startup_ts: float) -> list[str]:
    """Emit process-level resource metrics (CPU, RSS, FDs, GC).

    Pure-stdlib implementation — no prometheus_client dependency. Uses
    /proc/self/status on Linux (Railway containers) and resource.getrusage
    as fallback (macOS dev).
    """
    import gc
    import os

    try:
        import resource  # POSIX-only; guarded for cross-platform safety
        _resource_available = True
    except ImportError:
        _resource_available = False
        resource = None  # type: ignore[assignment]

    lines: list[str] = []
    prefix = "live_overlay_process"

    # CPU seconds (user + system) — POSIX only
    if _resource_available and resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        cpu_seconds = usage.ru_utime + usage.ru_stime
        lines.append(f"# TYPE {prefix}_cpu_seconds_total counter")
        lines.append(f"{prefix}_cpu_seconds_total {cpu_seconds:.6f}")

    # Memory — prefer /proc/self/status (Linux) for accurate RSS/VmSize
    rss_bytes = 0
    vm_bytes = 0
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_bytes = int(line.split()[1]) * 1024
                elif line.startswith("VmSize:"):
                    vm_bytes = int(line.split()[1]) * 1024
    except (OSError, ValueError):
        # macOS fallback: ru_maxrss is in bytes on macOS, KB on Linux
        if _resource_available and resource is not None:
            import sys

            rss_bytes = usage.ru_maxrss  # type: ignore[possibly-undefined]
            if sys.platform == "darwin":
                pass  # already in bytes on macOS
            else:
                rss_bytes *= 1024

    lines.append(f"# TYPE {prefix}_resident_memory_bytes gauge")
    lines.append(f"{prefix}_resident_memory_bytes {rss_bytes}")
    if vm_bytes:
        lines.append(f"# TYPE {prefix}_virtual_memory_bytes gauge")
        lines.append(f"{prefix}_virtual_memory_bytes {vm_bytes}")

    # Open file descriptors
    try:
        fd_count = len(os.listdir("/proc/self/fd"))
    except OSError:
        fd_count = 0
    lines.append(f"# TYPE {prefix}_open_fds gauge")
    lines.append(f"{prefix}_open_fds {fd_count}")

    # Start time and uptime
    lines.append(f"# TYPE {prefix}_start_time_seconds gauge")
    lines.append(f"{prefix}_start_time_seconds {startup_ts:.3f}")
    uptime = time.time() - startup_ts if startup_ts > 0 else 0
    lines.append(f"# TYPE {prefix}_uptime_seconds gauge")
    lines.append(f"{prefix}_uptime_seconds {uptime:.1f}")

    # Python GC collections
    gc_stats = gc.get_stats()
    lines.append(f"# TYPE {prefix}_python_gc_collections_total counter")
    for i, stat in enumerate(gc_stats):
        lines.append(
            f'{prefix}_python_gc_collections_total{{generation="{i}"}} {stat.get("collections", 0)}'
        )

    return lines


def render_metrics(startup_ts: float) -> str:
    """Return Prometheus text-format exposition of all daemon metrics."""
    lines: list[str] = []

    # --- Counters from observability ---
    with observability._counter_lock:
        counters = dict(observability._counters)

    # Traffic counters are incremented in main.py. After a fresh start or when
    # no requests arrive, the in-process counter dict does not yet contain
    # them, which causes Prometheus rate() queries in the dashboard to return
    # "No data". Seed them as 0.0 so the series are always scraped.
    for traffic_counter in (
        "live_overlay.smc_live_requests.total",
        "live_overlay.smc_live_success.total",
        "live_overlay.smc_live_errors.total",
        "live_overlay.smc_live_auth.denied",
        "live_overlay.smc_live_bad_tf.total",
        "live_overlay.smc_live_cache_miss.total",
        "live_overlay.smc_live_stale_served.total",
    ):
        counters.setdefault(traffic_counter, 0.0)

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
        lines.append(f"# TYPE live_overlay_hotspot_symbol_{sym}_requests_total counter")
        lines.append(
            f"live_overlay_hotspot_symbol_{sym}_requests_total {_prom_numeric_value(count)}"
        )

    for tf, count in hotspot.get("top_tfs") or []:
        tf_name = _sanitize_name(str(tf).lower())
        lines.append(f"# TYPE live_overlay_hotspot_tf_{tf_name}_requests_total counter")
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
        "ingest_queue_lag_ms_last",
        "ingest_queue_lag_ms_max",
    ):
        prom_name = f"live_overlay_feed_{_sanitize_name(key)}"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(backpressure.get(key, 0.0))}")

    # ingest_queue_dropped_total is a counter (monotonically increasing drops).
    prom_name = "live_overlay_feed_ingest_queue_dropped_total"
    lines.append(f"# TYPE {prom_name} counter")
    lines.append(f"{prom_name} {_prom_numeric_value(backpressure.get('ingest_queue_dropped_total', 0.0))}")

    provider_health = _provider_health_snapshot()
    for key in (
        "news_snapshot_loaded",
        "news_snapshot_age_seconds",
        "news_snapshot_age_known",
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
    snapshot_age = (
        max(0.0, time.time() - fetched_at_unix)
        if math.isfinite(fetched_at_unix) and fetched_at_unix > 0
        else 0.0
    )

    lines.append("# TYPE live_overlay_uptimerobot_bridge_enabled gauge")
    lines.append(f"live_overlay_uptimerobot_bridge_enabled {enabled}")
    lines.append("# TYPE live_overlay_uptimerobot_scrape_success gauge")
    lines.append(f"live_overlay_uptimerobot_scrape_success {ok}")
    lines.append("# TYPE live_overlay_uptimerobot_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_uptimerobot_snapshot_age_seconds {snapshot_age:.1f}")

    error_code = str(uptime_snapshot.get("error_code") or "")
    if error_code:
        escaped = _escape_label_value(error_code)
        lines.append("# TYPE live_overlay_uptimerobot_scrape_error_info gauge")
        lines.append(f'live_overlay_uptimerobot_scrape_error_info{{error_code="{escaped}"}} 1')
    else:
        lines.append("# TYPE live_overlay_uptimerobot_scrape_error_info gauge")
        lines.append('live_overlay_uptimerobot_scrape_error_info{error_code="none"} 0')

    counts = dict(uptime_snapshot.get("counts") or {})
    for key in ("total", "up", "down", "paused", "unknown"):
        suffix = "_total" if key != "total" else ""
        prom_name = f"live_overlay_uptimerobot_monitors_{key}{suffix}"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(counts.get(key, 0))}")

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
    wf_snapshot_age = (
        max(0.0, time.time() - wf_fetched_at_unix)
        if math.isfinite(wf_fetched_at_unix) and wf_fetched_at_unix > 0
        else 0.0
    )

    lines.append("# TYPE live_overlay_github_workflow_bridge_enabled gauge")
    lines.append(f"live_overlay_github_workflow_bridge_enabled {wf_enabled}")
    lines.append("# TYPE live_overlay_github_workflow_scrape_success gauge")
    lines.append(f"live_overlay_github_workflow_scrape_success {wf_ok}")
    lines.append("# TYPE live_overlay_github_workflow_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_github_workflow_snapshot_age_seconds {wf_snapshot_age:.1f}")

    wf_error_code = str(workflow_snapshot.get("error_code") or "")
    if wf_error_code:
        escaped = _escape_label_value(wf_error_code)
        lines.append("# TYPE live_overlay_github_workflow_scrape_error_info gauge")
        lines.append(f'live_overlay_github_workflow_scrape_error_info{{error_code="{escaped}"}} 1')
    else:
        lines.append("# TYPE live_overlay_github_workflow_scrape_error_info gauge")
        lines.append('live_overlay_github_workflow_scrape_error_info{error_code="none"} 0')

    workflow_counts = dict(workflow_snapshot.get("counts") or {})
    for key in ("seen", "success", "failed", "in_progress", "queued"):
        # Snapshot counts from the latest workflow-runs page can go up/down
        # across polls, so expose them as gauges (not monotonic counters).
        metric_name = f"live_overlay_github_workflow_runs_{key}_total"
        lines.append(f"# TYPE {metric_name} gauge")
        lines.append(
            f"{metric_name} {_prom_numeric_value(workflow_counts.get(key, 0))}"
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

    # Per-workflow series are emitted as labelled time series (workflow_id,
    # workflow name, trigger event) so Grafana can name each flow and render a
    # single shared, colour-coded status timeline / detail table. Each metric
    # name carries one ``# TYPE`` line followed by one sample per workflow.
    workflows = list(workflow_snapshot.get("workflows") or [])
    if workflows:
        lines.append("# TYPE live_overlay_github_workflow_phase_code gauge")
        for workflow in workflows:
            lines.append(
                f"live_overlay_github_workflow_phase_code{{{_workflow_labels(workflow)}}} "
                f"{_prom_numeric_value(workflow.get('phase_code', 0))}"
            )
        lines.append("# TYPE live_overlay_github_workflow_latest_success gauge")
        for workflow in workflows:
            lines.append(
                f"live_overlay_github_workflow_latest_success{{{_workflow_labels(workflow)}}} "
                f"{_prom_numeric_value(workflow.get('latest_success', 0))}"
            )
        lines.append("# TYPE live_overlay_github_workflow_latest_age_seconds gauge")
        for workflow in workflows:
            workflow_age = workflow.get("latest_age_seconds")
            if workflow_age is None:
                continue
            lines.append(
                f"live_overlay_github_workflow_latest_age_seconds{{{_workflow_labels(workflow)}}} "
                f"{_prom_numeric_value(workflow_age)}"
            )
        lines.append("# TYPE live_overlay_github_workflow_latest_duration_seconds gauge")
        for workflow in workflows:
            workflow_duration = workflow.get("latest_duration_seconds")
            if workflow_duration is None:
                continue
            lines.append(
                "live_overlay_github_workflow_latest_duration_seconds"
                f"{{{_workflow_labels(workflow)}}} {_prom_numeric_value(workflow_duration)}"
            )

    # ---- Realtime trading signals (A0 pre-breakout / A1 breakout) ----------
    # Sourced from the realtime engine snapshot via
    # compute._load_signals_snapshot (local file or SIGNALS_SNAPSHOT_URL).
    # Surfaced so Grafana can show which symbols are firing, their
    # score/freshness/technical bias, and how fresh the snapshot is. Per-signal
    # series are labelled (symbol/level/direction/tier) and capped to the
    # strongest signals to bound cardinality.
    signals_snapshot = _trading_signals_snapshot()
    signal_counts = signals_snapshot["counts"]
    if not isinstance(signal_counts, dict):
        signal_counts = {"active": 0, "a0": 0, "a1": 0, "watched": 0}
    lines.append("# TYPE live_overlay_trading_signals_loaded gauge")
    lines.append(
        "live_overlay_trading_signals_loaded "
        f"{_prom_numeric_value(signals_snapshot['loaded'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_active_total gauge")
    lines.append(
        "live_overlay_trading_signals_active_total "
        f"{_prom_numeric_value(signal_counts['active'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_a0_total gauge")
    lines.append(
        f"live_overlay_trading_signals_a0_total {_prom_numeric_value(signal_counts['a0'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_a1_total gauge")
    lines.append(
        f"live_overlay_trading_signals_a1_total {_prom_numeric_value(signal_counts['a1'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_watched_total gauge")
    lines.append(
        "live_overlay_trading_signals_watched_total "
        f"{_prom_numeric_value(signal_counts['watched'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_snapshot_age_known gauge")
    lines.append(
        "live_overlay_trading_signals_snapshot_age_known "
        f"{_prom_numeric_value(signals_snapshot['age_known'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_snapshot_age_seconds gauge")
    lines.append(
        "live_overlay_trading_signals_snapshot_age_seconds "
        f"{signals_snapshot['age_seconds']:.1f}"
    )
    lines.append("# TYPE live_overlay_trading_signals_snapshot_max_age_seconds gauge")
    lines.append(
        "live_overlay_trading_signals_snapshot_max_age_seconds "
        f"{_prom_numeric_value(signals_snapshot['max_age_seconds'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_snapshot_stale gauge")
    lines.append(
        "live_overlay_trading_signals_snapshot_stale "
        f"{_prom_numeric_value(signals_snapshot['stale'])}"
    )

    signal_rows = signals_snapshot["signals"]
    if isinstance(signal_rows, list) and signal_rows:
        lines.append("# TYPE live_overlay_trading_signal_score gauge")
        for sig in signal_rows:
            lines.append(
                f"live_overlay_trading_signal_score{{{_signal_labels(sig)}}} "
                f"{_prom_numeric_value(sig.get('score', 0))}"
            )
        lines.append("# TYPE live_overlay_trading_signal_freshness gauge")
        for sig in signal_rows:
            lines.append(
                f"live_overlay_trading_signal_freshness{{{_signal_labels(sig)}}} "
                f"{_prom_numeric_value(sig.get('freshness', 0))}"
            )
        lines.append("# TYPE live_overlay_trading_signal_technical_score gauge")
        for sig in signal_rows:
            lines.append(
                f"live_overlay_trading_signal_technical_score{{{_signal_labels(sig)}}} "
                f"{_prom_numeric_value(sig.get('technical_score', 0))}"
            )
        lines.append("# TYPE live_overlay_trading_signal_change_pct gauge")
        for sig in signal_rows:
            lines.append(
                f"live_overlay_trading_signal_change_pct{{{_signal_labels(sig)}}} "
                f"{_prom_numeric_value(sig.get('change_pct', 0))}"
            )
        lines.append("# TYPE live_overlay_trading_signal_info gauge")
        for sig in signal_rows:
            info_labels = (
                f"{_signal_labels(sig)},"
                f'technical_signal="{_escape_label_value(sig.get("technical_signal", "") or "unknown")}",'
                f'macd_signal="{_escape_label_value(sig.get("macd_signal", "") or "unknown")}",'
                f'symbol_regime="{_escape_label_value(sig.get("symbol_regime", "") or "unknown")}",'
                f'news_category="{_escape_label_value(sig.get("news_category", "") or "unknown")}"'
            )
            lines.append(f"live_overlay_trading_signal_info{{{info_labels}}} 1")

    # ----- TradingView storage-state credential age ------------------------
    # Sourced from the daily credential-health report via
    # compute._load_tradingview_credential_snapshot (local credential_health.json
    # or TRADINGVIEW_CREDENTIAL_SNAPSHOT_URL). Surfaces the cached TradingView
    # login age so Grafana can alert before it expires (policy TTL 72h, warn at
    # 57.6h). age_hours is only meaningful while age_known == 1.
    tv_credential = _tradingview_credential_snapshot()
    lines.append("# TYPE live_overlay_tradingview_credential_loaded gauge")
    lines.append(
        "live_overlay_tradingview_credential_loaded "
        f"{_prom_numeric_value(tv_credential['loaded'])}"
    )
    lines.append("# TYPE live_overlay_tradingview_credential_valid gauge")
    lines.append(
        "live_overlay_tradingview_credential_valid "
        f"{_prom_numeric_value(tv_credential['valid'])}"
    )
    lines.append("# TYPE live_overlay_tradingview_credential_age_known gauge")
    lines.append(
        "live_overlay_tradingview_credential_age_known "
        f"{_prom_numeric_value(tv_credential['age_known'])}"
    )
    lines.append("# TYPE live_overlay_tradingview_credential_age_hours gauge")
    lines.append(
        "live_overlay_tradingview_credential_age_hours "
        f"{tv_credential['age_hours']:.3f}"
    )
    lines.append("# TYPE live_overlay_tradingview_credential_validated_at_seconds gauge")
    lines.append(
        "live_overlay_tradingview_credential_validated_at_seconds "
        f"{tv_credential['validated_at_seconds']:.0f}"
    )

    # ----- Full credential-health report -----------------------------------
    # Sourced from the same daily credential-health report as the legacy
    # TradingView gauge above, but exposes every probe (TV storage state,
    # GitHub PAT, Databento delivery, FMP, NewsAPI, ...) as labelled metrics.
    credential = _credential_health_snapshot()
    lines.append("# TYPE live_overlay_credential_health_loaded gauge")
    lines.append(
        "live_overlay_credential_health_loaded "
        f"{_prom_numeric_value(credential['loaded'])}"
    )
    lines.append("# TYPE live_overlay_credential_health_overall_valid gauge")
    lines.append(
        "live_overlay_credential_health_overall_valid "
        f"{_prom_numeric_value(credential['overall_valid'])}"
    )
    lines.append("# TYPE live_overlay_credential_health_overall_severity_info gauge")
    overall_severity = _escape_label_value(str(credential["overall_severity"]))
    lines.append(
        f'live_overlay_credential_health_overall_severity_info{{severity="{overall_severity}"}} 1'
    )

    probe_rows = credential.get("probes") or []
    if probe_rows:
        lines.append("# TYPE live_overlay_credential_health_probe_severity_code gauge")
        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            code = _prom_numeric_value(probe["code"])
            lines.append(f"live_overlay_credential_health_{name}_severity_code {code}")

        lines.append("# TYPE live_overlay_credential_health_probe_valid gauge")
        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            valid = _prom_numeric_value(probe["valid"])
            lines.append(f"live_overlay_credential_health_{name}_valid {valid}")

        lines.append("# TYPE live_overlay_credential_health_probe_info gauge")
        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            severity = _escape_label_value(str(probe["severity"]))
            message = _escape_label_value(str(probe["message"])[:200])
            lines.append(
                f'live_overlay_credential_health_{name}_info{{severity="{severity}",'
                f'message="{message}"}} 1'
            )

        lines.append("# TYPE live_overlay_credential_health_probe_value gauge")
        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            numeric = probe.get("numeric") or {}
            for value_name, value in numeric.items():
                value_metric = _sanitize_name(str(value_name))
                lines.append(
                    f'live_overlay_credential_health_{name}_{value_metric} '
                    f"{_prom_numeric_value(value)}"
                )

    # ----- Daily experiment (Plan 2.8 family/timeframe scoring) -------------
    experiment = _experiment_snapshot()
    lines.append("# TYPE live_overlay_experiment_loaded gauge")
    lines.append(
        f"live_overlay_experiment_loaded {_prom_numeric_value(experiment['loaded'])}"
    )
    lines.append("# TYPE live_overlay_experiment_snapshot_age_known gauge")
    lines.append(
        "live_overlay_experiment_snapshot_age_known "
        f"{_prom_numeric_value(experiment['age_known'])}"
    )
    lines.append("# TYPE live_overlay_experiment_snapshot_age_seconds gauge")
    age_value = experiment["age_seconds"]
    age_float = float(age_value) if isinstance(age_value, (int, float)) else 0.0
    lines.append(f"live_overlay_experiment_snapshot_age_seconds {age_float:.1f}")
    lines.append("# TYPE live_overlay_experiment_files_scanned gauge")
    lines.append(
        "live_overlay_experiment_files_scanned "
        f"{_prom_numeric_value(experiment['files_scanned'])}"
    )

    tf_rows = experiment["tf_rows"]
    if isinstance(tf_rows, list) and tf_rows:
        lines.append("# TYPE live_overlay_experiment_tf_hit_rate gauge")
        for row in tf_rows:
            labels = _experiment_tf_labels(str(row.get("timeframe", "")))
            lines.append(
                f"live_overlay_experiment_tf_hit_rate{{{labels}}} "
                f"{_prom_numeric_value(row.get('hit_rate', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_tf_n_events gauge")
        for row in tf_rows:
            labels = _experiment_tf_labels(str(row.get("timeframe", "")))
            lines.append(
                f"live_overlay_experiment_tf_n_events{{{labels}}} "
                f"{_prom_numeric_value(row.get('n_events', 0))}"
            )

    family_rows = experiment["family_rows"]
    if isinstance(family_rows, list) and family_rows:
        lines.append("# TYPE live_overlay_experiment_family_hit_rate gauge")
        for row in family_rows:
            labels = _experiment_family_labels(
                str(row.get("timeframe", "")), str(row.get("family", ""))
            )
            lines.append(
                f"live_overlay_experiment_family_hit_rate{{{labels}}} "
                f"{_prom_numeric_value(row.get('hit_rate', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_family_n_events gauge")
        for row in family_rows:
            labels = _experiment_family_labels(
                str(row.get("timeframe", "")), str(row.get("family", ""))
            )
            lines.append(
                f"live_overlay_experiment_family_n_events{{{labels}}} "
                f"{_prom_numeric_value(row.get('n_events', 0))}"
            )

    verdicts = experiment["verdicts"]
    if isinstance(verdicts, list) and verdicts:
        lines.append("# TYPE live_overlay_experiment_verdict_status_code gauge")
        for verdict in verdicts:
            labels = _experiment_verdict_labels(
                str(verdict.get("hypothesis", "")), str(verdict.get("status", ""))
            )
            lines.append(
                f"live_overlay_experiment_verdict_status_code{{{labels}}} "
                f"{_prom_numeric_value(verdict.get('status_code', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_verdict_delta_hr gauge")
        for verdict in verdicts:
            labels = _experiment_verdict_labels(
                str(verdict.get("hypothesis", "")), str(verdict.get("status", ""))
            )
            lines.append(
                f"live_overlay_experiment_verdict_delta_hr{{{labels}}} "
                f"{_prom_numeric_value(verdict.get('delta_hr', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_verdict_underpowered gauge")
        for verdict in verdicts:
            labels = _experiment_verdict_labels(
                str(verdict.get("hypothesis", "")), str(verdict.get("status", ""))
            )
            lines.append(
                f"live_overlay_experiment_verdict_underpowered{{{labels}}} "
                f"{_prom_numeric_value(verdict.get('underpowered', 0))}"
            )
        # p-value is optional and is exported only for fully measured verdicts
        # (status == "measured") so underpowered/insufficient states cannot
        # expose a misleading numeric p-value.
        p_value_lines: list[str] = []
        for verdict in verdicts:
            p_value = verdict.get("p_value")
            if str(verdict.get("status", "")) != "measured":
                continue
            if not isinstance(p_value, (int, float)):
                continue
            labels = _experiment_verdict_labels(
                str(verdict.get("hypothesis", "")), str(verdict.get("status", ""))
            )
            p_value_lines.append(
                f"live_overlay_experiment_verdict_p_value{{{labels}}} "
                f"{_prom_numeric_value(p_value)}"
            )
        if p_value_lines:
            lines.append("# TYPE live_overlay_experiment_verdict_p_value gauge")
            lines.extend(p_value_lines)

    history_rows = _experiment_history()
    if history_rows:
        lines.append("# TYPE live_overlay_experiment_day_family_hit_rate gauge")
        for row in history_rows:
            labels = _experiment_day_labels(
                str(row.get("run_date", "")),
                str(row.get("timeframe", "")),
                str(row.get("family", "")),
            )
            lines.append(
                f"live_overlay_experiment_day_family_hit_rate{{{labels}}} "
                f"{_prom_numeric_value(row.get('hit_rate', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_day_family_n_events gauge")
        for row in history_rows:
            labels = _experiment_day_labels(
                str(row.get("run_date", "")),
                str(row.get("timeframe", "")),
                str(row.get("family", "")),
            )
            lines.append(
                f"live_overlay_experiment_day_family_n_events{{{labels}}} "
                f"{_prom_numeric_value(row.get('n_events', 0))}"
            )

    # --- Railway container resource metrics ---
    railway_snapshot = railway_metrics.snapshot()
    lines.append("# TYPE live_overlay_railway_metrics_enabled gauge")
    if railway_snapshot.get("enabled"):
        lines.append(
            f"live_overlay_railway_metrics_enabled {1 if railway_snapshot.get('ok') else 0}"
        )

        fetched_at = railway_snapshot.get("fetched_at_unix", 0.0)
        if fetched_at > 0:
            age_seconds = time.time() - fetched_at
            lines.append("# TYPE live_overlay_railway_metrics_age_seconds gauge")
            lines.append(f"live_overlay_railway_metrics_age_seconds {age_seconds:.1f}")

        error = railway_snapshot.get("error")
        if error:
            # Surface error as an info metric with the error text as label
            escaped_error = _escape_label_value(str(error)[:200])
            lines.append("# TYPE live_overlay_railway_metrics_error_info gauge")
            lines.append(f'live_overlay_railway_metrics_error_info{{error="{escaped_error}"}} 1')

        services = railway_snapshot.get("services") or []
        if services:
            # CPU cores
            lines.append("# TYPE live_overlay_railway_service_cpu_cores gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                cpu = svc.get("cpu_cores")
                if cpu is not None:
                    lines.append(
                        f'live_overlay_railway_service_cpu_cores{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(cpu)}"
                    )

            # Memory usage in GB (Railway native units)
            lines.append("# TYPE live_overlay_railway_service_memory_gb gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                memory_gb = svc.get("memory_gb")
                if memory_gb is not None:
                    lines.append(
                        f'live_overlay_railway_service_memory_gb{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(memory_gb)}"
                    )

            # Memory limit in GB
            lines.append("# TYPE live_overlay_railway_service_memory_limit_gb gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                limit_gb = svc.get("memory_limit_gb")
                if limit_gb is not None:
                    lines.append(
                        f'live_overlay_railway_service_memory_limit_gb{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(limit_gb)}"
                    )

            # Memory used ratio (memory_gb / memory_limit_gb)
            lines.append("# TYPE live_overlay_railway_service_memory_used_ratio gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                memory_gb = svc.get("memory_gb")
                limit_gb = svc.get("memory_limit_gb")
                if memory_gb is not None and limit_gb is not None and limit_gb > 0:
                    ratio = memory_gb / limit_gb
                    lines.append(
                        f'live_overlay_railway_service_memory_used_ratio{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(ratio)}"
                    )

            # Disk usage in GB
            lines.append("# TYPE live_overlay_railway_service_disk_gb gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                disk_gb = svc.get("disk_gb")
                if disk_gb is not None:
                    lines.append(
                        f'live_overlay_railway_service_disk_gb{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(disk_gb)}"
                    )

            # Network RX in GB
            lines.append("# TYPE live_overlay_railway_service_network_rx_gb gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                rx_gb = svc.get("network_rx_gb")
                if rx_gb is not None:
                    lines.append(
                        f'live_overlay_railway_service_network_rx_gb{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(rx_gb)}"
                    )

            # Network TX in GB
            lines.append("# TYPE live_overlay_railway_service_network_tx_gb gauge")
            for svc in services:
                service_name = _sanitize_name(svc.get("service", "unknown"))
                service_id = svc.get("service_id", "unknown")
                tx_gb = svc.get("network_tx_gb")
                if tx_gb is not None:
                    lines.append(
                        f'live_overlay_railway_service_network_tx_gb{{service="{service_name}",service_id="{service_id}"}} '
                        f"{_prom_numeric_value(tx_gb)}"
                    )
    else:
        lines.append("live_overlay_railway_metrics_enabled 0")

    # --- Process-level metrics (CPU, memory, FDs, GC) ---
    lines.extend(_collect_process_metrics(startup_ts))

    lines.append("")  # trailing newline
    return "\n".join(lines)
