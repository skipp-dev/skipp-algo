"""Tests for the recurring feature-importance report (ENG-WS4-02)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import open_prep.feature_importance_report as fr


# ── Status classification ────────────────────────────────────────────


class TestStatus:
    def test_no_data(self) -> None:
        assert fr._classify_status({"error": "no feature importance data found"}, 30) == "no_data"

    def test_insufficient(self) -> None:
        assert fr._classify_status({"labeled_samples": 5}, 30) == "insufficient_labels"

    def test_ok(self) -> None:
        assert fr._classify_status({"labeled_samples": 100, "features": {}}, 30) == "ok"


# ── Report generation wrapper ────────────────────────────────────────


class TestGenerateReport:
    def test_no_data_state(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fr, "compute_feature_importance",
            lambda **kw: {"error": "no feature importance data found"},
        )
        rec = fr.generate_report(lookback_days=30, min_samples=30)
        assert rec["status"] == "no_data"
        assert rec["report"] is None
        assert rec["labeled_samples"] == 0
        assert rec["shortfall"] == 0

    def test_insufficient_state_records_shortfall(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fr, "compute_feature_importance",
            lambda **kw: {"total_samples": 12, "labeled_samples": 7},
        )
        rec = fr.generate_report(lookback_days=30, min_samples=30)
        assert rec["status"] == "insufficient_labels"
        assert rec["report"] is None
        assert rec["labeled_samples"] == 7
        assert rec["shortfall"] == 23

    def test_ok_state_carries_full_report(self, monkeypatch) -> None:
        full = {"total_samples": 200, "labeled_samples": 150, "features": {"x": {"pearson_r": 0.4}}}
        monkeypatch.setattr(fr, "compute_feature_importance", lambda **kw: full)
        rec = fr.generate_report(lookback_days=30, min_samples=30)
        assert rec["status"] == "ok"
        assert rec["report"] == full
        assert rec["labeled_samples"] == 150
        assert rec["shortfall"] == 0


# ── Persistence ──────────────────────────────────────────────────────


class TestWriteReport:
    def test_writes_per_run_and_latest(self, tmp_path: Path) -> None:
        record = {
            "run_id": "20260420T120000",
            "generated_at_et": "2026-04-20T12:00:00",
            "lookback_days": 30,
            "min_samples_threshold": 30,
            "labeled_samples": 0,
            "total_samples": 0,
            "status": "no_data",
            "report": None,
            "shortfall": 0,
        }
        out = fr.write_report(record, report_dir=tmp_path)
        assert out.exists()
        assert json.loads(out.read_text())["status"] == "no_data"
        assert json.loads((tmp_path / "latest.json").read_text())["status"] == "no_data"


# ── Main exit code ───────────────────────────────────────────────────


class TestMain:
    def test_main_returns_zero_on_recognised_state(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(fr, "FI_REPORT_DIR", tmp_path)
        monkeypatch.setattr(
            fr, "compute_feature_importance",
            lambda **kw: {"labeled_samples": 5},
        )
        rc = fr.main(["--lookback", "5", "--min-samples", "30"])
        assert rc == 0
        assert (tmp_path / "latest.json").exists()
        rec = json.loads((tmp_path / "latest.json").read_text())
        assert rec["status"] == "insufficient_labels"

    def test_main_returns_two_on_unexpected_error(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(fr, "FI_REPORT_DIR", tmp_path)

        def boom(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(fr, "compute_feature_importance", boom)
        rc = fr.main([])
        assert rc == 2

    def test_dry_run_does_not_persist(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(fr, "FI_REPORT_DIR", tmp_path)
        monkeypatch.setattr(
            fr, "compute_feature_importance",
            lambda **kw: {"labeled_samples": 5},
        )
        rc = fr.main(["--dry-run"])
        assert rc == 0
        assert not (tmp_path / "latest.json").exists()


# ── Workflow integration ─────────────────────────────────────────────


class TestWorkflowIntegration:
    def test_workflow_runs_fi_report_step(self) -> None:
        text = Path(".github/workflows/open-prep-outcome-backfill.yml").read_text(encoding="utf-8")
        assert "python -m open_prep.feature_importance_report" in text
        assert "artifacts/open_prep/feature_importance/" in text
