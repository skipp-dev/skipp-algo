"""Unit tests for the ADR-0023 Stage-1 → promotion-gate snapshot wiring."""
from __future__ import annotations

import json

from governance.promotion_gate import FamilyMetrics
from scripts.magnitude_snapshot_wiring import (
    MagnitudeSnapshot,
    apply_to_family_metrics,
    gate_snapshots,
    latest_rows_by_family,
    load_magnitude_snapshots,
    main,
    snapshot_from_row,
)


def _row(
    *,
    date: str,
    family: str,
    status: str,
    auc: float = 0.62,
) -> dict[str, object]:
    return {
        "date": date,
        "family": family,
        "status": status,
        "magnitude_auc": auc,
    }


def _write_ledger(path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


# ---- snapshot_from_row / status mapping ---------------------------------


def test_pass_maps_to_true():
    snap = snapshot_from_row(_row(date="2026-06-01", family="BOS", status="PASS"))
    assert snap.magnitude_resolution_pass is True
    assert snap.magnitude_auc == 0.62
    assert snap.family == "BOS"
    assert snap.status == "PASS"
    assert snap.date == "2026-06-01"


def test_fail_maps_to_false():
    snap = snapshot_from_row(_row(date="2026-06-01", family="FVG", status="FAIL"))
    assert snap.magnitude_resolution_pass is False


def test_inconclusive_maps_to_none():
    snap = snapshot_from_row(
        _row(date="2026-06-01", family="SWEEP", status="INCONCLUSIVE")
    )
    assert snap.magnitude_resolution_pass is None


def test_unknown_status_maps_to_none():
    snap = snapshot_from_row(_row(date="2026-06-01", family="BOS", status="???"))
    assert snap.magnitude_resolution_pass is None


def test_non_numeric_auc_becomes_none():
    row = {"date": "2026-06-01", "family": "BOS", "status": "PASS", "magnitude_auc": None}
    assert snapshot_from_row(row).magnitude_auc is None


# ---- latest_rows_by_family ----------------------------------------------


def test_latest_row_per_family_picks_max_date():
    rows = [
        _row(date="2026-06-01", family="BOS", status="FAIL", auc=0.55),
        _row(date="2026-06-03", family="BOS", status="PASS", auc=0.63),
        _row(date="2026-06-02", family="SWEEP", status="PASS", auc=0.66),
    ]
    latest = latest_rows_by_family(rows)
    assert latest["BOS"]["date"] == "2026-06-03"
    assert latest["BOS"]["status"] == "PASS"
    assert latest["SWEEP"]["date"] == "2026-06-02"


def test_latest_row_tie_keeps_last_seen():
    rows = [
        _row(date="2026-06-03", family="BOS", status="FAIL", auc=0.55),
        _row(date="2026-06-03", family="BOS", status="PASS", auc=0.63),
    ]
    assert latest_rows_by_family(rows)["BOS"]["status"] == "PASS"


def test_latest_rows_ignores_rows_without_family():
    rows = [{"date": "2026-06-01", "status": "PASS"}]
    assert latest_rows_by_family(rows) == {}


# ---- load_magnitude_snapshots / gate_snapshots --------------------------


def test_load_all_families_sorted(tmp_path):
    ledger = tmp_path / "l.jsonl"
    _write_ledger(
        ledger,
        [
            _row(date="2026-06-01", family="SWEEP", status="PASS"),
            _row(date="2026-06-01", family="BOS", status="PASS"),
            _row(date="2026-06-01", family="FVG", status="FAIL"),
            _row(date="2026-06-01", family="OB", status="FAIL"),
        ],
    )
    snaps = load_magnitude_snapshots(str(ledger))
    assert list(snaps) == ["BOS", "FVG", "OB", "SWEEP"]


def test_gate_snapshots_excludes_controls(tmp_path):
    ledger = tmp_path / "l.jsonl"
    _write_ledger(
        ledger,
        [
            _row(date="2026-06-01", family="BOS", status="PASS"),
            _row(date="2026-06-01", family="SWEEP", status="PASS"),
            _row(date="2026-06-01", family="FVG", status="FAIL"),
            _row(date="2026-06-01", family="OB", status="FAIL"),
        ],
    )
    snaps = gate_snapshots(str(ledger))
    assert set(snaps) == {"BOS", "SWEEP"}


def test_load_missing_ledger_is_empty(tmp_path):
    assert load_magnitude_snapshots(str(tmp_path / "nope.jsonl")) == {}


# ---- apply_to_family_metrics --------------------------------------------


def test_apply_sets_fields_without_mutating():
    metrics = FamilyMetrics(family="BOS")
    snap = MagnitudeSnapshot(
        family="BOS",
        magnitude_resolution_pass=True,
        magnitude_auc=0.618,
        status="PASS",
        date="2026-06-01",
    )
    updated = apply_to_family_metrics(metrics, snap)
    assert updated.magnitude_resolution_pass is True
    assert updated.magnitude_auc == 0.618
    # original untouched
    assert metrics.magnitude_resolution_pass is None
    assert metrics.magnitude_auc is None
    # other fields preserved
    assert updated.family == "BOS"


def test_apply_propagates_none_for_inconclusive():
    metrics = FamilyMetrics(family="SWEEP", magnitude_resolution_pass=True)
    snap = MagnitudeSnapshot(
        family="SWEEP",
        magnitude_resolution_pass=None,
        magnitude_auc=None,
        status="INCONCLUSIVE",
        date="2026-06-01",
    )
    updated = apply_to_family_metrics(metrics, snap)
    assert updated.magnitude_resolution_pass is None
    assert updated.magnitude_auc is None


# ---- main CLI -----------------------------------------------------------


def test_main_empty_ledger_returns_3(tmp_path):
    assert main(["--ledger", str(tmp_path / "nope.jsonl")]) == 3


def test_main_text_default_candidates_only(tmp_path, capsys):
    ledger = tmp_path / "l.jsonl"
    _write_ledger(
        ledger,
        [
            _row(date="2026-06-01", family="BOS", status="PASS"),
            _row(date="2026-06-01", family="FVG", status="FAIL"),
        ],
    )
    assert main(["--ledger", str(ledger)]) == 0
    out = capsys.readouterr().out
    assert "BOS" in out
    assert "FVG" not in out  # control excluded by default


def test_main_all_families_flag_includes_controls(tmp_path, capsys):
    ledger = tmp_path / "l.jsonl"
    _write_ledger(
        ledger,
        [
            _row(date="2026-06-01", family="BOS", status="PASS"),
            _row(date="2026-06-01", family="FVG", status="FAIL"),
        ],
    )
    assert main(["--ledger", str(ledger), "--all-families"]) == 0
    out = capsys.readouterr().out
    assert "BOS" in out
    assert "FVG" in out


def test_main_json_format(tmp_path, capsys):
    ledger = tmp_path / "l.jsonl"
    _write_ledger(ledger, [_row(date="2026-06-01", family="BOS", status="PASS")])
    assert main(["--ledger", str(ledger), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["BOS"]["magnitude_resolution_pass"] is True
    assert payload["BOS"]["magnitude_auc"] == 0.62
