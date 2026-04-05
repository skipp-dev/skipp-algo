"""Pure helpers for per-ticker operator posture state.

The resolution layer tells us how a catalyst move is resolving. This module adds
the final operator-facing layer above it: whether the terminal should lean
long/short, keep a ticker on watch, or stand down entirely.
"""

from __future__ import annotations

import time
from typing import Any

from terminal_catalyst_state import (
    effective_catalyst_actionable,
    effective_catalyst_age_minutes,
    effective_catalyst_score,
    effective_catalyst_sentiment,
)
from terminal_reaction_state import (
    effective_reaction_actionable,
    effective_reaction_priority,
    effective_reaction_score,
    effective_reaction_state,
)
from terminal_resolution_state import (
    effective_resolution_actionable,
    effective_resolution_priority,
    effective_resolution_score,
    effective_resolution_state,
)


_POSTURE_PRIORITY = {
    "LONG": 5,
    "SHORT": 5,
    "WATCH_LONG": 4,
    "WATCH_SHORT": 4,
    "NEUTRAL": 2,
    "AVOID": 0,
}
_POSTURE_ACTION = {
    "LONG": "buy",
    "SHORT": "sell",
    "WATCH_LONG": "watch",
    "WATCH_SHORT": "watch",
    "NEUTRAL": "ignore",
    "AVOID": "ignore",
}


def _get_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _effective_direction(item: Any) -> str:
    direction = str(_get_field(item, "catalyst_direction", "") or "").strip().upper()
    if direction in {"BULLISH", "BEARISH", "NEUTRAL", "MIXED"}:
        return direction
    sentiment = effective_catalyst_sentiment(item)
    if sentiment == "bullish":
        return "BULLISH"
    if sentiment == "bearish":
        return "BEARISH"
    return "NEUTRAL"


def _row_priority(row: dict[str, Any]) -> tuple[int, float, int, float, float]:
    return (
        effective_resolution_priority(row),
        effective_resolution_score(row),
        effective_reaction_priority(row),
        effective_reaction_score(row),
        _safe_float(
            row.get("resolution_last_update_ts")
            or row.get("reaction_last_update_ts")
            or row.get("catalyst_last_update_ts")
            or row.get("story_last_seen_ts")
            or row.get("updated_ts")
            or row.get("published_ts"),
            0.0,
        ),
    )


def _derive_posture_fields(item: Any, *, now: float | None = None) -> dict[str, Any]:
    resolution_state = effective_resolution_state(item)
    reaction_state = effective_reaction_state(item)
    resolution_score = effective_resolution_score(item)
    resolution_actionable = effective_resolution_actionable(item, now=now)
    reaction_actionable = effective_reaction_actionable(item, now=now)
    catalyst_actionable = effective_catalyst_actionable(item, now=now)
    age_minutes = effective_catalyst_age_minutes(item, now=now)
    direction = _effective_direction(item)
    catalyst_conflict = bool(_get_field(item, "catalyst_conflict", False))

    if resolution_state in {"FAILED", "REVERSAL"}:
        posture_state = "AVOID"
        posture_reason = "negative_resolution"
    elif reaction_state in {"CONFLICTED", "FADE"} or catalyst_conflict:
        posture_state = "AVOID"
        posture_reason = "negative_reaction"
    elif direction not in {"BULLISH", "BEARISH"}:
        posture_state = "NEUTRAL"
        posture_reason = "no_directional_edge"
    elif resolution_state == "STALLED" and not resolution_actionable:
        posture_state = "NEUTRAL"
        posture_reason = "stalled_setup"
    elif resolution_actionable and resolution_score >= 0.80:
        posture_state = "LONG" if direction == "BULLISH" else "SHORT"
        posture_reason = (
            "follow_through_edge"
            if resolution_state == "FOLLOW_THROUGH"
            else "open_directional_edge"
        )
    elif age_minutes is not None and age_minutes > 1440.0:
        posture_state = "NEUTRAL"
        posture_reason = "stale_setup"
    elif resolution_actionable or reaction_actionable or catalyst_actionable or resolution_score >= 0.60:
        posture_state = "WATCH_LONG" if direction == "BULLISH" else "WATCH_SHORT"
        posture_reason = (
            "follow_through_monitor"
            if resolution_state == "FOLLOW_THROUGH"
            else "directional_setup_active"
        )
    else:
        posture_state = "NEUTRAL"
        posture_reason = "weak_directional_edge"

    posture_action = _POSTURE_ACTION[posture_state]
    posture_actionable = posture_state in {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"}

    confidence_inputs = [
        _safe_float(_get_field(item, "resolution_confidence", None), -1.0),
        _safe_float(_get_field(item, "reaction_confidence", None), -1.0),
        _safe_float(_get_field(item, "catalyst_confidence", effective_catalyst_score(item)), -1.0),
    ]
    valid_confidence = [value for value in confidence_inputs if value >= 0.0]
    if valid_confidence:
        posture_confidence = sum(valid_confidence) / len(valid_confidence)
    else:
        posture_confidence = resolution_score
    if posture_state in {"LONG", "SHORT"}:
        posture_confidence += 0.08
    elif posture_state in {"WATCH_LONG", "WATCH_SHORT"}:
        posture_confidence += 0.02
    elif posture_state == "AVOID":
        posture_confidence -= 0.18
    else:
        posture_confidence -= 0.04
    posture_confidence = min(max(posture_confidence, 0.0), 1.0)

    return {
        "posture_state": posture_state,
        "posture_action": posture_action,
        "posture_score": round(resolution_score, 6),
        "posture_confidence": round(posture_confidence, 6),
        "posture_actionable": posture_actionable,
        "posture_reason": posture_reason,
    }


def effective_posture_state(item: Any, *, now: float | None = None) -> str:
    posture_state = str(_get_field(item, "posture_state", "") or "").strip().upper()
    if posture_state in _POSTURE_PRIORITY:
        return posture_state
    return str(_derive_posture_fields(item, now=now)["posture_state"])


def effective_posture_priority(item: Any, *, now: float | None = None) -> int:
    return _POSTURE_PRIORITY.get(effective_posture_state(item, now=now), 0)


def effective_posture_action(item: Any, *, now: float | None = None) -> str:
    posture_action = str(_get_field(item, "posture_action", "") or "").strip().lower()
    if posture_action in {"buy", "sell", "watch", "ignore"}:
        return posture_action
    return str(_derive_posture_fields(item, now=now)["posture_action"])


def effective_posture_score(item: Any) -> float:
    posture_score = _get_field(item, "posture_score", None)
    if posture_score is not None:
        return _safe_float(posture_score, 0.0)
    return effective_resolution_score(item)


def effective_posture_confidence(item: Any, *, now: float | None = None) -> float:
    posture_confidence = _get_field(item, "posture_confidence", None)
    if posture_confidence is not None:
        return _safe_float(posture_confidence, 0.0)
    return _safe_float(_derive_posture_fields(item, now=now)["posture_confidence"], 0.0)


def effective_posture_actionable(item: Any, *, now: float | None = None) -> bool:
    posture_actionable = _get_field(item, "posture_actionable", None)
    if posture_actionable is not None:
        return bool(posture_actionable)
    return bool(_derive_posture_fields(item, now=now)["posture_actionable"])


def effective_posture_reason(item: Any, *, now: float | None = None) -> str:
    posture_reason = str(_get_field(item, "posture_reason", "") or "").strip()
    if posture_reason:
        return posture_reason
    return str(_derive_posture_fields(item, now=now)["posture_reason"])


def build_ticker_posture_state(
    feed: list[dict[str, Any]] | None,
    *,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    if now is None:
        now = time.time()

    best_rows: dict[str, dict[str, Any]] = {}
    for raw_row in feed or []:
        row = dict(raw_row)
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker == "MARKET":
            continue
        expires_at = _safe_float(row.get("catalyst_expires_at") or row.get("story_expires_at"), 0.0)
        if expires_at > 0.0 and expires_at <= float(now):
            continue
        previous = best_rows.get(ticker)
        if previous is None or _row_priority(row) > _row_priority(previous):
            best_rows[ticker] = row

    ticker_state: dict[str, dict[str, Any]] = {}
    for ticker, row in best_rows.items():
        state = _derive_posture_fields(row, now=now)
        ticker_state[ticker] = {
            "ticker": ticker,
            **state,
            "posture_last_update_ts": float(now),
        }
    return ticker_state


def annotate_feed_with_ticker_posture_state(
    feed: list[dict[str, Any]] | None,
    ticker_state: dict[str, dict[str, Any]] | None = None,
    *,
    now: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if now is None:
        now = time.time()
    resolved_state = ticker_state or build_ticker_posture_state(feed, now=now)
    annotated: list[dict[str, Any]] = []
    for row in feed or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        state = resolved_state.get(ticker)
        if state is None:
            annotated.append(dict(row))
            continue
        updated = dict(row)
        updated.update(state)
        annotated.append(updated)
    return annotated, resolved_state