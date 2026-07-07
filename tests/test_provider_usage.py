"""Tests for newsstack_fmp/provider_usage.py (provider API-usage recorder)."""
from __future__ import annotations

import json
from pathlib import Path

from newsstack_fmp.provider_usage import ProviderUsage


def test_record_accumulates_bytes_records_calls() -> None:
    u = ProviderUsage()
    u.record("fmp", response_bytes=1000, records=5)
    u.record("FMP", response_bytes=500, records=2)  # case-insensitive
    u.record("benzinga", response_bytes=200, records=1)
    snap = u.snapshot()
    assert snap["fmp"] == {"calls": 2, "bytes": 1500, "records": 7}
    assert snap["benzinga"] == {"calls": 1, "bytes": 200, "records": 1}


def test_record_is_fail_soft_on_bad_input() -> None:
    u = ProviderUsage()
    u.record("fmp", response_bytes=-10, records=-3)  # coerced to 0
    u.record("", response_bytes=100)                 # empty provider -> "unknown"
    snap = u.snapshot()
    assert snap["fmp"] == {"calls": 1, "bytes": 0, "records": 0}
    assert snap["unknown"]["bytes"] == 100


def test_flush_creates_monthly_snapshot(tmp_path: Path) -> None:
    u = ProviderUsage()
    u.record("fmp", response_bytes=1000, records=5)
    path = tmp_path / "monitoring" / "provider_usage.json"
    assert u.flush(path, month="2026-07", now_iso="2026-07-07T10:00:00Z") is True
    data = json.loads(path.read_text())
    assert data["current_month"] == "2026-07"
    assert data["months"]["2026-07"]["fmp"] == {"calls": 1, "bytes": 1000, "records": 5}
    # Recorder is reset after a successful flush (deltas already persisted).
    assert u.snapshot() == {}


def test_flush_accumulates_across_runs(tmp_path: Path) -> None:
    path = tmp_path / "provider_usage.json"
    u1 = ProviderUsage()
    u1.record("fmp", response_bytes=1000, records=5)
    u1.flush(path, month="2026-07", now_iso="2026-07-07T10:00:00Z")
    # Second, independent run (fresh process/recorder) adds to the same month.
    u2 = ProviderUsage()
    u2.record("fmp", response_bytes=250, records=1)
    u2.flush(path, month="2026-07", now_iso="2026-07-07T11:00:00Z")
    data = json.loads(path.read_text())
    assert data["months"]["2026-07"]["fmp"] == {"calls": 2, "bytes": 1250, "records": 6}


def test_flush_starts_fresh_counter_each_month(tmp_path: Path) -> None:
    path = tmp_path / "provider_usage.json"
    u = ProviderUsage()
    u.record("fmp", response_bytes=9_000_000)
    u.flush(path, month="2026-06", now_iso="2026-06-30T23:59:00Z")
    u.record("fmp", response_bytes=1000)
    u.flush(path, month="2026-07", now_iso="2026-07-01T00:01:00Z")
    data = json.loads(path.read_text())
    # New month is its own bucket; the prior month is retained (history).
    assert data["current_month"] == "2026-07"
    assert data["months"]["2026-07"]["fmp"]["bytes"] == 1000
    assert data["months"]["2026-06"]["fmp"]["bytes"] == 9_000_000


def test_flush_caps_history_to_recent_months(tmp_path: Path) -> None:
    path = tmp_path / "provider_usage.json"
    u = ProviderUsage()
    for m in ("2026-03", "2026-04", "2026-05", "2026-06"):
        u.record("fmp", response_bytes=1)
        u.flush(path, month=m, now_iso=f"{m}-01T00:00:00Z")
    data = json.loads(path.read_text())
    # Only the newest 3 months survive; the oldest is dropped.
    assert set(data["months"]) == {"2026-04", "2026-05", "2026-06"}


def test_flush_noop_when_nothing_recorded(tmp_path: Path) -> None:
    u = ProviderUsage()
    path = tmp_path / "provider_usage.json"
    assert u.flush(path, month="2026-07", now_iso="2026-07-07T10:00:00Z") is False
    assert not path.exists()


def test_flush_fail_soft_on_unwritable_path(tmp_path: Path) -> None:
    u = ProviderUsage()
    u.record("fmp", response_bytes=1000)
    # A file where a directory component must be -> mkdir/write raises, swallowed.
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    assert u.flush(blocker / "sub" / "usage.json", month="2026-07", now_iso="x") is False
