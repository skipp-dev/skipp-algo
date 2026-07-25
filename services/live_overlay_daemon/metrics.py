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
from typing import Any

from . import (
    cache,
    compute,
    config,
    evidence_freshness_bridge,
    feed,
    github_workflow_bridge,
    observability,
    pine_library_version_bridge,
    provider_usage_bridge,
    railway_metrics,
    request_hotspots,
    sweep_trap_shadow_bridge,
    tradingview_binding_bridge,
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
    - prefix with ``_`` when the token starts with a digit so the result
      always matches the Prometheus metric-name grammar
      ``[a-zA-Z_:][a-zA-Z0-9_:]*``
    - fallback to ``unknown`` when nothing remains
    """
    token = str(name).strip().lower().replace(".", "_").replace("-", "_")
    token = re.sub(r"[^a-z0-9_]", "_", token)
    token = re.sub(r"_+", "_", token).strip("_")
    # Prometheus metric names may not begin with a digit; prefix preserves
    # semantic digits (e.g. timeframe "5m", monitor id "803343156").
    if token and token[0].isdigit():
        token = f"_{token}"
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


# Provider health state codes exposed via live_overlay_provider_news_*_state_code
# and the live_overlay_provider_news_info{state=...} label.
# NOTE: the per-provider metric names (live_overlay_provider_news_<provider>_state_code)
# are intentionally dynamic. The Grafana dashboards select them with a
# ``__name__=~"live_overlay_provider_news_.*_state_code"`` regex matcher rather than a
# fixed metric name, so adding a provider needs no dashboard change. Cardinality stays
# bounded by the small, static provider set.
_PROVIDER_STATE_LABELS = {0: "unknown", 1: "degraded", 2: "ok", 3: "disabled"}
_HEALTH_STATUS_CODES = {
    "unknown": 0,
    "starting": 1,
    "idle_market_closed": 2,
    "ok": 3,
    "degraded": 4,  # sustained non-ok during open US session, past warmup (F-3)
}

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
    # Backslash and double-quote are the Prometheus label-value escapes; \n and
    # \r must not appear raw (a carriage return would truncate/break the line).
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _format_int_grouped(value: int) -> str:
    """Group an integer with English thousands separators (1234 -> "1,234")."""
    return f"{value:,}"


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

    Surfacing the breakout level (A0 = strongest confirmed / A1 = confirmed / A2 = early-warning), trade
    direction and confidence tier as labels lets Grafana name, colour and
    group each firing symbol instead of baking identity into the metric name.
    """
    return (
        f'symbol="{_escape_label_value(sig.get("symbol", "") or "unknown")}",'
        f'level="{_escape_label_value(sig.get("level", "") or "unknown")}",'
        f'direction="{_escape_label_value(sig.get("direction", "") or "unknown")}",'
        f'tier="{_escape_label_value(sig.get("confidence_tier", "") or "unknown")}"'
    )


def _coerce_count(value: Any) -> int:
    """Coerce an external-snapshot count to a non-negative int; 0 on anything
    non-numeric / non-finite.

    The daemon serves gauges from whatever ``SIGNALS_SNAPSHOT_URL`` / local JSON
    it is pointed at, so a corrupt or hostile snapshot can carry string counts
    (``"abc"``). A bare ``int("abc")`` raised ``ValueError`` synchronously in
    :func:`render_metrics`, 500-ing the whole ``/metrics`` scrape (Grafana blind).
    """
    # bool is an int subclass, so float(True) == 1.0 — a JSON ``true`` count
    # would silently expose as 1. A boolean is never a valid count → 0.
    if isinstance(value, bool):
        return 0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(numeric):
        return 0
    return max(0, int(numeric))


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
    counts = {"active": 0, "a0": 0, "a1": 0, "a2": 0, "watched": 0}

    if isinstance(raw, dict) and raw:
        loaded = 1.0
        signals_obj = raw.get("signals") or []
        counts["active"] = _coerce_count(raw.get("signal_count"))
        counts["a0"] = _coerce_count(raw.get("a0_count"))
        counts["a1"] = _coerce_count(raw.get("a1_count"))
        counts["a2"] = _coerce_count(raw.get("a2_count"))
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
            raw_age_seconds = time.time() - epoch_float
            if raw_age_seconds >= 0.0:
                age_known = 1.0
                age_seconds = raw_age_seconds
                stale = 1.0 if age_seconds > max_age_seconds else 0.0
            else:
                # A producer clock ahead of this process cannot prove that a
                # snapshot is current. Keep the age unknown and stale so the
                # alerting contract matches compute._signals_snapshot_is_fresh.
                stale = 1.0

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
                    parsed = datetime.datetime.fromisoformat(validated_at.replace("Z", "+00:00"))
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
      ``age_hours`` (and ``validated_at_seconds``) for ``tv_storage_state_age``,
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
        # Freshness of the daily probe report (report ``generated_at`` vs now).
        # A silently-frozen snapshot (e.g. the publish push failing) otherwise
        # keeps serving stale-green gauges — the exact 12-day blind spot the
        # credential-health workflow exists to prevent. age_known == 0 (no
        # timestamp / no snapshot) reads as not-stale so a fresh daemon with an
        # absent snapshot does not self-alarm; the ``_loaded``/``absent()`` alert
        # covers the missing-entirely case instead.
        "snapshot_age_known": 0.0,
        "snapshot_age_seconds": 0.0,
        "probes": [],
    }

    if not isinstance(raw, dict) or not raw:
        return snapshot

    snapshot["loaded"] = 1.0
    overall = str(raw.get("overall_severity", "") or "unknown").lower()
    snapshot["overall_severity"] = overall
    snapshot["overall_valid"] = 0.0 if overall == "error" else 1.0

    generated_at = raw.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        try:
            parsed = datetime.datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.UTC)
            age = (datetime.datetime.now(datetime.UTC) - parsed).total_seconds()
            snapshot["snapshot_age_known"] = 1.0
            snapshot["snapshot_age_seconds"] = max(0.0, age)

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
                        parsed = datetime.datetime.fromisoformat(validated_at.replace("Z", "+00:00"))
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
        f'timeframe="{_escape_label_value(timeframe or "unknown")}",family="{_escape_label_value(family or "unknown")}"'
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
    """Extract a ``YYYY-MM-DD`` run date from a rollup ``scoring_root`` path.

    Producers use both ``.../YYYY-MM-DD`` and ``.../results_YYYY-MM-DD``.  The
    latter is the current Plan 2.8 format and must not turn a fresh, loaded
    rollup into ``age_known=0``.
    """
    if not isinstance(scoring_root, str) or not scoring_root:
        return ""
    tail = scoring_root.rstrip("/").rsplit("/", 1)[-1]
    if tail.startswith("results_"):
        tail = tail.removeprefix("results_")
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
        parsed = datetime.datetime.strptime(run_date, "%Y-%m-%d").replace(tzinfo=datetime.UTC)
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
                            p_value if isinstance(p_value, (int, float)) and not isinstance(p_value, bool) else None
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


def _experiment_history_run_date(captured_at: object) -> str:
    """Derive a ``YYYY-MM-DD`` run date from a snapshot ``captured_at``.

    ``captured_at`` is normally an ISO-8601 string written by the Plan 2.8
    archive step, but a numeric Unix timestamp is tolerated the same way
    :func:`compute._parse_history_lines` tolerates it, so a numeric value is
    converted to its UTC date instead of silently dropping the whole row.
    """
    if isinstance(captured_at, str):
        # Validate the date prefix instead of blindly slicing: a non-date string
        # (or a malformed date like "2026-04-2") must be dropped (""), not passed
        # through as a bogus run_date. Honors this helper's "junk inputs never
        # yield a bogus date" contract — which the numeric branch already
        # enforces — and mirrors _snapshot_timestamp's validate-or-None parsing.
        prefix = captured_at[:10]
        try:
            datetime.date.fromisoformat(prefix)
        except ValueError:
            return ""
        return prefix
    if isinstance(captured_at, (int, float)) and not isinstance(captured_at, bool):
        ts = float(captured_at)
        if not math.isfinite(ts) or ts <= 0:
            return ""
        try:
            return datetime.datetime.fromtimestamp(ts, tz=datetime.UTC).strftime("%Y-%m-%d")
        except (ValueError, OverflowError, OSError):
            return ""
    return ""


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
        run_date = _experiment_history_run_date(snapshot.get("captured_at"))
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
    ingest_age_seconds = 0.0
    ingest_age_known = 0.0
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
        # last_ingest_success_at advances only when new items were accepted
        # (WP-C1c); it is the correct key for a 'news not flowing' alert since
        # generated_at refreshes every producer tick regardless of ingest.
        ingest_raw = raw.get("last_ingest_success_at")
        try:
            ingest_ts = float(ingest_raw) if ingest_raw is not None else 0.0
        except (TypeError, ValueError):
            ingest_ts = 0.0
        if math.isfinite(ingest_ts) and ingest_ts > 0.0:
            ingest_age_known = 1.0
            ingest_age_seconds = max(0.0, time.time() - ingest_ts)

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
    health_ok = 1.0 if consumed_total > 0 and degraded == 0 and unknown == 0 else 0.0
    health_degraded = 1.0 if degraded > 0 else 0.0
    health_unknown = 1.0 if consumed_total == 0 or unknown > 0 else 0.0

    return {
        "news_snapshot_loaded": snapshot_loaded,
        "news_snapshot_age_seconds": snapshot_age_seconds,
        "news_snapshot_age_known": snapshot_age_known,
        "news_last_ingest_age_seconds": ingest_age_seconds,
        "news_last_ingest_age_known": ingest_age_known,
        "news_providers_total": float(total),  # *_total below are GAUGE snapshots (non-monotonic per-state counts) — do NOT increase()/rate()
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


def _read_build_stamp() -> tuple[str, str]:
    """Read the ``(commit, branch)`` baked into the image at deploy time.

    ``scripts/deploy_live_overlay.sh`` stamps the real values into
    ``build_stamp.txt`` before ``railway up`` (a CLI upload injects no
    ``RAILWAY_GIT_*`` vars). Returns empty strings when the stamp is missing
    or still the ``unknown`` placeholder, so callers fall through cleanly.
    """
    import pathlib

    stamp = pathlib.Path(__file__).with_name("build_stamp.txt")
    try:
        raw = stamp.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "", ""
    commit = raw[0].strip() if raw else ""
    branch = raw[1].strip() if len(raw) > 1 else ""
    return (
        "" if commit == "unknown" else commit,
        "" if branch == "unknown" else branch,
    )


def _build_identity() -> tuple[str, str]:
    """Return the deployed ``(commit, branch)``.

    Precedence: ``RAILWAY_GIT_*`` (set on GitHub-connected deploys) wins, then
    the build stamp baked in by the ``railway up`` wrapper, then ``"unknown"``
    -- the label is never empty.
    """
    import os

    commit = os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()
    branch = os.getenv("RAILWAY_GIT_BRANCH", "").strip()
    if not commit or not branch:
        stamp_commit, stamp_branch = _read_build_stamp()
        if not commit:
            commit = stamp_commit
        if not branch:
            branch = stamp_branch
    if not commit:
        commit = "unknown"
    if not branch:
        branch = "unknown"
    return commit, branch


def _collect_process_metrics(startup_ts: float, startup_epoch: float = 0.0) -> list[str]:
    """Emit process-level resource metrics (CPU, RSS, FDs, GC).

    ``startup_ts`` is ``time.monotonic()`` (drift-free deltas → uptime);
    ``startup_epoch`` is ``time.time()`` (wall-clock → Prometheus
    ``start_time_seconds``). Mixing the two produced a ~55-year uptime.

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
        # macOS fallback: ru_maxrss is in bytes on macOS, KB on Linux. NOTE: this
        # is PEAK RSS, not current — so the gauge reports lifetime peak on the
        # dev fallback path. Prod (Linux) uses /proc VmRSS above = true current RSS.
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
    lines.append(f"{prefix}_start_time_seconds {startup_epoch:.3f}")
    # Restart-cause attribution as a start-time-VALUED gauge LABELED by cause:
    # restarts-per-cause = changes() of this series over the window. The old
    # live_overlay_daemon_restart_cause_*_total counters were set to 1 once per
    # process and stayed constant (Prometheus saw 1,1,1,… so increase() was
    # always 0); start_time jumps on every restart, so changes() actually counts.
    lines.append("# TYPE live_overlay_daemon_start_time_seconds gauge")
    lines.append(
        f'live_overlay_daemon_start_time_seconds{{cause="{_escape_label_value(config.restart_cause())}"}} '
        f"{startup_epoch:.3f}"
    )
    uptime = time.monotonic() - startup_ts if startup_ts > 0 else 0
    lines.append(f"# TYPE {prefix}_uptime_seconds gauge")
    lines.append(f"{prefix}_uptime_seconds {uptime:.1f}")

    # Build identity — expose the deployed commit so "is the right code
    # running?" is answerable straight from Grafana (this exact blind spot
    # cost two silent no-op redeploys on 2026-07-06). Value is always 1 with
    # the identity in labels (Prometheus info-metric convention); never blank.
    commit, branch = _build_identity()
    lines.append("# TYPE live_overlay_build_info gauge")
    lines.append(
        f'live_overlay_build_info{{commit="{_escape_label_value(commit)}",'
        f'branch="{_escape_label_value(branch)}"}} 1'
    )

    # Python GC collections
    gc_stats = gc.get_stats()
    lines.append(f"# TYPE {prefix}_python_gc_collections_total counter")
    for i, stat in enumerate(gc_stats):
        lines.append(f'{prefix}_python_gc_collections_total{{generation="{i}"}} {stat.get("collections", 0)}')

    return lines


def _bridge_last_success_age(
    last_success_ts: float,
    *,
    enabled: bool,
    configured: bool,
    startup_epoch: float,
) -> float | None:
    """Age of the bridge's last SUCCESSFUL poll — never fabricated.

    ``last_success_ts > 0`` → real age since that success. ``0`` means the
    bridge has never succeeded in this process (all bridges preserve a cached
    ``last_success_fetched_at_unix`` across later failures, so zero cannot
    mean "lost during a failure"): for an enabled+configured bridge return
    the time since daemon start instead — a truthful lower bound for "time
    without a success" that keeps the series present (contract alert stays
    satisfied) and lets the staleness alerts fire once thresholds are
    exceeded. Previously the callers fell back to ``fetched_at_unix``, the
    timestamp of the failed ATTEMPT, which reported a near-zero age while a
    bridge was failing from boot and kept the stale alerts permanently blind.
    Disabled/unconfigured bridges return None (series omitted, as before).
    """
    if math.isfinite(last_success_ts) and last_success_ts > 0:
        return max(0.0, time.time() - last_success_ts)
    if enabled and configured and startup_epoch > 0:
        return max(0.0, time.time() - startup_epoch)
    return None


def _append_bridge_metrics(
    lines: list[str],
    *,
    bridge: str,
    enabled: bool,
    configured: bool,
    scrape_success: bool,
    last_success_age_seconds: float | None,
    scrape_duration_seconds: float | None,
    error_code: str | None,
) -> None:
    """Append generic Prometheus series for a live-overlay bridge.

    Bridges expose intent (enabled/configured) separately from outcome
    (scrape_success) so Grafana and alerts can distinguish disabled,
    misconfigured, scrape_failed, stale and ok without guessing.

    Low-cardinality labels only: ``bridge`` and a stable ``error``.
    """
    error = error_code or "none"
    escaped_error = _escape_label_value(error)

    lines.append("# TYPE live_overlay_bridge_enabled gauge")
    lines.append(f'live_overlay_bridge_enabled{{bridge="{bridge}"}} {1 if enabled else 0}')

    lines.append("# TYPE live_overlay_bridge_configured gauge")
    lines.append(f'live_overlay_bridge_configured{{bridge="{bridge}"}} {1 if configured else 0}')

    lines.append("# TYPE live_overlay_bridge_scrape_success gauge")
    lines.append(f'live_overlay_bridge_scrape_success{{bridge="{bridge}"}} {1 if scrape_success else 0}')

    if last_success_age_seconds is not None:
        lines.append("# TYPE live_overlay_bridge_last_success_age_seconds gauge")
        lines.append(
            f'live_overlay_bridge_last_success_age_seconds{{bridge="{bridge}"}} {last_success_age_seconds:.3f}'
        )

    if scrape_duration_seconds is not None:
        lines.append("# TYPE live_overlay_bridge_last_scrape_duration_seconds gauge")
        lines.append(
            f'live_overlay_bridge_last_scrape_duration_seconds{{bridge="{bridge}"}} {scrape_duration_seconds:.3f}'
        )

    lines.append("# TYPE live_overlay_bridge_error_info gauge")
    lines.append(
        f'live_overlay_bridge_error_info{{bridge="{bridge}",error="{escaped_error}"}} '
        f"{0 if error == 'none' else 1}"
    )


def render_metrics(startup_ts: float, startup_epoch: float = 0.0) -> str:
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
        # Compute-cycle error counters feed lo-compute-errors-rate. They were
        # created lazily on first error, so Prometheus increase() treated the
        # first-seen sample as baseline and the FIRST error burst per process
        # lifetime never fired the alert. Seed 0 like the traffic counters.
        "live_overlay.full_compute_cycle.errors",
        "live_overlay.flow_patch_cycle.errors",
    ):
        counters.setdefault(traffic_counter, 0.0)

    for name, value in sorted(counters.items()):
        prom_name = _sanitize_name(name)
        lines.append(f"# TYPE {prom_name} counter")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    hotspot = request_hotspots.snapshot(top_n=5)
    lines.append("# TYPE live_overlay_hotspot_symbols_tracked gauge")
    lines.append(f"live_overlay_hotspot_symbols_tracked {_prom_numeric_value(hotspot.get('symbol_count', 0))}")
    lines.append("# TYPE live_overlay_hotspot_timeframes_tracked gauge")
    lines.append(f"live_overlay_hotspot_timeframes_tracked {_prom_numeric_value(hotspot.get('tf_count', 0))}")

    # Aggregate by SANITIZED name: distinct raw keys can collide after
    # sanitization ("BRK.A"/"BRK-A" -> brk_a), and duplicate TYPE headers +
    # samples make Prometheus reject the entire exposition (whole-scrape
    # blackout from one colliding request pair).
    symbol_totals: dict[str, float] = {}
    for symbol, count in hotspot.get("top_symbols") or []:
        sym = _sanitize_name(str(symbol).lower())
        symbol_totals[sym] = symbol_totals.get(sym, 0.0) + float(_prom_numeric_value(count))
    for sym, total in symbol_totals.items():
        lines.append(f"# TYPE live_overlay_hotspot_symbol_{sym}_requests_total counter")
        lines.append(f"live_overlay_hotspot_symbol_{sym}_requests_total {total}")

    tf_totals: dict[str, float] = {}
    for tf, count in hotspot.get("top_tfs") or []:
        tf_name = _sanitize_name(str(tf).lower())
        tf_totals[tf_name] = tf_totals.get(tf_name, 0.0) + float(_prom_numeric_value(count))
    for tf_name, total in tf_totals.items():
        lines.append(f"# TYPE live_overlay_hotspot_tf_{tf_name}_requests_total counter")
        lines.append(f"live_overlay_hotspot_tf_{tf_name}_requests_total {total}")

    # --- Latency histogram -------------------------------------------------
    # Export real classic histogram bucket series so Prometheus can compute
    # rolling quantiles with histogram_quantile() instead of relying on
    # lifetime gauges derived from in-memory counters.
    # Always emit every known default bucket (with 0 when not yet observed)
    # so histogram_quantile() and Grafana transformations see a stable,
    # complete bucket set on every scrape.
    latency_base = "live_overlay.smc_live_latency"
    latency_count = counters.get(f"{latency_base}.count")
    latency_bucket_keys = [key for key in counters if key.startswith(f"{latency_base}.bucket_le_")]
    # latency_count / latency_bucket_keys are intentionally kept as local
    # documentation of where observations come from; they feed the running
    # fill logic below which now always emits the histogram series.
    # Emit the classic histogram on every scrape, even before the first
    # observation, so dashboard/alert consumers never see missing series.
    default_buckets = getattr(observability, "_HISTOGRAM_DEFAULT_BUCKETS_MS", ())
    bucket_values: dict[float, float] = {bucket: 0.0 for bucket in default_buckets}
    bucket_values[float("inf")] = 0.0
    prefix = f"{latency_base}.bucket_le_"
    for key in latency_bucket_keys:
        suffix = key[len(prefix) :]
        upper = _parse_bucket_upper_bound(suffix)
        if upper is None:
            continue
        bucket_values[upper] = _prom_numeric_value(counters[key])
    running = 0.0
    for bucket in sorted(default_buckets):
        running = max(running, bucket_values.get(bucket, running))
        bucket_values[bucket] = running
    bucket_values[float("inf")] = _prom_numeric_value(
        counters.get(f"{latency_base}.bucket_le_inf", latency_count or 0.0)
    )

    lines.append("# TYPE live_overlay_smc_live_latency_ms histogram")
    for upper in sorted(bucket_values, key=lambda u: (math.isinf(u), u)):
        le = "+Inf" if upper == float("inf") else f"{upper:.0f}"
        lines.append(
            f'live_overlay_smc_live_latency_ms_bucket{{le="{le}"}} {_prom_numeric_value(bucket_values[upper])}'
        )
    lines.append(
        f"live_overlay_smc_live_latency_ms_sum {_prom_numeric_value(counters.get(f'{latency_base}.sum_ms', 0.0))}"
    )
    lines.append(f"live_overlay_smc_live_latency_ms_count {_prom_numeric_value(latency_count or 0.0)}")

    # The derived p95/p99 gauges that lived here were kept only "until
    # dashboard/alert consumers are fully migrated to histogram_quantile() over
    # the buckets". That migration is complete and now enforced:
    # test_dashboard_latency_panel_uses_only_histogram_quantile and
    # test_latency_alert_uses_histogram_quantile_bucket assert the gauges are
    # ABSENT from every panel and rule. Emitting a series nothing may consume is
    # the blind spot the orphan scan exists to surface, so they are gone.

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
        "news_last_ingest_age_seconds",
        "news_last_ingest_age_known",
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
        lines.append(f"{prom_name} {_prom_numeric_value(provider_health.get(key, 0.0))}")

    for provider_name, value in sorted((provider_health.get("news_provider_ok") or {}).items()):
        prom_name = f"live_overlay_provider_news_{provider_name}_ok"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    for provider_name, value in sorted((provider_health.get("news_provider_degraded") or {}).items()):
        prom_name = f"live_overlay_provider_news_{provider_name}_degraded"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    for provider_name, value in sorted((provider_health.get("news_provider_state_code") or {}).items()):
        prom_name = f"live_overlay_provider_news_{provider_name}_state_code"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(value)}")

    for provider_name, value in sorted((provider_health.get("news_provider_consumed") or {}).items()):
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

    # Cap-churn visibility (2026-07-22): without these the bar cache could
    # thrash at the symbol cap — one bar per symbol, every rolling metric
    # unavailable — with no metric moving. NOTE (2026-07-24): under the
    # ALL_SYMBOLS feed this GLOBAL mean sits at ~1.0 by design — demand-aware
    # retention (#3903) pins the cache at the cap with the unrequested majority
    # holding one bar — so it is NOT the health signal for the rolling features.
    # `requested_bars_per_symbol` below (depth of the symbols a consumer reads)
    # is; `evicted_protected_total` rising means real demand exceeds the cap.
    lines.append("# TYPE live_overlay_bars_per_symbol gauge")
    lines.append(
        f"live_overlay_bars_per_symbol {bar_count / bar_symbols if bar_symbols else 0}"
    )
    # Requested-symbol depth: the number that actually gates squeeze /
    # relative-volume / ATS z-score (needs >= 20). Restricted to cached symbols
    # a consumer has read, so the ALL_SYMBOLS churn no longer masks or fakes it.
    req_bar_symbols, req_bars_per_symbol = cache.requested_bar_depth()
    lines.append("# TYPE live_overlay_requested_bar_symbols gauge")
    lines.append(f"live_overlay_requested_bar_symbols {req_bar_symbols}")
    lines.append("# TYPE live_overlay_requested_bars_per_symbol gauge")
    lines.append(f"live_overlay_requested_bars_per_symbol {req_bars_per_symbol}")
    lines.append("# TYPE live_overlay_bar_symbols_evicted_total counter")
    lines.append(f"live_overlay_bar_symbols_evicted_total {cache.evicted_symbols_total()}")
    lines.append("# TYPE live_overlay_bar_requested_symbols_evicted_total counter")
    lines.append(
        f"live_overlay_bar_requested_symbols_evicted_total {cache.evicted_protected_total()}"
    )

    overlay_age = cache.overlay_age_secs()
    overlay_age_known = 1.0 if overlay_age != float("inf") else 0.0
    lines.append("# TYPE live_overlay_overlay_age_known gauge")
    lines.append(f"live_overlay_overlay_age_known {overlay_age_known}")
    lines.append("# TYPE live_overlay_overlay_age_seconds gauge")
    # Unknown age renders 0.0, NOT nan: `lo-overlay-stale` selects arithmetically with
    # `(age * known) + ((1 - known) * 3601)`, and NaN * 0 = NaN would poison that sum so the
    # 3601 unknown-sentinel never breaches its 3600 threshold. Keep 0.0 unless that rule changes.
    lines.append(
        f"live_overlay_overlay_age_seconds {overlay_age:.1f}"
        if overlay_age != float("inf")
        else "live_overlay_overlay_age_seconds 0.0"
    )

    bar_age = feed.last_bar_age_secs()
    bar_age_known = 1.0 if bar_age is not None else 0.0
    if bar_age is None:
        bar_age = 0.0
    lines.append("# TYPE live_overlay_last_bar_age_known gauge")
    lines.append(f"live_overlay_last_bar_age_known {bar_age_known}")
    lines.append("# TYPE live_overlay_last_bar_age_seconds gauge")
    lines.append(f"live_overlay_last_bar_age_seconds {bar_age:.1f}")

    vix_level = cache.get_vix()
    vix_age = cache.vix_age_secs()
    vix_age_known = 1.0 if vix_age != float("inf") else 0.0
    lines.append("# TYPE live_overlay_vix_age_known gauge")
    lines.append(f"live_overlay_vix_age_known {vix_age_known}")
    lines.append("# TYPE live_overlay_vix_age_seconds gauge")
    # Unknown age renders 0.0, NOT nan: `lo-vix-unavailable` selects arithmetically
    # with `(age * known) + ((1 - known) * 5401)` — the same contract as
    # live_overlay_overlay_age_seconds above, where NaN * 0 would poison the sum.
    lines.append(
        f"live_overlay_vix_age_seconds {vix_age:.1f}"
        if vix_age != float("inf")
        else "live_overlay_vix_age_seconds 0.0"
    )
    lines.append("# TYPE live_overlay_vix_level gauge")
    # 0.0 while never-fetched keeps the series present (absent-vs-zero stays
    # distinguishable via vix_age_known; the dashboard panel gates on it).
    lines.append(
        f"live_overlay_vix_level {vix_level:.2f}"
        if vix_level is not None
        else "live_overlay_vix_level 0.0"
    )

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
    overlay_fresh = overlay_symbols > 0 and overlay_age != float("inf") and overlay_age <= max_stale
    lines.append("# TYPE live_overlay_overlay_fresh gauge")
    lines.append(f"live_overlay_overlay_fresh {1 if overlay_fresh else 0}")
    status = compute_daemon_health_status(
        feed_healthy=bool(feed_healthy),
        workers_healthy=bool(workers_healthy),
        overlay_fresh=overlay_fresh,
        market_open=us_open,
        bar_count=bar_count,
        uptime_secs=uptime,  # distinguishes warmup from sustained failure (F-3)
    )

    lines.append("# TYPE live_overlay_market_open gauge")
    lines.append(f"live_overlay_market_open {1 if market_open else 0}")
    expected_traffic = config.expect_market_traffic()
    lines.append("# TYPE live_overlay_expected_market_traffic gauge")
    lines.append(f"live_overlay_expected_market_traffic {1 if expected_traffic else 0}")
    lines.append("# TYPE live_overlay_market_us_open gauge")
    lines.append(f"live_overlay_market_us_open {1 if us_open else 0}")
    lines.append("# TYPE live_overlay_market_europe_open gauge")
    lines.append(f"live_overlay_market_europe_open {1 if eu_open else 0}")
    lines.append("# TYPE live_overlay_market_asia_open gauge")
    lines.append(f"live_overlay_market_asia_open {1 if asia_open else 0}")
    lines.append("# TYPE live_overlay_max_stale_seconds gauge")
    lines.append(f"live_overlay_max_stale_seconds {max_stale}")
    health_status_code = _HEALTH_STATUS_CODES.get(status, _HEALTH_STATUS_CODES["unknown"])
    lines.append("# TYPE live_overlay_health_status_code gauge")
    lines.append(f"live_overlay_health_status_code {health_status_code}")
    lines.append("# TYPE live_overlay_health_status_info gauge")
    lines.append(f'live_overlay_health_status_info{{status="{_escape_label_value(status)}"}} 1')

    for worker_name, alive in workers.items():
        prom_worker = _sanitize_name(worker_name)
        lines.append(f"# TYPE live_overlay_worker_{prom_worker}_alive gauge")
        lines.append(f"live_overlay_worker_{prom_worker}_alive {1 if alive else 0}")

    # --- Optional UptimeRobot bridge ---
    uptime_snapshot = uptimerobot_bridge.snapshot()
    uptime_enabled = bool(uptime_snapshot.get("enabled"))
    uptime_configured = bool(uptime_snapshot.get("configured", uptime_enabled))
    # scrape_success reflects the LAST ATTEMPT, not the retained snapshot's
    # ok: the keep-last-good cache preserves data across failures, and mapping
    # its ok froze scrape_success=1/error=none during persistent outages.
    uptime_ok = bool(uptime_snapshot.get("last_attempt_ok", uptime_snapshot.get("ok")))
    # Age comes from last_success ONLY — never from fetched_at, which on a
    # failed poll is the timestamp of the failed ATTEMPT and fabricated a
    # near-zero "last success age" while a bridge was failing from boot,
    # keeping the stale alerts blind. Never-succeeded-yet (both bridges
    # preserve a cached last_success across later failures, so ts==0 means
    # exactly that): report time since daemon start — the truthful lower
    # bound for "time without a success" — so the series stays present for
    # the contract alert and staleness fires once thresholds are exceeded.
    last_success_ts = _prom_numeric_value(
        uptime_snapshot.get("last_success_fetched_at_unix") or 0.0
    )
    snapshot_age = _bridge_last_success_age(
        last_success_ts,
        enabled=uptime_enabled,
        configured=uptime_configured,
        startup_epoch=startup_epoch,
    )

    # Presence-based (not truthiness) preference: last_attempt_error_code
    # exists only on retained-failure snapshots and then always wins.
    if "last_attempt_error_code" in uptime_snapshot:
        error_code = str(uptime_snapshot["last_attempt_error_code"])
    else:
        error_code = str(uptime_snapshot.get("error_code") or "")

    _append_bridge_metrics(
        lines,
        bridge="uptimerobot",
        enabled=uptime_enabled,
        configured=uptime_configured,
        scrape_success=uptime_ok,
        last_success_age_seconds=snapshot_age,
        scrape_duration_seconds=uptime_snapshot.get("scrape_duration_seconds"),
        error_code=error_code or None,
    )

    counts = dict(uptime_snapshot.get("counts") or {})
    for key in ("total", "up", "down", "paused", "unknown"):
        suffix = "_total" if key != "total" else ""  # legacy alias on a GAUGE (point-in-time count, rises+falls) — do NOT increase()/rate()
        prom_name = f"live_overlay_uptimerobot_monitors_{key}{suffix}"
        lines.append(f"# TYPE {prom_name} gauge")
        lines.append(f"{prom_name} {_prom_numeric_value(counts.get(key, 0))}")

    expected_monitor_ids = config.uptimerobot_monitor_ids()
    if expected_monitor_ids:
        lines.append("# TYPE live_overlay_uptimerobot_monitors_expected gauge")
        lines.append(
            f"live_overlay_uptimerobot_monitors_expected {float(len(expected_monitor_ids))}"
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
        lines.append(f"{monitor_prefix}_status_code {_prom_numeric_value(monitor.get('status_code', 1))}")
        response_time_ms = monitor.get("response_time_ms")
        if response_time_ms is not None:
            lines.append(f"# TYPE {monitor_prefix}_response_time_ms gauge")
            lines.append(f"{monitor_prefix}_response_time_ms {_prom_numeric_value(response_time_ms)}")

    # --- Optional GitHub workflow bridge ---
    workflow_snapshot = github_workflow_bridge.snapshot()
    wf_enabled = bool(workflow_snapshot.get("enabled"))
    wf_configured = bool(workflow_snapshot.get("configured", wf_enabled))
    # Last-attempt mapping — see the uptimerobot block above.
    wf_ok = bool(workflow_snapshot.get("last_attempt_ok", workflow_snapshot.get("ok")))
    # last_success only — see the uptimerobot block above for the rationale
    # (fetched_at on a failed poll fabricated a fresh "last success age").
    wf_last_success_ts = _prom_numeric_value(
        workflow_snapshot.get("last_success_fetched_at_unix") or 0.0
    )
    wf_snapshot_age = _bridge_last_success_age(
        wf_last_success_ts,
        enabled=wf_enabled,
        configured=wf_configured,
        startup_epoch=startup_epoch,
    )

    # Presence-based preference — see the uptimerobot block above.
    if "last_attempt_error_code" in workflow_snapshot:
        wf_error_code = str(workflow_snapshot["last_attempt_error_code"])
    else:
        wf_error_code = str(workflow_snapshot.get("error_code") or "")

    _append_bridge_metrics(
        lines,
        bridge="github_workflow",
        enabled=wf_enabled,
        configured=wf_configured,
        scrape_success=wf_ok,
        last_success_age_seconds=wf_snapshot_age,
        scrape_duration_seconds=workflow_snapshot.get("scrape_duration_seconds"),
        error_code=wf_error_code or None,
    )

    workflow_counts = dict(workflow_snapshot.get("counts") or {})
    for key in ("seen", "success", "failed", "in_progress", "queued"):
        # Snapshot counts from the latest workflow-runs page can go up/down
        # across polls, so expose them as gauges (not monotonic counters).
        metric_name = f"live_overlay_github_workflow_runs_{key}_total"
        lines.append(f"# TYPE {metric_name} gauge")
        lines.append(f"{metric_name} {_prom_numeric_value(workflow_counts.get(key, 0))}")

    latest_run_age = workflow_snapshot.get("latest_run_age_seconds")
    if latest_run_age is not None:
        lines.append("# TYPE live_overlay_github_workflow_latest_run_age_seconds gauge")
        lines.append(f"live_overlay_github_workflow_latest_run_age_seconds {_prom_numeric_value(latest_run_age)}")

    latest_run_duration = workflow_snapshot.get("latest_run_duration_seconds")
    if latest_run_duration is not None:
        lines.append("# TYPE live_overlay_github_workflow_latest_run_duration_seconds gauge")
        lines.append(
            f"live_overlay_github_workflow_latest_run_duration_seconds {_prom_numeric_value(latest_run_duration)}"
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

    # Presence of each DECLARED workflow (config.github_workflow_expected).
    # Every other workflow series is keyed off rows discovered in the fetched
    # runs page, so a flow that stops running loses its series entirely and each
    # rule over it goes NoData -> silent. This gauge is the one series that
    # survives that disappearance: it stays present and reads 0. Labelled by
    # NAME only -- workflow_id/event are unknown for a flow with no runs, and
    # inventing them would churn labels the moment it returns.
    expected_present = workflow_snapshot.get("expected_present")
    if isinstance(expected_present, Mapping) and expected_present:
        lines.append("# TYPE live_overlay_github_workflow_expected_present gauge")
        for workflow_name in sorted(expected_present):
            lines.append(
                "live_overlay_github_workflow_expected_present"
                f'{{workflow="{_escape_label_value(workflow_name)}"}} '
                f"{_prom_numeric_value(expected_present[workflow_name])}"
            )

    # ---- Realtime trading signals (A0 strongest / A1 confirmed / A2 early-warning) ----------
    # Sourced from the realtime engine snapshot via
    # compute._load_signals_snapshot (local file or SIGNALS_SNAPSHOT_URL).
    # Surfaced so Grafana can show which symbols are firing, their
    # score/freshness/technical bias, and how fresh the snapshot is. Per-signal
    # series are labelled (symbol/level/direction/tier) and capped to the
    # strongest signals to bound cardinality.
    signals_snapshot = _trading_signals_snapshot()
    signal_counts = signals_snapshot["counts"]
    if not isinstance(signal_counts, dict):
        signal_counts = {"active": 0, "a0": 0, "a1": 0, "a2": 0, "watched": 0}
    lines.append("# TYPE live_overlay_trading_signals_loaded gauge")
    lines.append(f"live_overlay_trading_signals_loaded {_prom_numeric_value(signals_snapshot['loaded'])}")
    # These are point-in-time gauges: currently-loaded signal counts that rise
    # AND fall. The canonical names are suffix-less to match the Prometheus
    # gauge convention (cf. trading_signals_loaded above). The historical
    # *_total aliases (non-monotonic despite the counter-style suffix) were
    # dropped 2026-07-22: every committed dashboard uses the suffix-less names,
    # and the orphan scan in test_monitoring_metric_alert_coverage now covers
    # the trading_signals family, so unconsumed aliases fail CI.
    _sig_active = _prom_numeric_value(signal_counts['active'])
    lines.append("# TYPE live_overlay_trading_signals_active gauge")
    lines.append(f"live_overlay_trading_signals_active {_sig_active}")
    _sig_a0 = _prom_numeric_value(signal_counts['a0'])
    lines.append("# TYPE live_overlay_trading_signals_a0 gauge")
    lines.append(f"live_overlay_trading_signals_a0 {_sig_a0}")
    _sig_a1 = _prom_numeric_value(signal_counts['a1'])
    lines.append("# TYPE live_overlay_trading_signals_a1 gauge")
    lines.append(f"live_overlay_trading_signals_a1 {_sig_a1}")
    # A2 = early-warning tier (building momentum, not confirmed). Emitted since
    # 2026-07-08 so Grafana can surface all three levels; the producer counts it
    # in a2_count. active already includes A2.
    _sig_a2 = _prom_numeric_value(signal_counts['a2'])
    lines.append("# TYPE live_overlay_trading_signals_a2 gauge")
    lines.append(f"live_overlay_trading_signals_a2 {_sig_a2}")
    _sig_watched = _prom_numeric_value(signal_counts['watched'])
    lines.append("# TYPE live_overlay_trading_signals_watched gauge")
    lines.append(f"live_overlay_trading_signals_watched {_sig_watched}")
    lines.append("# TYPE live_overlay_trading_signals_snapshot_age_known gauge")
    lines.append(
        f"live_overlay_trading_signals_snapshot_age_known {_prom_numeric_value(signals_snapshot['age_known'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_trading_signals_snapshot_age_seconds {signals_snapshot['age_seconds']:.1f}")
    lines.append("# TYPE live_overlay_trading_signals_snapshot_max_age_seconds gauge")
    lines.append(
        "live_overlay_trading_signals_snapshot_max_age_seconds "
        f"{_prom_numeric_value(signals_snapshot['max_age_seconds'])}"
    )
    lines.append("# TYPE live_overlay_trading_signals_snapshot_stale gauge")
    lines.append(f"live_overlay_trading_signals_snapshot_stale {_prom_numeric_value(signals_snapshot['stale'])}")

    signal_rows = signals_snapshot["signals"]
    if isinstance(signal_rows, list) and signal_rows:
        lines.append("# TYPE live_overlay_trading_signal_score gauge")
        for sig in signal_rows:
            lines.append(
                f"live_overlay_trading_signal_score{{{_signal_labels(sig)}}} {_prom_numeric_value(sig.get('score', 0))}"
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
    lines.append(f"live_overlay_tradingview_credential_loaded {_prom_numeric_value(tv_credential['loaded'])}")
    lines.append("# TYPE live_overlay_tradingview_credential_valid gauge")
    lines.append(f"live_overlay_tradingview_credential_valid {_prom_numeric_value(tv_credential['valid'])}")
    lines.append("# TYPE live_overlay_tradingview_credential_age_known gauge")
    lines.append(f"live_overlay_tradingview_credential_age_known {_prom_numeric_value(tv_credential['age_known'])}")
    lines.append("# TYPE live_overlay_tradingview_credential_age_hours gauge")
    lines.append(f"live_overlay_tradingview_credential_age_hours {tv_credential['age_hours']:.3f}")

    # ----- Full credential-health report -----------------------------------
    # Sourced from the same daily credential-health report as the legacy
    # TradingView gauge above, but exposes every probe (TV storage state,
    # GitHub PAT, Databento delivery, FMP, NewsAPI, ...) as labelled metrics.
    credential = _credential_health_snapshot()
    lines.append("# TYPE live_overlay_credential_health_loaded gauge")
    lines.append(f"live_overlay_credential_health_loaded {_prom_numeric_value(credential['loaded'])}")
    lines.append("# TYPE live_overlay_credential_health_overall_valid gauge")
    lines.append(f"live_overlay_credential_health_overall_valid {_prom_numeric_value(credential['overall_valid'])}")
    lines.append("# TYPE live_overlay_credential_health_overall_severity_info gauge")
    overall_severity = _escape_label_value(str(credential["overall_severity"]))
    lines.append(f'live_overlay_credential_health_overall_severity_info{{severity="{overall_severity}"}} 1')
    lines.append("# TYPE live_overlay_credential_health_snapshot_age_known gauge")
    lines.append(
        f"live_overlay_credential_health_snapshot_age_known {_prom_numeric_value(credential['snapshot_age_known'])}"
    )
    lines.append("# TYPE live_overlay_credential_health_snapshot_age_seconds gauge")
    cred_age_value = credential["snapshot_age_seconds"]
    cred_age_float = float(cred_age_value) if isinstance(cred_age_value, (int, float)) else 0.0
    lines.append(f"live_overlay_credential_health_snapshot_age_seconds {cred_age_float:.1f}")

    # Per-probe series are dynamically named (credential_health_<probe>_valid
    # etc.), so a single # TYPE line cannot describe them. Four such headers
    # used to be emitted for names no sample ever carried — inert metadata
    # that the orphan scan then reported as unconsumed metrics. Dropped.
    probe_rows = credential.get("probes") or []
    if probe_rows:
        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            code = _prom_numeric_value(probe["code"])
            lines.append(f"live_overlay_credential_health_{name}_severity_code {code}")

        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            valid = _prom_numeric_value(probe["valid"])
            lines.append(f"live_overlay_credential_health_{name}_valid {valid}")

        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            severity = _escape_label_value(str(probe["severity"]))
            message = _escape_label_value(str(probe["message"])[:200])
            lines.append(f'live_overlay_credential_health_{name}_info{{severity="{severity}",message="{message}"}} 1')

        for probe in probe_rows:
            name = _sanitize_name(str(probe["name"]))
            numeric = probe.get("numeric") or {}
            for value_name, value in numeric.items():
                value_metric = _sanitize_name(str(value_name))
                lines.append(f"live_overlay_credential_health_{name}_{value_metric} {_prom_numeric_value(value)}")

    # ----- Daily experiment (Plan 2.8 family/timeframe scoring) -------------
    experiment = _experiment_snapshot()
    lines.append("# TYPE live_overlay_experiment_loaded gauge")
    lines.append(f"live_overlay_experiment_loaded {_prom_numeric_value(experiment['loaded'])}")
    lines.append("# TYPE live_overlay_experiment_snapshot_age_known gauge")
    lines.append(f"live_overlay_experiment_snapshot_age_known {_prom_numeric_value(experiment['age_known'])}")
    lines.append("# TYPE live_overlay_experiment_snapshot_age_seconds gauge")
    age_value = experiment["age_seconds"]
    age_float = float(age_value) if isinstance(age_value, (int, float)) else 0.0
    lines.append(f"live_overlay_experiment_snapshot_age_seconds {age_float:.1f}")
    # Staleness verdict mirrors the trading-signals pattern: this wires the
    # documented-but-previously-inert OVERLAY_EXPERIMENT_MAX_AGE_SECS knob
    # (config.experiment_max_age_secs, default 96h) to an alertable 0/1 gauge.
    # Unknown age (age_known == 0) reads as not-stale so a fresh daemon does
    # not page before the first snapshot load.
    experiment_max_age = float(config.experiment_max_age_secs())
    experiment_age_known = _prom_numeric_value(experiment["age_known"])
    experiment_stale = (
        1.0
        if experiment_age_known > 0 and age_float > experiment_max_age
        else 0.0
    )
    lines.append("# TYPE live_overlay_experiment_snapshot_max_age_seconds gauge")
    lines.append(f"live_overlay_experiment_snapshot_max_age_seconds {experiment_max_age:.1f}")
    lines.append("# TYPE live_overlay_experiment_snapshot_stale gauge")
    lines.append(f"live_overlay_experiment_snapshot_stale {experiment_stale:.1f}")
    lines.append("# TYPE live_overlay_experiment_files_scanned gauge")
    lines.append(f"live_overlay_experiment_files_scanned {_prom_numeric_value(experiment['files_scanned'])}")

    tf_rows = experiment["tf_rows"]
    if isinstance(tf_rows, list) and tf_rows:
        lines.append("# TYPE live_overlay_experiment_tf_hit_rate gauge")
        for row in tf_rows:
            labels = _experiment_tf_labels(str(row.get("timeframe", "")))
            lines.append(
                f"live_overlay_experiment_tf_hit_rate{{{labels}}} {_prom_numeric_value(row.get('hit_rate', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_tf_n_events gauge")
        for row in tf_rows:
            labels = _experiment_tf_labels(str(row.get("timeframe", "")))
            lines.append(
                f"live_overlay_experiment_tf_n_events{{{labels}}} {_prom_numeric_value(row.get('n_events', 0))}"
            )

    family_rows = experiment["family_rows"]
    if isinstance(family_rows, list) and family_rows:
        lines.append("# TYPE live_overlay_experiment_family_hit_rate gauge")
        for row in family_rows:
            labels = _experiment_family_labels(str(row.get("timeframe", "")), str(row.get("family", "")))
            lines.append(
                f"live_overlay_experiment_family_hit_rate{{{labels}}} {_prom_numeric_value(row.get('hit_rate', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_family_n_events gauge")
        for row in family_rows:
            labels = _experiment_family_labels(str(row.get("timeframe", "")), str(row.get("family", "")))
            lines.append(
                f"live_overlay_experiment_family_n_events{{{labels}}} {_prom_numeric_value(row.get('n_events', 0))}"
            )

    verdicts = experiment["verdicts"]
    if isinstance(verdicts, list) and verdicts:
        lines.append("# TYPE live_overlay_experiment_verdict_status_code gauge")
        for verdict in verdicts:
            labels = _experiment_verdict_labels(str(verdict.get("hypothesis", "")), str(verdict.get("status", "")))
            lines.append(
                f"live_overlay_experiment_verdict_status_code{{{labels}}} "
                f"{_prom_numeric_value(verdict.get('status_code', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_verdict_delta_hr gauge")
        for verdict in verdicts:
            labels = _experiment_verdict_labels(str(verdict.get("hypothesis", "")), str(verdict.get("status", "")))
            lines.append(
                f"live_overlay_experiment_verdict_delta_hr{{{labels}}} "
                f"{_prom_numeric_value(verdict.get('delta_hr', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_verdict_underpowered gauge")
        for verdict in verdicts:
            labels = _experiment_verdict_labels(str(verdict.get("hypothesis", "")), str(verdict.get("status", "")))
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
            labels = _experiment_verdict_labels(str(verdict.get("hypothesis", "")), str(verdict.get("status", "")))
            p_value_lines.append(f"live_overlay_experiment_verdict_p_value{{{labels}}} {_prom_numeric_value(p_value)}")
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
                f"live_overlay_experiment_day_family_hit_rate{{{labels}}} {_prom_numeric_value(row.get('hit_rate', 0))}"
            )
        lines.append("# TYPE live_overlay_experiment_day_family_n_events gauge")
        for row in history_rows:
            labels = _experiment_day_labels(
                str(row.get("run_date", "")),
                str(row.get("timeframe", "")),
                str(row.get("family", "")),
            )
            lines.append(
                f"live_overlay_experiment_day_family_n_events{{{labels}}} {_prom_numeric_value(row.get('n_events', 0))}"
            )

    # --- Railway container resource metrics ---
    railway_snapshot = railway_metrics.snapshot()
    railway_enabled = bool(railway_snapshot.get("enabled"))
    railway_configured = bool(railway_snapshot.get("configured", railway_enabled))
    railway_ok = bool(railway_snapshot.get("ok"))
    # last_success only — see the uptimerobot block above for the rationale.
    railway_last_success_ts = _prom_numeric_value(
        railway_snapshot.get("last_success_fetched_at_unix") or 0.0
    )
    railway_age = _bridge_last_success_age(
        railway_last_success_ts,
        enabled=railway_enabled,
        configured=railway_configured,
        startup_epoch=startup_epoch,
    )

    error = railway_snapshot.get("error")

    _append_bridge_metrics(
        lines,
        bridge="railway_metrics",
        enabled=railway_enabled,
        configured=railway_configured,
        scrape_success=railway_ok,
        last_success_age_seconds=railway_age,
        scrape_duration_seconds=railway_snapshot.get("scrape_duration_seconds"),
        error_code=str(error)[:200] if error else None,
    )

    services = railway_snapshot.get("services") or []
    if services:
        # CPU cores
        lines.append("# TYPE live_overlay_railway_service_cpu_cores gauge")
        for svc in services:
            service_name = _sanitize_name(svc.get("service", "unknown"))
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
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
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
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
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
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
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
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
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
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
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
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
            service_id = _escape_label_value(svc.get("service_id", "unknown"))
            tx_gb = svc.get("network_tx_gb")
            if tx_gb is not None:
                lines.append(
                    f'live_overlay_railway_service_network_tx_gb{{service="{service_name}",service_id="{service_id}"}} '
                    f"{_prom_numeric_value(tx_gb)}"
                )
    # ----- Evidence-freshness (ADR-0023 chain output age) ------------------
    # Serves the freshness of the evidence chain that stayed silently frozen
    # in 2026-06/07: magnitude ledger, data/phase-a-audit branch, paper-fills
    # progress, WSH snapshot. Sourced from the CI-produced snapshot via
    # evidence_freshness_bridge (URL or local fallback). If the producer stops,
    # snapshot_age_seconds keeps growing and the "Evidence snapshot stale"
    # alert fires — the failure mode is self-covering, unlike the silent
    # freeze it replaces.
    lines.extend(_render_evidence_freshness_metrics())

    # Repo↔TradingView Pine-library version drift (#3599/#3603). The
    # `import preuss_steffen/<lib>/<N>` pins silently diverged from the real
    # published TV version for ~4 months — CE10272 on every modern mp.* symbol.
    # These gauges make each library's TV version, each consumer's pin, and any
    # drift visible + alertable; snapshot age keeps the producer honest.
    lines.extend(_render_pine_library_version_metrics())
    lines.extend(_render_tradingview_binding_metrics())

    # Sweep-trap shadow eval (WS4a): Brier-delta + sample accrual toward the
    # promotion decision, from sweep_trap_shadow_bridge. The detector stays in
    # shadow (no score weight); these gauges make the evidence + producer
    # liveness visible instead of buried in a committed JSONL ledger.
    lines.extend(_render_sweep_trap_shadow_metrics())

    # Provider API data-VOLUME (bytes) consumed this month, per REST provider,
    # from the ingest-side usage snapshot. Makes the FMP bandwidth quota (the
    # "90% used" blind spot) visible + alertable; the limit gauge lets the
    # dashboard show a percentage.
    lines.extend(_render_provider_usage_metrics())

    # --- Process-level metrics (CPU, memory, FDs, GC) ---
    lines.extend(_collect_process_metrics(startup_ts, startup_epoch))

    lines.append("")  # trailing newline
    return "\n".join(lines)


def _render_provider_usage_metrics() -> list[str]:
    """Prometheus gauges for per-provider API data-volume consumption."""
    snap = provider_usage_bridge.snapshot()
    lines: list[str] = []

    loaded = _prom_numeric_value(snap.get("loaded", 0.0))
    lines.append("# TYPE live_overlay_provider_usage_loaded gauge")
    lines.append(f"live_overlay_provider_usage_loaded {loaded}")

    age = snap.get("snapshot_age_seconds")
    age_known = 1.0 if isinstance(age, (int, float)) else 0.0
    lines.append("# TYPE live_overlay_provider_usage_snapshot_age_known gauge")
    lines.append(f"live_overlay_provider_usage_snapshot_age_known {age_known}")
    lines.append("# TYPE live_overlay_provider_usage_snapshot_age_seconds gauge")
    lines.append(
        f"live_overlay_provider_usage_snapshot_age_seconds {float(age) if age_known else 0.0:.1f}"
    )

    raw_providers = snap.get("providers")
    providers = dict(raw_providers) if isinstance(raw_providers, dict) else {}
    providers.setdefault("fmp", {})
    lines.append("# TYPE live_overlay_provider_usage_bytes gauge")
    lines.append("# TYPE live_overlay_provider_usage_calls gauge")
    lines.append("# TYPE live_overlay_provider_usage_records gauge")
    # 429 rate-limit hits (current month). The vendors expose no X-RateLimit-*
    # headers, so this month-accumulating gauge — bumped across the ingest/provider
    # clients — is the only "throttled" signal. Alert on increase() (safe across reset).
    lines.append("# TYPE live_overlay_provider_usage_rate_limit_hits gauge")
    for name in sorted(providers):
        vals = providers[name] or {}
        label = _escape_label_value(name)
        lines.append(
            f'live_overlay_provider_usage_bytes{{provider="{label}"}} '
            f"{_prom_numeric_value(vals.get('bytes', 0))}"
        )
        lines.append(
            f'live_overlay_provider_usage_calls{{provider="{label}"}} '
            f"{_prom_numeric_value(vals.get('calls', 0))}"
        )
        lines.append(
            f'live_overlay_provider_usage_records{{provider="{label}"}} '
            f"{_prom_numeric_value(vals.get('records', 0))}"
        )
        lines.append(
            f'live_overlay_provider_usage_rate_limit_hits{{provider="{label}"}} '
            f"{_prom_numeric_value(vals.get('rate_limit_hits', 0))}"
        )

    # The FMP plan's monthly bandwidth quota (bytes) so the dashboard can show a
    # percentage and alert before it is exhausted. Always emitted so the panel
    # never goes blank before the first usage snapshot lands.
    lines.append("# TYPE live_overlay_provider_bandwidth_limit_bytes gauge")
    lines.append(
        'live_overlay_provider_bandwidth_limit_bytes{provider="fmp"} '
        f"{float(config.fmp_monthly_bandwidth_limit_bytes())}"
    )
    return lines


def _render_pine_library_version_metrics() -> list[str]:
    """Prometheus gauges for Repo↔TradingView Pine-library version drift."""
    snap = pine_library_version_bridge.snapshot()
    lines: list[str] = []

    loaded = _prom_numeric_value(snap.get("loaded", 0.0))
    lines.append("# TYPE live_overlay_pine_library_snapshot_loaded gauge")
    lines.append(f"live_overlay_pine_library_snapshot_loaded {loaded}")

    # Age of the snapshot itself (producer heartbeat). Known only once loaded.
    generated_at = _prom_numeric_value(snap.get("generated_at_unix", 0.0))
    snap_age_known = 1.0 if generated_at > 0 else 0.0
    snap_age = max(0.0, time.time() - generated_at) if generated_at > 0 else 0.0
    lines.append("# TYPE live_overlay_pine_library_snapshot_age_known gauge")
    lines.append(f"live_overlay_pine_library_snapshot_age_known {snap_age_known}")
    lines.append("# TYPE live_overlay_pine_library_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_pine_library_snapshot_age_seconds {snap_age:.1f}")

    # Top-level drift rollup — the single series the drift alert watches, plus a
    # count for the dashboard. facade_ok distinguishes "no drift" from "couldn't
    # probe TV this run" (facade_error set) so a probe outage is not read green.
    lines.append("# TYPE live_overlay_pine_library_any_drift gauge")
    lines.append(f"live_overlay_pine_library_any_drift {_prom_numeric_value(snap.get('any_drift', 0.0))}")
    lines.append("# TYPE live_overlay_pine_libraries_drifted gauge")
    lines.append(f"live_overlay_pine_libraries_drifted {_prom_numeric_value(snap.get('libraries_drifted', 0.0))}")
    lines.append("# TYPE live_overlay_pine_libraries_probed gauge")
    lines.append(f"live_overlay_pine_libraries_probed {_prom_numeric_value(snap.get('libraries_probed', 0.0))}")
    facade_ok = 0.0 if str(snap.get("facade_error", "") or "") else 1.0
    lines.append("# TYPE live_overlay_pine_library_facade_ok gauge")
    lines.append(f"live_overlay_pine_library_facade_ok {facade_ok}")

    # Per-library TV version + per-consumer pin/drift. Emitted once regardless
    # of library count so the panel never blanks before the first snapshot.
    lines.append("# TYPE live_overlay_pine_library_tv_version gauge")
    lines.append("# TYPE live_overlay_pine_library_tv_version_known gauge")
    lines.append("# TYPE live_overlay_pine_library_data_age_seconds gauge")
    lines.append("# TYPE live_overlay_pine_library_data_age_known gauge")
    lines.append("# TYPE live_overlay_pine_consumer_pin_version gauge")
    lines.append("# TYPE live_overlay_pine_consumer_drift gauge")
    # ADR-0029: payload volume. Every other gauge here measures metadata about
    # the library — version, ASOF_DATE — so an empty payload under a fresh date
    # reads green. These measure the payload itself.
    lines.append("# TYPE live_overlay_pine_library_payload_known gauge")
    lines.append("# TYPE live_overlay_pine_library_payload_symbols gauge")
    lines.append("# TYPE live_overlay_pine_library_payload_lists gauge")
    lines.append("# TYPE live_overlay_pine_library_payload_universe_size gauge")
    libraries = snap.get("libraries") or []
    for lib in libraries:
        name = _escape_label_value(str(lib.get("name", "") or "unknown"))
        tv_known = _prom_numeric_value(lib.get("tv_version_known", 0.0))
        lines.append(f'live_overlay_pine_library_tv_version_known{{library="{name}"}} {tv_known}')
        data_asof_unix = _prom_numeric_value(lib.get("data_asof_unix", 0.0))
        data_age_known = 1.0 if (
            _prom_numeric_value(lib.get("data_asof_known", 0.0)) >= 1.0 and data_asof_unix > 0
        ) else 0.0
        data_age = max(0.0, time.time() - data_asof_unix) if data_age_known >= 1.0 else 0.0
        lines.append(f'live_overlay_pine_library_data_age_known{{library="{name}"}} {data_age_known}')
        lines.append(f'live_overlay_pine_library_data_age_seconds{{library="{name}"}} {data_age:.1f}')
        # Only emit the version number when it is actually known — an unreachable
        # facade must not report version 0 as if it were the real TV version.
        if tv_known >= 1.0:
            lines.append(
                f'live_overlay_pine_library_tv_version{{library="{name}"}} '
                f"{_prom_numeric_value(lib.get('tv_version', 0.0))}"
            )
        # Payload counts are emitted ONLY when measured. A hand-authored library
        # carries no payload exports, and an unreadable generated one must not
        # report 0 symbols as though it had been measured and found empty.
        payload_known = _prom_numeric_value(lib.get("payload_known", 0.0))
        lines.append(f'live_overlay_pine_library_payload_known{{library="{name}"}} {payload_known}')
        if payload_known >= 1.0:
            lines.append(
                f'live_overlay_pine_library_payload_symbols{{library="{name}"}} '
                f"{_prom_numeric_value(lib.get('payload_universe_symbols', 0.0))}"
            )
            lines.append(
                f'live_overlay_pine_library_payload_lists{{library="{name}"}} '
                f"{_prom_numeric_value(lib.get('payload_list_symbols', 0.0))}"
            )
            lines.append(
                f'live_overlay_pine_library_payload_universe_size{{library="{name}"}} '
                f"{_prom_numeric_value(lib.get('payload_universe_size', 0.0))}"
            )
        for consumer in lib.get("consumers") or []:
            cfile = _escape_label_value(str(consumer.get("file", "") or "unknown"))
            lines.append(
                f'live_overlay_pine_consumer_pin_version{{library="{name}",consumer="{cfile}"}} '
                f"{_prom_numeric_value(consumer.get('pinned_version', 0.0))}"
            )
            lines.append(
                f'live_overlay_pine_consumer_drift{{library="{name}",consumer="{cfile}"}} '
                f"{_prom_numeric_value(consumer.get('drift', 0.0))}"
            )
    return lines


def _render_tradingview_binding_metrics() -> list[str]:
    """Prometheus gauges for measured TradingView input.source dropdown drift."""
    snap = tradingview_binding_bridge.snapshot()
    generated_at = _prom_numeric_value(snap.get("generated_at_unix", 0.0))
    age_known = 1.0 if generated_at > 0 else 0.0
    age = max(0.0, time.time() - generated_at) if generated_at > 0 else 0.0
    lines = [
        "# TYPE live_overlay_tv_binding_snapshot_loaded gauge",
        f"live_overlay_tv_binding_snapshot_loaded {_prom_numeric_value(snap.get('loaded', 0.0))}",
        "# TYPE live_overlay_tv_binding_snapshot_age_known gauge",
        f"live_overlay_tv_binding_snapshot_age_known {age_known}",
        "# TYPE live_overlay_tv_binding_snapshot_age_seconds gauge",
        f"live_overlay_tv_binding_snapshot_age_seconds {age:.1f}",
        "# TYPE live_overlay_tv_binding_drift gauge",
        f"live_overlay_tv_binding_drift {_prom_numeric_value(snap.get('binding_drift', 0.0))}",
        "# TYPE live_overlay_tv_binding_check_known gauge",
        f"live_overlay_tv_binding_check_known {_prom_numeric_value(snap.get('binding_check_known', 0.0))}",
        "# TYPE live_overlay_tv_binding_consumers_expected gauge",
        f"live_overlay_tv_binding_consumers_expected {_prom_numeric_value(snap.get('binding_expected_consumers', 0.0))}",
        "# TYPE live_overlay_tv_binding_consumers_checked gauge",
        f"live_overlay_tv_binding_consumers_checked {_prom_numeric_value(snap.get('binding_checked_consumers', 0.0))}",
        "# TYPE live_overlay_tv_binding_mismatches gauge",
        f"live_overlay_tv_binding_mismatches {_prom_numeric_value(snap.get('mismatches', 0.0))}",
        "# TYPE live_overlay_tv_binding_failed_consumers gauge",
        f"live_overlay_tv_binding_failed_consumers {_prom_numeric_value(snap.get('failed_consumers', 0.0))}",
        "# TYPE live_overlay_tv_bindings_checked gauge",
        f"live_overlay_tv_bindings_checked {_prom_numeric_value(snap.get('checked_bindings', 0.0))}",
        "# TYPE live_overlay_tv_consumer_source_check_known gauge",
        f"live_overlay_tv_consumer_source_check_known {_prom_numeric_value(snap.get('source_check_known', 0.0))}",
        "# TYPE live_overlay_tv_consumer_source_drift gauge",
        f"live_overlay_tv_consumer_source_drift {_prom_numeric_value(snap.get('source_drift', 0.0))}",
        "# TYPE live_overlay_tv_consumer_sources_expected gauge",
        f"live_overlay_tv_consumer_sources_expected {_prom_numeric_value(snap.get('source_expected', 0.0))}",
        "# TYPE live_overlay_tv_consumer_sources_checked gauge",
        f"live_overlay_tv_consumer_sources_checked {_prom_numeric_value(snap.get('source_checked', 0.0))}",
        "# TYPE live_overlay_tv_consumer_sources_drifted gauge",
        f"live_overlay_tv_consumer_sources_drifted {_prom_numeric_value(snap.get('source_drifted', 0.0))}",
        "# TYPE live_overlay_tv_consumer_source_failures gauge",
        f"live_overlay_tv_consumer_source_failures {_prom_numeric_value(snap.get('source_failed_consumers', 0.0))}",
        "# TYPE live_overlay_tv_consumer_binding_mismatches gauge",
        "# TYPE live_overlay_tv_consumer_source_matches gauge",
    ]
    for consumer in snap.get("consumers") or []:
        name = _escape_label_value(str(consumer.get("script_name", "unknown")))
        lines.append(
            f'live_overlay_tv_consumer_binding_mismatches{{consumer="{name}"}} '
            f'{_prom_numeric_value(consumer.get("mismatches", 0.0))}'
        )
    for consumer in snap.get("source_consumers") or []:
        name = _escape_label_value(str(consumer.get("script_name", "unknown")))
        lines.append(
            f'live_overlay_tv_consumer_source_matches{{consumer="{name}"}} '
            f'{_prom_numeric_value(consumer.get("matches", 0.0))}'
        )
    return lines


def _render_evidence_freshness_metrics() -> list[str]:
    """Prometheus gauges for the ADR-0023 evidence-chain output freshness."""
    snap = evidence_freshness_bridge.snapshot()
    lines: list[str] = []

    loaded = _prom_numeric_value(snap.get("loaded", 0.0))
    lines.append("# TYPE live_overlay_evidence_freshness_loaded gauge")
    lines.append(f"live_overlay_evidence_freshness_loaded {loaded}")

    # Age of the snapshot itself (producer heartbeat). Known only once loaded.
    generated_at = _prom_numeric_value(snap.get("generated_at_unix", 0.0))
    snap_age_known = 1.0 if generated_at > 0 else 0.0
    snap_age = max(0.0, time.time() - generated_at) if generated_at > 0 else 0.0
    lines.append("# TYPE live_overlay_evidence_freshness_snapshot_age_known gauge")
    lines.append(f"live_overlay_evidence_freshness_snapshot_age_known {snap_age_known}")
    lines.append("# TYPE live_overlay_evidence_freshness_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_evidence_freshness_snapshot_age_seconds {snap_age:.1f}")

    def _emit_age(metric: str, date_str: str) -> None:
        age = evidence_freshness_bridge.age_seconds_from_date(date_str)
        known = 1.0 if age is not None else 0.0
        lines.append(f"# TYPE {metric}_known gauge")
        lines.append(f"{metric}_known {known}")
        lines.append(f"# TYPE {metric}_seconds gauge")
        lines.append(f"{metric}_seconds {(age if age is not None else 0.0):.1f}")

    ledger = snap.get("ledger") or {}
    _emit_age("live_overlay_evidence_ledger_age", str(ledger.get("newest_date", "")))
    lines.append("# TYPE live_overlay_evidence_ledger_rows gauge")
    lines.append(f"live_overlay_evidence_ledger_rows {_prom_numeric_value(ledger.get('rows', 0))}")
    lines.append("# TYPE live_overlay_evidence_ledger_candidate_pass gauge")
    lines.append(
        "live_overlay_evidence_ledger_candidate_pass "
        f"{_prom_numeric_value(ledger.get('candidate_pass', 0))}"
    )
    # Info metric carries the measurement plane + newest date as labels so the
    # dashboard shows BOS@1D vs BOS@15m without a separate query.
    lines.append("# TYPE live_overlay_evidence_ledger_info gauge")
    lines.append(
        "live_overlay_evidence_ledger_info{"
        f'plane="{_escape_label_value(str(ledger.get("plane", "") or "unknown"))}",'
        f'newest_date="{_escape_label_value(str(ledger.get("newest_date", "") or "none"))}"'
        "} 1"
    )

    audit = snap.get("audit_branch") or {}
    _emit_age("live_overlay_evidence_audit_branch_age", str(audit.get("last_commit_date", "")))

    # §2/§5 progress: per-family usable FamilyEvent samples toward the target
    # (40). This is the REAL distance to a §5 verdict — §5 reads FamilyEvent
    # records, not the C13 paper fills below. Each series is labelled with the
    # family's governance classification so the dashboard can grey out
    # non-operational families (SWEEP proof_of_concept, FVG/OB control).
    samples = snap.get("samples") or {}
    lines.append("# TYPE live_overlay_evidence_samples_target gauge")
    lines.append(f"live_overlay_evidence_samples_target {_prom_numeric_value(samples.get('target', 0))}")
    per_family = samples.get("per_family") or {}
    if per_family:
        lines.append("# TYPE live_overlay_evidence_samples_usable gauge")
        for family, row in sorted(per_family.items()):
            classification = str((row or {}).get("classification", "") or "unknown")
            usable = (row or {}).get("usable", 0)
            lines.append(
                "live_overlay_evidence_samples_usable{"
                f'family="{_escape_label_value(family)}",'
                f'classification="{_escape_label_value(classification)}"'
                f"}} {_prom_numeric_value(usable)}"
            )

    # C13 paper-trading fill activity (operational health — is paper trading
    # filling?). NOT the §5 gate; kept for visibility, distinct from the
    # per-family sample progress above.
    fills = snap.get("fills") or {}
    lines.append("# TYPE live_overlay_evidence_fills_filled_total gauge")
    lines.append(
        f"live_overlay_evidence_fills_filled_total {_prom_numeric_value(fills.get('filled_cumulative', 0))}"
    )
    lines.append("# TYPE live_overlay_evidence_fills_closed_total gauge")
    lines.append(
        f"live_overlay_evidence_fills_closed_total {_prom_numeric_value(fills.get('closed_cumulative', 0))}"
    )
    # Paper submits that placed a bracket but landed no resting leg (all
    # cancelled/rejected, e.g. IB error-110). With filled_total==0 this says
    # "submits are actively dying", not merely "hasn't filled yet" — powers
    # lo-evidence-submit-failed and would have surfaced the 2026-07-08 C8 stall.
    lines.append("# TYPE live_overlay_evidence_fills_submit_failed_total gauge")
    lines.append(
        f"live_overlay_evidence_fills_submit_failed_total "
        f"{_prom_numeric_value(fills.get('submit_failed_cumulative', 0))}"
    )
    lines.append("# TYPE live_overlay_evidence_fills_target gauge")
    lines.append(f"live_overlay_evidence_fills_target {_prom_numeric_value(fills.get('target', 0))}")
    # Age of the newest incubation record: distinguishes "actively submitting
    # orders but nothing fills" (a stalled C8 ladder) from "no trading at all"
    # (intentional pause / holidays). Powers lo-evidence-incubation-fills-stalled.
    _emit_age(
        "live_overlay_evidence_fills_newest_incubation_age",
        str(fills.get("newest_incubation_date", "")),
    )

    # Deploy-hygiene: commits the C13 submit Mac's checkout is behind origin/main
    # on the paper-submit order path (published by run-c13-phase-a.sh). >0 means a
    # merged fix (e.g. #3297's min-tick snap) is sitting undeployed on the box that
    # actually submits — the silent gap that kept the C8 ladder at 0 fills for
    # weeks. _known=0 when the Mac never published, so the alert stays silent
    # rather than falsely green. Powers lo-c13-submitter-stale-checkout.
    submitter = snap.get("submitter") or {}
    lines.append("# TYPE live_overlay_evidence_c13_submit_code_behind_commits gauge")
    lines.append(
        f"live_overlay_evidence_c13_submit_code_behind_commits "
        f"{_prom_numeric_value(submitter.get('submit_code_behind_commits', 0))}"
    )
    lines.append("# TYPE live_overlay_evidence_c13_submit_code_behind_commits_known gauge")
    lines.append(
        f"live_overlay_evidence_c13_submit_code_behind_commits_known "
        f"{_prom_numeric_value(submitter.get('known', 0))}"
    )

    wsh = snap.get("wsh") or {}
    _emit_age("live_overlay_evidence_wsh_age", str(wsh.get("newest_date", "")))
    return lines


def _render_sweep_trap_shadow_metrics() -> list[str]:
    """Prometheus gauges for the sweep-trap shadow evaluation."""
    snap = sweep_trap_shadow_bridge.snapshot()
    lines: list[str] = []

    loaded = _prom_numeric_value(snap.get("loaded", 0.0))
    lines.append("# TYPE live_overlay_sweep_trap_shadow_loaded gauge")
    lines.append(f"live_overlay_sweep_trap_shadow_loaded {loaded}")

    # Producer heartbeat: age of the snapshot itself, known only once loaded.
    # `_stale` is a precomputed 0/1 gauge so the alert threshold isn't the
    # gt-0-inert trap (a bare comparison whose true-value is 0).
    generated_at = _prom_numeric_value(snap.get("generated_at_unix", 0.0))
    age_known = 1.0 if generated_at > 0 else 0.0
    age = max(0.0, time.time() - generated_at) if generated_at > 0 else 0.0
    stale = 1.0 if (age_known and age > config.sweep_trap_shadow_max_age_secs()) else 0.0
    lines.append("# TYPE live_overlay_sweep_trap_shadow_snapshot_age_known gauge")
    lines.append(f"live_overlay_sweep_trap_shadow_snapshot_age_known {age_known}")
    lines.append("# TYPE live_overlay_sweep_trap_shadow_snapshot_age_seconds gauge")
    lines.append(f"live_overlay_sweep_trap_shadow_snapshot_age_seconds {age:.1f}")
    lines.append("# TYPE live_overlay_sweep_trap_shadow_snapshot_stale gauge")
    lines.append(f"live_overlay_sweep_trap_shadow_snapshot_stale {stale}")

    # Evidence: both Brier inputs, their delta (>0 = the score adds skill),
    # tercile lift, sample accrual vs MIN_SHADOW_SAMPLES, and the promotion verdict.
    lines.append("# TYPE live_overlay_sweep_trap_shadow_brier_signal gauge")
    lines.append(
        f"live_overlay_sweep_trap_shadow_brier_signal {_prom_numeric_value(snap.get('brier_signal', 0.0))}"
    )
    lines.append("# TYPE live_overlay_sweep_trap_shadow_brier_baseline gauge")
    lines.append(
        f"live_overlay_sweep_trap_shadow_brier_baseline {_prom_numeric_value(snap.get('brier_baseline', 0.0))}"
    )
    lines.append("# TYPE live_overlay_sweep_trap_shadow_brier_delta gauge")
    lines.append(
        f"live_overlay_sweep_trap_shadow_brier_delta {_prom_numeric_value(snap.get('brier_delta', 0.0))}"
    )
    lines.append("# TYPE live_overlay_sweep_trap_shadow_lift gauge")
    lines.append(f"live_overlay_sweep_trap_shadow_lift {_prom_numeric_value(snap.get('lift', 0.0))}")
    lines.append("# TYPE live_overlay_sweep_trap_shadow_sample_count gauge")
    lines.append(
        f"live_overlay_sweep_trap_shadow_sample_count {_prom_numeric_value(snap.get('n_samples', 0.0))}"
    )
    lines.append("# TYPE live_overlay_sweep_trap_shadow_min_samples gauge")
    lines.append(
        f"live_overlay_sweep_trap_shadow_min_samples {_prom_numeric_value(snap.get('min_samples', 0.0))}"
    )
    verdict = _escape_label_value(str(snap.get("verdict", "") or "unknown"))
    lines.append("# TYPE live_overlay_sweep_trap_shadow_verdict_code gauge")
    lines.append(
        f'live_overlay_sweep_trap_shadow_verdict_code{{verdict="{verdict}"}} '
        f"{_prom_numeric_value(snap.get('verdict_code', 0.0))}"
    )

    # A presentation-only info metric powers the single latest-evidence table in
    # Grafana. It is deliberately NOT low-cardinality: the snapshot date and the
    # formatted value ride in labels, so a fresh series set churns in whenever the
    # (roughly daily) snapshot changes — active series stay bounded at len(rows),
    # stale ones age out. We accept that churn to keep the gate wording in Python
    # instead of recreating it in PromQL. The numeric gauges above stay the source
    # for any future alerting/recording rules; nothing alerts on them yet.
    date = _escape_label_value(str(snap.get("date", "") or "unknown"))
    n_samples = _prom_numeric_value(snap.get("n_samples", 0.0))
    min_samples = float(snap.get("min_samples", 0.0) or 0.0)
    brier_signal = float(snap.get("brier_signal", 0.0) or 0.0)
    brier_baseline = float(snap.get("brier_baseline", 0.0) or 0.0)
    brier_delta = float(snap.get("brier_delta", 0.0) or 0.0)
    lift = float(snap.get("lift", 0.0) or 0.0)
    verdict_name = str(snap.get("verdict", "") or "INCONCLUSIVE")

    # Absent snapshot / too-few samples: don't assert pass/fail on unknown data;
    # `have_terciles` mirrors the evaluator's n>=6 floor for a real lift value.
    na = "—"
    have_snapshot = loaded == 1.0
    samples_known = math.isfinite(n_samples)
    have_data = have_snapshot and samples_known and n_samples > 0
    have_terciles = have_data and n_samples >= 6
    samples_assessment = (
        "Sample floor met"
        if min_samples > 0 and n_samples >= min_samples
        else "Sample floor not met"
    ) if have_snapshot and samples_known else na
    # Compute the data-derived assessments only when there is data (and, for
    # lift, enough samples for terciles); otherwise they stay "—". This keeps
    # the have_data/have_terciles test in one place rather than at every use.
    if have_data:
        baseline_assessment = (
            "better than signal" if brier_baseline < brier_signal else "not better than signal"
        )
        delta_assessment = "Gate passed" if brier_delta > 0 else "Gate failed"
    else:
        baseline_assessment = delta_assessment = na
    verdict_assessment = (
        {"PROMOTABLE": "promotable", "SHADOW": "not promotable"}.get(
            verdict_name, "no decision possible"
        )
        if have_snapshot
        else na
    )
    lift_assessment = ("positive" if lift > 0 else "not positive") if have_terciles else na
    # (idx, metric, value, assessment) — idx is zero-padded so the dashboard's
    # lexicographic sortBy keeps numeric order; it pins the display order and is
    # not shown as a column.
    rows = (
        (0, "Valid samples", _format_int_grouped(int(n_samples)) if have_snapshot and samples_known else na, samples_assessment),
        (1, "Brier Signal", f"{brier_signal:.6f}" if have_data else na, na),
        (2, "Brier Baseline", f"{brier_baseline:.6f}" if have_data else na, baseline_assessment),
        (3, "Brier Delta", f"{brier_delta:+.6f}" if have_data else na, delta_assessment),
        (4, "Tercile Lift", f"{lift:+.6f}" if have_terciles else na, lift_assessment),
        (5, "Verdict", verdict_name if have_snapshot else na, verdict_assessment),
    )
    lines.append("# TYPE live_overlay_sweep_trap_shadow_evidence_info gauge")
    for idx, metric_name, value, assessment in rows:
        labels = (
            f'date="{date}",idx="{idx:02d}",metric="{_escape_label_value(metric_name)}",'
            f'metric_value="{_escape_label_value(value)}",'
            f'assessment="{_escape_label_value(assessment)}"'
        )
        lines.append(f"live_overlay_sweep_trap_shadow_evidence_info{{{labels}}} 1")

    return lines
