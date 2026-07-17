"""Tests for open_prep.signal_events — the persistent signal-event log."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from open_prep import signal_events as se


def _sig(symbol: str, level: str, direction: str = "LONG", **extra: Any) -> Any:
    base = dict(symbol=symbol, level=level, direction=direction, price=100.0,
                volume_ratio=2.4, change_pct=1.1, atr_pct=0.03, freshness=1.0,
                score=0.7, confidence_tier="high", pattern="orb", news_score=0.6,
                technical_score=0.8, rsi=61.0, symbol_regime="BULL", fired_epoch=1000.0)
    base.update(extra)
    return SimpleNamespace(**base)


def test_from_env_disabled_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RT_SIGNAL_EVENT_LOG_DIR", raising=False)
    assert se.SignalEventLogger.from_env() is None
    monkeypatch.setenv("RT_SIGNAL_EVENT_LOG_DIR", "/tmp/x")
    assert se.SignalEventLogger.from_env() is not None


def _read(path_dir: Any, epoch: float) -> list[dict[str, Any]]:
    from datetime import UTC, datetime
    day = datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")
    p = path_dir / f"signal_events_{day}.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_records_fresh_and_dedups_same_level(tmp_path: Any) -> None:
    logger = se.SignalEventLogger(tmp_path)
    t = 1_700_000_000.0
    assert logger.record([_sig("NVDA", "A1"), _sig("MSFT", "A2")], now=t) == 2
    # Same (symbol,direction,level) re-detected next cycle -> not a new event.
    assert logger.record([_sig("NVDA", "A1")], now=t + 30) == 0
    rows = _read(tmp_path, t)
    assert {r["symbol"] for r in rows} == {"NVDA", "MSFT"}
    nvda = next(r for r in rows if r["symbol"] == "NVDA")
    assert nvda["level"] == "A1" and nvda["news_score"] == 0.6 and nvda["technical_score"] == 0.8


def test_event_row_emits_explicit_v2_volume_semantics() -> None:
    signal = _sig(
        "NVDA",
        "A1",
        details={
            "signal_schema_version": 2,
            "raw_daily_volume_ratio": 0.6,
            "expected_volume_fraction": 0.25,
            "normalized_volume_pace": 2.4,
            "effective_a0_volume_threshold": 3.0,
            "effective_a0_price_threshold": 2.0,
            "decision_contract_version": 1,
            "detector_version": "a0-contract-v1",
            "core_level": "A1",
            "final_level": "A1",
            "reason_codes": ["core_a1_thresholds"],
            "decision_id": "decision-123",
            "ts_event": 1_699_999_998.0,
            "ts_recv": 1_699_999_999.0,
            "observed_at": 1_700_000_000.0,
            "decision_at": 1_700_000_000.0,
            "data_age_ms": 2_000.0,
            "data_age_unknown": False,
            "source": "fmp",
            "session_date": "2023-11-14",
        },
    )
    row = se.event_row(signal, now_epoch=1_700_000_000.0)
    assert row["schema_version"] == 2
    assert row["raw_daily_volume_ratio"] == 0.6
    assert row["normalized_volume_pace"] == 2.4
    assert row["volume_semantics"] == "normalized_pace_v2"
    assert row["reason_codes"] == ["core_a1_thresholds"]
    assert row["decision_id"] == "decision-123"
    assert row["data_age_unknown"] is False


def test_event_row_marks_missing_normalized_pace() -> None:
    row = se.event_row(_sig("NVDA", "A1"), now_epoch=1_700_000_000.0)
    assert row["schema_version"] == 2
    assert row["normalized_volume_pace"] is None
    assert row["volume_semantics"] == "legacy_raw_only"


def test_strengthen_logs_new_row(tmp_path: Any) -> None:
    logger = se.SignalEventLogger(tmp_path)
    t = 1_700_000_000.0
    logger.record([_sig("NVDA", "A2")], now=t)
    # A2 -> A0 is a strengthen: a second row.
    assert logger.record([_sig("NVDA", "A0")], now=t + 60) == 1
    # A weaker re-detect afterwards does not.
    assert logger.record([_sig("NVDA", "A1")], now=t + 90) == 0
    levels = [r["level"] for r in _read(tmp_path, t)]
    assert levels == ["A2", "A0"]


def test_unknown_level_is_ignored(tmp_path: Any) -> None:
    logger = se.SignalEventLogger(tmp_path)
    assert logger.record([_sig("NVDA", "WATCH"), _sig("NVDA", "")], now=1_700_000_000.0) == 0


def test_write_failure_is_fail_soft(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    logger = se.SignalEventLogger(tmp_path)
    # Make the JSONL append blow up; record must swallow it and return 0.
    monkeypatch.setattr(se.Path, "open", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert logger.record([_sig("NVDA", "A1")], now=1_700_000_000.0) == 0
