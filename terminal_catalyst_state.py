"""Pure helpers for per-ticker live catalyst state.

The live story layer tracks canonical stories, but the terminal still needs a
second derived view at the ticker level so rankings, actionable filters, and
outbound alerting can react to the current catalyst picture instead of a single
raw story row.
"""

from __future__ import annotations

import time
from typing import Any

from terminal_live_story_state import live_story_key


_MATERIALITY_BONUS = {
    "LOW": 0.00,
    "MEDIUM": 0.08,
    "HIGH": 0.15,
}
_SOURCE_RANK_BONUS = {
    1: 0.10,
    2: 0.06,
    3: 0.03,
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


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _story_timestamp(row: dict[str, Any]) -> float:
    for field_name in ("story_last_seen_ts", "updated_ts", "published_ts"):
        value = _safe_float(row.get(field_name), 0.0)
        if value > 0:
            return value
    return 0.0


def _story_age_minutes(row: dict[str, Any], *, now: float) -> float | None:
    timestamp = _story_timestamp(row)
    if timestamp <= 0:
        explicit = row.get("age_minutes")
        if explicit is None:
            return None
        return _safe_float(explicit, 0.0)
    return max((float(now) - timestamp) / 60.0, 0.0)


def _freshness_bucket(age_minutes: float | None) -> str:
    if age_minutes is None:
        return "UNKNOWN"
    if age_minutes <= 15.0:
        return "ULTRA_FRESH"
    if age_minutes <= 60.0:
        return "FRESH"
    if age_minutes <= 240.0:
        return "WARM"
    if age_minutes <= 1440.0:
        return "AGING"
    return "STALE"


def _freshness_weight(age_minutes: float | None) -> float:
    bucket = _freshness_bucket(age_minutes)
    if bucket == "ULTRA_FRESH":
        return 1.00
    if bucket == "FRESH":
        return 0.92
    if bucket == "WARM":
        return 0.78
    if bucket == "AGING":
        return 0.58
    if bucket == "STALE":
        return 0.35
    return 0.50


def _providers_seen_count(row: dict[str, Any]) -> int:
    raw = row.get("story_providers_seen") or []
    if not isinstance(raw, list):
        return 0
    return len({str(value).strip() for value in raw if str(value).strip()})


def _story_strength(row: dict[str, Any], *, now: float) -> float:
    base_score = min(max(_safe_float(row.get("news_score"), 0.0), 0.0), 1.0)
    materiality = str(row.get("materiality") or "").strip().upper()
    source_rank = _safe_int(row.get("source_rank"), 99)
    providers_seen = _providers_seen_count(row)
    age_minutes = _story_age_minutes(row, now=now)
    story_score = min(
        1.0,
        base_score
        + _MATERIALITY_BONUS.get(materiality, 0.0)
        + _SOURCE_RANK_BONUS.get(source_rank, 0.0)
        + min(max(providers_seen - 1, 0), 3) * 0.04,
    )
    return round(min(1.0, story_score * _freshness_weight(age_minutes)), 6)


def _story_sentiment(row: dict[str, Any]) -> str:
    sentiment = str(row.get("sentiment_label") or "").strip().lower()
    if sentiment in {"bullish", "bearish", "neutral"}:
        return sentiment
    direction = str(row.get("catalyst_direction") or "").strip().upper()
    if direction == "BULLISH":
        return "bullish"
    if direction == "BEARISH":
        return "bearish"
    return "neutral"


def _state_priority(row: dict[str, Any], *, now: float) -> tuple[float, float, int, float]:
    return (
        _story_strength(row, now=now),
        _safe_float(row.get("news_score"), 0.0),
        -_safe_int(row.get("source_rank"), 99),
        _story_timestamp(row),
    )


def effective_catalyst_score(item: Any) -> float:
    catalyst_score = _get_field(item, "catalyst_score", None)
    if catalyst_score is not None:
        return _safe_float(catalyst_score, 0.0)
    return _safe_float(_get_field(item, "news_score", 0.0), 0.0)


def effective_catalyst_sentiment(item: Any) -> str:
    catalyst_direction = str(_get_field(item, "catalyst_direction", "") or "").strip().upper()
    if catalyst_direction == "BULLISH":
        return "bullish"
    if catalyst_direction == "BEARISH":
        return "bearish"
    if catalyst_direction in {"NEUTRAL", "MIXED"}:
        return "neutral"
    sentiment = str(_get_field(item, "sentiment_label", "neutral") or "neutral").strip().lower()
    if sentiment in {"bullish", "bearish", "neutral"}:
        return sentiment
    return "neutral"


def effective_catalyst_age_minutes(item: Any, *, now: float | None = None) -> float | None:
    catalyst_age = _get_field(item, "catalyst_age_minutes", None)
    if catalyst_age is not None:
        return _safe_float(catalyst_age, 0.0)

    age = _get_field(item, "age_minutes", None)
    if age is not None:
        return _safe_float(age, 0.0)

    if now is None:
        now = time.time()
    timestamp = 0.0
    for field_name in ("published_ts", "updated_ts", "story_last_seen_ts"):
        value = _safe_float(_get_field(item, field_name, 0.0), 0.0)
        if value > 0:
            timestamp = value
            break
    if timestamp <= 0:
        return None
    return max((float(now) - timestamp) / 60.0, 0.0)


def effective_catalyst_actionable(item: Any, *, now: float | None = None) -> bool:
    catalyst_actionable = _get_field(item, "catalyst_actionable", None)
    if catalyst_actionable is not None:
        return bool(catalyst_actionable)

    raw_actionable = _get_field(item, "is_actionable", False)
    if raw_actionable:
        return True

    score = effective_catalyst_score(item)
    age_minutes = effective_catalyst_age_minutes(item, now=now)
    if score >= 0.65:
        return True
    if age_minutes is not None and age_minutes <= 1440.0 and score >= 0.45:
        return True
    return False


def build_ticker_catalyst_state(
    feed: list[dict[str, Any]] | None,
    *,
    now: float | None = None,
) -> dict[str, dict[str, Any]]:
    if now is None:
        now = time.time()

    story_rows_by_ticker: dict[str, dict[str, dict[str, Any]]] = {}
    for row in feed or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker or ticker == "MARKET":
            continue

        expires_at = _safe_float(row.get("story_expires_at"), 0.0)
        if expires_at > 0.0 and expires_at <= float(now):
            continue

        story_key = str(row.get("story_key") or "").strip() or live_story_key(row)
        ticker_story_rows = story_rows_by_ticker.setdefault(ticker, {})
        previous = ticker_story_rows.get(story_key)
        if previous is None or _state_priority(row, now=now) > _state_priority(previous, now=now):
            ticker_story_rows[story_key] = dict(row)

    ticker_state: dict[str, dict[str, Any]] = {}
    for ticker, story_rows in story_rows_by_ticker.items():
        rows = list(story_rows.values())
        if not rows:
            continue

        positive_strength = 0.0
        negative_strength = 0.0
        neutral_strength = 0.0
        provider_union: set[str] = set()
        best_row = rows[0]
        best_strength = _story_strength(best_row, now=now)
        latest_story_ts = 0.0
        expires_at = 0.0

        for row in rows:
            row_strength = _story_strength(row, now=now)
            sentiment = _story_sentiment(row)
            if sentiment == "bullish":
                positive_strength += row_strength
            elif sentiment == "bearish":
                negative_strength += row_strength
            else:
                neutral_strength += row_strength

            latest_story_ts = max(latest_story_ts, _story_timestamp(row))
            expires_at = max(expires_at, _safe_float(row.get("story_expires_at"), 0.0))
            providers = row.get("story_providers_seen") or []
            if isinstance(providers, list):
                provider_union.update(str(value).strip() for value in providers if str(value).strip())
            elif row.get("provider"):
                provider_union.add(str(row.get("provider") or "").strip())

            if row_strength > best_strength or (
                abs(row_strength - best_strength) < 1e-9 and _story_timestamp(row) > _story_timestamp(best_row)
            ):
                best_row = row
                best_strength = row_strength

        directional_total = positive_strength + negative_strength
        net_strength = positive_strength - negative_strength
        conflict = positive_strength >= 0.35 and negative_strength >= 0.35
        if conflict and abs(net_strength) < 0.18:
            direction = "MIXED"
        elif net_strength > 0.10:
            direction = "BULLISH"
        elif net_strength < -0.10:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        corroboration_bonus = min(max(len(rows) - 1, 0), 2) * 0.05
        provider_bonus = min(max(len(provider_union) - 1, 0), 3) * 0.03
        score = min(1.0, best_strength + corroboration_bonus + provider_bonus)
        if conflict:
            score *= 0.80
        if direction == "MIXED":
            score *= 0.85

        best_source_rank = _safe_int(best_row.get("source_rank"), 99)
        confidence = 0.35
        confidence += max(0, 5 - min(best_source_rank, 5)) * 0.10
        confidence += min(len(provider_union), 3) * 0.06
        if direction in {"BULLISH", "BEARISH"}:
            confidence += 0.12
        if conflict:
            confidence -= 0.18
        confidence = min(max(confidence, 0.0), 1.0)

        age_minutes = _story_age_minutes(best_row, now=now)
        freshness = _freshness_bucket(age_minutes)
        best_story_actionable = bool(best_row.get("is_actionable", False))
        actionable = bool(
            direction in {"BULLISH", "BEARISH"}
            and not conflict
            and age_minutes is not None
            and age_minutes <= 240.0
            and (
                best_story_actionable
                or score >= 0.78
                or (score >= 0.65 and age_minutes <= 60.0)
            )
        )

        ticker_state[ticker] = {
            "ticker": ticker,
            "catalyst_score": round(score, 6),
            "catalyst_direction": direction,
            "catalyst_confidence": round(confidence, 6),
            "catalyst_freshness": freshness,
            "catalyst_story_count": len(rows),
            "catalyst_provider_count": len(provider_union),
            "catalyst_best_story_key": str(best_row.get("story_key") or "").strip() or live_story_key(best_row),
            "catalyst_best_provider": str(best_row.get("story_best_provider") or best_row.get("provider") or "").strip(),
            "catalyst_best_source": str(best_row.get("story_best_source") or best_row.get("source") or "").strip(),
            "catalyst_headline": str(best_row.get("story_headline") or best_row.get("headline") or "").strip(),
            "catalyst_actionable": actionable,
            "catalyst_age_minutes": round(age_minutes, 3) if age_minutes is not None else None,
            "catalyst_last_update_ts": latest_story_ts,
            "catalyst_expires_at": expires_at or None,
            "catalyst_conflict": conflict,
        }

    return ticker_state


def annotate_feed_with_ticker_catalyst_state(
    feed: list[dict[str, Any]] | None,
    ticker_state: dict[str, dict[str, Any]] | None = None,
    *,
    now: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if now is None:
        now = time.time()
    resolved_state = ticker_state or build_ticker_catalyst_state(feed, now=now)
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