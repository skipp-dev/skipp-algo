"""Pure helpers for per-ticker operator attention state.

Posture tells us the directional lean. Attention adds the next operator-facing
layer above it: whether a setup should be suppressed, left in the background,
monitored, featured prominently, or dispatched externally.
"""

from __future__ import annotations

import time
from typing import Any

from terminal_catalyst_state import effective_catalyst_age_minutes, effective_catalyst_score
from terminal_posture_state import (
    effective_posture_confidence,
    effective_posture_priority,
    effective_posture_score,
    effective_posture_state,
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


_ATTENTION_PRIORITY = {
    "ALERT": 4,
    "FOCUS": 3,
    "MONITOR": 2,
    "BACKGROUND": 1,
    "SUPPRESS": 0,
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


def _row_priority(row: dict[str, Any]) -> tuple[int, int, int, float, float, float, float]:
    return (
        effective_posture_priority(row),
        effective_resolution_priority(row),
        effective_reaction_priority(row),
        effective_posture_score(row),
        effective_resolution_score(row),
        effective_reaction_score(row),
        _safe_float(
            row.get("posture_last_update_ts")
            or row.get("resolution_last_update_ts")
            or row.get("reaction_last_update_ts")
            or row.get("catalyst_last_update_ts")
            or row.get("story_last_seen_ts")
            or row.get("updated_ts")
            or row.get("published_ts"),
            0.0,
        ),
    )


def _derive_attention_fields(item: Any, *, now: float | None = None) -> dict[str, Any]:
    posture_state = effective_posture_state(item, now=now)
    posture_score = effective_posture_score(item)
    posture_confidence = effective_posture_confidence(item, now=now)
    resolution_state = effective_resolution_state(item)
    resolution_score = effective_resolution_score(item)
    resolution_actionable = effective_resolution_actionable(item, now=now)
    reaction_state = effective_reaction_state(item)
    reaction_score = effective_reaction_score(item)
    reaction_actionable = effective_reaction_actionable(item, now=now)
    catalyst_score = effective_catalyst_score(item)
    age_minutes = effective_catalyst_age_minutes(item, now=now)
    materiality = str(_get_field(item, "materiality", "") or "").strip().upper()
    high_materiality = materiality == "HIGH"

    if (
        posture_state == "AVOID"
        or resolution_state in {"FAILED", "REVERSAL"}
        or reaction_state in {"CONFLICTED", "FADE"}
    ):
        attention_state = "SUPPRESS"
        attention_reason = "negative_state"
    elif age_minutes is not None and age_minutes > 1440.0:
        attention_state = "BACKGROUND"
        attention_reason = "stale_setup"
    elif posture_state == "NEUTRAL":
        attention_state = "BACKGROUND"
        attention_reason = "neutral_posture"
    elif (
        posture_state in {"LONG", "SHORT"}
        and posture_score >= 0.85
        and (age_minutes is None or age_minutes <= 45.0)
        and (resolution_state == "FOLLOW_THROUGH" or reaction_state == "CONFIRMED")
    ):
        attention_state = "ALERT"
        attention_reason = (
            "follow_through_alert"
            if resolution_state == "FOLLOW_THROUGH"
            else "confirmed_directional_alert"
        )
    elif (
        posture_state in {"LONG", "SHORT"}
        and posture_score >= 0.72
        and (resolution_actionable or reaction_actionable or resolution_state == "OPEN")
    ) or (
        posture_state in {"WATCH_LONG", "WATCH_SHORT"}
        and posture_score >= 0.74
        and (resolution_actionable or reaction_actionable or high_materiality)
    ):
        attention_state = "FOCUS"
        attention_reason = "directional_focus"
    elif posture_state in {"LONG", "SHORT", "WATCH_LONG", "WATCH_SHORT"} and (
        resolution_actionable or reaction_actionable or catalyst_score >= 0.60
    ):
        attention_state = "MONITOR"
        attention_reason = "directional_monitor"
    else:
        attention_state = "BACKGROUND"
        attention_reason = "background_only"

    attention_active = attention_state in {"ALERT", "FOCUS", "MONITOR"}
    attention_featured = attention_state in {"ALERT", "FOCUS"}
    attention_dispatchable = attention_state == "ALERT"

    attention_score = posture_score
    if attention_state == "ALERT":
        attention_score = min(1.0, attention_score + 0.08 + max(resolution_score - 0.75, 0.0) * 0.10)
    elif attention_state == "FOCUS":
        attention_score = min(1.0, attention_score + 0.04 + (0.02 if high_materiality else 0.0))
    elif attention_state == "BACKGROUND":
        attention_score *= 0.78
    elif attention_state == "SUPPRESS":
        attention_score *= 0.45

    confidence_inputs = [
        posture_confidence,
        _safe_float(_get_field(item, "resolution_confidence", None), -1.0),
        _safe_float(_get_field(item, "reaction_confidence", None), -1.0),
    ]
    valid_confidence = [value for value in confidence_inputs if value >= 0.0]
    if valid_confidence:
        attention_confidence = sum(valid_confidence) / len(valid_confidence)
    else:
        attention_confidence = attention_score
    if age_minutes is not None and age_minutes <= 30.0 and attention_active:
        attention_confidence += 0.05
    if attention_state == "ALERT":
        attention_confidence += 0.08
    elif attention_state == "FOCUS":
        attention_confidence += 0.03
    elif attention_state == "BACKGROUND":
        attention_confidence -= 0.10
    elif attention_state == "SUPPRESS":
        attention_confidence -= 0.25
    attention_confidence = min(max(attention_confidence, 0.0), 1.0)

    return {
        "attention_state": attention_state,
        "attention_score": round(attention_score, 6),
        "attention_confidence": round(attention_confidence, 6),
        "attention_active": attention_active,
        "attention_featured": attention_featured,
        "attention_dispatchable": attention_dispatchable,
        "attention_reason": attention_reason,
    }


def effective_attention_state(item: Any, *, now: float | None = None) -> str:
    attention_state = str(_get_field(item, "attention_state", "") or "").strip().upper()
    if attention_state in _ATTENTION_PRIORITY:
        return attention_state
    return str(_derive_attention_fields(item, now=now)["attention_state"])


def effective_attention_priority(item: Any, *, now: float | None = None) -> int:
    return _ATTENTION_PRIORITY.get(effective_attention_state(item, now=now), 0)


def effective_attention_score(item: Any, *, now: float | None = None) -> float:
    attention_score = _get_field(item, "attention_score", None)
    if attention_score is not None:
        return _safe_float(attention_score, 0.0)
    return _safe_float(_derive_attention_fields(item, now=now)["attention_score"], 0.0)


def effective_attention_confidence(item: Any, *, now: float | None = None) -> float:
    attention_confidence = _get_field(item, "attention_confidence", None)
    if attention_confidence is not None:
        return _safe_float(attention_confidence, 0.0)
    return _safe_float(_derive_attention_fields(item, now=now)["attention_confidence"], 0.0)


def effective_attention_active(item: Any, *, now: float | None = None) -> bool:
    attention_active = _get_field(item, "attention_active", None)
    if attention_active is not None:
        return bool(attention_active)
    return bool(_derive_attention_fields(item, now=now)["attention_active"])


def effective_attention_featured(item: Any, *, now: float | None = None) -> bool:
    attention_featured = _get_field(item, "attention_featured", None)
    if attention_featured is not None:
        return bool(attention_featured)
    return bool(_derive_attention_fields(item, now=now)["attention_featured"])


def effective_attention_dispatchable(item: Any, *, now: float | None = None) -> bool:
    attention_dispatchable = _get_field(item, "attention_dispatchable", None)
    if attention_dispatchable is not None:
        return bool(attention_dispatchable)
    return bool(_derive_attention_fields(item, now=now)["attention_dispatchable"])


def effective_attention_reason(item: Any, *, now: float | None = None) -> str:
    attention_reason = str(_get_field(item, "attention_reason", "") or "").strip()
    if attention_reason:
        return attention_reason
    return str(_derive_attention_fields(item, now=now)["attention_reason"])


def build_ticker_attention_state(
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
        state = _derive_attention_fields(row, now=now)
        ticker_state[ticker] = {
            "ticker": ticker,
            **state,
            "attention_last_update_ts": float(now),
        }
    return ticker_state


def annotate_feed_with_ticker_attention_state(
    feed: list[dict[str, Any]] | None,
    ticker_state: dict[str, dict[str, Any]] | None = None,
    *,
    now: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if now is None:
        now = time.time()
    resolved_state = ticker_state or build_ticker_attention_state(feed, now=now)
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