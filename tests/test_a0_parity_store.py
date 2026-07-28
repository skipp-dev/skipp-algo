"""Persistence and deterministic daily-report tests for A0 parity evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_prep.a0_contract import (
    A0ThresholdContext,
    build_market_snapshot,
    decide_core_level,
)
from open_prep.a0_parity_store import (
    A0ParityJournal,
    load_shadow_decisions,
    parity_source_from_env,
    record_realtime_a0_signals,
    shadow_decision_row,
)
from scripts.report_a0_parity import build_daily_report

_SESSION = "2026-07-17"


def _fast_row(*, decision_at: float | None = None) -> dict[str, object]:
    event_at = datetime(2026, 7, 17, 14, 0, tzinfo=UTC).timestamp()
    snapshot = build_market_snapshot(
        symbol="NVDA",
        price=103.0,
        prev_close=100.0,
        change_pct=3.0,
        raw_daily_volume_ratio=0.8,
        expected_volume_fraction=0.2,
        normalized_volume_pace=4.0,
        source="databento",
        raw_ts_event=event_at,
        observed_at=event_at + 0.2,
    )
    thresholds = A0ThresholdContext(3.0, 1.0, 0.6, 2.0, 1.0, 0.5)
    decision = decide_core_level(
        snapshot,
        thresholds,
        decision_at=event_at + 0.3 if decision_at is None else decision_at,
    )
    return shadow_decision_row(
        decision,
        thresholds,
        direction="LONG",
        decision_scope="core_only",
        cumulative_regular_volume=800_000,
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_journal_fsyncs_first_episode_and_deduplicates_across_restart(
    tmp_path: Path,
) -> None:
    row = _fast_row()
    journal = A0ParityJournal(tmp_path, source="databento")
    assert journal.record(row) is True
    assert journal.record(row) is False

    restored = A0ParityJournal(tmp_path, source="databento")
    assert restored.record(row) is False
    path = tmp_path / f"a0_shadow_databento_{_SESSION}.jsonl"
    loaded = load_shadow_decisions([path], expected_source="databento")
    assert len(loaded) == 1
    assert loaded[0].cumulative_regular_volume == 800_000
    assert loaded[0].decision_scope == "core_only"


def test_journal_accepts_qualified_databento_source_family(tmp_path: Path) -> None:
    row = _fast_row()
    row["source"] = "databento:daily"
    journal = A0ParityJournal(tmp_path, source="databento")
    assert journal.record(row) is True
    loaded = load_shadow_decisions(
        [tmp_path / f"a0_shadow_databento_{_SESSION}.jsonl"],
        expected_source="databento",
    )
    assert loaded[0].source == "databento:daily"


def test_loader_accepts_fmp_signal_event_shape_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    fmp = {
        "decision_id": "fmp-1",
        "symbol": "NVDA",
        "direction": "LONG",
        "final_level": "A0",
        "decision_at": 100.0,
        "source": "fmp",
        "reason_codes": ["core_a0_thresholds"],
        "session_date": _SESSION,
        "price": 102.5,
        "prev_close": 100.0,
    }
    path = tmp_path / "fmp.jsonl"
    _write_jsonl(path, [fmp])
    loaded = load_shadow_decisions([path])
    assert loaded[0].previous_close == 100.0

    conflicting = {**fmp, "price": 104.0}
    _write_jsonl(path, [fmp, conflicting])
    with pytest.raises(ValueError, match="conflicting duplicate"):
        load_shadow_decisions([path])


def test_daily_report_is_reproducible_and_contains_both_snapshots(
    tmp_path: Path,
) -> None:
    fast_row = _fast_row()
    fast_path = tmp_path / "fast.jsonl"
    fmp_path = tmp_path / "fmp.jsonl"
    _write_jsonl(fast_path, [fast_row])
    _write_jsonl(fmp_path, [{
        "decision_id": "fmp-1",
        "symbol": "NVDA",
        "direction": "LONG",
        "level": "A0",
        "decision_at": float(fast_row["decision_at"]) + 7.0,
        "source": "fmp",
        "core_level": "A0",
        "reason_codes": ["core_a0_thresholds", "technical_alignment_upgrade"],
        "session_date": _SESSION,
        "raw_daily_volume_ratio": 0.82,
        "normalized_volume_pace": 4.1,
        "effective_a0_volume_threshold": 3.0,
        "effective_a0_price_threshold": 2.0,
        "price": 103.1,
        "prev_close": 100.0,
        "change_pct": 3.1,
        "expected_volume_fraction": 0.2,
    }])

    first = build_daily_report(
        session_date=_SESSION,
        fast_paths=[fast_path],
        fmp_paths=[fmp_path],
        matching_window_seconds=30,
    )
    second = build_daily_report(
        session_date=_SESSION,
        fast_paths=[fast_path],
        fmp_paths=[fmp_path],
        matching_window_seconds=30,
    )
    assert first == second
    assert first["status_counts"] == {"same_decision_fast_first": 1}
    assert first["median_fast_lead_seconds"] == 7.0
    match = first["matches"][0]
    assert match["fast_snapshot"]["cumulative_regular_volume"] == 800_000
    assert match["fmp_snapshot"]["price"] == 103.1


def test_fmp_sink_persists_core_a0_even_when_final_state_downgrades(
    tmp_path: Path,
) -> None:
    journal = A0ParityJournal(tmp_path, source="fmp")
    signal = SimpleNamespace(
        symbol="NVDA",
        level="A1",
        direction="LONG",
        fired_epoch=100.0,
        price=102.0,
        prev_close=100.0,
        volume_ratio=0.7,
        change_pct=2.0,
        details={
            "decision_id": "fmp-core-a0-final-a1",
            "core_level": "A0",
            "final_level": "A1",
            "decision_at": 101.0,
            "source": "fmp",
            "reason_codes": ["core_a0_thresholds", "cooldown_downgrade"],
            "session_date": _SESSION,
        },
    )
    assert record_realtime_a0_signals(journal, [signal], now_epoch=101.0) == 1
    path = tmp_path / f"a0_shadow_fmp_{_SESSION}.jsonl"
    loaded = load_shadow_decisions([path], include_core_a0=True)
    assert loaded[0].level == "A1"
    assert loaded[0].core_level == "A0"

    restored = A0ParityJournal(tmp_path, source="fmp")
    assert record_realtime_a0_signals(restored, [signal], now_epoch=102.0) == 0


def test_loader_fails_closed_on_truncated_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "truncated.jsonl"
    path.write_text('{"decision_id":', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_shadow_decisions([path])


def test_parity_source_defaults_to_databento(monkeypatch):
    monkeypatch.delenv("RT_QUOTE_SOURCE", raising=False)
    assert parity_source_from_env() == "databento"


def test_parity_source_uses_fmp_only_when_explicitly_selected(monkeypatch):
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    assert parity_source_from_env() == "databento"
    monkeypatch.setenv("RT_QUOTE_SOURCE", "fmp")
    assert parity_source_from_env() == "fmp"
    monkeypatch.setenv("RT_QUOTE_SOURCE", "something-else")
    assert parity_source_from_env() == "databento"


def test_parity_source_labels_journal_that_report_a0_parity_accepts(tmp_path, monkeypatch):
    """End-to-end: a shadow producer (RT_QUOTE_SOURCE=databento) must label its
    journal 'databento' so report_a0_parity's --fast side
    (expected_source='databento') accepts it. A hardcoded 'fmp' would have
    written an a0_shadow_fmp_*.jsonl that collides with the real FMP producer
    and is rejected on the --fast side."""
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    journal = A0ParityJournal(tmp_path, source=parity_source_from_env())
    assert journal.record(_fast_row()) is True
    written = sorted(tmp_path.glob("a0_shadow_databento_*.jsonl"))
    assert written, "journal must be written under the databento-labeled filename"
    assert not sorted(tmp_path.glob("a0_shadow_fmp_*.jsonl")), "must NOT write an fmp journal"
    # exactly what report_a0_parity's --fast side does:
    assert load_shadow_decisions(written, expected_source="databento")
