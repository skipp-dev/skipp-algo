"""Provider API-usage recorder — bytes / records / calls for REST ingest clients.

Why this exists
---------------
REST data providers (FMP first, but also Benzinga and Unusual Whales) meter a
monthly **data volume**, not just a call count — an FMP "you've used 90% of your
volume" email was the first and only signal we had, because nothing in the stack
measured provider consumption. The FMP (ingest_fmp) and Benzinga/Massive
(_bz_http) clients record response size here; NOTE: Unusual Whales, FMP-filings,
and FMP-political ingest through their own clients and are NOT yet recorded (a
metering blind spot). The item-count (``records``) field is not currently
populated by any caller — it stays 0. At run end the totals are flushed into a
monthly snapshot that the live-overlay daemon surfaces as Prometheus gauges.

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


@dataclass
class ProviderUsage:
    """Thread-safe in-memory accumulator of per-provider API usage for one run."""

    _totals: dict[str, dict[str, float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, provider: str, *, response_bytes: int = 0, records: int = 0) -> None:
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
            slot = self._totals.setdefault(name, {"calls": 0.0, "bytes": 0.0, "records": 0.0})
            slot["calls"] += 1
            slot["bytes"] += rb
            slot["records"] += rec

    def snapshot(self) -> dict[str, dict[str, float]]:
        with self._lock:
            return {p: dict(v) for p, v in self._totals.items()}

    def reset(self) -> None:
        with self._lock:
            self._totals.clear()

    def flush(self, path: str | Path, *, month: str, now_iso: str) -> bool:
        """Merge this run's deltas into the monthly snapshot at ``path``.

        ``month`` is the current ``YYYY-MM``; ``now_iso`` the flush timestamp
        (both injected so callers stay testable and the workflow sandbox's
        clock restrictions never apply). Returns ``True`` if anything was
        written. Fail-soft: a read/write error is logged, not raised.
        """
        deltas = self.snapshot()
        if not deltas:
            return False
        try:
            from scripts.smc_atomic_write import atomic_write_json

            target = Path(path)
            existing = _load(target)
            months: dict[str, Any] = dict(existing.get("months") or {})
            month_slot: dict[str, Any] = dict(months.get(month) or {})
            for provider, d in deltas.items():
                cur = dict(month_slot.get(provider) or {"calls": 0, "bytes": 0, "records": 0})
                cur["calls"] = cur.get("calls", 0) + int(d["calls"])
                cur["bytes"] = cur.get("bytes", 0) + int(d["bytes"])
                cur["records"] = cur.get("records", 0) + int(d["records"])
                month_slot[provider] = cur
            months[month] = month_slot
            # Cap to the newest _MAX_MONTHS months (lexical sort works on YYYY-MM).
            for stale in sorted(months)[:-_MAX_MONTHS]:
                months.pop(stale, None)
            payload = {"updated_at": now_iso, "current_month": month, "months": months}
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


def record(provider: str, *, response_bytes: int = 0, records: int = 0) -> None:
    """Record usage on the process-wide recorder (see :meth:`ProviderUsage.record`)."""
    _RECORDER.record(provider, response_bytes=response_bytes, records=records)


def snapshot() -> dict[str, dict[str, float]]:
    return _RECORDER.snapshot()


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
