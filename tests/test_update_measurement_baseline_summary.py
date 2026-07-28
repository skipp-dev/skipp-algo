"""The committed measurement baseline actually accumulates cross-run history.

Wired 2026-07-28 (B-sweep): ``--measurement-baseline-summary`` had no feeder —
these tests pin the merge semantics of the new roll-up script AND its
compatibility with the existing loader in ``run_smc_release_gates``.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_smc_release_gates import _load_measurement_history_rows
from scripts.update_measurement_baseline_summary import main, merge_history


def _summary(history_by_pair: dict) -> dict:
    return {"report_kind": "gate_evidence_summary", "measurement_history": {"history_by_pair": history_by_pair}}


def _row(checked_at: float, commit: str, marker: str = "") -> dict:
    return {"pair": "SPY/1D", "checked_at": checked_at, "commit": commit, "brier_score": 0.1, "marker": marker}


def test_accumulates_across_runs_newest_first(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    out = tmp_path / "out.json"
    baseline.write_text(json.dumps(_summary({"SPY/1D": [_row(100.0, "aaa")]})), encoding="utf-8")
    current.write_text(json.dumps(_summary({"SPY/1D": [_row(200.0, "bbb")]})), encoding="utf-8")

    rc = main(["--current", str(current), "--baseline", str(baseline), "--out", str(out)])
    assert rc == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    rows = merged["measurement_history"]["history_by_pair"]["SPY/1D"]
    assert [r["checked_at"] for r in rows] == [200.0, 100.0]

    loaded, note = _load_measurement_history_rows(str(out), symbol="SPY", timeframe="1D")
    assert note is None
    assert len(loaded) == 2  # >= required_history_runs=2: tightening can arm


def test_dedupes_rerun_rows_current_wins(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    out = tmp_path / "out.json"
    baseline.write_text(json.dumps(_summary({"SPY/1D": [_row(100.0, "aaa", marker="old")]})), encoding="utf-8")
    current.write_text(json.dumps(_summary({"SPY/1D": [_row(100.0, "aaa", marker="new")]})), encoding="utf-8")

    assert main(["--current", str(current), "--baseline", str(baseline), "--out", str(out)]) == 0
    rows = json.loads(out.read_text(encoding="utf-8"))["measurement_history"]["history_by_pair"]["SPY/1D"]
    assert len(rows) == 1
    assert rows[0]["marker"] == "new"


def test_caps_rows_per_pair_keeps_newest(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    out = tmp_path / "out.json"
    rows = [_row(float(ts), f"c{ts}") for ts in (10, 50, 30, 40, 20)]
    current.write_text(json.dumps(_summary({"SPY/1D": rows})), encoding="utf-8")

    assert main(["--current", str(current), "--baseline", str(tmp_path / "missing.json"), "--out", str(out), "--max-rows-per-pair", "3"]) == 0
    kept = json.loads(out.read_text(encoding="utf-8"))["measurement_history"]["history_by_pair"]["SPY/1D"]
    assert [r["checked_at"] for r in kept] == [50.0, 40.0, 30.0]


def test_bootstraps_without_existing_baseline(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    out = tmp_path / "out.json"
    current.write_text(json.dumps(_summary({"QQQ/1H": [_row(300.0, "ccc")]})), encoding="utf-8")

    assert main(["--current", str(current), "--baseline", str(tmp_path / "never-written.json"), "--out", str(out)]) == 0
    merged = json.loads(out.read_text(encoding="utf-8"))
    assert merged["measurement_history"]["history_by_pair"]["QQQ/1H"][0]["checked_at"] == 300.0


def test_broken_current_fails_without_writing(tmp_path: Path) -> None:
    current = tmp_path / "current.json"
    out = tmp_path / "out.json"
    current.write_text("{not json", encoding="utf-8")

    assert main(["--current", str(current), "--baseline", str(tmp_path / "missing.json"), "--out", str(out)]) != 0
    assert not out.exists()


def test_merge_preserves_disjoint_pairs() -> None:
    merged = merge_history(
        {"SPY/1D": [_row(200.0, "bbb")]},
        {"QQQ/1H": [{"pair": "QQQ/1H", "checked_at": 90.0, "commit": "zzz"}]},
        max_rows_per_pair=30,
    )
    assert sorted(merged) == ["QQQ/1H", "SPY/1D"]
    assert merged["QQQ/1H"][0]["checked_at"] == 90.0
