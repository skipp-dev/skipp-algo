"""Shared timeframe predicates.

Centralises the canonical definition of "daily" across structure and
measurement pipelines. Previously each callsite inlined ``tf == "1D"`` which
silently broke for ``"1d"``, ``"D"``, ``" 1D "`` or ``"daily"`` variants and
re-opened the intraday-workbook-fallback hole.
"""

from __future__ import annotations

_DAILY_ALIASES = frozenset({"1D", "D", "DAILY", "1DAY"})


def is_daily_timeframe(timeframe: str) -> bool:
    """Return True if ``timeframe`` denotes a daily bar stream.

    Accepts the canonical ``"1D"`` plus common casing / synonym variants so
    a single surface decides whether the daily workbook fallback is legal.
    """

    return str(timeframe).strip().upper() in _DAILY_ALIASES
