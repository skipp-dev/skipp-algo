from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_reaction_state import (
    annotate_feed_with_ticker_reaction_state,
    build_ticker_reaction_state,
    effective_reaction_actionable,
    effective_reaction_priority,
    effective_reaction_score,
    effective_reaction_state,
)


def _row(
    *,
    ticker: str = "AAPL",
    story_key: str = "story-a",
    catalyst_direction: str = "BULLISH",
    catalyst_score: float = 0.82,
    catalyst_actionable: bool = True,
    catalyst_confidence: float = 0.7,
    catalyst_conflict: bool = False,
    updated_ts: float = 995.0,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "story_key": story_key,
        "catalyst_best_story_key": story_key,
        "catalyst_direction": catalyst_direction,
        "catalyst_score": catalyst_score,
        "catalyst_actionable": catalyst_actionable,
        "catalyst_confidence": catalyst_confidence,
        "catalyst_conflict": catalyst_conflict,
        "catalyst_last_update_ts": updated_ts,
        "published_ts": updated_ts,
        "updated_ts": updated_ts,
        "sentiment_label": "bullish" if catalyst_direction == "BULLISH" else "bearish",
    }


def test_build_ticker_reaction_state_confirms_rt_price_and_volume() -> None:
    state = build_ticker_reaction_state(
        [_row()],
        rt_quotes={
            "AAPL": {
                "price": 101.5,
                "chg_pct": 1.5,
                "vol_ratio": 1.8,
            },
        },
        previous_state={
            "AAPL": {
                "reaction_state": "WATCH",
                "reaction_anchor_story_key": "story-a",
                "reaction_anchor_price": 100.0,
                "reaction_anchor_ts": 990.0,
                "reaction_peak_impulse_pct": 0.5,
                "catalyst_direction": "BULLISH",
            },
        },
        now=1000.0,
    )

    assert state["AAPL"]["reaction_state"] == "CONFIRMED"
    assert state["AAPL"]["reaction_source"] == "rt"
    assert state["AAPL"]["reaction_alignment"] == "ALIGNED"
    assert state["AAPL"]["reaction_actionable"] is True
    assert state["AAPL"]["reaction_score"] > 0.82


def test_build_ticker_reaction_state_uses_databento_as_watch_fallback() -> None:
    state = build_ticker_reaction_state(
        [
            _row(
                ticker="MSFT",
                story_key="story-b",
                catalyst_direction="BEARISH",
                catalyst_score=0.78,
            ),
        ],
        quote_map={
            "MSFT": {
                "price": 97.0,
                "changesPercentage": -1.2,
            },
        },
        previous_state={
            "MSFT": {
                "reaction_anchor_story_key": "story-b",
                "reaction_anchor_price": 100.0,
                "reaction_anchor_ts": 990.0,
                "reaction_peak_impulse_pct": -0.4,
                "catalyst_direction": "BEARISH",
            },
        },
        now=1000.0,
    )

    assert state["MSFT"]["reaction_state"] == "WATCH"
    assert state["MSFT"]["reaction_source"] == "databento"
    assert state["MSFT"]["reaction_actionable"] is True
    assert state["MSFT"]["reaction_alignment"] == "ALIGNED"


def test_build_ticker_reaction_state_marks_conflicted_and_fade() -> None:
    conflicted = build_ticker_reaction_state(
        [_row(catalyst_conflict=True)],
        rt_quotes={"AAPL": {"price": 100.2, "chg_pct": 0.2, "vol_ratio": 1.0}},
        now=1000.0,
    )
    assert conflicted["AAPL"]["reaction_state"] == "CONFLICTED"

    faded = build_ticker_reaction_state(
        [_row()],
        rt_quotes={"AAPL": {"price": 100.4, "chg_pct": 0.4, "vol_ratio": 1.1}},
        previous_state={
            "AAPL": {
                "reaction_state": "CONFIRMED",
                "reaction_anchor_story_key": "story-a",
                "reaction_anchor_price": 100.0,
                "reaction_anchor_ts": 990.0,
                "reaction_peak_impulse_pct": 2.0,
                "catalyst_direction": "BULLISH",
            },
        },
        now=1000.0,
    )
    assert faded["AAPL"]["reaction_state"] == "FADE"
    assert faded["AAPL"]["reaction_actionable"] is False


def test_annotate_feed_and_effective_helpers_prefer_reaction_values() -> None:
    annotated, state = annotate_feed_with_ticker_reaction_state(
        [_row()],
        ticker_state={
            "AAPL": {
                "reaction_state": "WATCH",
                "reaction_alignment": "ALIGNED",
                "reaction_score": 0.88,
                "reaction_actionable": True,
            },
        },
        now=1000.0,
    )

    assert annotated[0]["reaction_state"] == "WATCH"
    assert state["AAPL"]["reaction_score"] == pytest.approx(0.88)
    assert effective_reaction_state(annotated[0]) == "WATCH"
    assert effective_reaction_score(annotated[0]) == pytest.approx(0.88)
    assert effective_reaction_actionable(annotated[0]) is True
    assert effective_reaction_priority({"reaction_state": "CONFIRMED"}) > effective_reaction_priority({"reaction_state": "WATCH"})