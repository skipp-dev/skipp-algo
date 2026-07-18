"""Provider API-usage recorder — bytes / records / calls for REST ingest clients.

Why this exists
---------------
REST data providers (FMP first, but also Benzinga and Unusual Whales) meter a
monthly **data volume**, not just a call count — an FMP "you've used 90% of your
volume" email was the first and only signal we had, because nothing in the stack
measured provider consumption. The FMP (ingest_fmp) and Benzinga/Massive
(_bz_http) clients record response size here; endpoint/consumer dimensions
additionally record parsed rows, cache hits/misses, latency, errors, and rate
limits. Some legacy FMP-filings/political and UW paths remain outside this
instrumentation. At run end the totals are flushed into a monthly snapshot
that the live-overlay daemon surfaces as Prometheus gauges.

Accumulation model
------------------
Ingest is a batch/cron job, NOT a long-running process — each invocation is a
fresh Python process. So usage must ACCUMULATE across runs on disk:
:func:`ProviderUsage.flush` reads the current month's snapshot, adds this run's
in-memory deltas, and atomically rewrites it. A new calendar month starts a
fresh counter (keyed ``YYYY-MM``); the file keeps the last few months so a
month boundary never loses the just-closed month before the daemon reads it.

The recorder is deliberately fail-soft: instrumentation must never break an
ingest. Callers use :func:`record` inside a broad ``try`` and a bad path or a
disk error at flush time is swallowed with a warning.
"""
from __future__ import annotations

import atexit
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Keep this many trailing months in the snapshot (current + a little history so
# the daemon can still read last month right after a boundary). Small on purpose.
_MAX_MONTHS = 3


def _empty_slot() -> dict[str, float]:
    """A fresh per-provider counter slot (calls / bytes / records / 429 hits)."""
    return {"calls": 0.0, "bytes": 0.0, "records": 0.0, "rate_limit_hits": 0.0}


def _empty_dimension_slot() -> dict[str, float]:
    """Detailed per-endpoint/consumer counters.

    The provider totals above are intentionally kept backwards compatible with
    the existing dashboard contract.  Detailed counters live in a separate
    top-level snapshot section so adding dimensions cannot break consumers that
    compare the legacy provider slots exactly.
    """
    return {
        "calls": 0.0,
        "bytes": 0.0,
        "records": 0.0,
        "rate_limit_hits": 0.0,
        "errors": 0.0,
        "cache_hits": 0.0,
        "cache_misses": 0.0,
        "latency_ms_total": 0.0,
    }


@dataclass
class ProviderUsage:
    """Thread-safe in-memory accumulator of per-provider API usage for one run."""

    _totals: dict[str, dict[str, float]] = field(default_factory=dict)
    _dimensions: dict[str, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        provider: str,
        *,
        response_bytes: int = 0,
        records: int = 0,
        endpoint: str = "",
        consumer: str = "",
        latency_ms: float = 0.0,
    ) -> None:
        """Record one API call's payload size and item count for ``provider``.

        ``response_bytes`` is the raw response body length (the metered volume);
        ``records`` is how many items that call yielded (useful context). Never
        raises — a bad provider name or negative value is coerced/ignored.
        """
        name = str(provider or "unknown").strip().lower() or "unknown"
        try:
            rb = max(0, int(response_bytes))
            rec = max(0, int(records))
        except (TypeError, ValueError):
            return
        with self._lock:
            slot = self._totals.setdefault(name, _empty_slot())
            slot["calls"] += 1
            slot["bytes"] += rb
            slot["records"] += rec
            if endpoint or consumer or latency_ms:
                self._record_dimension_locked(
                    name,
                    endpoint=endpoint,
                    consumer=consumer,
                    response_bytes=rb,
                    records=rec,
                    latency_ms=latency_ms,
                    count_call=True,
                )

    def record_rate_limit_hit(self, provider: str, *, endpoint: str = "", consumer: str = "") -> None:
        """Record one HTTP-429 (rate-limit) hit for ``provider``.

        Distinct from :meth:`record`, which only counts SUCCESSFUL calls: a 429
        never reaches the success path, so its bytes/calls are never recorded.
        This is the only "we are being throttled" signal available — the vendors
        (FMP, Massive/Benzinga) send no ``X-RateLimit-*`` headers (verified
        2026-07-11). Never raises.
        """
        name = str(provider or "unknown").strip().lower() or "unknown"
        with self._lock:
            slot = self._totals.setdefault(name, _empty_slot())
            slot["rate_limit_hits"] = slot.get("rate_limit_hits", 0.0) + 1
            if endpoint or consumer:
                self._record_dimension_locked(name, endpoint=endpoint, consumer=consumer, rate_limit_hits=1, count_call=False)

    def record_cache_event(self, provider: str, *, endpoint: str = "", consumer: str = "", hit: bool) -> None:
        """Record a shared-cache hit/miss without counting a provider call."""
        name = str(provider or "unknown").strip().lower() or "unknown"
        with self._lock:
            if endpoint or consumer:
                self._record_dimension_locked(
                    name,
                    endpoint=endpoint,
                    consumer=consumer,
                    cache_hits=1 if hit else 0,
                    cache_misses=0 if hit else 1,
                    count_call=False,
                )

    def record_records(self, provider: str, records: int, *, endpoint: str = "", consumer: str = "") -> None:
        """Add parsed record count after a response has been decoded.

        HTTP instrumentation knows the byte volume but not the number of
        records until the adapter parses the body.  This method updates the
        legacy aggregate and detailed dimensions without inventing another
        API call.
        """
        name = str(provider or "unknown").strip().lower() or "unknown"
        try:
            count = max(0, int(records))
        except (TypeError, ValueError):
            return
        with self._lock:
            slot = self._totals.setdefault(name, _empty_slot())
            slot["records"] += count
            if endpoint or consumer:
                self._record_dimension_locked(name, endpoint=endpoint, consumer=consumer, records=count, count_call=False)

    def record_error(self, provider: str, *, endpoint: str = "", consumer: str = "") -> None:
        """Record a failed provider request in detailed telemetry."""
        name = str(provider or "unknown").strip().lower() or "unknown"
        with self._lock:
            if endpoint or consumer:
                self._record_dimension_locked(name, endpoint=endpoint, consumer=consumer, errors=1, count_call=False)

    def _record_dimension_locked(
        self,
        provider: str,
        *,
        endpoint: str = "",
        consumer: str = "",
        response_bytes: int = 0,
        records: int = 0,
        rate_limit_hits: int = 0,
        errors: int = 0,
        cache_hits: int = 0,
        cache_misses: int = 0,
        latency_ms: float = 0.0,
        count_call: bool = False,
    ) -> None:
        endpoint_name = str(endpoint or "unknown").strip().lower() or "unknown"
        consumer_name = str(consumer or "unknown").strip().lower() or "unknown"
        key = f"{provider}|{endpoint_name}|{consumer_name}"
        slot = self._dimensions.setdefault(key, _empty_dimension_slot())
        if count_call:
            slot["calls"] += 1
        slot["bytes"] += max(0, int(response_bytes))
        slot["records"] += max(0, int(records))
        slot["rate_limit_hits"] += max(0, int(rate_limit_hits))
        slot["errors"] += max(0, int(errors))
        slot["cache_hits"] += max(0, int(cache_hits))
        slot["cache_misses"] += max(0, int(cache_misses))
        try:
            numeric_latency = float(latency_ms)
        except (TypeError, ValueError):
            numeric_latency = 0.0
        if numeric_latency >= 0:
            slot["latency_ms_total"] += numeric_latency

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {p: dict(v) for p, v in self._totals.items()}

    def detailed_snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {key: dict(value) for key, value in self._dimensions.items()}

    def reset(self) -> None:
        with self._lock:
            self._totals.clear()
            self._dimensions.clear()

    def flush(self, path: str | Path, *, month: str, now_iso: str) -> bool:
        """Merge this run's deltas into the monthly snapshot at ``path``.

        ``month`` is the current ``YYYY-MM``; ``now_iso`` the flush timestamp
        (both injected so callers stay testable and the workflow sandbox's
        clock restrictions never apply). Returns ``True`` if anything was
        written. Fail-soft: a read/write error is logged, not raised.
        """
        deltas = self.snapshot()
        dimension_deltas = self.detailed_snapshot()
        if not deltas and not dimension_deltas:
            return False
        try:
            from scripts.smc_atomic_write import atomic_write_json

            target = Path(path)
            existing = _load(target)
            months: dict[str, Any] = dict(existing.get("months") or {})
            month_slot: dict[str, Any] = dict(months.get(month) or {})
            for provider, d in deltas.items():
                cur = dict(month_slot.get(provider) or {"calls": 0, "bytes": 0, "records": 0, "rate_limit_hits": 0})
                cur["calls"] = cur.get("calls", 0) + int(d.get("calls", 0))
                cur["bytes"] = cur.get("bytes", 0) + int(d.get("bytes", 0))
                cur["records"] = cur.get("records", 0) + int(d.get("records", 0))
                cur["rate_limit_hits"] = cur.get("rate_limit_hits", 0) + int(d.get("rate_limit_hits", 0))
                month_slot[provider] = cur
            months[month] = month_slot
            # Cap to the newest _MAX_MONTHS months (lexical sort works on YYYY-MM).
            for stale in sorted(months)[:-_MAX_MONTHS]:
                months.pop(stale, None)
            payload = {"updated_at": now_iso, "current_month": month, "months": months}
            existing_dimensions = dict(existing.get("dimensions") or {})
            if dimension_deltas:
                month_dimensions = dict(existing_dimensions.get(month) or {})
                for key, delta in dimension_deltas.items():
                    cur = dict(month_dimensions.get(key) or _empty_dimension_slot())
                    for field_name in _empty_dimension_slot():
                        increment = (
                            float(delta.get(field_name, 0))
                            if field_name == "latency_ms_total"
                            else int(delta.get(field_name, 0))
                        )
                        cur[field_name] = cur.get(field_name, 0) + increment
                    month_dimensions[key] = cur
                existing_dimensions[month] = month_dimensions
                for stale in sorted(existing_dimensions)[:-_MAX_MONTHS]:
                    existing_dimensions.pop(stale, None)
            if existing_dimensions:
                payload["dimensions"] = existing_dimensions
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(payload, target, sort_keys=True)
            self.reset()
            return True
        except Exception as exc:  # fail-soft: monitoring must never break ingest
            logger.warning("provider-usage flush failed for %s: %s", path, exc)
            return False


def _load(path: Path) -> dict[str, Any]:
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("provider-usage snapshot unreadable (%s); starting fresh: %s", path, exc)
        return {}


# Process-wide singleton so ingest HTTP layers can record without threading a
# recorder through every call site.
_RECORDER = ProviderUsage()


def record(
    provider: str,
    *,
    response_bytes: int = 0,
    records: int = 0,
    endpoint: str = "",
    consumer: str = "",
    latency_ms: float = 0.0,
) -> None:
    """Record usage on the process-wide recorder (see :meth:`ProviderUsage.record`)."""
    _RECORDER.record(
        provider,
        response_bytes=response_bytes,
        records=records,
        endpoint=endpoint,
        consumer=consumer,
        latency_ms=latency_ms,
    )


def record_rate_limit_hit(provider: str, *, endpoint: str = "", consumer: str = "") -> None:
    """Record a 429 on the process-wide recorder (see :meth:`ProviderUsage.record_rate_limit_hit`)."""
    _RECORDER.record_rate_limit_hit(provider, endpoint=endpoint, consumer=consumer)


def record_cache_event(provider: str, *, endpoint: str = "", consumer: str = "", hit: bool) -> None:
    """Record a shared-cache hit/miss without incrementing API calls."""
    _RECORDER.record_cache_event(provider, endpoint=endpoint, consumer=consumer, hit=hit)


def record_records(provider: str, records: int, *, endpoint: str = "", consumer: str = "") -> None:
    _RECORDER.record_records(provider, records, endpoint=endpoint, consumer=consumer)


def record_error(provider: str, *, endpoint: str = "", consumer: str = "") -> None:
    _RECORDER.record_error(provider, endpoint=endpoint, consumer=consumer)


def snapshot() -> dict[str, dict[str, float]]:
    return _RECORDER.snapshot()


def detailed_snapshot() -> dict[str, dict[str, float]]:
    return _RECORDER.detailed_snapshot()


def reset() -> None:
    _RECORDER.reset()


def flush(path: str | Path, *, month: str, now_iso: str) -> bool:
    return _RECORDER.flush(path, month=month, now_iso=now_iso)


def snapshot_path() -> Path:
    """Where the monthly usage snapshot is written (env ``PROVIDER_USAGE_SNAPSHOT_PATH``).

    The daily open-prep workflow commits this file so the live-overlay daemon
    can fetch and surface it (same transport as credential_health.json).
    """
    import os

    return Path(os.environ.get("PROVIDER_USAGE_SNAPSHOT_PATH", "artifacts/monitoring/provider_usage.json"))


def _flush_at_exit() -> None:
    """atexit hook: persist this process's accumulated usage on the way out.

    Ingest is a batch/cron process, so an atexit flush is robust to however the
    run was launched. Registered once at import (below); a no-op when nothing
    was recorded, so importing this module in tests never writes a file.
    """
    try:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        _RECORDER.flush(snapshot_path(), month=now.strftime("%Y-%m"), now_iso=now.isoformat())
    except Exception as exc:  # fail-soft
        logger.debug("provider-usage atexit flush skipped: %s", exc)


# Register the flush once, at import time. The HTTP layers import this module
# lazily on their first recorded call, which arms the flush for that process.
atexit.register(_flush_at_exit)
