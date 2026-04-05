from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_resolution_state import (
    annotate_feed_with_ticker_resolution_state,
    build_ticker_resolution_state,
    effective_resolution_actionable,
    effective_resolution_priority,
    effective_resolution_score,
    effective_resolution_state,
)


def _row(
    *,
    ticker: str = "AAPL",
    story_key: str = "story-a",
    catalyst_direction: str = "BULLISH",
    catalyst_score: float = 0.84,
    reaction_state: str = "CONFIRMED",
    reaction_score: float = 0.86,
    reaction_confidence: float = 0.74,
    reaction_actionable: bool = True,
    anchor_price: float = 100.0,
    anchor_ts: float = 900.0,
    peak_impulse_pct: float = 1.3,
    updated_ts: float = 995.0,
) -> dict[str, object]:
    sentiment_label = "bullish" if catalyst_direction == "BULLISH" else "bearish"
    return {
        "ticker": ticker,
        "story_key": story_key,
        "catalyst_best_story_key": story_key,
        "catalyst_direction": catalyst_direction,
        "catalyst_score": catalyst_score,
        "catalyst_actionable": True,
        "catalyst_confidence": 0.70,
        "catalyst_last_update_ts": updated_ts,
        "reaction_state": reaction_state,
        "reaction_score": reaction_score,
        "reaction_confidence": reaction_confidence,
        "reaction_actionable": reaction_actionable,
        "reaction_anchor_story_key": story_key,
        "reaction_anchor_price": anchor_price,
        "reaction_anchor_ts": anchor_ts,
        "reaction_peak_impulse_pct": peak_impulse_pct,
        "reaction_last_update_ts": updated_ts,
        "published_ts": updated_ts,
        "updated_ts": updated_ts,
        "sentiment_label": sentiment_label,
    }


def test_build_ticker_resolution_state_marks_follow_through() -> None:
    state = build_ticker_resolution_state(
        [_row()],
        rt_quotes={"AAPL": {"price": 101.0, "chg_pct": 1.0, "vol_ratio": 1.8}},
        now=1500.0,
    )

    assert state["AAPL"]["resolution_state"] == "FOLLOW_THROUGH"
    assert state["AAPL"]["resolution_source"] == "rt"
    assert state["AAPL"]["resolution_actionable"] is True
    assert state["AAPL"]["resolution_score"] > 0.86


def test_build_ticker_resolution_state_marks_reversal() -> None:
    state = build_ticker_resolution_state(
        [_row(peak_impulse_pct=1.6)],
        rt_quotes={"AAPL": {"price": 98.5, "chg_pct": -1.5, "vol_ratio": 1.4}},
        now=1500.0,
    )

    assert state["AAPL"]["resolution_state"] == "REVERSAL"
    assert state["AAPL"]["resolution_actionable"] is False
    assert state["AAPL"]["resolution_resolved"] is True
    assert state["AAPL"]["resolution_score"] < 0.86


def test_annotate_feed_and_effective_helpers_prefer_resolution_values() -> None:
    annotated, state = annotate_feed_with_ticker_resolution_state(
        [_row()],
        ticker_state={
            "AAPL": {
                "resolution_state": "STALLED",
                "resolution_score": 0.51,
                "resolution_actionable": False,
            },
        },
        now=1500.0,
    )

    assert annotated[0]["resolution_state"] == "STALLED"
    assert state["AAPL"]["resolution_score"] == pytest.approx(0.51)
    assert effective_resolution_state(annotated[0]) == "STALLED"
    assert effective_resolution_score(annotated[0]) == pytest.approx(0.51)
    assert effective_resolution_actionable(annotated[0]) is False
    assert effective_resolution_priority({"resolution_state": "FOLLOW_THROUGH"}) > effective_resolution_priority({"resolution_state": "OPEN"})