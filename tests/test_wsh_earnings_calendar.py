"""Tests for scripts.wsh_earnings_calendar (C13/T7.1)."""

from __future__ import annotations

import json

from scripts.wsh_earnings_calendar import (
    WSH_EARNINGS_EVENT_TYPES,
    WSH_EVENTS_SCHEMA_VERSION,
    WshEvent,
    filter_earnings_events,
    parse_wsh_event_data,
)


def test_schema_version_is_pinned() -> None:
    assert WSH_EVENTS_SCHEMA_VERSION == "1.0.0"


def test_earnings_event_types_cover_known_wsh_strings() -> None:
    # The TWS WSH filter docs list these as the canonical earnings
    # event identifiers.
    expected = {
        "Earnings",
        "EarningsAnnouncement",
        "EarningsDated",
        "EarningsRevised",
    }
    assert expected.issubset(WSH_EARNINGS_EVENT_TYPES)


def test_parse_wsh_event_data_happy_path() -> None:
    payload = json.dumps({
        "events": [
            {
                "type": "EarningsAnnouncement",
                "date": "2026-05-01",
                "time": "16:00",
                "tz": "America/New_York",
                "confidence": "Confirmed",
            },
            {
                "type": "Dividend",
                "date": "2026-05-15",
            },
        ]
    })
    events = parse_wsh_event_data(symbol="AAPL", con_id=265598, raw_payload=payload)
    assert len(events) == 2
    aa = events[0]
    assert isinstance(aa, WshEvent)
    assert aa.symbol == "AAPL"
    assert aa.con_id == 265598
    assert aa.event_type == "EarningsAnnouncement"
    assert aa.event_date == "2026-05-01"
    assert aa.event_time == "16:00"
    assert aa.confidence == "Confirmed"


def test_parse_wsh_event_data_skips_invalid_records() -> None:
    payload = json.dumps({
        "events": [
            {"type": "Earnings"},  # missing date → skipped
            {"date": "2026-05-01"},  # missing type → skipped
            "not a dict",
        ]
    })
    events = parse_wsh_event_data(symbol="X", con_id=1, raw_payload=payload)
    assert events == []


def test_parse_wsh_event_data_returns_empty_on_garbage() -> None:
    assert parse_wsh_event_data(symbol="X", con_id=1, raw_payload="") == []
    assert parse_wsh_event_data(symbol="X", con_id=1, raw_payload="not json") == []
    # Top-level list (not dict) → ignored.
    assert parse_wsh_event_data(symbol="X", con_id=1, raw_payload="[]") == []


def test_filter_earnings_events_keeps_only_earnings_types() -> None:
    events = [
        WshEvent("AAPL", 1, "EarningsAnnouncement", "2026-05-01", None, None, None, "wsh"),
        WshEvent("AAPL", 1, "Dividend", "2026-05-15", None, None, None, "wsh"),
        WshEvent("MSFT", 2, "EarningsRevised", "2026-04-30", None, None, None, "wsh"),
    ]
    kept = filter_earnings_events(events)
    assert len(kept) == 2
    assert all(e.event_type in WSH_EARNINGS_EVENT_TYPES for e in kept)


def test_wsh_event_to_dict_round_trip() -> None:
    e = WshEvent("X", 9, "Earnings", "2026-05-01", "08:00", "UTC", "Confirmed", "wsh")
    d = e.to_dict()
    assert d["symbol"] == "X"
    assert d["schema_version"] == WSH_EVENTS_SCHEMA_VERSION
