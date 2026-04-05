"""Pure helpers for per-ticker live reaction confirmation state.

The catalyst layer tells us whether a ticker currently has a credible news
setup. This module adds the next decision surface above it: whether the market
is actually reacting in a way that confirms, weakens, or fades that catalyst.

Reaction uses the existing quote-source precedence already present elsewhere in
the terminal:

- RT engine quotes are preferred for confirmation because they include
  intraday direction and relative-volume context.
- Databento quotes are only a price-direction fallback when RT is unavailable.
"""

from __future__ import annotations

import time
from typing import Any

from terminal_catalyst_state import (
    effective_catalyst_actionable,
    effective_catalyst_score,
    effective_catalyst_sentiment,
)


_REACTION_PRIORITY = {
    "CONFIRMED": 4,
    "WATCH": 3,
    "IDLE": 2,
    "FADE": 1,
    "CONFLICTED": 0,
}
_REACTION_ICONS = {
    "CONFIRMED": "confirmed",
    "WATCH": "watch",
    "IDLE": "idle",
    "FADE": "fade",
    "CONFLICTED": "conflicted",
}
_DIRECTION_SIGN = {
    "BULLISH": 1.0,
    "BEARISH": -1.0,
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


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _effective_direction(row: dict[str, Any]) -> str:
    direction = str(row.get("catalyst_direction") or "").strip().upper()
    if direction in {"BULLISH", "BEARISH", "NEUTRAL", "MIXED"}:
        return direction
    sentiment = effective_catalyst_sentiment(row)
    if sentiment == "bullish":
        return "BULLISH"
    if sentiment == "bearish":
        return "BEARISH"
    return "NEUTRAL"


def _row_priority(row: dict[str, Any]) -> tuple[float, float, int]:
    return (
        effective_catalyst_score(row),
        _safe_float(
            row.get("catalyst_last_update_ts")
            or row.get("story_last_seen_ts")
            or row.get("updated_ts")
            or row.get("published_ts"),
            0.0,
        ),
        -int(_safe_float(row.get("source_rank"), 99.0)),
    )


def _normalize_quotes(quotes: dict[str, dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for symbol, row in (quotes or {}).items():
        key = str(symbol or "").strip().upper()
        if not key:
            continue
        normalized[key] = dict(row)
    return normalized


def _quote_change_pct(rt_row: dict[str, Any], db_row: dict[str, Any]) -> float | None:
    for raw in (
        rt_row.get("chg_pct"),
        db_row.get("changesPercentage"),
        db_row.get("changePercentage"),
        db_row.get("change_pct"),
    ):
        value = _optional_float(raw)
        if value is not None:
            return value
    return None


def _reaction_seed(row: dict[str, Any], previous_state: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    ticker = str(row.get("ticker") or "").strip().upper()
    state = dict((previous_state or {}).get(ticker) or {})
    if state:
        return state
    seeded: dict[str, Any] = {}
    for field_name in (
        "reaction_state",
        "reaction_anchor_story_key",
        "reaction_anchor_price",
        "reaction_anchor_ts",
        "reaction_peak_impulse_pct",
        "reaction_confirmed",
        "reaction_last_update_ts",
    ):
        value = row.get(field_name)
        if value is not None and value != "":
            seeded[field_name] = value
    if seeded:
        seeded["catalyst_direction"] = row.get("catalyst_direction")
    return seeded


def effective_reaction_state(item: Any) -> str:
    reaction_state = str(_get_field(item, "reaction_state", "") or "").strip().upper()
    if reaction_state in _REACTION_PRIORITY:
        return reaction_state
    if effective_catalyst_actionable(item):
        return "WATCH"
    return "IDLE"


def effective_reaction_priority(item: Any) -> int:
    return _REACTION_PRIORITY.get(effective_reaction_state(item), 0)


def effective_reaction_score(item: Any) -> float:
    reaction_score = _get_field(item, "reaction_score", None)
    if reaction_score is not None:
        return _safe_float(reaction_score, 0.0)
    return effective_catalyst_score(item)


def effective_reaction_actionable(item: Any, *, now: float | None = None) -> bool:
    reaction_actionable = _get_field(item, "reaction_actionable", None)
    if reaction_actionable is not None:
        return bool(reaction_actionable)
    return effective_catalyst_actionable(item, now=now)


def build_ticker_reaction_state(
    feed: list[dict[str, Any]] | None,
    *,
    rt_quotes: dict[str, dict[str, Any]] | None = None,
    quote_map: dict[str, dict[str, Any]] | None = None,
    previous_state: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    if now is None:
        now = time.time()

    normalized_rt = _normalize_quotes(rt_quotes)
    normalized_db = _normalize_quotes(quote_map)

    best_rows: dict[str, dict[str, Any]] = {}
    for raw_row in feed or []:
        row = dict(raw_row)
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker == "MARKET":
            continue
        expires_at = _optional_float(row.get("catalyst_expires_at"))
        if expires_at is None:
            expires_at = _optional_float(row.get("story_expires_at"))
        if expires_at is not None and expires_at > 0 and expires_at <= float(now):
            continue
        existing = best_rows.get(ticker)
        if existing is None or _row_priority(row) > _row_priority(existing):
            best_rows[ticker] = row

    ticker_state: dict[str, dict[str, Any]] = {}
    for ticker, row in best_rows.items():
        catalyst_score = effective_catalyst_score(row)
        catalyst_actionable = effective_catalyst_actionable(row)
        catalyst_conflict = bool(row.get("catalyst_conflict", False))
        direction = _effective_direction(row)
        direction_sign = _DIRECTION_SIGN.get(direction, 0.0)
        active_story_key = str(
            row.get("catalyst_best_story_key") or row.get("story_key") or ""
        ).strip()

        rt_row = normalized_rt.get(ticker) or {}
        db_row = normalized_db.get(ticker) or {}
        reaction_source = ""
        if rt_row:
            reaction_source = "rt"
        elif db_row:
            reaction_source = "databento"

        current_price = _optional_float((rt_row or db_row).get("price"))
        change_pct = _quote_change_pct(rt_row, db_row)
        vol_ratio = _optional_float(rt_row.get("vol_ratio"))

        seed = _reaction_seed(row, previous_state)
        previous_label = str(seed.get("reaction_state") or "").strip().upper()
        previous_direction = str(seed.get("catalyst_direction") or direction).strip().upper() or direction
        seeded_story_key = str(
            seed.get("reaction_anchor_story_key") or seed.get("catalyst_best_story_key") or ""
        ).strip()

        keep_anchor = bool(
            active_story_key
            and active_story_key == seeded_story_key
            and previous_direction == direction
        )
        anchor_price = _optional_float(seed.get("reaction_anchor_price")) if keep_anchor else None
        anchor_ts = _optional_float(seed.get("reaction_anchor_ts")) if keep_anchor else None
        peak_impulse = _safe_float(seed.get("reaction_peak_impulse_pct"), 0.0) if keep_anchor else 0.0

        if current_price is not None and current_price > 0 and anchor_price is None:
            anchor_price = current_price
            anchor_ts = float(now)
            peak_impulse = 0.0

        impulse_pct: float | None = None
        if current_price is not None and anchor_price is not None and anchor_price > 0:
            impulse_pct = ((current_price - anchor_price) / anchor_price) * 100.0

        effective_move = impulse_pct if impulse_pct is not None else change_pct
        aligned_move = direction_sign * effective_move if direction_sign and effective_move is not None else 0.0
        aligned_change = direction_sign * change_pct if direction_sign and change_pct is not None else None

        if impulse_pct is not None and direction_sign > 0:
            peak_impulse = max(peak_impulse, impulse_pct)
        elif impulse_pct is not None and direction_sign < 0:
            peak_impulse = min(peak_impulse, impulse_pct)

        peak_aligned = direction_sign * peak_impulse if direction_sign else 0.0
        retraced_from_peak = bool(
            peak_aligned >= 0.9
            and aligned_move >= 0.0
            and aligned_move <= (peak_aligned * 0.4)
        )

        if catalyst_conflict or direction == "MIXED":
            reaction_state = "CONFLICTED"
            reaction_reason = "conflicting_catalyst"
        elif direction_sign == 0.0 or catalyst_score < 0.35:
            reaction_state = "IDLE"
            reaction_reason = "non_directional_catalyst"
        elif current_price is None and change_pct is None:
            reaction_state = "WATCH" if catalyst_actionable or catalyst_score >= 0.65 else "IDLE"
            reaction_reason = "missing_quote_context"
        elif aligned_move <= -0.35 or (aligned_change is not None and aligned_change <= -0.75):
            if previous_label == "CONFIRMED" or peak_aligned >= 0.9:
                reaction_state = "FADE"
                reaction_reason = "price_reversed_after_confirmation"
            else:
                reaction_state = "CONFLICTED"
                reaction_reason = "price_conflicts_catalyst"
        elif retraced_from_peak:
            reaction_state = "FADE"
            reaction_reason = "retraced_from_peak"
        elif reaction_source == "rt" and aligned_move >= 0.75 and vol_ratio is not None and vol_ratio >= 1.25:
            reaction_state = "CONFIRMED"
            reaction_reason = "rt_price_volume_confirmation"
        elif aligned_move >= 0.35 or (aligned_change is not None and aligned_change >= 0.75):
            reaction_state = "WATCH"
            reaction_reason = (
                "price_aligned_waiting_volume"
                if reaction_source == "rt"
                else "price_aligned_databento_fallback"
            )
        elif previous_label == "CONFIRMED" and aligned_move >= 0.0:
            reaction_state = "FADE"
            reaction_reason = "post_confirmation_stall"
        else:
            reaction_state = "WATCH" if catalyst_actionable and catalyst_score >= 0.65 else "IDLE"
            reaction_reason = "waiting_for_reaction"

        if current_price is None and change_pct is None:
            reaction_alignment = "UNKNOWN"
        elif aligned_move >= 0.35:
            reaction_alignment = "ALIGNED"
        elif aligned_move <= -0.35:
            reaction_alignment = "CONTRARY"
        else:
            reaction_alignment = "NEUTRAL"

        reaction_confirmed = reaction_state == "CONFIRMED"
        reaction_actionable = bool(
            reaction_state == "CONFIRMED"
            or (
                reaction_state == "WATCH"
                and catalyst_actionable
                and reaction_alignment != "CONTRARY"
            )
        )

        confidence = (_safe_float(row.get("catalyst_confidence"), 0.0) * 0.55) + 0.20
        if reaction_source == "rt":
            confidence += 0.15
        elif reaction_source == "databento":
            confidence += 0.07
        if aligned_move > 0:
            confidence += min(aligned_move, 2.0) * 0.08
        if vol_ratio is not None and vol_ratio > 1.0:
            confidence += min(vol_ratio - 1.0, 2.0) * 0.06
        if reaction_state == "CONFIRMED":
            confidence += 0.10
        elif reaction_state == "WATCH":
            confidence += 0.02
        elif reaction_state == "FADE":
            confidence -= 0.12
        elif reaction_state == "CONFLICTED":
            confidence -= 0.22
        confidence = min(max(confidence, 0.0), 1.0)

        reaction_score = catalyst_score
        if reaction_state == "CONFIRMED":
            reaction_score = min(
                1.0,
                reaction_score
                + 0.12
                + min(max(aligned_move, 0.0), 2.0) * 0.03
                + max((_optional_float(vol_ratio) or 1.0) - 1.0, 0.0) * 0.04,
            )
        elif reaction_state == "WATCH":
            reaction_score = min(1.0, reaction_score + min(max(aligned_move, 0.0), 1.5) * 0.03)
        elif reaction_state == "FADE":
            reaction_score *= 0.68
        elif reaction_state == "CONFLICTED":
            reaction_score *= 0.55
        else:
            reaction_score *= 0.82

        ticker_state[ticker] = {
            "ticker": ticker,
            "reaction_state": reaction_state,
            "reaction_alignment": reaction_alignment,
            "reaction_score": round(reaction_score, 6),
            "reaction_confidence": round(confidence, 6),
            "reaction_price": round(current_price, 6) if current_price is not None else None,
            "reaction_change_pct": round(change_pct, 6) if change_pct is not None else None,
            "reaction_impulse_pct": round(impulse_pct, 6) if impulse_pct is not None else None,
            "reaction_volume_ratio": round(vol_ratio, 6) if vol_ratio is not None else None,
            "reaction_source": reaction_source,
            "reaction_anchor_story_key": active_story_key,
            "reaction_anchor_price": round(anchor_price, 6) if anchor_price is not None else None,
            "reaction_anchor_ts": round(anchor_ts, 6) if anchor_ts is not None else None,
            "reaction_peak_impulse_pct": round(peak_impulse, 6) if anchor_price is not None else None,
            "reaction_last_update_ts": float(now),
            "reaction_confirmed": reaction_confirmed,
            "reaction_actionable": reaction_actionable,
            "reaction_reason": reaction_reason,
        }

    return ticker_state


def annotate_feed_with_ticker_reaction_state(
    feed: list[dict[str, Any]] | None,
    ticker_state: dict[str, dict[str, Any]] | None = None,
    *,
    rt_quotes: dict[str, dict[str, Any]] | None = None,
    quote_map: dict[str, dict[str, Any]] | None = None,
    previous_state: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if now is None:
        now = time.time()
    resolved_state = ticker_state or build_ticker_reaction_state(
        feed,
        rt_quotes=rt_quotes,
        quote_map=quote_map,
        previous_state=previous_state,
        now=now,
    )
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