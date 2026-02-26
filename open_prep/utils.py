from __future__ import annotations

import logging
import math
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


def to_float(value: Any, default: float = 0.0) -> float:
    """Safely parse numeric-like values to float with default fallback.

    Returns *default* for ``None``, non-numeric strings, **and** ``NaN``
    values so that downstream arithmetic never silently propagates NaN.
    """
    try:
        f = float(value)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Shared screening constants (used by screen.py and scorer.py)
# ---------------------------------------------------------------------------
MIN_PRICE_THRESHOLD: float = 5.0
"""Hard floor — reject any candidate priced below this."""

SEVERE_GAP_DOWN_THRESHOLD: float = -8.0
"""Gap-down percentage that triggers the *severe gap-down* filter."""


# ---------------------------------------------------------------------------
# Pipeline Stage Profiler
# ---------------------------------------------------------------------------

class StageProfiler:
    """Lightweight wall-clock profiler for pipeline stages.

    Inspired by IB_MON's performance instrumentation.  Usage::

        profiler = StageProfiler()
        with profiler.stage("Load quotes"):
            quotes = load_all_quotes()
        with profiler.stage("Score candidates"):
            ranked = score_pipeline(quotes)
        profiler.log_report()
    """

    def __init__(self) -> None:
        self._timings: list[tuple[str, float]] = []
        self._t0: float = time.monotonic()

    @contextmanager
    def stage(self, name: str) -> Generator[None, None, None]:
        """Context manager that records elapsed time for *name*."""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            self._timings.append((name, elapsed))

    def report(self) -> dict[str, Any]:
        """Return a dict with per-stage timings and total elapsed time.

        Returns
        -------
        dict
            ``{"stages": [{"name": str, "seconds": float, "pct": float}, ...],
              "total_seconds": float}``
        """
        total = time.monotonic() - self._t0
        stages = []
        for name, secs in self._timings:
            stages.append({
                "name": name,
                "seconds": round(secs, 3),
                "pct": round(100.0 * secs / total, 1) if total > 0 else 0.0,
            })
        return {"stages": stages, "total_seconds": round(total, 3)}

    def log_report(self, level: int = logging.INFO) -> dict[str, Any]:
        """Log the profiling report and return it."""
        rpt = self.report()
        lines = [
            f"Pipeline profiler — {rpt['total_seconds']:.3f}s total",
        ]
        for s in rpt["stages"]:
            lines.append(f"  {s['name']:.<40s} {s['seconds']:>6.3f}s ({s['pct']:>5.1f}%)")
        logger.log(level, "\n".join(lines))
        return rpt
