"""Tests for the recurring feature-importance report (ENG-WS4-02)."""
from __future__ import annotations

import json
from pathlib import Path

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


# ── Ranking drift detection (E4) ─────────────────────────────────────


class TestRankingDrift:
    def test_extract_ranking_from_features_dict(self) -> None:
        raw = {
            "features": {
                "a": {"importance_normalized": 0.9},
                "b": {"importance_normalized": 0.1},
                "c": {"importance_normalized": 0.5},
            }
        }
        assert fr._extract_ranking(raw) == ["a", "c", "b"]

    def test_extract_ranking_handles_missing(self) -> None:
        assert fr._extract_ranking(None) == []
        assert fr._extract_ranking({}) == []
        assert fr._extract_ranking({"features": "not a dict"}) == []

    def test_compute_ranking_drift_ok_when_stable(self) -> None:
        drift = fr.compute_ranking_drift(
            ["a", "b", "c", "d"], ["a", "b", "c", "d"],
            position_threshold=3, top_n=10,
        )
        assert drift["status"] == "ok"
        assert drift["max_position_delta"] == 0
        assert drift["drifted_features"] == []

    def test_compute_ranking_drift_warns_on_large_shift(self) -> None:
        drift = fr.compute_ranking_drift(
            current=["c", "a", "b"],
            previous=["a", "b", "c"],
            position_threshold=1, top_n=10,
        )
        assert drift["status"] == "warn"
        # 'c' moved from pos 3 to pos 1 → delta -2, abs 2 > 1
        names = {d["feature"] for d in drift["drifted_features"]}
        assert "c" in names

    def test_compute_ranking_drift_unknown_on_empty(self) -> None:
        assert fr.compute_ranking_drift([], [])["status"] == "unknown"
        assert fr.compute_ranking_drift(["a"], [])["status"] == "unknown"

    def test_generate_report_attaches_drift_when_both_ok(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fr, "compute_feature_importance",
            lambda **kw: {
                "labeled_samples": 100,
                "total_samples": 120,
                "features": {
                    "a": {"importance_normalized": 0.9},
                    "b": {"importance_normalized": 0.7},
                    "c": {"importance_normalized": 0.5},
                    "d": {"importance_normalized": 0.3},
                    "e": {"importance_normalized": 0.1},
                },
            },
        )
        # previous ranking is reversed → top feature drifts 4 positions,
        # which exceeds the default threshold of 3.
        previous = {
            "status": "ok",
            "report": {
                "features": {
                    "a": {"importance_normalized": 0.1},
                    "b": {"importance_normalized": 0.3},
                    "c": {"importance_normalized": 0.5},
                    "d": {"importance_normalized": 0.7},
                    "e": {"importance_normalized": 0.9},
                }
            },
        }
        rec = fr.generate_report(lookback_days=30, min_samples=30, previous_report=previous)
        assert rec["status"] == "ok"
        drift = rec["ranking_drift"]
        assert drift["status"] == "warn"
        assert drift["max_position_delta"] >= 4

    def test_generate_report_drift_unknown_when_no_prior(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fr, "compute_feature_importance",
            lambda **kw: {
                "labeled_samples": 100,
                "total_samples": 100,
                "features": {"a": {"importance_normalized": 1.0}},
            },
        )
        rec = fr.generate_report(lookback_days=30, min_samples=30, previous_report=None)
        assert rec["ranking_drift"]["status"] == "unknown"

    def test_load_previous_latest_missing(self, tmp_path) -> None:
        assert fr._load_previous_latest(tmp_path) is None

    def test_load_previous_latest_invalid_json(self, tmp_path) -> None:
        (tmp_path / "latest.json").write_text("{not json", encoding="utf-8")
        assert fr._load_previous_latest(tmp_path) is None

    def test_load_previous_latest_roundtrip(self, tmp_path) -> None:
        payload = {"status": "ok", "run_id": "x"}
        (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
        assert fr._load_previous_latest(tmp_path) == payload
