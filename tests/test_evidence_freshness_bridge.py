"""Tests for the daemon-side evidence_freshness_bridge (URL/local, fail-soft)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.live_overlay_daemon import evidence_freshness_bridge as bridge


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch):
    # Never hit a real URL; isolate the module cache between tests.
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_URL", "")
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0
    yield
    bridge._cached = None
    bridge._cached_at_monotonic = 0.0


def _write(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "evidence.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_missing_snapshot_is_fail_soft(monkeypatch, tmp_path):
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(tmp_path / "nope.json"))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "missing_snapshot"
    # Shape is still complete so metric rendering never KeyErrors.
    assert snap["ledger"]["newest_date"] == ""
    assert snap["fills"]["closed_cumulative"] == 0


def test_unreadable_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "evidence.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "unreadable_snapshot"


def test_valid_snapshot_is_normalized(monkeypatch, tmp_path):
    p = _write(
        tmp_path,
        {
            "generated_at_unix": 1_783_000_000.0,
            "ledger": {"newest_date": "2026-06-11", "plane": "15m", "rows": 4, "candidate_pass": 2},
            "audit_branch": {"last_commit_date": "2026-07-06"},
            "fills": {"filled_cumulative": 3, "closed_cumulative": 1, "target": 20,
                      "newest_incubation_date": "2026-07-06"},
            "wsh": {"newest_date": "2026-06-23", "status": "degraded:no-events"},
        },
    )
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["ledger"]["plane"] == "15m"
    assert snap["ledger"]["candidate_pass"] == 2.0
    assert snap["audit_branch"]["last_commit_date"] == "2026-07-06"
    assert snap["fills"]["closed_cumulative"] == 1.0


def test_partial_snapshot_tolerated(monkeypatch, tmp_path):
    """A snapshot missing whole sections must not raise — missing sections
    normalize to their empty defaults."""
    p = _write(tmp_path, {"generated_at_unix": 1_783_000_000.0, "ledger": {"newest_date": "2026-07-06"}})
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 1.0
    assert snap["ledger"]["newest_date"] == "2026-07-06"
    assert snap["audit_branch"]["last_commit_date"] == ""
    assert snap["fills"]["target"] == 0.0


def test_non_dict_snapshot_is_fail_soft(monkeypatch, tmp_path):
    p = tmp_path / "evidence.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setenv("EVIDENCE_FRESHNESS_SNAPSHOT_PATH", str(p))
    snap = bridge.snapshot()
    assert snap["loaded"] == 0.0
    assert snap["error"] == "malformed_snapshot"


# --------------------------------------------------------------------------- #
# age_seconds_from_date
# --------------------------------------------------------------------------- #


def test_age_seconds_from_date_monotonic():
    now = 1_783_000_000.0
    # 2026-06-11 midnight UTC is well before `now`; age must be positive.
    age = bridge.age_seconds_from_date("2026-06-11", now=now)
    assert age is not None and age > 0


def test_age_seconds_from_date_unparseable_is_none():
    assert bridge.age_seconds_from_date("", now=1_783_000_000.0) is None
    assert bridge.age_seconds_from_date("not-a-date", now=1_783_000_000.0) is None


def test_age_seconds_never_negative_for_future_date():
    # A future date must clamp to 0, not report negative age.
    assert bridge.age_seconds_from_date("2099-01-01", now=1_783_000_000.0) == 0.0
