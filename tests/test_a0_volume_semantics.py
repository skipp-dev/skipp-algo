"""Focused tests for explicit A0 volume semantics and early warning."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from open_prep import realtime_signals as rt


def test_volume_semantics_separates_raw_ratio_from_normalized_pace() -> None:
    raw, expected, normalized = rt._volume_semantics(200_000, 1_000_000, 0.25)
    assert raw == 0.2
    assert expected == 0.25
    assert normalized == 0.8


def test_upcoming_a2_uses_normalized_volume_pace() -> None:
    raw, _expected, normalized = rt._volume_semantics(200_000, 1_000_000, 0.25)
    assert raw < 0.8
    assert rt._is_upcoming_a2(normalized, 0.8, 1.0, 1.0)


def test_fmp_detection_emits_replayable_decision_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = rt.RealtimeEngine.__new__(rt.RealtimeEngine)
    engine._last_prices = {}
    engine._price_history = {}
    engine._hysteresis = rt.GateHysteresis()
    engine._dynamic_cooldown = rt.DynamicCooldown()
    engine._volume_regime = rt.VolumeRegimeDetector()
    engine._technical_scorer = SimpleNamespace(
        get_technical_data=lambda *_args: {
            "technical_score": 0.5,
            "technical_signal": "NEUTRAL",
            "rsi": None,
            "macd_signal": "",
        }
    )
    monkeypatch.setattr(rt, "_is_within_market_hours", lambda: True)
    signal = engine._detect_signal(
        "NVDA",
        {
            "price": 102.0,
            "previousClose": 100.0,
            "volume": 750_000,
            "avgVolume": 1_000_000,
            "expected_volume_fraction": 0.25,
            "timestamp": (time.time() - 2) * 1000,
            "source": "FMP",
        },
        {},
    )
    assert signal is not None
    assert signal.level == "A0"
    assert signal.details["core_level"] == "A0"
    assert signal.details["final_level"] == "A0"
    assert signal.details["reason_codes"] == ["core_a0_thresholds"]
    assert signal.details["data_age_unknown"] is False
    assert 1_000 <= signal.details["data_age_ms"] <= 3_000
    assert len(signal.details["decision_id"]) == 24
