from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_export import load_jsonl_feed
from terminal_live_story_state import (
    apply_live_story_state,
    build_live_story_state_from_feed,
    live_story_key,
)


def _story_item(
    *,
    item_id: str,
    provider: str,
    source: str,
    source_rank: int,
    news_score: float,
    materiality: str,
    updated_ts: float,
    headline: str = "Apple launches enterprise AI suite",
    ticker: str = "AAPL",
    published_ts: float = 1000.0,
    is_actionable: bool = True,
) -> dict[str, object]:
    return {
        "item_id": item_id,
        "ticker": ticker,
        "headline": headline,
        "provider": provider,
        "source": source,
        "source_rank": source_rank,
        "news_score": news_score,
        "materiality": materiality,
        "is_actionable": is_actionable,
        "published_ts": published_ts,
        "updated_ts": updated_ts,
        "event_label": "product",
    }


def test_apply_live_story_state_upgrade_replaces_without_second_alert() -> None:
    first = _story_item(
        item_id="fmp-1",
        provider="fmp_stock",
        source="FMP",
        source_rank=3,
        news_score=0.58,
        materiality="MEDIUM",
        updated_ts=1000.0,
    )

    first_result = apply_live_story_state([dict(first)], {}, now=1005.0)

    assert len(first_result.feed_items) == 1
    assert len(first_result.alert_items) == 1
    assert first_result.replace_story_keys == []

    story_key = first_result.feed_items[0]["story_key"]

    upgrade = _story_item(
        item_id="bz-1",
        provider="benzinga_rest",
        source="Benzinga",
        source_rank=1,
        news_score=0.91,
        materiality="HIGH",
        updated_ts=1050.0,
    )

    second_result = apply_live_story_state(
        [dict(upgrade)],
        first_result.story_state,
        now=1055.0,
    )

    assert len(second_result.feed_items) == 1
    assert len(second_result.alert_items) == 0
    assert second_result.replace_story_keys == [story_key]

    upgraded_item = second_result.feed_items[0]
    assert upgraded_item["story_key"] == story_key
    assert upgraded_item["story_update_kind"] == "upgrade"
    assert upgraded_item["story_best_provider"] == "benzinga_rest"
    assert upgraded_item["story_best_source"] == "Benzinga"
    assert set(upgraded_item["story_providers_seen"]) == {"benzinga_rest", "fmp_stock"}


def test_apply_live_story_state_repeat_only_refreshes_state() -> None:
    first = _story_item(
        item_id="fmp-1",
        provider="fmp_stock",
        source="FMP",
        source_rank=3,
        news_score=0.58,
        materiality="MEDIUM",
        updated_ts=1000.0,
    )
    seeded = apply_live_story_state([dict(first)], {}, now=1005.0)

    repeat = _story_item(
        item_id="fmp-2",
        provider="fmp_stock",
        source="FMP",
        source_rank=3,
        news_score=0.58,
        materiality="MEDIUM",
        updated_ts=1060.0,
    )
    result = apply_live_story_state([dict(repeat)], seeded.story_state, now=1065.0)

    assert result.feed_items == []
    assert result.alert_items == []

    state = result.story_state[live_story_key(repeat)]
    assert state["last_action"] == "repeat"
    assert state["last_seen_ts"] == pytest.approx(1065.0)
    assert state["best_provider"] == "fmp_stock"


def test_build_live_story_state_from_feed_collapses_mixed_legacy_and_upgraded_rows() -> None:
    legacy_row = _story_item(
        item_id="fmp-1",
        provider="fmp_stock",
        source="FMP",
        source_rank=3,
        news_score=0.58,
        materiality="MEDIUM",
        updated_ts=1000.0,
    )
    upgraded_row = _story_item(
        item_id="bz-1",
        provider="benzinga_rest",
        source="Benzinga",
        source_rank=1,
        news_score=0.91,
        materiality="HIGH",
        updated_ts=1050.0,
    )
    upgraded_row["story_key"] = live_story_key(legacy_row)

    state = build_live_story_state_from_feed([legacy_row, upgraded_row], now=1100.0)

    assert list(state) == [live_story_key(legacy_row)]
    assert state[live_story_key(legacy_row)]["best_provider"] == "benzinga_rest"
    assert set(state[live_story_key(legacy_row)]["providers_seen"]) == {
        "benzinga_rest",
        "fmp_stock",
    }


def test_load_jsonl_feed_story_key_is_newest_wins(tmp_path: Path) -> None:
    path = tmp_path / "feed.jsonl"
    older = _story_item(
        item_id="fmp-1",
        provider="fmp_stock",
        source="FMP",
        source_rank=3,
        news_score=0.58,
        materiality="MEDIUM",
        updated_ts=1000.0,
    )
    story_key = live_story_key(older)
    older["story_key"] = story_key

    newer = _story_item(
        item_id="bz-1",
        provider="benzinga_rest",
        source="Benzinga",
        source_rank=1,
        news_score=0.91,
        materiality="HIGH",
        updated_ts=1050.0,
    )
    newer["story_key"] = story_key

    path.write_text(
        json.dumps(older) + "\n" + json.dumps(newer) + "\n",
        encoding="utf-8",
    )

    loaded = load_jsonl_feed(str(path))

    assert len(loaded) == 1
    assert loaded[0]["item_id"] == "bz-1"
    assert loaded[0]["story_key"] == story_key