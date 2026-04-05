from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_catalyst_state import (
    annotate_feed_with_ticker_catalyst_state,
    build_ticker_catalyst_state,
    effective_catalyst_actionable,
    effective_catalyst_age_minutes,
    effective_catalyst_score,
    effective_catalyst_sentiment,
)


def _row(
    *,
    ticker: str = "AAPL",
    story_key: str,
    news_score: float,
    sentiment_label: str,
    provider: str,
    source: str,
    source_rank: int,
    materiality: str,
    updated_ts: float,
    story_last_seen_ts: float | None = None,
    story_providers_seen: list[str] | None = None,
    story_best_provider: str | None = None,
    story_best_source: str | None = None,
    story_expires_at: float | None = 5000.0,
    headline: str | None = None,
    is_actionable: bool = False,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "story_key": story_key,
        "headline": headline or f"{ticker} catalyst {story_key}",
        "news_score": news_score,
        "sentiment_label": sentiment_label,
        "provider": provider,
        "source": source,
        "source_rank": source_rank,
        "materiality": materiality,
        "updated_ts": updated_ts,
        "published_ts": updated_ts,
        "story_last_seen_ts": story_last_seen_ts or updated_ts,
        "story_providers_seen": story_providers_seen or [provider],
        "story_best_provider": story_best_provider or provider,
        "story_best_source": story_best_source or source,
        "story_expires_at": story_expires_at,
        "is_actionable": is_actionable,
    }


def test_build_ticker_catalyst_state_aggregates_story_strength() -> None:
    feed = [
        _row(
            story_key="story-a",
            news_score=0.62,
            sentiment_label="bullish",
            provider="fmp_stock",
            source="FMP",
            source_rank=3,
            materiality="MEDIUM",
            updated_ts=990.0,
        ),
        _row(
            story_key="story-b",
            news_score=0.84,
            sentiment_label="bullish",
            provider="benzinga_rest",
            source="Benzinga",
            source_rank=1,
            materiality="HIGH",
            updated_ts=999.0,
            story_providers_seen=["benzinga_rest", "tradingview"],
            is_actionable=True,
        ),
    ]

    state = build_ticker_catalyst_state(feed, now=1000.0)

    assert state["AAPL"]["catalyst_direction"] == "BULLISH"
    assert state["AAPL"]["catalyst_story_count"] == 2
    assert state["AAPL"]["catalyst_provider_count"] == 3
    assert state["AAPL"]["catalyst_best_story_key"] == "story-b"
    assert state["AAPL"]["catalyst_best_provider"] == "benzinga_rest"
    assert state["AAPL"]["catalyst_score"] == pytest.approx(1.0)
    assert state["AAPL"]["catalyst_actionable"] is True


def test_build_ticker_catalyst_state_marks_conflict_non_actionable() -> None:
    feed = [
        _row(
            story_key="bull",
            news_score=0.90,
            sentiment_label="bullish",
            provider="benzinga_rest",
            source="Benzinga",
            source_rank=1,
            materiality="HIGH",
            updated_ts=999.0,
        ),
        _row(
            story_key="bear",
            news_score=0.88,
            sentiment_label="bearish",
            provider="fmp_press",
            source="FMP",
            source_rank=1,
            materiality="HIGH",
            updated_ts=998.0,
        ),
    ]

    state = build_ticker_catalyst_state(feed, now=1000.0)

    assert state["AAPL"]["catalyst_conflict"] is True
    assert state["AAPL"]["catalyst_direction"] == "MIXED"
    assert state["AAPL"]["catalyst_actionable"] is False
    assert state["AAPL"]["catalyst_score"] < 0.9


def test_build_ticker_catalyst_state_skips_expired_rows() -> None:
    feed = [
        _row(
            story_key="expired",
            news_score=0.95,
            sentiment_label="bullish",
            provider="benzinga_rest",
            source="Benzinga",
            source_rank=1,
            materiality="HIGH",
            updated_ts=800.0,
            story_expires_at=900.0,
        ),
        _row(
            ticker="MSFT",
            story_key="active",
            news_score=0.70,
            sentiment_label="bullish",
            provider="fmp_stock",
            source="FMP",
            source_rank=2,
            materiality="MEDIUM",
            updated_ts=995.0,
        ),
    ]

    state = build_ticker_catalyst_state(feed, now=1000.0)

    assert "AAPL" not in state
    assert state["MSFT"]["catalyst_story_count"] == 1


def test_annotate_feed_and_effective_helpers_prefer_catalyst_values() -> None:
    feed = [
        _row(
            story_key="story-a",
            news_score=0.40,
            sentiment_label="neutral",
            provider="fmp_stock",
            source="FMP",
            source_rank=3,
            materiality="MEDIUM",
            updated_ts=995.0,
        ),
    ]

    annotated, state = annotate_feed_with_ticker_catalyst_state(feed, now=1000.0)

    assert annotated[0]["catalyst_score"] == state["AAPL"]["catalyst_score"]
    assert effective_catalyst_score(annotated[0]) == pytest.approx(state["AAPL"]["catalyst_score"])
    assert effective_catalyst_sentiment({"catalyst_direction": "BEARISH", "sentiment_label": "bullish"}) == "bearish"
    assert effective_catalyst_age_minutes({"catalyst_age_minutes": 7.5, "age_minutes": 30.0}) == pytest.approx(7.5)
    assert effective_catalyst_actionable({"catalyst_actionable": True, "news_score": 0.1}) is True