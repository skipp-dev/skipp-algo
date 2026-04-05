"""Pure helpers for stateful live-news story lifecycle management.

The polling layer returns classified items quickly, but the terminal still needs
one more decision layer before alerting or persisting feed rows:

- first arrival should become the operator-facing live story,
- later provider observations may upgrade the same story,
- repeated sightings must not create repeated alerts,
- story state should expire automatically after a bounded TTL.

This module keeps that logic free of Streamlit/session-state side effects so it
can be tested directly.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_LIVE_STORY_TTL_S = 7200.0
DEFAULT_LIVE_STORY_COOLDOWN_S = 900.0
LIVE_STORY_BUCKET_SECONDS = 900
_HEADLINE_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_MATERIALITY_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}


@dataclass(slots=True)
class LiveStoryBatchResult:
    """Result of applying story lifecycle state to one poll batch."""

    story_state: dict[str, dict[str, Any]]
    feed_items: list[Any]
    alert_items: list[Any]
    replace_story_keys: list[str]


def _get_field(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _set_field(item: Any, name: str, value: Any) -> None:
    if isinstance(item, dict):
        item[name] = value
    else:
        setattr(item, name, value)


def _headline_key(headline: str) -> str:
    collapsed = _HEADLINE_NORMALIZE_RE.sub(" ", str(headline or "").lower())
    return " ".join(collapsed.split())


def _provider_priority(provider: str) -> int:
    lowered = str(provider or "").strip().lower()
    if lowered.startswith("benzinga"):
        return 0
    if lowered.startswith("fmp"):
        return 1
    if lowered.startswith("tv_") or lowered == "tradingview":
        return 2
    return 3


def _materiality_weight(materiality: str) -> int:
    return _MATERIALITY_WEIGHT.get(str(materiality or "").strip().upper(), 0)


def _story_timestamp(item: Any) -> float:
    for field_name in ("story_last_seen_ts", "updated_ts", "published_ts"):
        try:
            value = float(_get_field(item, field_name, 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def live_story_key(item: Any, *, bucket_seconds: int = LIVE_STORY_BUCKET_SECONDS) -> str:
    """Return a per-symbol canonical story key.

    Preference order:
    1. Explicit ``story_key`` if already assigned.
    2. ``ticker`` + normalized headline + coarse time bucket.
    3. ``ticker`` + cluster hash + coarse time bucket.
    4. ``ticker`` + item_id as a last resort.
    """
    explicit = str(_get_field(item, "story_key", "") or "").strip()
    if explicit:
        return explicit

    ticker = str(_get_field(item, "ticker", "") or "").strip().upper()
    headline = _headline_key(str(_get_field(item, "headline", "") or ""))
    cluster = str(_get_field(item, "cluster_hash", "") or "").strip().lower()
    item_id = str(_get_field(item, "item_id", "") or "").strip().lower()
    ts = _story_timestamp(item)
    bucket = int(ts // bucket_seconds) if ts > 0 else 0
    base = headline or cluster or item_id or "unknown"
    return f"{ticker}:{base}:{bucket}"


def prune_live_story_state(
    story_state: dict[str, dict[str, Any]] | None,
    *,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    """Drop expired story-state entries."""
    if now is None:
        now = time.time()
    pruned: dict[str, dict[str, Any]] = {}
    for story_key, state in dict(story_state or {}).items():
        expires_at = float(state.get("expires_at", 0.0) or 0.0)
        if expires_at > float(now):
            pruned[str(story_key)] = dict(state)
    return pruned


def _build_state_entry(
    item: Any,
    *,
    story_key: str,
    now: float,
    ttl_s: float,
    cooldown_s: float,
    previous: dict[str, Any] | None = None,
    action: str,
) -> dict[str, Any]:
    previous = dict(previous or {})
    provider = str(_get_field(item, "provider", "") or "").strip()
    source = str(_get_field(item, "source", "") or "").strip()
    source_rank = int(_get_field(item, "source_rank", 99) or 99)
    provider_priority = _provider_priority(provider)
    providers_seen = sorted(
        {
            *[str(value).strip() for value in previous.get("providers_seen", []) if str(value).strip()],
            provider,
        }
    )
    first_seen_ts = float(previous.get("first_seen_ts", 0.0) or 0.0) or float(now)
    last_seen_ts = float(now)
    published_ts = _story_timestamp(item) or float(now)
    current_score = float(_get_field(item, "news_score", 0.0) or 0.0)
    current_materiality = str(_get_field(item, "materiality", "") or "").strip().upper()
    current_actionable = bool(_get_field(item, "is_actionable", False))

    best_source_rank = int(previous.get("best_source_rank", 99) or 99)
    best_provider_priority = int(previous.get("best_provider_priority", 99) or 99)
    best_is_better = (
        source_rank < best_source_rank
        or (source_rank == best_source_rank and provider_priority < best_provider_priority)
    )

    return {
        "story_key": story_key,
        "ticker": str(_get_field(item, "ticker", "") or "").strip().upper(),
        "headline": str(_get_field(item, "headline", "") or "").strip(),
        "item_id": str(_get_field(item, "item_id", "") or "").strip(),
        "first_seen_ts": first_seen_ts,
        "last_seen_ts": last_seen_ts,
        "published_ts": published_ts,
        "providers_seen": providers_seen,
        "best_source": source if best_is_better or not previous else str(previous.get("best_source", source) or source),
        "best_provider": provider if best_is_better or not previous else str(previous.get("best_provider", provider) or provider),
        "best_source_rank": source_rank if best_is_better or not previous else best_source_rank,
        "best_provider_priority": provider_priority if best_is_better or not previous else best_provider_priority,
        "materiality": current_materiality
        if _materiality_weight(current_materiality) >= _materiality_weight(str(previous.get("materiality", "") or ""))
        else str(previous.get("materiality", "") or "").strip().upper(),
        "news_score": max(float(previous.get("news_score", 0.0) or 0.0), current_score),
        "event_label": str(_get_field(item, "event_label", "") or previous.get("event_label", "") or "").strip(),
        "is_actionable": current_actionable or bool(previous.get("is_actionable", False)),
        "cooldown_until": max(
            float(previous.get("cooldown_until", 0.0) or 0.0),
            float(now) + float(cooldown_s),
        ),
        "expires_at": max(
            float(previous.get("expires_at", 0.0) or 0.0),
            max(float(now), published_ts) + float(ttl_s),
        ),
        "last_action": action,
    }


def _annotate_item(item: Any, state: dict[str, Any], *, action: str) -> Any:
    _set_field(item, "story_key", state["story_key"])
    _set_field(item, "story_update_kind", action)
    _set_field(item, "story_first_seen_ts", state["first_seen_ts"])
    _set_field(item, "story_last_seen_ts", state["last_seen_ts"])
    _set_field(item, "story_providers_seen", list(state["providers_seen"]))
    _set_field(item, "story_best_source", state["best_source"])
    _set_field(item, "story_best_provider", state["best_provider"])
    _set_field(item, "story_cooldown_until", state["cooldown_until"])
    _set_field(item, "story_expires_at", state["expires_at"])
    return item


def build_live_story_state_from_feed(
    feed: list[dict[str, Any]] | None,
    *,
    now: float | None = None,
    ttl_s: float = DEFAULT_LIVE_STORY_TTL_S,
    cooldown_s: float = DEFAULT_LIVE_STORY_COOLDOWN_S,
) -> dict[str, dict[str, Any]]:
    """Seed live-story state from an existing feed snapshot."""
    if now is None:
        now = time.time()

    seeded: dict[str, dict[str, Any]] = {}
    ordered_feed = sorted(
        list(feed or []),
        key=lambda row: float(
            row.get("story_last_seen_ts")
            or row.get("updated_ts")
            or row.get("published_ts")
            or 0.0
        ),
    )
    for row in ordered_feed:
        story_key = live_story_key(row)
        previous = seeded.get(story_key)
        action = "upgrade" if previous is not None else "new"
        state = _build_state_entry(
            row,
            story_key=story_key,
            now=float(row.get("story_last_seen_ts") or row.get("updated_ts") or row.get("published_ts") or now),
            ttl_s=ttl_s,
            cooldown_s=cooldown_s,
            previous=previous,
            action=action,
        )
        explicit_first = float(row.get("story_first_seen_ts", 0.0) or 0.0)
        if explicit_first > 0:
            state["first_seen_ts"] = explicit_first
        explicit_cooldown = float(row.get("story_cooldown_until", 0.0) or 0.0)
        if explicit_cooldown > 0:
            state["cooldown_until"] = explicit_cooldown
        explicit_expires = float(row.get("story_expires_at", 0.0) or 0.0)
        if explicit_expires > 0:
            state["expires_at"] = explicit_expires
        explicit_providers = [
            str(value).strip()
            for value in row.get("story_providers_seen", [])
            if str(value).strip()
        ]
        if explicit_providers:
            state["providers_seen"] = sorted(set(explicit_providers))
        explicit_best_source = str(row.get("story_best_source", "") or "").strip()
        if explicit_best_source:
            state["best_source"] = explicit_best_source
        explicit_best_provider = str(row.get("story_best_provider", "") or "").strip()
        if explicit_best_provider:
            state["best_provider"] = explicit_best_provider
            state["best_provider_priority"] = _provider_priority(explicit_best_provider)
        seeded[story_key] = state

    return prune_live_story_state(seeded, now=now)


def apply_live_story_state(
    items: list[Any],
    story_state: dict[str, dict[str, Any]] | None,
    *,
    now: float | None = None,
    ttl_s: float = DEFAULT_LIVE_STORY_TTL_S,
    cooldown_s: float = DEFAULT_LIVE_STORY_COOLDOWN_S,
) -> LiveStoryBatchResult:
    """Apply stateful story lifecycle rules to one incoming batch.

    Rules:
    - first sighting becomes a new feed item and may alert,
    - later stronger sightings become feed replacements but do not alert again,
    - lower-quality repeats only refresh state and provider history,
    - expired stories fall out of state automatically.
    """
    if now is None:
        now = time.time()
    current_state = prune_live_story_state(story_state, now=now)
    feed_items: list[Any] = []
    alert_items: list[Any] = []
    replace_story_keys: list[str] = []

    for item in items:
        story_key = live_story_key(item)
        previous = current_state.get(story_key)
        provider = str(_get_field(item, "provider", "") or "").strip()
        source_rank = int(_get_field(item, "source_rank", 99) or 99)
        provider_priority = _provider_priority(provider)
        score = float(_get_field(item, "news_score", 0.0) or 0.0)
        materiality = str(_get_field(item, "materiality", "") or "").strip().upper()
        is_actionable = bool(_get_field(item, "is_actionable", False))

        if previous is None:
            action = "new"
            state = _build_state_entry(
                item,
                story_key=story_key,
                now=now,
                ttl_s=ttl_s,
                cooldown_s=cooldown_s,
                previous=None,
                action=action,
            )
            current_state[story_key] = state
            annotated = _annotate_item(item, state, action=action)
            feed_items.append(annotated)
            alert_items.append(annotated)
            continue

        previous_providers = {str(value).strip() for value in previous.get("providers_seen", []) if str(value).strip()}
        provider_seen = provider in previous_providers
        better_source = (
            source_rank < int(previous.get("best_source_rank", 99) or 99)
            or (
                source_rank == int(previous.get("best_source_rank", 99) or 99)
                and provider_priority < int(previous.get("best_provider_priority", 99) or 99)
            )
        )
        stronger_materiality = _materiality_weight(materiality) > _materiality_weight(str(previous.get("materiality", "") or ""))
        stronger_score = score > float(previous.get("news_score", 0.0) or 0.0) + 1e-6
        actionable_upgrade = is_actionable and not bool(previous.get("is_actionable", False))
        display_upgrade = better_source or stronger_materiality or stronger_score or actionable_upgrade
        action = "upgrade" if display_upgrade else ("provider_seen" if not provider_seen else "repeat")

        state = _build_state_entry(
            item,
            story_key=story_key,
            now=now,
            ttl_s=ttl_s,
            cooldown_s=cooldown_s,
            previous=previous,
            action=action,
        )
        current_state[story_key] = state
        annotated = _annotate_item(item, state, action=action)
        if display_upgrade:
            replace_story_keys.append(story_key)
            feed_items.append(annotated)

    return LiveStoryBatchResult(
        story_state=current_state,
        feed_items=feed_items,
        alert_items=alert_items,
        replace_story_keys=sorted(set(replace_story_keys)),
    )