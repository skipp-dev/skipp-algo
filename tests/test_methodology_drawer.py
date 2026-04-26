"""Tests for terminal_tabs.methodology_drawer (C7/T5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from terminal_tabs.methodology_drawer import (
    GATE_THRESHOLDS,
    SOURCE_LINKS,
    SPRINT_PLAN_LINKS,
    build_methodology,
    freshness_label,
)


def test_source_links_pinned() -> None:
    # Three canonical sources from the sprint-plan ToC.
    assert len(SOURCE_LINKS) == 3
    for label, url in SOURCE_LINKS:
        assert label
        assert url.startswith("http")


def test_sprint_plan_links_present_for_each_sprint() -> None:
    labels = [lbl for lbl, _ in SPRINT_PLAN_LINKS]
    for sprint in ("C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9"):
        assert any(sprint in lbl for lbl in labels), sprint


def test_sprint_plan_links_point_to_existing_files_when_present() -> None:
    # Repo-relative paths must exist in the workspace.  The tests
    # tolerate missing files only with an explicit message so the
    # reviewer sees the gap immediately.
    repo = Path(__file__).resolve().parent.parent
    missing = [path for _, path in SPRINT_PLAN_LINKS if not (repo / path).exists()]
    assert not missing, f"sprint plan files missing in repo: {missing}"


def test_gate_thresholds_have_required_fields() -> None:
    assert GATE_THRESHOLDS
    for entry in GATE_THRESHOLDS:
        assert {"name", "value", "rationale"} <= entry.keys()


def test_min_psr_threshold_single_sourced_from_gate_module() -> None:
    """C6 deep-review fix: methodology drawer must read the gate constant.

    Hardcoding 0.95 here was a literal duplicate of
    scripts.track_record_gate.MIN_PSR — drift between the two would
    show up as the sidebar advertising a threshold the gate does not
    enforce. Pin the relationship.
    """
    from scripts.track_record_gate import MIN_PSR

    psr_entry = next(e for e in GATE_THRESHOLDS if e["name"] == "min_psr")
    assert psr_entry["value"] == MIN_PSR


def test_freshness_label_unknown_when_missing() -> None:
    assert freshness_label(computed_at=None) == "unknown"
    assert freshness_label(computed_at="not-a-date") == "unknown"


def test_freshness_label_fresh_within_24h() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    ts = (now - timedelta(hours=2)).isoformat()
    assert freshness_label(computed_at=ts, now=now) == "fresh"


def test_freshness_label_stale_after_24h() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    ts = (now - timedelta(hours=48)).isoformat()
    assert freshness_label(computed_at=ts, now=now) == "stale"


def test_freshness_label_naive_datetime_assumed_utc() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    ts = "2026-04-26T11:00:00"
    assert freshness_label(computed_at=ts, now=now) == "fresh"


def test_build_methodology_with_payload_carries_freshness() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    payload = {"computed_at": "2026-04-26T11:00:00+00:00"}
    out = build_methodology(payload, now=now)
    assert out["freshness"] == "fresh"
    assert out["computed_at"] == "2026-04-26T11:00:00+00:00"


def test_build_methodology_without_payload_returns_unknown_freshness() -> None:
    out = build_methodology(None)
    assert out["freshness"] == "unknown"
    assert out["computed_at"] is None
    # Always returns the catalogue regardless of payload state.
    assert len(out["sources"]) == 3
    assert len(out["sprint_plans"]) == 8
    assert len(out["thresholds"]) == len(GATE_THRESHOLDS)


def test_build_methodology_is_deterministic() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    a = build_methodology(None, now=now)
    b = build_methodology(None, now=now)
    assert a == b
