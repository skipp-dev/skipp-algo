"""Tests for smc_integration.earnings_filter (C13/T7.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smc_integration.earnings_filter import (
    DEFAULT_POST_WINDOW_DAYS,
    DEFAULT_PRE_WINDOW_DAYS,
    EARNINGS_EVENT_TYPES,
    EarningsFilter,
    EarningsFilterDecision,
)


def _write_events(tmp_path: Path, events: list[dict]) -> Path:
    p = tmp_path / "wsh_events.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return p


def test_default_windows_are_one_day_each() -> None:
    assert DEFAULT_PRE_WINDOW_DAYS == 1
    assert DEFAULT_POST_WINDOW_DAYS == 1


def test_missing_jsonl_returns_unblocked_with_marker(tmp_path: Path) -> None:
    f = EarningsFilter(tmp_path / "does_not_exist.jsonl")
    assert f.data_available is False
    d = f.decide(symbol="AAPL", trade_date="2026-04-30")
    assert d.blocked is False
    assert d.reason == "WSH_DATA_MISSING"


def test_decide_blocks_inside_pre_window(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "AAPL", "event_type": "EarningsAnnouncement",
         "event_date": "2026-05-02"},
    ])
    f = EarningsFilter(p, pre_window_days=1, post_window_days=1)
    d = f.decide(symbol="AAPL", trade_date="2026-05-01")
    assert d.blocked is True
    assert d.reason == "EARNINGS_WINDOW"
    assert d.matched_event_date == "2026-05-02"
    assert d.matched_event_type == "EarningsAnnouncement"


def test_decide_blocks_inside_post_window(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "MSFT", "event_type": "Earnings",
         "event_date": "2026-04-30"},
    ])
    f = EarningsFilter(p, pre_window_days=1, post_window_days=1)
    d = f.decide(symbol="MSFT", trade_date="2026-05-01")
    assert d.blocked is True
    assert d.reason == "EARNINGS_WINDOW"


def test_decide_passes_outside_window(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "TSLA", "event_type": "EarningsDated",
         "event_date": "2026-05-10"},
    ])
    f = EarningsFilter(p, pre_window_days=1, post_window_days=1)
    d = f.decide(symbol="TSLA", trade_date="2026-05-01")
    assert d.blocked is False
    assert d.reason == "OUTSIDE_GUARD_WINDOW"


def test_decide_passes_when_symbol_has_no_events(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "AAPL", "event_type": "Earnings",
         "event_date": "2026-05-02"},
    ])
    f = EarningsFilter(p)
    d = f.decide(symbol="ZZZZ", trade_date="2026-05-01")
    assert d.blocked is False
    assert d.reason == "NO_EARNINGS_EVENT"


def test_non_earnings_event_types_are_ignored(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "AAPL", "event_type": "Dividend",
         "event_date": "2026-05-01"},
    ])
    f = EarningsFilter(p)
    d = f.decide(symbol="AAPL", trade_date="2026-05-01")
    # Non-earnings event types fall through to the windowed scan,
    # find no match, and end up unblocked.
    assert d.blocked is False
    assert d.reason == "OUTSIDE_GUARD_WINDOW"


def test_symbol_lookup_is_case_insensitive(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "aapl", "event_type": "Earnings",
         "event_date": "2026-05-01"},
    ])
    f = EarningsFilter(p)
    d = f.decide(symbol="AAPL", trade_date="2026-05-01")
    assert d.blocked is True


def test_negative_window_raises(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [])
    with pytest.raises(ValueError):
        EarningsFilter(p, pre_window_days=-1)


def test_filter_candidates_aggregates_stats(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "AAPL", "event_type": "Earnings",
         "event_date": "2026-05-01"},
    ])
    f = EarningsFilter(p)
    decisions, stats = f.filter_candidates([
        ("AAPL", "2026-05-01"),  # blocked
        ("AAPL", "2026-05-10"),  # passed (outside)
        ("ZZZZ", "2026-05-01"),  # passed (no event)
    ])
    assert len(decisions) == 3
    assert stats.candidates == 3
    assert stats.blocked == 1
    assert stats.passed == 2


def test_audit_dict_carries_kind(tmp_path: Path) -> None:
    p = _write_events(tmp_path, [
        {"symbol": "AAPL", "event_type": "Earnings",
         "event_date": "2026-05-01"},
    ])
    f = EarningsFilter(p)
    d = f.decide(symbol="AAPL", trade_date="2026-05-01")
    audit = d.as_audit_dict()
    assert audit["kind"] == "earnings_filter_decision"
    assert audit["symbol"] == "AAPL"
    assert audit["blocked"] is True


def test_reload_picks_up_new_file(tmp_path: Path) -> None:
    path = tmp_path / "wsh.jsonl"
    f = EarningsFilter(path)  # missing initially
    assert not f.data_available
    path.write_text(json.dumps({
        "symbol": "AAPL", "event_type": "Earnings",
        "event_date": "2026-05-01"
    }) + "\n", encoding="utf-8")
    f.reload()
    assert f.data_available
    d = f.decide(symbol="AAPL", trade_date="2026-05-01")
    assert d.blocked is True


def test_event_types_constant_aligns_with_wsh_calendar() -> None:
    # Mirrors WSH_EARNINGS_EVENT_TYPES in scripts/wsh_earnings_calendar.py.
    from scripts.wsh_earnings_calendar import WSH_EARNINGS_EVENT_TYPES

    assert EARNINGS_EVENT_TYPES == WSH_EARNINGS_EVENT_TYPES
