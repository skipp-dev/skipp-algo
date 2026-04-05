from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_posture_state import (
    annotate_feed_with_ticker_posture_state,
    build_ticker_posture_state,
    effective_posture_action,
    effective_posture_actionable,
    effective_posture_priority,
    effective_posture_score,
    effective_posture_state,
)


def _row(
    *,
    ticker: str = "AAPL",
    catalyst_direction: str = "BULLISH",
    resolution_state: str = "FOLLOW_THROUGH",
    resolution_score: float = 0.91,
    resolution_actionable: bool = True,
    reaction_state: str = "CONFIRMED",
    reaction_score: float = 0.86,
    reaction_actionable: bool = True,
) -> dict[str, object]:
    sentiment_label = "bullish" if catalyst_direction == "BULLISH" else "bearish"
    return {
        "ticker": ticker,
        "catalyst_direction": catalyst_direction,
        "catalyst_score": 0.84,
        "catalyst_confidence": 0.72,
        "catalyst_actionable": True,
        "sentiment_label": sentiment_label,
        "reaction_state": reaction_state,
        "reaction_score": reaction_score,
        "reaction_confidence": 0.78,
        "reaction_actionable": reaction_actionable,
        "resolution_state": resolution_state,
        "resolution_score": resolution_score,
        "resolution_confidence": 0.83,
        "resolution_actionable": resolution_actionable,
        "published_ts": 1000.0,
        "updated_ts": 1000.0,
    }


def test_build_ticker_posture_state_marks_long() -> None:
    state = build_ticker_posture_state([_row()], now=1500.0)

    assert state["AAPL"]["posture_state"] == "LONG"
    assert state["AAPL"]["posture_action"] == "buy"
    assert state["AAPL"]["posture_actionable"] is True
    assert state["AAPL"]["posture_score"] == pytest.approx(0.91)


def test_build_ticker_posture_state_marks_avoid() -> None:
    state = build_ticker_posture_state(
        [_row(resolution_state="REVERSAL", resolution_score=0.44, resolution_actionable=False)],
        now=1500.0,
    )

    assert state["AAPL"]["posture_state"] == "AVOID"
    assert state["AAPL"]["posture_action"] == "ignore"
    assert state["AAPL"]["posture_actionable"] is False


def test_annotate_feed_and_effective_helpers_prefer_explicit_posture_values() -> None:
    annotated, state = annotate_feed_with_ticker_posture_state(
        [_row()],
        ticker_state={
            "AAPL": {
                "posture_state": "WATCH_LONG",
                "posture_action": "watch",
                "posture_score": 0.73,
                "posture_actionable": True,
            },
        },
        now=1500.0,
    )

    assert annotated[0]["posture_state"] == "WATCH_LONG"
    assert state["AAPL"]["posture_score"] == pytest.approx(0.73)
    assert effective_posture_state(annotated[0]) == "WATCH_LONG"
    assert effective_posture_action(annotated[0]) == "watch"
    assert effective_posture_score(annotated[0]) == pytest.approx(0.73)
    assert effective_posture_actionable(annotated[0]) is True
    assert effective_posture_priority({"posture_state": "LONG"}) > effective_posture_priority({"posture_state": "WATCH_LONG"})