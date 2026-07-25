"""Golden replay cases for the A0 threshold and modifier contract."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from open_prep import realtime_signals as rt
from open_prep.a0_contract import (
    A0ThresholdContext,
    build_market_snapshot,
    decide_core_level,
)

_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "a0_decision_cases.json").read_text(
        encoding="utf-8"
    )
)
_THRESHOLDS = A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5)


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case["name"])
def test_core_golden_cases(case: dict[str, Any]) -> None:
    snapshot = build_market_snapshot(
        symbol="TEST",
        price=100.0 + float(case["change_pct"]),
        prev_close=100.0,
        change_pct=float(case["change_pct"]),
        raw_daily_volume_ratio=float(case["pace"]) * 0.25,
        expected_volume_fraction=0.25,
        normalized_volume_pace=float(case["pace"]),
        source="fixture",
        raw_ts_event=1_700_000_000,
        observed_at=1_700_000_002,
    )
    decision = decide_core_level(snapshot, _THRESHOLDS)
    assert decision.final_level == case["level"]
    expected_reasons = [] if case["reason"] is None else [case["reason"]]
    assert list(decision.reason_codes) == expected_reasons


class _Cooldown:
    def __init__(self, active: bool = False) -> None:
        self.active = active

    def check_cooldown(self, *_args: Any, **_kwargs: Any) -> tuple[bool, float]:
        return self.active, 30.0 if self.active else 0.0

    def record_transition(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _Hysteresis:
    def __init__(self, forced_level: str | None = None) -> None:
        self.forced_level = forced_level

    def evaluate(self, _symbol: str, level: str, *_args: Any, **_kwargs: Any) -> str:
        return self.forced_level or level


def _engine(
    *,
    previous_price: float | None = None,
    price_history: list[float] | None = None,
    rsi: float | None = None,
    technical_score: float = 0.5,
    technical_signal: str = "NEUTRAL",
    cooldown_active: bool = False,
    hysteresis_level: str | None = None,
) -> rt.RealtimeEngine:
    engine = rt.RealtimeEngine.__new__(rt.RealtimeEngine)
    engine._last_prices = {} if previous_price is None else {"TEST": previous_price}
    engine._price_history = {} if price_history is None else {"TEST": price_history}
    engine._hysteresis = _Hysteresis(hysteresis_level)
    engine._dynamic_cooldown = _Cooldown(cooldown_active)
    engine._volume_regime = SimpleNamespace(regime="NORMAL")
    engine._technical_scorer = SimpleNamespace(
        get_technical_data=lambda *_args: {
            "technical_score": technical_score,
            "technical_signal": technical_signal,
            "rsi": rsi,
            "macd_signal": "",
        }
    )
    return engine


def _detect(
    monkeypatch: pytest.MonkeyPatch,
    engine: rt.RealtimeEngine,
    *,
    pace: float,
    change_pct: float,
    watchlist: dict[str, Any] | None = None,
) -> rt.RealtimeSignal | None:
    monkeypatch.setattr(rt, "_is_within_market_hours", lambda: True)
    prev_close = 100.0
    return engine._detect_signal(
        "TEST",
        {
            "price": prev_close * (1 + change_pct / 100.0),
            "previousClose": prev_close,
            "volume": pace * 0.25 * 1_000_000,
            "avgVolume": 1_000_000,
            "expected_volume_fraction": 0.25,
            "timestamp": time.time() - 1,
        },
        watchlist or {},
    )


@pytest.mark.parametrize(
    ("engine", "pace", "change", "watchlist", "level", "reason"),
    [
        (_engine(previous_price=103.0), 3.0, 2.0, {}, "A1", "falling_knife_downgrade"),
        (_engine(previous_price=100.5), 1.2, 1.2, {"pdh": 101.0}, "A0", "pdh_breakout_upgrade"),
        (_engine(previous_price=99.5), 1.2, -1.2, {"pdl": 99.0}, "A0", "pdl_breakdown_upgrade"),
        (_engine(price_history=[101.99] * 5), 3.0, 2.0, {}, "A1", "stale_velocity_downgrade"),
        (_engine(rsi=20.0), 1.2, 1.2, {}, "A0", "rsi_directional_upgrade"),
        (_engine(technical_signal="STRONG_SELL"), 3.0, 2.0, {}, "A1", "technical_contra_downgrade"),
        (_engine(technical_score=0.8, technical_signal="BUY"), 1.6, 1.2, {}, "A0", "technical_alignment_upgrade"),
        # SHORT mirror: strong BEARISH technical alignment (low score / STRONG_SELL)
        # must upgrade an A1-band SHORT to A0, symmetric to the LONG case above.
        (_engine(technical_score=0.05, technical_signal="STRONG_SELL"), 1.6, -1.2, {}, "A0", "technical_alignment_upgrade"),
        (_engine(cooldown_active=True), 3.0, 2.0, {}, "A1", "cooldown_downgrade"),
        (_engine(previous_price=102.0), 3.0, 2.0, {}, "A1", "momentum_not_confirmed"),
        (_engine(hysteresis_level="A1"), 3.0, 2.0, {}, "A1", "hysteresis_adjustment"),
    ],
)
def test_modifier_golden_cases(
    monkeypatch: pytest.MonkeyPatch,
    engine: rt.RealtimeEngine,
    pace: float,
    change: float,
    watchlist: dict[str, Any],
    level: str,
    reason: str,
) -> None:
    signal = _detect(
        monkeypatch,
        engine,
        pace=pace,
        change_pct=change,
        watchlist=watchlist,
    )
    assert signal is not None
    assert signal.level == level
    assert signal.details["final_level"] == level
    assert signal.details["reason_codes"][0].startswith("core_")
    assert reason in signal.details["reason_codes"]


@pytest.mark.parametrize("bad_volume", [float("nan"), -1.0])
def test_invalid_or_negative_volume_never_creates_signal(
    monkeypatch: pytest.MonkeyPatch,
    bad_volume: float,
) -> None:
    monkeypatch.setattr(rt, "_is_within_market_hours", lambda: True)
    engine = _engine()
    signal = engine._detect_signal(
        "TEST",
        {
            "price": 102.0,
            "previousClose": 100.0,
            "volume": bad_volume,
            "avgVolume": 1_000_000,
            "expected_volume_fraction": 0.25,
        },
        {},
    )
    assert signal is None
