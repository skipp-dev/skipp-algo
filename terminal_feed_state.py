"""Pure feed-state orchestration for terminal restore, resync, and merge paths."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from terminal_catalyst_state import annotate_feed_with_ticker_catalyst_state
from terminal_attention_state import annotate_feed_with_ticker_attention_state
from terminal_export import load_jsonl_feed
from terminal_live_story_state import build_live_story_state_from_feed, live_story_key
from terminal_poller import seed_provider_cursors
from terminal_posture_state import annotate_feed_with_ticker_posture_state
from terminal_reaction_state import annotate_feed_with_ticker_reaction_state
from terminal_resolution_state import annotate_feed_with_ticker_resolution_state
from terminal_ui_helpers import dedup_feed_items, dedup_merge


@dataclass(slots=True)
class DerivedFeedState:
	feed: list[dict[str, Any]]
	live_story_state: dict[str, dict[str, Any]]
	ticker_catalyst_state: dict[str, dict[str, Any]]
	ticker_reaction_state: dict[str, dict[str, Any]]
	ticker_resolution_state: dict[str, dict[str, Any]]
	ticker_posture_state: dict[str, dict[str, Any]]
	ticker_attention_state: dict[str, dict[str, Any]]
	annotated_new_rows: list[dict[str, Any]] = field(default_factory=list)
	new_count: int = 0
	legacy_cursor: str | None = None
	provider_cursors: dict[str, str] = field(default_factory=dict)


def _feed_max_age_s(cfg: Any | None, *, market_hours: bool) -> float:
	max_age_s = float(getattr(cfg, "feed_max_age_s", 14400.0) or 14400.0)
	if not market_hours:
		max_age_s = max(max_age_s, 259200.0)
	return max_age_s


def _prune_feed(
	feed: list[dict[str, Any]],
	*,
	max_age_s: float,
	now: float | None,
) -> list[dict[str, Any]]:
	if max_age_s <= 0:
		return list(feed)
	current_now = float(now if now is not None else time.time())
	cutoff = current_now - float(max_age_s)
	return [
		row for row in feed
		if (row.get("published_ts") or 0) >= cutoff
		or (row.get("published_ts") or 0) == 0
	]


def _story_key_for_feed_row(row: dict[str, Any]) -> str:
	explicit = str(row.get("story_key") or "").strip()
	return explicit or live_story_key(row)


def _annotate_rows_with_states(
	rows: list[dict[str, Any]],
	*,
	ticker_catalyst_state: dict[str, dict[str, Any]],
	ticker_reaction_state: dict[str, dict[str, Any]],
	ticker_resolution_state: dict[str, dict[str, Any]],
	ticker_posture_state: dict[str, dict[str, Any]],
	ticker_attention_state: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
	annotated, _ = annotate_feed_with_ticker_catalyst_state(rows, ticker_catalyst_state)
	annotated, _ = annotate_feed_with_ticker_reaction_state(annotated, ticker_reaction_state)
	annotated, _ = annotate_feed_with_ticker_resolution_state(annotated, ticker_resolution_state)
	annotated, _ = annotate_feed_with_ticker_posture_state(annotated, ticker_posture_state)
	annotated, _ = annotate_feed_with_ticker_attention_state(annotated, ticker_attention_state)
	return annotated


def _hydrate_feed_story_state(
	feed: list[dict[str, Any]],
	*,
	cfg: Any | None = None,
	now: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
	story_state = build_live_story_state_from_feed(
		feed,
		now=now,
		ttl_s=float(getattr(cfg, "live_story_ttl_s", 7200.0) or 7200.0),
		cooldown_s=float(getattr(cfg, "live_story_cooldown_s", 900.0) or 900.0),
	)
	hydrated: list[dict[str, Any]] = []
	for row in feed:
		hydrated_row = dict(row)
		story_key = live_story_key(hydrated_row)
		state = story_state.get(story_key)
		if state is None:
			hydrated.append(hydrated_row)
			continue

		hydrated_row["story_key"] = state["story_key"]
		hydrated_row["story_update_kind"] = str(
			hydrated_row.get("story_update_kind") or state.get("last_action") or "restored"
		)
		hydrated_row["story_first_seen_ts"] = float(
			hydrated_row.get("story_first_seen_ts") or state.get("first_seen_ts") or 0.0
		)
		hydrated_row["story_last_seen_ts"] = float(
			hydrated_row.get("story_last_seen_ts")
			or hydrated_row.get("updated_ts")
			or hydrated_row.get("published_ts")
			or state.get("last_seen_ts")
			or 0.0
		)
		hydrated_row["story_providers_seen"] = list(
			hydrated_row.get("story_providers_seen") or state.get("providers_seen") or []
		)
		hydrated_row["story_best_source"] = str(
			hydrated_row.get("story_best_source") or state.get("best_source") or ""
		)
		hydrated_row["story_best_provider"] = str(
			hydrated_row.get("story_best_provider") or state.get("best_provider") or ""
		)
		hydrated_row["story_cooldown_until"] = float(
			hydrated_row.get("story_cooldown_until") or state.get("cooldown_until") or 0.0
		)
		hydrated_row["story_expires_at"] = float(
			hydrated_row.get("story_expires_at") or state.get("expires_at") or 0.0
		)
		hydrated.append(hydrated_row)
	return dedup_feed_items(hydrated), story_state


def _derive_cursors(feed: list[dict[str, Any]]) -> tuple[str | None, dict[str, str]]:
	timestamps = [
		row.get("updated_ts") or row.get("published_ts") or 0
		for row in feed
	]
	timestamps = [ts for ts in timestamps if isinstance(ts, (int, float)) and ts > 0]
	if not timestamps:
		return None, {}
	legacy_cursor = str(int(max(timestamps)))
	return legacy_cursor, seed_provider_cursors(legacy_cursor)


def build_derived_feed_state(
	feed: list[dict[str, Any]] | None,
	*,
	cfg: Any | None = None,
	previous_reaction_state: dict[str, dict[str, Any]] | None = None,
	previous_resolution_state: dict[str, dict[str, Any]] | None = None,
	rt_quotes: dict[str, dict[str, Any]] | None = None,
	quote_map: dict[str, dict[str, Any]] | None = None,
	now: float | None = None,
	market_hours: bool = True,
) -> DerivedFeedState:
	base_feed = dedup_feed_items(list(feed or []))
	base_feed = _prune_feed(
		base_feed,
		max_age_s=_feed_max_age_s(cfg, market_hours=market_hours),
		now=now,
	)
	hydrated_feed, story_state = _hydrate_feed_story_state(base_feed, cfg=cfg, now=now)
	annotated_feed, ticker_catalyst_state = annotate_feed_with_ticker_catalyst_state(
		hydrated_feed,
		now=now,
	)
	annotated_feed, ticker_reaction_state = annotate_feed_with_ticker_reaction_state(
		annotated_feed,
		rt_quotes=rt_quotes,
		quote_map=quote_map,
		previous_state=previous_reaction_state,
		now=now,
	)
	annotated_feed, ticker_resolution_state = annotate_feed_with_ticker_resolution_state(
		annotated_feed,
		rt_quotes=rt_quotes,
		quote_map=quote_map,
		previous_state=previous_resolution_state,
		now=now,
	)
	annotated_feed, ticker_posture_state = annotate_feed_with_ticker_posture_state(
		annotated_feed,
		now=now,
	)
	annotated_feed, ticker_attention_state = annotate_feed_with_ticker_attention_state(
		annotated_feed,
		now=now,
	)
	legacy_cursor, provider_cursors = _derive_cursors(annotated_feed)
	return DerivedFeedState(
		feed=dedup_feed_items(annotated_feed),
		live_story_state=story_state,
		ticker_catalyst_state=ticker_catalyst_state,
		ticker_reaction_state=ticker_reaction_state,
		ticker_resolution_state=ticker_resolution_state,
		ticker_posture_state=ticker_posture_state,
		ticker_attention_state=ticker_attention_state,
		legacy_cursor=legacy_cursor,
		provider_cursors=provider_cursors,
	)


def restore_feed_state(
	jsonl_path: str,
	*,
	cfg: Any | None = None,
	previous_reaction_state: dict[str, dict[str, Any]] | None = None,
	previous_resolution_state: dict[str, dict[str, Any]] | None = None,
	rt_quotes: dict[str, dict[str, Any]] | None = None,
	quote_map: dict[str, dict[str, Any]] | None = None,
	now: float | None = None,
	market_hours: bool = True,
) -> DerivedFeedState:
	restored = load_jsonl_feed(jsonl_path) if jsonl_path else []
	return build_derived_feed_state(
		restored,
		cfg=cfg,
		previous_reaction_state=previous_reaction_state,
		previous_resolution_state=previous_resolution_state,
		rt_quotes=rt_quotes,
		quote_map=quote_map,
		now=now,
		market_hours=market_hours,
	)


def resync_feed_from_jsonl(
	current_feed: list[dict[str, Any]],
	jsonl_path: str,
	*,
	cfg: Any | None = None,
	previous_reaction_state: dict[str, dict[str, Any]] | None = None,
	previous_resolution_state: dict[str, dict[str, Any]] | None = None,
	rt_quotes: dict[str, dict[str, Any]] | None = None,
	quote_map: dict[str, dict[str, Any]] | None = None,
	now: float | None = None,
	market_hours: bool = True,
) -> DerivedFeedState:
	restored = load_jsonl_feed(jsonl_path) if jsonl_path else []
	if not restored:
		result = build_derived_feed_state(
			current_feed,
			cfg=cfg,
			previous_reaction_state=previous_reaction_state,
			previous_resolution_state=previous_resolution_state,
			rt_quotes=rt_quotes,
			quote_map=quote_map,
			now=now,
			market_hours=market_hours,
		)
		result.new_count = 0
		return result

	existing_len = len(current_feed)
	merged = dedup_merge(current_feed, restored)
	merged = dedup_feed_items(merged)
	result = build_derived_feed_state(
		merged,
		cfg=cfg,
		previous_reaction_state=previous_reaction_state,
		previous_resolution_state=previous_resolution_state,
		rt_quotes=rt_quotes,
		quote_map=quote_map,
		now=now,
		market_hours=market_hours,
	)
	result.new_count = max(0, len(result.feed) - existing_len)
	return result


def merge_live_feed_rows(
	current_feed: list[dict[str, Any]],
	new_rows: list[dict[str, Any]],
	*,
	cfg: Any,
	replace_story_keys: list[str] | None = None,
	previous_reaction_state: dict[str, dict[str, Any]] | None = None,
	previous_resolution_state: dict[str, dict[str, Any]] | None = None,
	rt_quotes: dict[str, dict[str, Any]] | None = None,
	quote_map: dict[str, dict[str, Any]] | None = None,
	now: float | None = None,
	market_hours: bool = True,
) -> DerivedFeedState:
	replace_story_key_set = {
		str(story_key).strip()
		for story_key in (replace_story_keys or [])
		if str(story_key).strip()
	}
	raw_new_rows = dedup_feed_items(list(new_rows or []))
	filtered_current = list(current_feed)
	if replace_story_key_set:
		filtered_current = [
			row
			for row in filtered_current
			if _story_key_for_feed_row(row) not in replace_story_key_set
		]

	merged = dedup_feed_items(raw_new_rows + filtered_current)
	max_items = int(getattr(cfg, "max_items", 0) or 0)
	if max_items > 0 and len(merged) > max_items:
		merged = merged[:max_items]

	result = build_derived_feed_state(
		merged,
		cfg=cfg,
		previous_reaction_state=previous_reaction_state,
		previous_resolution_state=previous_resolution_state,
		rt_quotes=rt_quotes,
		quote_map=quote_map,
		now=now,
		market_hours=market_hours,
	)
	result.annotated_new_rows = _annotate_rows_with_states(
		raw_new_rows,
		ticker_catalyst_state=result.ticker_catalyst_state,
		ticker_reaction_state=result.ticker_reaction_state,
		ticker_resolution_state=result.ticker_resolution_state,
		ticker_posture_state=result.ticker_posture_state,
		ticker_attention_state=result.ticker_attention_state,
	)
	result.new_count = len(result.annotated_new_rows)
	return result
