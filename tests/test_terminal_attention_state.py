from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from terminal_attention_state import (
    annotate_feed_with_ticker_attention_state,
    build_ticker_attention_state,
    effective_attention_active,
    effective_attention_dispatchable,
    effective_attention_priority,
    effective_attention_reason,
    effective_attention_score,
    effective_attention_state,
)


def _row(
    *,
    ticker: str = "AAPL",
    posture_state: str = "LONG",
    posture_score: float = 0.91,
    posture_confidence: float = 0.82,
    reaction_state: str = "CONFIRMED",
    reaction_score: float = 0.86,
    reaction_confidence: float = 0.78,
    reaction_actionable: bool = True,
    resolution_state: str = "FOLLOW_THROUGH",
    resolution_score: float = 0.90,
    resolution_confidence: float = 0.84,
    resolution_actionable: bool = True,
    materiality: str = "HIGH",
    catalyst_score: float = 0.88,
    catalyst_age_minutes: float = 5.0,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "posture_state": posture_state,
        "posture_score": posture_score,
        "posture_confidence": posture_confidence,
        "reaction_state": reaction_state,
        "reaction_score": reaction_score,
        "reaction_confidence": reaction_confidence,
        "reaction_actionable": reaction_actionable,
        "resolution_state": resolution_state,
        "resolution_score": resolution_score,
        "resolution_confidence": resolution_confidence,
        "resolution_actionable": resolution_actionable,
        "materiality": materiality,
        "catalyst_score": catalyst_score,
        "catalyst_age_minutes": catalyst_age_minutes,
        "published_ts": 1000.0,
        "updated_ts": 1000.0,
    }


def test_build_ticker_attention_state_marks_alert() -> None:
    state = build_ticker_attention_state([_row()], now=1500.0)

    assert state["AAPL"]["attention_state"] == "ALERT"
    assert state["AAPL"]["attention_dispatchable"] is True
    assert state["AAPL"]["attention_active"] is True
    assert state["AAPL"]["attention_reason"] == "follow_through_alert"


def test_build_ticker_attention_state_marks_suppress_on_negative_state() -> None:
    state = build_ticker_attention_state(
        [_row(reaction_state="CONFLICTED", reaction_actionable=False, resolution_state="REVERSAL")],
        now=1500.0,
    )

    assert state["AAPL"]["attention_state"] == "SUPPRESS"
    assert state["AAPL"]["attention_dispatchable"] is False
    assert state["AAPL"]["attention_active"] is False
    assert state["AAPL"]["attention_reason"] == "negative_state"


def test_annotate_feed_and_effective_helpers_prefer_attention_values() -> None:
    annotated, state = annotate_feed_with_ticker_attention_state(
        [_row()],
        ticker_state={
            "AAPL": {
                "attention_state": "FOCUS",
                "attention_score": 0.77,
                "attention_confidence": 0.73,
                "attention_active": True,
                "attention_dispatchable": False,
                "attention_reason": "directional_focus",
            },
        },
        now=1500.0,
    )

    assert annotated[0]["attention_state"] == "FOCUS"
    assert state["AAPL"]["attention_score"] == pytest.approx(0.77)
    assert effective_attention_state(annotated[0]) == "FOCUS"
    assert effective_attention_score(annotated[0]) == pytest.approx(0.77)
    assert effective_attention_active(annotated[0]) is True
    assert effective_attention_dispatchable(annotated[0]) is False
    assert effective_attention_reason(annotated[0]) == "directional_focus"
    assert effective_attention_priority({"attention_state": "ALERT"}) > effective_attention_priority({"attention_state": "FOCUS"})