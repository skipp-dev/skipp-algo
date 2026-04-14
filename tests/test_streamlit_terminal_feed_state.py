from __future__ import annotations

from dataclasses import dataclass

import terminal_feed_state as feed_state_module
from terminal_feed_state import build_derived_feed_state, hydrate_feed_story_state


@dataclass(slots=True)
class _Cfg:
    feed_max_age_s: float = 14400.0
    live_story_ttl_s: float = 7200.0
    live_story_cooldown_s: float = 900.0


def _row(**overrides):
    row = {
        "item_id": "item-1",
        "ticker": "AAPL",
        "headline": "Apple launches enterprise AI suite",
        "provider": "benzinga_rest",
        "source": "Benzinga",
        "source_rank": 1,
        "news_score": 0.92,
        "materiality": "HIGH",
        "published_ts": 1000.0,
        "updated_ts": 1000.0,
        "sentiment_label": "bullish",
        "event_label": "product",
        "is_actionable": True,
    }
    row.update(overrides)
    return row


def test_build_derived_feed_state_handles_empty_feed() -> None:
    result = build_derived_feed_state([], cfg=_Cfg(), now=1500.0)

    assert result.feed == []
    assert result.live_story_state == {}
    assert result.ticker_catalyst_state == {}
    assert result.ticker_reaction_state == {}
    assert result.ticker_resolution_state == {}
    assert result.ticker_posture_state == {}
    assert result.ticker_attention_state == {}
    assert result.provider_cursors == {}
    assert result.legacy_cursor is None


def test_hydrate_feed_story_state_deduplicates_duplicate_rows() -> None:
    first = _row(item_id="item-1", story_key="story-1")
    duplicate = _row(item_id="item-2", story_key="story-1", headline="Duplicate story")

    hydrated, story_state = hydrate_feed_story_state([first, duplicate], cfg=_Cfg(), now=1500.0)

    assert len(hydrated) == 1
    assert "story-1" in story_state
    assert hydrated[0]["story_key"] == "story-1"


def test_hydrate_feed_story_state_handles_corrupt_story_state(monkeypatch) -> None:
    row = _row(story_key="story-1")

    monkeypatch.setattr(
        feed_state_module,
        "build_live_story_state_from_feed",
        lambda *_args, **_kwargs: {
            "story-1": {
                "story_key": "story-1",
                "last_action": "restored",
                "first_seen_ts": "bad-float",
                "last_seen_ts": None,
                "providers_seen": "benzinga_rest",
                "best_source": "Benzinga",
                "best_provider": "benzinga_rest",
                "cooldown_until": "bad-float",
                "expires_at": object(),
            }
        },
    )

    hydrated, story_state = hydrate_feed_story_state([row], cfg=_Cfg(), now=1500.0)

    assert len(hydrated) == 1
    assert story_state["story-1"]["story_key"] == "story-1"
    assert hydrated[0]["story_first_seen_ts"] == 0.0
    assert hydrated[0]["story_last_seen_ts"] == 1000.0
    assert hydrated[0]["story_providers_seen"] == []
    assert hydrated[0]["story_cooldown_until"] == 0.0
    assert hydrated[0]["story_expires_at"] == 0.0