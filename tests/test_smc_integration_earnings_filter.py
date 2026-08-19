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


def test_missing_jsonl_blocks_by_default(tmp_path: Path) -> None:
    """Fail-closed is the default since 2026-08-19 (operator decision).

    "I cannot tell whether this symbol reports today" must not be a reason to
    trade. Before this, a missing calendar passed every candidate.
    """
    f = EarningsFilter(tmp_path / "does_not_exist.jsonl")
    assert f.data_available is False
    d = f.decide(symbol="AAPL", trade_date="2026-04-30")
    assert d.blocked is True
    assert d.reason == "WSH_DATA_MISSING"


def test_missing_jsonl_can_still_pass_for_replays(tmp_path: Path) -> None:
    """``pass`` stays reachable so replays of genuinely unfiltered periods
    (2026-06-11…2026-08-19) reproduce what actually happened."""
    f = EarningsFilter(tmp_path / "does_not_exist.jsonl", on_missing_data="pass")
    d = f.decide(symbol="AAPL", trade_date="2026-04-30")
    assert d.blocked is False
    assert d.reason == "WSH_DATA_MISSING"


def test_unknown_missing_data_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="on_missing_data"):
        EarningsFilter(tmp_path / "x.jsonl", on_missing_data="ignore")


def test_present_but_empty_calendar_counts_as_missing(tmp_path: Path) -> None:
    """The defect that hid the outage for 69 days.

    The WSH feed writes a zero-byte snapshot on its rc=2 path. Only
    ``exists()`` was checked, so such a file was accepted as a valid calendar
    and every symbol got the POSITIVE verdict ``NO_EARNINGS_EVENT`` — a claim
    that the calendar had been consulted, indistinguishable in the audit from a
    real all-clear. Measured 2026-08-19 on the production tree: 22 snapshots
    under ``cache/wsh/``, all 0 bytes, 41/41 feed markers degraded since
    2026-06-11.
    """
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    f = EarningsFilter(empty)
    assert f.data_available is False, "empty file must not read as valid data"
    d = f.decide(symbol="AAPL", trade_date="2026-04-30")
    assert d.reason == "WSH_DATA_MISSING", "must never be NO_EARNINGS_EVENT"
    assert d.blocked is True


def test_calendar_with_only_unusable_rows_counts_as_missing(tmp_path: Path) -> None:
    """Whitespace and symbol-less rows index to nothing — same class as empty."""
    p = tmp_path / "junk.jsonl"
    p.write_text('\n  \n{"event_type": "Earnings", "event_date": "2026-05-02"}\n',
                 encoding="utf-8")
    f = EarningsFilter(p)
    assert f.data_available is False
    assert f.decide(symbol="AAPL", trade_date="2026-04-30").reason == "WSH_DATA_MISSING"


def test_missing_data_is_not_counted_as_passed(tmp_path: Path) -> None:
    """Stats accounting must follow the verdict, not the old fail-open story."""
    f = EarningsFilter(tmp_path / "does_not_exist.jsonl")
    _decisions, stats = f.filter_candidates([("AAPL", "2026-04-30"), ("MSFT", "2026-04-30")])
    assert stats.missing_data == 2
    assert stats.blocked == 2
    assert stats.passed == 0


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


# ----------------------------------------------------------------------
# Producer <-> consumer coupling and the campaign-evidence claim.
# ----------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PILOT_DOC = _REPO_ROOT / "docs" / "commercial" / "PHASE1_PAPER_PRODUCER_PILOT.md"


def test_fmp_producer_emits_an_event_type_the_filter_accepts() -> None:
    """A second source is only a source if its rows survive the consumer.

    ``decide()`` skips any event whose ``event_type`` is not in
    ``EARNINGS_EVENT_TYPES``, silently and without a log line — so a producer
    inventing its own literal would write a full calendar that blocks nothing.
    """
    from scripts.fmp_earnings_calendar import FMP_EVENT_TYPE

    assert FMP_EVENT_TYPE in EARNINGS_EVENT_TYPES


def test_fmp_producer_rows_index_and_block(tmp_path: Path) -> None:
    """Round-trip the producer's own record shape through the filter."""
    from scripts.fmp_earnings_calendar import FmpEarningsEvent, write_jsonl

    out = tmp_path / "fmp.jsonl"
    write_jsonl(
        [
            FmpEarningsEvent(
                symbol="NAMM",
                con_id=-1,
                event_type="Earnings",
                event_date="2026-08-27",
                event_time=None,
                timezone=None,
                confidence=None,
                source="fmp",
            )
        ],
        out,
    )
    f = EarningsFilter(out, pre_window_days=1, post_window_days=1)
    assert f.data_available is True
    blocked = f.decide(symbol="NAMM", trade_date="2026-08-27")
    assert blocked.blocked is True
    assert blocked.reason == "EARNINGS_WINDOW"
    assert f.decide(symbol="NAMM", trade_date="2026-09-10").blocked is False


def test_pilot_doc_marks_the_campaign_window_as_unfiltered() -> None:
    """The doc claims this test pins the window; make that claim true.

    Without this, the 2026-06-11…2026-08-19 disclosure is prose that a later
    edit can quietly drop, and the paper-flip gate would once again read those
    days as "earnings checked".
    """
    text = _PILOT_DOC.read_text(encoding="utf-8")
    assert "UNFILTERED for earnings" in text
    assert "2026-06-11" in text
    assert "41 of 41 days" in text
    assert "paper-flip PASS" in text
