"""Tests for candidate weight production with drift-gate (ENG-WS4-03)."""
from __future__ import annotations

import json
from pathlib import Path

import open_prep.candidate_weights as cw
from open_prep.scorer import DEFAULT_WEIGHTS

# ── Fixtures ─────────────────────────────────────────────────────────


def _make_fi_report(features: dict[str, dict] | None = None,
                    labeled: int = 100,
                    error: str | None = None) -> dict:
    if error:
        return {"error": error, "labeled_samples": labeled}
    return {
        "labeled_samples": labeled,
        "total_samples": labeled,
        "features": features or {
            # Mild importances to keep weights well within drift band.
            "rvol": {"importance_normalized": 0.5, "pearson_r": 0.2,
                     "mean_separation": 0.1, "mean_win": 0.0, "mean_loss": 0.0},
        },
        "recommendations": [],
    }


# ── Generation states ────────────────────────────────────────────────


class TestGenerationStates:
    def test_insufficient_when_below_threshold(self, monkeypatch) -> None:
        monkeypatch.setattr(cw, "compute_feature_importance",
                            lambda **kw: _make_fi_report(labeled=5))
        rec = cw.generate_candidate(min_samples=30)
        assert rec["status"] == "insufficient_data"
        assert rec["weights"] is None
        assert rec["candidate_label"] is None
        assert rec["shortfall"] == 25

    def test_insufficient_when_fi_error(self, monkeypatch) -> None:
        monkeypatch.setattr(cw, "compute_feature_importance",
                            lambda **kw: _make_fi_report(error="no feature importance data found", labeled=0))
        rec = cw.generate_candidate(min_samples=30)
        assert rec["status"] == "insufficient_data"
        assert rec["fi_error"] == "no feature importance data found"

    def test_ok_when_within_drift(self, monkeypatch) -> None:
        monkeypatch.setattr(cw, "compute_feature_importance",
                            lambda **kw: _make_fi_report(labeled=100))
        rec = cw.generate_candidate(min_samples=30, max_drift=0.5)
        assert rec["status"] == "ok"
        assert rec["candidate_label"] == "candidate"
        assert isinstance(rec["weights"], dict)
        assert rec["drift_violations"] == []

    def test_drift_blocked_when_above_threshold(self, monkeypatch) -> None:
        # Maximal importance forces every mapped weight to scale by the
        # full Bayesian formula (data_weight = cur*1.5, blended back to
        # 0.7*cur*1.5 + 0.3*cur = 1.35*cur). Any non-zero drift then
        # exceeds the tiny gate threshold.
        loud = {
            "rvol_component": {"importance_normalized": 1.0, "pearson_r": 0.9,
                               "mean_separation": 1.0, "mean_win": 1.0, "mean_loss": 0.0,
                               # eval-findings B3: weight movement now requires
                               # the BH-FDR significance gate to pass.
                               "p_value": 0.0001, "fdr_significant": True},
        }
        monkeypatch.setattr(cw, "compute_feature_importance",
                            lambda **kw: _make_fi_report(features=loud, labeled=100))
        rec = cw.generate_candidate(min_samples=30, max_drift=0.001)
        assert rec["status"] == "drift_blocked"
        assert rec["candidate_label"] is None
        # Weights are still computed so callers can inspect what the
        # drift gate refused.
        assert isinstance(rec["weights"], dict)
        assert rec["drift_violations"]


# ── Persistence + drift-gate enforcement ─────────────────────────────


class TestPersistence:
    def test_run_log_is_written(self, tmp_path: Path) -> None:
        record = {"run_id": "20260420T120000", "status": "ok",
                  "weights": dict(DEFAULT_WEIGHTS), "drift_violations": []}
        out = cw.write_run_log(record, log_dir=tmp_path)
        assert out.exists()
        latest = json.loads((tmp_path / "latest.json").read_text())
        assert latest["status"] == "ok"

    def test_persist_writes_candidate_when_ok(self, monkeypatch, tmp_path: Path) -> None:
        saved: list[tuple[str, dict]] = []
        monkeypatch.setattr(cw, "save_weight_set",
                            lambda label, weights: saved.append((label, weights)))
        record = {"status": "ok", "weights": {"rvol": 1.2}}
        assert cw.persist_candidate(record) is True
        assert saved == [("candidate", {"rvol": 1.2})]

    def test_persist_refuses_drift_blocked(self, monkeypatch) -> None:
        called: list = []
        monkeypatch.setattr(cw, "save_weight_set",
                            lambda label, weights: called.append((label, weights)))
        record = {"status": "drift_blocked", "weights": {"rvol": 99.0}}
        assert cw.persist_candidate(record) is False
        assert called == []  # the drift gate must block writes

    def test_persist_refuses_insufficient(self, monkeypatch) -> None:
        called: list = []
        monkeypatch.setattr(cw, "save_weight_set",
                            lambda label, weights: called.append((label, weights)))
        record = {"status": "insufficient_data", "weights": None}
        assert cw.persist_candidate(record) is False
        assert called == []


# ── Versioning ───────────────────────────────────────────────────────


class TestVersioning:
    def test_candidate_label_distinct_from_default(self) -> None:
        # 'default' label is reserved for DEFAULT_WEIGHTS; CANDIDATE_LABEL
        # must differ so the two are unambiguously distinguishable.
        assert cw.CANDIDATE_LABEL != "default"
        assert cw.CANDIDATE_LABEL == "candidate"


# ── Main exit code ───────────────────────────────────────────────────


class TestMain:
    def test_main_returns_zero_for_known_states(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(cw, "CANDIDATE_RUN_LOG_DIR", tmp_path)
        monkeypatch.setattr(cw, "compute_feature_importance",
                            lambda **kw: _make_fi_report(labeled=5))
        monkeypatch.setattr(cw, "save_weight_set", lambda ln, w: None)
        rc = cw.main(["--min-samples", "30"])
        assert rc == 0
        rec = json.loads((tmp_path / "latest.json").read_text())
        assert rec["status"] == "insufficient_data"

    def test_main_returns_two_on_unexpected_error(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(cw, "CANDIDATE_RUN_LOG_DIR", tmp_path)

        def boom(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(cw, "compute_feature_importance", boom)
        rc = cw.main([])
        assert rc == 2

    def test_dry_run_skips_persistence(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(cw, "CANDIDATE_RUN_LOG_DIR", tmp_path)
        monkeypatch.setattr(cw, "compute_feature_importance",
                            lambda **kw: _make_fi_report(labeled=100))
        called: list = []
        monkeypatch.setattr(cw, "save_weight_set",
                            lambda ln, w: called.append((ln, w)))
        rc = cw.main(["--dry-run"])
        assert rc == 0
        assert not (tmp_path / "latest.json").exists()
        assert called == []
