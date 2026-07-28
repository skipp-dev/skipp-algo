"""Deterministic evidence contract for FMP intraday/EOD volume semantics."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, time
from statistics import median
from typing import Any


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0.0 else None


def _bar_datetime(row: dict[str, Any]) -> datetime | None:
    raw_value = row.get("date")
    if raw_value is None:
        raw_value = row.get("datetime")
    raw = str(raw_value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def intraday_volume_totals(
    rows: list[dict[str, Any]],
    *,
    session_date: str,
) -> tuple[float, float, int]:
    """Return ``(full_provider_day, regular_session, valid_bar_count)``.

    FMP intraday timestamps are exchange-local when naive. A timezone-aware
    row is compared by its represented calendar date/time; the artifact keeps
    the raw provider basis visible instead of silently relabelling it.
    """
    wanted = date.fromisoformat(session_date)
    full = 0.0
    regular = 0.0
    count = 0
    for row in rows:
        stamp = _bar_datetime(row)
        volume = _positive_float(row.get("volume"))
        if stamp is None or volume is None or stamp.date() != wanted:
            continue
        count += 1
        full += volume
        if time(9, 30) <= stamp.timetz().replace(tzinfo=None) < time(16, 0):
            regular += volume
    return full, regular, count


def eod_volume_for_session(
    response: list[dict[str, Any]] | dict[str, Any],
    *,
    session_date: str,
) -> float | None:
    rows = response.get("historical") if isinstance(response, dict) else response
    if not isinstance(rows, list):
        return None
    for row in rows:
        if str(row.get("date") or "")[:10] == session_date:
            return _positive_float(row.get("volume"))
    return None


def build_volume_measurement(
    *,
    symbol: str,
    session_date: str,
    quote_row: dict[str, Any],
    minute_rows: list[dict[str, Any]],
    eod_response: list[dict[str, Any]] | dict[str, Any],
) -> dict[str, Any]:
    """Build one auditable same-symbol, same-session FMP basis comparison."""
    quote_volume = _positive_float(quote_row.get("volume"))
    full_volume, regular_volume, bar_count = intraday_volume_totals(
        minute_rows,
        session_date=session_date,
    )
    eod_volume = eod_volume_for_session(eod_response, session_date=session_date)
    full_value = full_volume if full_volume > 0.0 else None
    return {
        "schema_version": 1,
        "session_date": session_date,
        "symbol": symbol.strip().upper(),
        "quote_volume": quote_volume,
        "minute_volume_full_provider_day": full_value,
        "minute_volume_regular_session": regular_volume if regular_volume > 0.0 else None,
        "minute_bar_count": bar_count,
        "eod_volume": eod_volume,
        "quote_to_minute_full_ratio": (
            round(quote_volume / full_value, 6)
            if quote_volume is not None and full_value is not None
            else None
        ),
        "eod_to_minute_full_ratio": (
            round(eod_volume / full_value, 6)
            if eod_volume is not None and full_value is not None
            else None
        ),
        "provider": "fmp",
        "quote_endpoint": "/stable/quote",
        "minute_endpoint": "/stable/historical-chart/1min",
        "eod_endpoint": "/stable/historical-price-eod/full",
    }


def build_multi_session_summary(
    measurements: list[dict[str, Any]],
    *,
    minimum_sessions: int = 5,
) -> dict[str, Any]:
    """Aggregate session medians so a large symbol-day cannot dominate F3."""
    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in measurements:
        session = str(row.get("session_date") or "")
        if session:
            by_session[session].append(row)

    session_rows: list[dict[str, Any]] = []
    for session, rows in sorted(by_session.items()):
        quote_ratios = [
            float(value)
            for row in rows
            if (value := row.get("quote_to_minute_full_ratio")) is not None
        ]
        eod_ratios = [
            float(value)
            for row in rows
            if (value := row.get("eod_to_minute_full_ratio")) is not None
        ]
        session_rows.append({
            "session_date": session,
            "symbols_measured": len(rows),
            "quote_to_minute_median": round(median(quote_ratios), 6) if quote_ratios else None,
            "eod_to_minute_median": round(median(eod_ratios), 6) if eod_ratios else None,
        })

    quote_session_medians = [
        float(row["quote_to_minute_median"])
        for row in session_rows
        if row["quote_to_minute_median"] is not None
    ]
    eod_session_medians = [
        float(row["eod_to_minute_median"])
        for row in session_rows
        if row["eod_to_minute_median"] is not None
    ]
    sessions = len(session_rows)
    quote_median = median(quote_session_medians) if quote_session_medians else None
    eod_median = median(eod_session_medians) if eod_session_medians else None
    ready = sessions >= minimum_sessions and quote_median is not None and eod_median is not None
    if not ready:
        verdict = "accumulating_evidence"
    elif abs(quote_median - 1.0) <= 0.05 and abs(eod_median - 1.0) > 0.10:
        verdict = "confirmed_basis_mismatch"
    elif abs(quote_median - 1.0) <= 0.05 and abs(eod_median - 1.0) <= 0.05:
        verdict = "basis_compatible"
    else:
        verdict = "inconclusive"
    return {
        "schema_version": 1,
        "minimum_sessions": minimum_sessions,
        "sessions_observed": sessions,
        "ready_for_decision": ready,
        "verdict": verdict,
        "quote_to_minute_session_median": round(quote_median, 6) if quote_median is not None else None,
        "eod_to_minute_session_median": round(eod_median, 6) if eod_median is not None else None,
        "recommended_next_step": (
            "replace FMP ADV with the same intraday aggregation basis"
            if verdict == "confirmed_basis_mismatch"
            else "continue collection; do not change source semantics yet"
            if verdict in {"accumulating_evidence", "inconclusive"}
            else "retain the explicit 15-session EOD ADV contract"
        ),
        "sessions": session_rows,
    }
