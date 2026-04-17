"""Tests for the E2E smoke CI script."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_smoke_snapshot_collects_expected_keys() -> None:
    from scripts.e2e_smoke_ci import collect_smoke_snapshot
    snapshot = collect_smoke_snapshot()
    assert snapshot["schema"] == "e2e_smoke_v1"
    assert isinstance(snapshot["governance_codes"], list)
    assert len(snapshot["governance_codes"]) >= 10
    assert isinstance(snapshot["hard_blocking_codes"], list)
    assert isinstance(snapshot["threshold_fields"], list)
    assert isinstance(snapshot["reference_symbols"], list)
    assert isinstance(snapshot["gate_names"], list)
    assert snapshot["governance_validation_errors"] == []


def test_smoke_snapshot_matches_reference() -> None:
    from scripts.e2e_smoke_ci import collect_smoke_snapshot, compare_snapshots, DEFAULT_REFERENCE
    if not DEFAULT_REFERENCE.exists():
        pytest.skip("Reference file not generated yet")
    reference = json.loads(DEFAULT_REFERENCE.read_text(encoding="utf-8"))
    current = collect_smoke_snapshot()
    diffs = compare_snapshots(current, reference)
    assert diffs == [], f"Structural regressions: {diffs}"


def test_compare_detects_governance_code_change() -> None:
    from scripts.e2e_smoke_ci import compare_snapshots
    reference = {
        "governance_codes": ["A", "B"],
        "governance_by_status": {},
        "governance_status_values": [],
        "hard_blocking_codes": [],
        "threshold_fields": [],
        "threshold_defaults": {},
        "reference_symbols": [],
        "reference_timeframes": [],
        "gate_names": [],
        "dashboard_audit_row_count": 10,
        "reference_symbols_count": 5,
    }
    current = dict(reference)
    current["governance_codes"] = ["A", "B", "C"]
    current["governance_validation_errors"] = []
    diffs = compare_snapshots(current, reference)
    assert any("governance_codes" in d for d in diffs)


def test_compare_detects_dashboard_row_shift() -> None:
    from scripts.e2e_smoke_ci import compare_snapshots
    reference = {
        "governance_codes": [],
        "governance_by_status": {},
        "governance_status_values": [],
        "hard_blocking_codes": [],
        "threshold_fields": [],
        "threshold_defaults": {},
        "reference_symbols": [],
        "reference_timeframes": [],
        "gate_names": [],
        "dashboard_audit_row_count": 55,
        "reference_symbols_count": 12,
    }
    current = dict(reference)
    current["dashboard_audit_row_count"] = 57
    current["governance_validation_errors"] = []
    diffs = compare_snapshots(current, reference)
    assert any("Dashboard audit row count" in d for d in diffs)


def test_compare_detects_governance_validation_failure() -> None:
    from scripts.e2e_smoke_ci import compare_snapshots
    reference = {
        "governance_codes": [],
        "governance_by_status": {},
        "governance_status_values": [],
        "hard_blocking_codes": [],
        "threshold_fields": [],
        "threshold_defaults": {},
        "reference_symbols": [],
        "reference_timeframes": [],
        "gate_names": [],
        "dashboard_audit_row_count": 10,
        "reference_symbols_count": 5,
    }
    current = dict(reference)
    current["governance_validation_errors"] = ["some error"]
    diffs = compare_snapshots(current, reference)
    assert any("Governance validation failed" in d for d in diffs)


def test_compare_detects_symbol_count_shrink() -> None:
    from scripts.e2e_smoke_ci import compare_snapshots
    reference = {
        "governance_codes": [],
        "governance_by_status": {},
        "governance_status_values": [],
        "hard_blocking_codes": [],
        "threshold_fields": [],
        "threshold_defaults": {},
        "reference_symbols": ["AAPL", "MSFT"],
        "reference_timeframes": [],
        "gate_names": [],
        "dashboard_audit_row_count": 10,
        "reference_symbols_count": 12,
    }
    current = dict(reference)
    current["reference_symbols"] = ["AAPL"]
    current["reference_symbols_count"] = 1
    current["governance_validation_errors"] = []
    diffs = compare_snapshots(current, reference)
    assert any("symbol count shrank" in d for d in diffs)


def test_compare_no_diff_on_identical() -> None:
    from scripts.e2e_smoke_ci import compare_snapshots
    snapshot = {
        "governance_codes": ["A"],
        "governance_by_status": {"HARD_BLOCKING": ["A"]},
        "governance_status_values": ["HARD_BLOCKING"],
        "hard_blocking_codes": ["A"],
        "threshold_fields": ["x"],
        "threshold_defaults": {"x": 1.0},
        "reference_symbols": ["AAPL"],
        "reference_timeframes": ["5m"],
        "gate_names": ["test"],
        "dashboard_audit_row_count": 10,
        "reference_symbols_count": 1,
        "governance_validation_errors": [],
    }
    diffs = compare_snapshots(snapshot, snapshot)
    assert diffs == []
