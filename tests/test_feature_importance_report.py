"""Tests for the recurring feature-importance report (ENG-WS4-02)."""
from __future__ import annotations

import json
import logging
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

    def test_backend_metadata_is_bubbled_up_even_without_full_report(self, monkeypatch) -> None:
        monkeypatch.setattr(
            fr,
            "compute_feature_importance",
            lambda **kw: {
                "error": "insufficient labeled samples",
                "labeled_samples": 7,
                "backend": {"used": "gpu", "reason": "cuda_device:0", "device_name": "Test GPU"},
            },
        )
        rec = fr.generate_report(lookback_days=30, min_samples=30)
        assert rec["status"] == "insufficient_labels"
        assert rec["report"] is None
        assert rec["backend"]["used"] == "gpu"
        assert rec["backend"]["device_name"] == "Test GPU"


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

    def test_main_prints_backend_details(self, monkeypatch, tmp_path: Path, capsys) -> None:
        monkeypatch.setattr(fr, "FI_REPORT_DIR", tmp_path)
        monkeypatch.setattr(
            fr,
            "compute_feature_importance",
            lambda **kw: {
                "labeled_samples": 35,
                "total_samples": 40,
                "features": {"x": {"pearson_r": 0.1, "importance_normalized": 1.0}},
                "backend": {"used": "gpu", "reason": "cuda_device:0", "device_name": "Test GPU"},
            },
        )
        rc = fr.main(["--dry-run"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "backend=gpu" in out
        assert "backend_reason=cuda_device:0" in out
        assert "backend_device=Test GPU" in out


# ── Workflow integration ─────────────────────────────────────────────


class TestWorkflowIntegration:
    def test_workflow_runs_fi_report_step(self) -> None:
        text = Path(".github/workflows/open-prep-outcome-backfill.yml").read_text(encoding="utf-8")
        assert "-m open_prep.feature_importance_report" in text
        assert "artifacts/open_prep/feature_importance/" in text


class TestBackendSelection:
    def test_cpu_backend_is_selected_explicitly(self, monkeypatch) -> None:
        import open_prep.outcomes as outcomes

        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")
        backend = outcomes._resolve_feature_importance_backend()

        assert backend["used"] == "cpu"
        assert backend["reason"] == "requested_cpu"

    def test_compute_feature_importance_reports_backend(self, monkeypatch, tmp_path: Path) -> None:
        import open_prep.outcomes as outcomes

        monkeypatch.setattr(outcomes, "FEATURE_IMPORTANCE_DIR", tmp_path)
        sample_path = tmp_path / "fi_samples_2026-05-15.jsonl"
        sample_path.write_text(
            "\n".join(
                json.dumps(
                    {
                        "symbol": f"SYM{i}",
                        "date": "2026-05-15",
                        "profitable_30m": bool(i % 2),
                        **{key: float(i + idx) for idx, key in enumerate(outcomes.FEATURE_KEYS)},
                    }
                )
                for i in range(12)
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")

        report = outcomes.compute_feature_importance(lookback_days=1)

        assert report["backend"]["used"] == "cpu"
        assert report["backend"]["reason"] == "requested_cpu"
        assert report["labeled_samples"] == 12
        assert set(outcomes.FEATURE_KEYS).issubset(report["features"].keys())

    def test_compute_feature_importance_skips_bad_jsonl_lines(self, monkeypatch, tmp_path: Path) -> None:
        import open_prep.outcomes as outcomes

        monkeypatch.setattr(outcomes, "FEATURE_IMPORTANCE_DIR", tmp_path)
        sample_path = tmp_path / "fi_samples_2026-05-15.jsonl"
        # Distinct symbols: identical (symbol, date) rows would be removed
        # by the dedup layer, which is not what this test measures.
        good_a = json.dumps(
            {
                "symbol": "SYM1",
                "date": "2026-05-15",
                "profitable_30m": True,
                **{key: float(idx) for idx, key in enumerate(outcomes.FEATURE_KEYS)},
            }
        )
        good_b = json.dumps(
            {
                "symbol": "SYM2",
                "date": "2026-05-15",
                "profitable_30m": True,
                **{key: float(idx) for idx, key in enumerate(outcomes.FEATURE_KEYS)},
            }
        )
        sample_path.write_text(f"{good_a}\n{{bad json line}}\n{good_b}\n", encoding="utf-8")
        monkeypatch.setenv("OPEN_PREP_FI_BACKEND", "cpu")

        report = outcomes.compute_feature_importance(lookback_days=1)
        assert report["labeled_samples"] == 2


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

    def test_load_previous_latest_invalid_json_logs_debug(self, tmp_path, caplog) -> None:
        (tmp_path / "latest.json").write_text("{not json", encoding="utf-8")
        with caplog.at_level(logging.DEBUG, logger="open_prep.feature_importance_report"):
            assert fr._load_previous_latest(tmp_path) is None
        assert "FI latest.json unreadable/corrupt" in caplog.text
        debug_records = [r for r in caplog.records if "FI latest.json unreadable/corrupt" in r.message]
        assert debug_records, "Expected at least one log record matching the message"
        assert all(r.levelno == logging.DEBUG for r in debug_records), (
            f"Expected DEBUG level, got: {[r.levelname for r in debug_records]}"
        )
    def test_load_previous_latest_invalid_utf8_logs_debug(self, tmp_path, caplog) -> None:
        (tmp_path / "latest.json").write_bytes(b"\xff\xfe\xfa")
        with caplog.at_level(logging.DEBUG, logger="open_prep.feature_importance_report"):
            assert fr._load_previous_latest(tmp_path) is None
        assert "FI latest.json unlesbar" in caplog.text
        debug_records = [r for r in caplog.records if "FI latest.json unlesbar" in r.message]
        assert debug_records, "Expected at least one log record matching the message"
        assert all(r.levelno == logging.DEBUG for r in debug_records), (
            f"Expected DEBUG level, got: {[r.levelname for r in debug_records]}"
        )

    def test_load_previous_latest_invalid_utf8_logs_debug(self, tmp_path, caplog) -> None:
        (tmp_path / "latest.json").write_bytes(b"\xff\xfe\xfa")
        with caplog.at_level(logging.DEBUG, logger="open_prep.feature_importance_report"):
            assert fr._load_previous_latest(tmp_path) is None
        assert "FI latest.json unreadable/corrupt" in caplog.text
        debug_records = [r for r in caplog.records if "FI latest.json unreadable/corrupt" in r.message]
        assert debug_records, "Expected at least one log record matching the message"
        assert all(r.levelno == logging.DEBUG for r in debug_records), (
            f"Expected DEBUG level, got: {[r.levelname for r in debug_records]}"
        )

    def test_load_previous_latest_roundtrip(self, tmp_path) -> None:
        payload = {"status": "ok", "run_id": "x"}
        (tmp_path / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
        assert fr._load_previous_latest(tmp_path) == payload
