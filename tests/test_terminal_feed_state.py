from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_feed_state import restore_feed_state, resync_feed_from_jsonl
from terminal_live_story_state import live_story_key


@dataclass(slots=True)
class _Cfg:
    feed_max_age_s: float = 14400.0
    live_story_ttl_s: float = 7200.0
    live_story_cooldown_s: float = 900.0
    max_items: int = 50


def _story_row(
    *,
    item_id: str,
    ticker: str,
    headline: str,
    provider: str,
    source: str,
    source_rank: int,
    news_score: float,
    materiality: str,
    published_ts: float,
    updated_ts: float,
    sentiment_label: str = "bullish",
    story_key: str | None = None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "item_id": item_id,
        "ticker": ticker,
        "headline": headline,
        "provider": provider,
        "source": source,
        "source_rank": source_rank,
        "news_score": news_score,
        "materiality": materiality,
        "published_ts": published_ts,
        "updated_ts": updated_ts,
        "sentiment_label": sentiment_label,
        "event_label": "product",
        "is_actionable": True,
    }
    if story_key:
        row["story_key"] = story_key
    return row


def _reaction_state_for(row: dict[str, object], *, anchor_price: float = 100.0) -> dict[str, dict[str, object]]:
    story_key = live_story_key(row)
    ticker = str(row["ticker"])
    return {
        ticker: {
            "reaction_state": "CONFIRMED",
            "reaction_score": 0.86,
            "reaction_confidence": 0.76,
            "reaction_actionable": True,
            "reaction_anchor_story_key": story_key,
            "reaction_anchor_price": anchor_price,
            "reaction_anchor_ts": 900.0,
            "reaction_peak_impulse_pct": 1.3,
            "catalyst_direction": "BULLISH",
        },
    }


def _resolution_state_for(row: dict[str, object], *, anchor_price: float = 100.0) -> dict[str, dict[str, object]]:
    story_key = live_story_key(row)
    ticker = str(row["ticker"])
    return {
        ticker: {
            "resolution_state": "OPEN",
            "resolution_anchor_story_key": story_key,
            "resolution_anchor_price": anchor_price,
            "resolution_anchor_ts": 900.0,
            "resolution_peak_impulse_pct": 1.3,
            "resolution_last_update_ts": 950.0,
            "catalyst_direction": "BULLISH",
        },
    }


def test_restore_feed_state_hydrates_story_reaction_and_resolution(tmp_path: Path) -> None:
    row = _story_row(
        item_id="aapl-1",
        ticker="AAPL",
        headline="Apple launches enterprise AI suite",
        provider="benzinga_rest",
        source="Benzinga",
        source_rank=1,
        news_score=0.92,
        materiality="HIGH",
        published_ts=1000.0,
        updated_ts=1000.0,
    )
    path = tmp_path / "feed.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    result = restore_feed_state(
        str(path),
        cfg=_Cfg(),
        previous_reaction_state=_reaction_state_for(row),
        previous_resolution_state=_resolution_state_for(row),
        rt_quotes={"AAPL": {"price": 101.0, "chg_pct": 1.0, "vol_ratio": 1.8}},
        now=1500.0,
    )

    story_key = live_story_key(row)
    assert len(result.feed) == 1
    assert result.feed[0]["story_key"] == story_key
    assert story_key in result.live_story_state
    assert result.ticker_reaction_state["AAPL"]["reaction_state"] == "CONFIRMED"
    assert result.ticker_resolution_state["AAPL"]["resolution_state"] == "FOLLOW_THROUGH"
    assert result.ticker_posture_state["AAPL"]["posture_state"] == "LONG"
    assert result.ticker_attention_state["AAPL"]["attention_state"] == "ALERT"
    assert result.feed[0]["attention_state"] == "ALERT"
    assert result.provider_cursors["benzinga"] == "1000"
    assert result.legacy_cursor == "1000"


def test_resync_feed_from_jsonl_adds_missing_persisted_rows(tmp_path: Path) -> None:
    current = _story_row(
        item_id="aapl-1",
        ticker="AAPL",
        headline="Apple launches enterprise AI suite",
        provider="benzinga_rest",
        source="Benzinga",
        source_rank=1,
        news_score=0.92,
        materiality="HIGH",
        published_ts=1000.0,
        updated_ts=1000.0,
    )
    missing = _story_row(
        item_id="msft-1",
        ticker="MSFT",
        headline="Microsoft expands Azure AI contracts",
        provider="fmp_press",
        source="FMP",
        source_rank=1,
        news_score=0.81,
        materiality="HIGH",
        published_ts=1010.0,
        updated_ts=1010.0,
    )
    path = tmp_path / "feed.jsonl"
    path.write_text(
        json.dumps(current) + "\n" + json.dumps(missing) + "\n",
        encoding="utf-8",
    )

    result = resync_feed_from_jsonl(
        [current],
        str(path),
        cfg=_Cfg(),
        previous_reaction_state={**_reaction_state_for(current), **_reaction_state_for(missing)},
        previous_resolution_state={**_resolution_state_for(current), **_resolution_state_for(missing)},
        rt_quotes={
            "AAPL": {"price": 101.0, "chg_pct": 1.0, "vol_ratio": 1.8},
            "MSFT": {"price": 102.0, "chg_pct": 2.0, "vol_ratio": 1.9},
        },
        now=1500.0,
    )

    assert result.new_count == 1
    assert {row["ticker"] for row in result.feed} == {"AAPL", "MSFT"}
    assert result.ticker_reaction_state["MSFT"]["reaction_state"] == "CONFIRMED"
    assert result.ticker_resolution_state["MSFT"]["resolution_state"] == "FOLLOW_THROUGH"
    assert result.ticker_posture_state["MSFT"]["posture_state"] == "LONG"
    assert result.ticker_attention_state["MSFT"]["attention_state"] == "ALERT"