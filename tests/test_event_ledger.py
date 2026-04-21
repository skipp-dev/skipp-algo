"""Tests for the per-event SMC ledger (Amendment A1.A)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from smc_core.event_ledger import (
    EVENT_LEDGER_SCHEMA_VERSION,
    EventLedgerRecord,
    ledger_path_for_pair,
    read_event_ledger,
    write_event_ledger,
)


@dataclass(slots=True, frozen=True)
class _FakeScoredEvent:
    """Minimal duck-type for ScoredEvent without importing the heavy module."""

    event_id: str
    family: str
    predicted_prob: float
    outcome: bool
    timestamp: float
    context: dict = field(default_factory=dict)
    raw_score: float | None = None
    raw_score_name: str | None = None


def test_schema_version_pinned() -> None:
    assert EVENT_LEDGER_SCHEMA_VERSION == "1.0"


def test_record_default_features_empty() -> None:
    record = EventLedgerRecord(
        schema_version=EVENT_LEDGER_SCHEMA_VERSION,
        event_id="e1",
        symbol="AAPL",
        timeframe="15m",
        family="FVG",
        timestamp=1.0,
        predicted_prob=0.5,
        outcome=True,
    )
    assert record.features == {}
    assert record.outcome_extras == {}
    assert record.context == {}


def test_round_trip_jsonl(tmp_path: Path) -> None:
    events = [
        _FakeScoredEvent(
            event_id="bos-1",
            family="BOS",
            predicted_prob=0.75,
            outcome=True,
            timestamp=1.0,
            context={"session": "NY_AM", "vol_regime": "NORMAL"},
            raw_score=82.5,
            raw_score_name="SIGNAL_QUALITY_SCORE",
        ),
        _FakeScoredEvent(
            event_id="fvg-1",
            family="FVG",
            predicted_prob=0.42,
            outcome=False,
            timestamp=2.0,
            context={"session": "ASIA", "vol_regime": "HIGH_VOL"},
        ),
    ]
    path = tmp_path / "events_AAPL_15m.jsonl"
    n = write_event_ledger(
        events, output_path=path, symbol="AAPL", timeframe="15m"
    )
    assert n == 2
    rows = list(read_event_ledger(path))
    assert len(rows) == 2
    assert rows[0]["event_id"] == "bos-1"
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["timeframe"] == "15m"
    assert rows[0]["family"] == "BOS"
    assert rows[0]["context"] == {"session": "NY_AM", "vol_regime": "NORMAL"}
    assert rows[0]["raw_score"] == pytest.approx(82.5)
    assert rows[0]["raw_score_name"] == "SIGNAL_QUALITY_SCORE"
    assert rows[0]["schema_version"] == "1.0"
    assert rows[1]["raw_score"] is None
    assert rows[1]["features"] == {}


def test_empty_input_creates_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "events_AAPL_15m.jsonl"
    n = write_event_ledger([], output_path=path, symbol="AAPL", timeframe="15m")
    assert n == 0
    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_dict_input_supported(tmp_path: Path) -> None:
    events = [
        {
            "event_id": "ob-1",
            "family": "OB",
            "predicted_prob": 0.6,
            "outcome": True,
            "timestamp": 3.0,
            "context": {"session": "NY_PM"},
            "features": {"gap_size_atr": 0.42, "hurst_50": 0.561, "htf_aligned": 1},
        }
    ]
    path = tmp_path / "events.jsonl"
    write_event_ledger(events, output_path=path, symbol="MSFT", timeframe="1H")
    rows = list(read_event_ledger(path))
    assert rows[0]["features"]["gap_size_atr"] == pytest.approx(0.42)
    assert rows[0]["features"]["hurst_50"] == pytest.approx(0.561)
    assert rows[0]["features"]["htf_aligned"] == 1


def test_ledger_path_for_pair() -> None:
    p = ledger_path_for_pair(
        Path("/tmp/out/AAPL/15m"), symbol="AAPL", timeframe="15m"
    )
    assert p.name == "events_AAPL_15m.jsonl"


def test_context_string_coerced(tmp_path: Path) -> None:
    events = [
        _FakeScoredEvent(
            event_id="bos-2",
            family="BOS",
            predicted_prob=0.5,
            outcome=True,
            timestamp=1.0,
            context={"session": "NY_AM", "n_pings": 3},  # int value
        )
    ]
    path = tmp_path / "events.jsonl"
    write_event_ledger(events, output_path=path, symbol="X", timeframe="15m")
    row = next(read_event_ledger(path))
    assert row["context"] == {"session": "NY_AM", "n_pings": "3"}


def test_jsonl_each_row_independently_parseable(tmp_path: Path) -> None:
    events = [
        _FakeScoredEvent(
            event_id=f"id-{i}",
            family="FVG",
            predicted_prob=0.5,
            outcome=bool(i % 2),
            timestamp=float(i),
        )
        for i in range(5)
    ]
    path = tmp_path / "events.jsonl"
    write_event_ledger(events, output_path=path, symbol="X", timeframe="15m")
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        assert record["schema_version"] == "1.0"
        assert "event_id" in record
