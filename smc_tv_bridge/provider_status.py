"""Lightweight provider health / SLA tracking for adapter-backed services.

Tracks per-provider:
  - availability  (up / degraded / down)
  - call latency  (rolling window)
  - recent failure counts
  - degraded-mode reason

Thread-safe: all mutations go through a ``threading.Lock``.

Usage::

    from smc_tv_bridge.provider_status import ProviderTracker, ProviderStatus

    tracker = ProviderTracker()
    with tracker.track("fmp_candles"):
        candles = provider.fetch_candles(...)

    status = tracker.status("fmp_candles")
    print(status.availability, status.avg_latency_ms, status.reason)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Generator

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_LATENCY_WINDOW = 50  # rolling latency samples to keep
_FAILURE_WINDOW = 20  # recent outcomes to judge availability
_DEGRADED_FAILURE_RATIO = 0.3  # ≥30% failures → degraded
_DOWN_FAILURE_RATIO = 0.8  # ≥80% failures → down
_DOWN_CONSECUTIVE = 5  # 5+ consecutive failures → down


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProviderStatus:
    """Immutable snapshot of a provider's health state."""

    name: str
    availability: str  # "up" | "degraded" | "down" | "unknown"
    reason: str  # human-readable reason for current state
    total_calls: int
    total_failures: int
    consecutive_failures: int
    avg_latency_ms: float  # rolling average; 0.0 if no data
    p95_latency_ms: float  # p95 from rolling window; 0.0 if no data
    last_success_ts: float  # epoch; 0.0 if never succeeded
    last_failure_ts: float  # epoch; 0.0 if never failed
    last_error: str  # repr of last exception; "" if clean


class _ProviderState:
    """Mutable internal state for one provider.  Not exposed directly."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.total_calls = 0
        self.total_failures = 0
        self.consecutive_failures = 0
        self.last_success_ts: float = 0.0
        self.last_failure_ts: float = 0.0
        self.last_error: str = ""
        self._latencies: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        self._outcomes: deque[bool] = deque(maxlen=_FAILURE_WINDOW)  # True=ok

    # ── Mutations ───────────────────────────────────────────────────

    def record_success(self, latency_s: float) -> None:
        self.total_calls += 1
        self.consecutive_failures = 0
        self.last_success_ts = time.time()
        self._latencies.append(latency_s * 1000.0)
        self._outcomes.append(True)

    def record_failure(self, latency_s: float, error: Exception | str) -> None:
        self.total_calls += 1
        self.total_failures += 1
        self.consecutive_failures += 1
        self.last_failure_ts = time.time()
        self.last_error = str(error)[:300]
        self._latencies.append(latency_s * 1000.0)
        self._outcomes.append(False)

    # ── Derived metrics ─────────────────────────────────────────────

    def _avg_latency(self) -> float:
        if not self._latencies:
            return 0.0
        return sum(self._latencies) / len(self._latencies)

    def _p95_latency(self) -> float:
        if not self._latencies:
            return 0.0
        s = sorted(self._latencies)
        idx = int(len(s) * 0.95)
        return s[min(idx, len(s) - 1)]

    def _failure_ratio(self) -> float:
        if not self._outcomes:
            return 0.0
        return 1.0 - (sum(self._outcomes) / len(self._outcomes))

    # ── Availability classification ─────────────────────────────────

    def availability_and_reason(self) -> tuple[str, str]:
        if self.total_calls == 0:
            return "unknown", "no calls recorded"

        if self.consecutive_failures >= _DOWN_CONSECUTIVE:
            return "down", f"{self.consecutive_failures} consecutive failures"

        ratio = self._failure_ratio()
        if ratio >= _DOWN_FAILURE_RATIO:
            return "down", f"{ratio:.0%} failure rate in last {len(self._outcomes)} calls"

        if ratio >= _DEGRADED_FAILURE_RATIO:
            return "degraded", f"{ratio:.0%} failure rate in last {len(self._outcomes)} calls"

        if self.consecutive_failures > 0:
            return "degraded", f"{self.consecutive_failures} recent failure(s): {self.last_error}"

        return "up", "healthy"

    # ── Snapshot ────────────────────────────────────────────────────

    def snapshot(self) -> ProviderStatus:
        avail, reason = self.availability_and_reason()
        return ProviderStatus(
            name=self.name,
            availability=avail,
            reason=reason,
            total_calls=self.total_calls,
            total_failures=self.total_failures,
            consecutive_failures=self.consecutive_failures,
            avg_latency_ms=round(self._avg_latency(), 2),
            p95_latency_ms=round(self._p95_latency(), 2),
            last_success_ts=self.last_success_ts,
            last_failure_ts=self.last_failure_ts,
            last_error=self.last_error,
        )


# ── Tracker (top-level API) ────────────────────────────────────────────────

class ProviderTracker:
    """Thread-safe registry that tracks health for multiple named providers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._providers: dict[str, _ProviderState] = {}

    def _get_or_create(self, name: str) -> _ProviderState:
        if name not in self._providers:
            self._providers[name] = _ProviderState(name)
        return self._providers[name]

    # ── Context-manager instrumentation ─────────────────────────────

    class _TrackContext:
        """Context manager returned by ``ProviderTracker.track()``."""

        def __init__(self, tracker: ProviderTracker, name: str) -> None:
            self._tracker = tracker
            self._name = name
            self._t0: float = 0.0

        def __enter__(self) -> _TrackContext:
            self._t0 = time.monotonic()
            return self

        def __exit__(self, exc_type: type | None, exc_val: BaseException | None, tb: Any) -> None:
            elapsed = time.monotonic() - self._t0
            with self._tracker._lock:
                state = self._tracker._get_or_create(self._name)
                if exc_val is not None:
                    state.record_failure(elapsed, exc_val)
                else:
                    state.record_success(elapsed)
            return None  # don't suppress exceptions

    def track(self, name: str) -> _TrackContext:
        """Return a context manager that records success/failure + latency.

        Usage::

            with tracker.track("fmp_candles"):
                result = provider.fetch_candles(...)
        """
        return self._TrackContext(self, name)

    # ── Manual recording ────────────────────────────────────────────

    def record_success(self, name: str, latency_s: float = 0.0) -> None:
        with self._lock:
            self._get_or_create(name).record_success(latency_s)

    def record_failure(self, name: str, error: Exception | str, latency_s: float = 0.0) -> None:
        with self._lock:
            self._get_or_create(name).record_failure(latency_s, error)

    # ── Queries ─────────────────────────────────────────────────────

    def status(self, name: str) -> ProviderStatus:
        """Get a frozen snapshot of a provider's health."""
        with self._lock:
            return self._get_or_create(name).snapshot()

    def all_statuses(self) -> dict[str, ProviderStatus]:
        """Return snapshots for all known providers."""
        with self._lock:
            return {k: v.snapshot() for k, v in self._providers.items()}

    def is_degraded(self, name: str) -> bool:
        return self.status(name).availability in ("degraded", "down")

    def summary_lines(self) -> list[str]:
        """One-line human-readable summary per provider (for dashboards)."""
        lines: list[str] = []
        for st in self.all_statuses().values():
            icon = {"up": "✅", "degraded": "⚡", "down": "🔴", "unknown": "❓"}.get(
                st.availability, "❓"
            )
            lat = f" avg={st.avg_latency_ms:.0f}ms" if st.avg_latency_ms else ""
            lines.append(f"{icon} {st.name}: {st.availability}{lat} — {st.reason}")
        return lines

    def reset(self, name: str | None = None) -> None:
        """Clear tracked state.  If *name* is None, clear all."""
        with self._lock:
            if name is None:
                self._providers.clear()
            else:
                self._providers.pop(name, None)
