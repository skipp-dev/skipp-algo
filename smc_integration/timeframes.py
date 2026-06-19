"""Shared timeframe predicates.

Centralises the canonical definition of "daily" across structure and
measurement pipelines. Previously each callsite inlined ``tf == "1D"`` which
silently broke for ``"1d"``, ``"D"``, ``" 1D "`` or ``"daily"`` variants and
re-opened the intraday-workbook-fallback hole.
"""

from __future__ import annotations

CANONICAL_TIMEFRAMES: tuple[str, ...] = ("5m", "10m", "15m", "30m", "1H", "4H", "1D")
DAILY_TIMEFRAMES: tuple[str, ...] = ("1D",)
INTRADAY_TIMEFRAMES: tuple[str, ...] = tuple(tf for tf in CANONICAL_TIMEFRAMES if tf not in DAILY_TIMEFRAMES)
LIVE_OVERLAY_TIMEFRAMES: tuple[str, ...] = INTRADAY_TIMEFRAMES

_DAILY_ALIASES = frozenset({"1D", "D", "DAILY", "1DAY"})


class WorkbookFallbackTimeframeError(ValueError):
    """Raised when the workbook fallback is asked for a non-daily timeframe.

    Subclass of :class:`ValueError` so existing ``except ValueError`` handlers
    continue to work — callers that want to bucket gate rejects separately
    from genuine input errors (telemetry, dashboards) can narrow to this type.
    """


def is_daily_timeframe(timeframe: str | None) -> bool:
    """Return True if ``timeframe`` denotes a daily bar stream.

    Accepts the canonical ``"1D"`` plus common casing / synonym variants so
    a single surface decides whether the daily workbook fallback is legal.
    ``None`` and empty strings are treated as non-daily (safe-default-reject).
    """

    if timeframe is None:
        return False
    return str(timeframe).strip().upper() in _DAILY_ALIASES
