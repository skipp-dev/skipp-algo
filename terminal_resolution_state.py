"""Pure helpers for per-ticker catalyst resolution state.

The reaction layer answers whether the market is starting to confirm a catalyst.
This module adds the next operator-facing question above it: how that move is
resolving over a slightly longer window.

Resolution tracks whether a live catalyst is still open, has produced clean
follow-through, stalled, failed, or fully reversed.
"""

from __future__ import annotations

import time
from typing import Any

from terminal_catalyst_state import effective_catalyst_score, effective_catalyst_sentiment
from terminal_reaction_state import (
	effective_reaction_actionable,
	effective_reaction_priority,
	effective_reaction_score,
	effective_reaction_state,
)


_RESOLUTION_PRIORITY = {
	"FOLLOW_THROUGH": 4,
	"OPEN": 3,
	"STALLED": 2,
	"FAILED": 1,
	"REVERSAL": 0,
}
_DIRECTION_SIGN = {
	"BULLISH": 1.0,
	"BEARISH": -1.0,
}
_MIN_OPEN_WINDOW_MINUTES = 5.0
_STALL_WINDOW_MINUTES = 12.0
_DEFAULT_RESOLUTION_WINDOW_MINUTES = 20.0


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


def _row_priority(row: dict[str, Any]) -> tuple[int, float, float, float]:
	return (
		effective_reaction_priority(row),
		effective_reaction_score(row),
		effective_catalyst_score(row),
		_safe_float(
			row.get("reaction_last_update_ts")
			or row.get("catalyst_last_update_ts")
			or row.get("story_last_seen_ts")
			or row.get("updated_ts")
			or row.get("published_ts"),
			0.0,
		),
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


def _resolution_seed(row: dict[str, Any], previous_state: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
	ticker = str(row.get("ticker") or "").strip().upper()
	state = dict((previous_state or {}).get(ticker) or {})
	if state:
		return state

	seeded: dict[str, Any] = {}
	for field_name in (
		"resolution_state",
		"resolution_anchor_story_key",
		"resolution_anchor_price",
		"resolution_anchor_ts",
		"resolution_peak_impulse_pct",
		"resolution_last_update_ts",
	):
		value = row.get(field_name)
		if value is not None and value != "":
			seeded[field_name] = value
	if seeded:
		seeded["catalyst_direction"] = row.get("catalyst_direction")
	return seeded


def effective_resolution_state(item: Any) -> str:
	resolution_state = str(_get_field(item, "resolution_state", "") or "").strip().upper()
	if resolution_state in _RESOLUTION_PRIORITY:
		return resolution_state

	reaction_state = effective_reaction_state(item)
	if reaction_state in {"FADE", "CONFLICTED"}:
		return "FAILED"
	return "OPEN"


def effective_resolution_priority(item: Any) -> int:
	resolution_state = str(_get_field(item, "resolution_state", "") or "").strip().upper()
	if resolution_state in _RESOLUTION_PRIORITY:
		return _RESOLUTION_PRIORITY[resolution_state]
	return effective_reaction_priority(item)


def effective_resolution_score(item: Any) -> float:
	resolution_score = _get_field(item, "resolution_score", None)
	if resolution_score is not None:
		return _safe_float(resolution_score, 0.0)
	return effective_reaction_score(item)


def effective_resolution_actionable(item: Any, *, now: float | None = None) -> bool:
	resolution_actionable = _get_field(item, "resolution_actionable", None)
	if resolution_actionable is not None:
		return bool(resolution_actionable)

	resolution_state = effective_resolution_state(item)
	if resolution_state == "FOLLOW_THROUGH":
		return True
	if resolution_state in {"STALLED", "FAILED", "REVERSAL"}:
		return False
	return effective_reaction_actionable(item, now=now)


def build_ticker_resolution_state(
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
		reaction_score = effective_reaction_score(row)
		reaction_state = effective_reaction_state(row)
		reaction_actionable = effective_reaction_actionable(row)
		direction = _effective_direction(row)
		direction_sign = _DIRECTION_SIGN.get(direction, 0.0)
		active_story_key = str(
			row.get("reaction_anchor_story_key")
			or row.get("catalyst_best_story_key")
			or row.get("story_key")
			or ""
		).strip()

		rt_row = normalized_rt.get(ticker) or {}
		db_row = normalized_db.get(ticker) or {}
		resolution_source = ""
		if rt_row:
			resolution_source = "rt"
		elif db_row:
			resolution_source = "databento"

		current_price = _optional_float((rt_row or db_row).get("price"))
		change_pct = _quote_change_pct(rt_row, db_row)

		seed = _resolution_seed(row, previous_state)
		previous_direction = str(seed.get("catalyst_direction") or direction).strip().upper() or direction
		seeded_story_key = str(
			seed.get("resolution_anchor_story_key")
			or row.get("resolution_anchor_story_key")
			or row.get("reaction_anchor_story_key")
			or ""
		).strip()
		keep_anchor = bool(
			active_story_key
			and active_story_key == seeded_story_key
			and previous_direction == direction
		)

		anchor_price = _optional_float(row.get("reaction_anchor_price"))
		anchor_ts = _optional_float(row.get("reaction_anchor_ts"))
		peak_impulse = _safe_float(row.get("reaction_peak_impulse_pct"), 0.0)

		if keep_anchor:
			anchor_price = _optional_float(seed.get("resolution_anchor_price")) or anchor_price
			anchor_ts = _optional_float(seed.get("resolution_anchor_ts")) or anchor_ts
			seed_peak = _optional_float(seed.get("resolution_peak_impulse_pct"))
			if seed_peak is not None:
				if direction_sign >= 0.0:
					peak_impulse = max(peak_impulse, seed_peak)
				else:
					peak_impulse = min(peak_impulse, seed_peak)

		if current_price is not None and current_price > 0 and anchor_price is None:
			anchor_price = current_price
			anchor_ts = float(now)
			peak_impulse = 0.0

		impulse_pct: float | None = None
		if current_price is not None and anchor_price is not None and anchor_price > 0:
			impulse_pct = ((current_price - anchor_price) / anchor_price) * 100.0

		effective_move = impulse_pct if impulse_pct is not None else change_pct
		aligned_move = direction_sign * effective_move if direction_sign and effective_move is not None else 0.0
		peak_aligned = direction_sign * peak_impulse if direction_sign else 0.0

		if impulse_pct is not None:
			if direction_sign >= 0.0:
				peak_impulse = max(peak_impulse, impulse_pct)
			else:
				peak_impulse = min(peak_impulse, impulse_pct)
			peak_aligned = direction_sign * peak_impulse if direction_sign else 0.0

		elapsed_minutes = None
		if anchor_ts is not None and anchor_ts > 0:
			elapsed_minutes = max((float(now) - anchor_ts) / 60.0, 0.0)

		resolution_window_minutes = _DEFAULT_RESOLUTION_WINDOW_MINUTES
		if direction_sign == 0.0 or catalyst_score < 0.35:
			resolution_state = "OPEN"
			resolution_reason = "non_directional_catalyst"
		elif current_price is None and change_pct is None:
			resolution_state = "OPEN"
			resolution_reason = "missing_quote_context"
		elif aligned_move <= -1.0:
			resolution_state = "REVERSAL"
			resolution_reason = "decisive_move_against_anchor"
		elif reaction_state in {"FADE", "CONFLICTED"} and (elapsed_minutes or 0.0) >= _MIN_OPEN_WINDOW_MINUTES:
			resolution_state = "FAILED"
			resolution_reason = "negative_reaction_persisted"
		elif elapsed_minutes is None or elapsed_minutes < _MIN_OPEN_WINDOW_MINUTES:
			resolution_state = "OPEN"
			resolution_reason = "resolution_window_open"
		elif peak_aligned >= 1.20 and aligned_move >= 0.75:
			resolution_state = "FOLLOW_THROUGH"
			resolution_reason = "sustained_aligned_move"
		elif peak_aligned >= 0.90 and aligned_move <= 0.0:
			resolution_state = "FAILED"
			resolution_reason = "gave_back_confirmed_move"
		elif elapsed_minutes >= _STALL_WINDOW_MINUTES and peak_aligned < 0.90 and aligned_move < 0.25:
			resolution_state = "STALLED"
			resolution_reason = "no_follow_through"
		elif elapsed_minutes >= resolution_window_minutes and aligned_move < 0.50:
			resolution_state = "STALLED"
			resolution_reason = "weak_resolution_after_window"
		else:
			resolution_state = "OPEN"
			resolution_reason = "awaiting_resolution"

		resolution_resolved = resolution_state != "OPEN"
		resolution_actionable = bool(
			resolution_state == "FOLLOW_THROUGH"
			or (
				resolution_state == "OPEN"
				and reaction_actionable
				and reaction_state not in {"FADE", "CONFLICTED"}
			)
		)

		confidence = (_safe_float(row.get("reaction_confidence"), 0.0) * 0.65) + 0.15
		if elapsed_minutes is not None:
			confidence += min(elapsed_minutes / resolution_window_minutes, 1.0) * 0.12
		if peak_aligned > 0:
			confidence += min(peak_aligned, 2.0) * 0.05
		if resolution_state == "FOLLOW_THROUGH":
			confidence += 0.10
		elif resolution_state == "STALLED":
			confidence -= 0.06
		elif resolution_state == "FAILED":
			confidence -= 0.14
		elif resolution_state == "REVERSAL":
			confidence -= 0.22
		confidence = min(max(confidence, 0.0), 1.0)

		resolution_score = reaction_score
		if resolution_state == "FOLLOW_THROUGH":
			resolution_score = min(
				1.0,
				resolution_score
				+ 0.10
				+ min(max(aligned_move, 0.0), 2.0) * 0.03,
			)
		elif resolution_state == "OPEN":
			resolution_score = min(1.0, resolution_score + min(max(aligned_move, 0.0), 1.0) * 0.02)
		elif resolution_state == "STALLED":
			resolution_score *= 0.76
		elif resolution_state == "FAILED":
			resolution_score *= 0.58
		elif resolution_state == "REVERSAL":
			resolution_score *= 0.45

		ticker_state[ticker] = {
			"ticker": ticker,
			"resolution_state": resolution_state,
			"resolution_score": round(resolution_score, 6),
			"resolution_confidence": round(confidence, 6),
			"resolution_window_minutes": float(resolution_window_minutes),
			"resolution_elapsed_minutes": round(elapsed_minutes, 6) if elapsed_minutes is not None else None,
			"resolution_price": round(current_price, 6) if current_price is not None else None,
			"resolution_change_pct": round(change_pct, 6) if change_pct is not None else None,
			"resolution_impulse_pct": round(impulse_pct, 6) if impulse_pct is not None else None,
			"resolution_peak_impulse_pct": round(peak_impulse, 6) if anchor_price is not None else None,
			"resolution_source": resolution_source,
			"resolution_anchor_story_key": active_story_key,
			"resolution_anchor_price": round(anchor_price, 6) if anchor_price is not None else None,
			"resolution_anchor_ts": round(anchor_ts, 6) if anchor_ts is not None else None,
			"resolution_last_update_ts": float(now),
			"resolution_resolved": resolution_resolved,
			"resolution_actionable": resolution_actionable,
			"resolution_reason": resolution_reason,
		}

	return ticker_state


def annotate_feed_with_ticker_resolution_state(
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
	resolved_state = ticker_state or build_ticker_resolution_state(
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
