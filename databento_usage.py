"""Low-cardinality, fail-soft Databento usage and value telemetry."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_VERSION = "databento-usage/v1"
_OPTIONAL_COUNTERS = ("records", "bytes", "availability_lag_seconds")


def _series_key(dataset: str, schema: str, mode: str, consumer: str) -> str:
    return "|".join(
        str(value or "unknown").strip().lower()
        for value in (dataset, schema, mode, consumer)
    )


def _empty_slot(dataset: str, schema: str, mode: str, consumer: str) -> dict[str, Any]:
    return {
        "dataset": str(dataset).strip().upper() or "UNKNOWN",
        "schema": str(schema).strip().lower() or "unknown",
        "mode": str(mode).strip().lower() or "unknown",
        "consumer": str(consumer).strip().lower() or "unknown",
        "external_requests": 0,
        "subscriptions": 0,
        "symbols_requested": 0,
        "records": None,
        "bytes": None,
        "latency_ms_total": 0.0,
        "latency_samples": 0,
        "availability_lag_seconds": None,
        "cache_hits": 0,
        "cache_misses": 0,
        "errors": 0,
        "reconnects": 0,
        "gaps": 0,
        "dropped_records": 0,
        "unknown_instruments": 0,
        "candidates": 0,
        "downstream_reads": 0,
    }


@dataclass
class DatabentoUsageRecorder:
    """Thread-safe accumulator keyed only by dataset/schema/mode/consumer."""

    _series: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(
        self,
        *,
        dataset: str,
        schema: str,
        mode: str,
        consumer: str,
        external_requests: int = 0,
        subscriptions: int = 0,
        symbols_requested: int = 0,
        records: int | None = None,
        response_bytes: int | None = None,
        latency_ms: float | None = None,
        availability_lag_seconds: float | None = None,
        cache_hits: int = 0,
        cache_misses: int = 0,
        errors: int = 0,
        reconnects: int = 0,
        gaps: int = 0,
        dropped_records: int = 0,
        unknown_instruments: int = 0,
        candidates: int = 0,
        downstream_reads: int = 0,
    ) -> None:
        """Add one event. Unknown optional measurements remain JSON null."""
        key = _series_key(dataset, schema, mode, consumer)
        with self._lock:
            slot = self._series.setdefault(
                key, _empty_slot(dataset, schema, mode, consumer)
            )
            increments = {
                "external_requests": external_requests,
                "subscriptions": subscriptions,
                "symbols_requested": symbols_requested,
                "cache_hits": cache_hits,
                "cache_misses": cache_misses,
                "errors": errors,
                "reconnects": reconnects,
                "gaps": gaps,
                "dropped_records": dropped_records,
                "unknown_instruments": unknown_instruments,
                "candidates": candidates,
                "downstream_reads": downstream_reads,
            }
            for name, value in increments.items():
                try:
                    slot[name] += max(0, int(value))
                except (TypeError, ValueError):
                    continue
            for name, value in (
                ("records", records),
                ("bytes", response_bytes),
                ("availability_lag_seconds", availability_lag_seconds),
            ):
                if value is not None:
                    numeric = max(0.0, float(value))
                    slot[name] = numeric + float(slot[name] or 0.0)
            if latency_ms is not None:
                slot["latency_ms_total"] += max(0.0, float(latency_ms))
                slot["latency_samples"] += 1

    def snapshot(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(value) for key, value in self._series.items()}

    def reset(self) -> None:
        with self._lock:
            self._series.clear()

    def flush(self, path: str | Path, *, month: str, now_iso: str) -> bool:
        target = Path(path)
        with self._lock:
            if not self._series:
                return False
            deltas = {key: dict(value) for key, value in self._series.items()}
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with _file_lock(target.with_suffix(target.suffix + ".lock")):
                    existing = _load(target)
                    months = dict(existing.get("months") or {})
                    month_slot = dict(months.get(month) or {})
                    series = dict(month_slot.get("series") or {})
                    for key, delta in deltas.items():
                        current = dict(
                            series.get(key)
                            or _empty_slot(
                                delta["dataset"],
                                delta["schema"],
                                delta["mode"],
                                delta["consumer"],
                            )
                        )
                        for name, value in delta.items():
                            if name in {"dataset", "schema", "mode", "consumer"}:
                                current[name] = value
                            elif name in _OPTIONAL_COUNTERS:
                                if value is not None:
                                    current[name] = float(current.get(name) or 0.0) + float(value)
                            else:
                                current[name] = float(current.get(name) or 0.0) + float(value)
                        series[key] = current
                    months[month] = {"series": series}
                    for stale in sorted(months)[:-3]:
                        months.pop(stale, None)
                    payload = {
                        "version": _VERSION,
                        "updated_at": now_iso,
                        "current_month": month,
                        "months": months,
                    }
                    from scripts.smc_atomic_write import atomic_write_json

                    atomic_write_json(payload, target, sort_keys=True)
                self._series.clear()
                return True
            except Exception as exc:
                logger.warning("Databento usage flush failed for %s: %s", target, exc)
                return False


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:  # pragma: no cover - Windows has atomic replace but no fcntl
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:  # pragma: no cover
            pass
        handle.close()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("Databento usage snapshot unreadable (%s): %s", path, exc)
        return {}


_RECORDER = DatabentoUsageRecorder()


def record(**kwargs: Any) -> None:
    """Fail-soft process-wide telemetry entry point."""
    try:
        _RECORDER.record(**kwargs)
    except Exception:
        logger.debug("Databento usage event skipped", exc_info=True)


def snapshot() -> dict[str, dict[str, Any]]:
    return _RECORDER.snapshot()


def reset() -> None:
    _RECORDER.reset()


def snapshot_path() -> Path:
    return Path(
        os.environ.get(
            "DATABENTO_USAGE_SNAPSHOT_PATH",
            "artifacts/monitoring/databento_usage.json",
        )
    )


def flush(path: str | Path | None = None, *, now: datetime | None = None) -> bool:
    if path is None and "pytest" in sys.modules:
        return False
    instant = now or datetime.now(UTC)
    return _RECORDER.flush(
        path or snapshot_path(),
        month=instant.strftime("%Y-%m"),
        now_iso=instant.isoformat(),
    )
