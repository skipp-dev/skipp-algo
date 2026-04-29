"""Tests for scripts/smc_performance_report.py (WP-OV3)."""

from __future__ import annotations

from pathlib import Path

from scripts.smc_performance_report import generate_performance_report


def _good_summary() -> dict:
    return {
        "schema_version": "2.0",
        "symbol": "AAPL",
        "timeframe": "15",
        "scoring": {
            "n_events": 120,
            "brier_score": 0.18,
            "log_score": 0.42,
            "hit_rate": 0.62,
            "families_present": ["BOS", "OB"],
            "family_metrics": {
                "BOS": {"hit_rate": 0.65, "brier_score": 0.15, "n_events": 80},
                "OB": {"hit_rate": 0.55, "brier_score": 0.22, "n_events": 40},
            },
            "calibration": {
                "method": "isotonic",
                "calibrated_brier_score": 0.16,
                "calibrated_log_score": 0.38,
                "raw_ece": 0.05,
                "calibrated_ece": 0.03,
            },
            "stratified_calibration_summary": {
                "dimensions_present": ["session", "vol_regime"],
            },
            "stratified_calibration": {
                "session:us": {"brier_score": 0.17, "ece": 0.04, "n_events": 60},
                "vol_regime:high": {"brier_score": 0.20, "ece": 0.06, "n_events": 30},
            },
            "contextual_calibration_summary": {
                "best_dimension_by_adjusted_brier": "session",
                "best_dimension_by_adjusted_ece": "session",
                "dimensions_present": ["session"],
            },
        },
        "ensemble_quality": {
            "score": 0.72,
            "tier": "good",
            "available_components": 4,
            "contributions": {
                "heuristic": 0.25,
                "bias": 0.18,
                "scoring": 0.20,
                "vol_regime": 0.09,
            },
        },
        "warnings": [],
    }


class TestPerformanceReport:
    def test_good_data_generates_report(self, tmp_path: Path) -> None:
        out = tmp_path / "report.md"
        result = generate_performance_report(_good_summary(), out)
        assert result == out
        assert out.exists()
        text = out.read_text()
        assert "# SMC Performance Report — AAPL / 15" in text
        assert "Brier Score" in text
        assert "0.1800" in text
        assert "BOS" in text
        assert "OB" in text
        assert "Ensemble Score" in text
        assert "good" in text

    def test_missing_data_produces_fallbacks(self, tmp_path: Path) -> None:
        sparse = {
            "schema_version": "2.0",
            "symbol": "???",
            "timeframe": "60",
            "scoring": {
                "n_events": 0,
                "brier_score": float("nan"),
                "log_score": float("nan"),
                "hit_rate": float("nan"),
                "calibration": {"method": "identity"},
                "stratified_calibration_summary": {"dimensions_present": []},
                "contextual_calibration_summary": {},
            },
            "warnings": ["no data"],
        }
        out = tmp_path / "sparse.md"
        generate_performance_report(sparse, out)
        text = out.read_text()
        assert "— " in text or "—" in text  # fallback dash
        assert "No scored events" in text or "warning(s)" in text
        assert "No stratified calibration dimensions" in text

    def test_markdown_structure(self, tmp_path: Path) -> None:
        out = tmp_path / "structure.md"
        generate_performance_report(_good_summary(), out)
        text = out.read_text()
        expected_headings = [
            "# SMC Performance Report",
            "## Signal Quality",
            "## Regime Performance",
            "## Enrichment Value",
            "## Trust-Tier Correlation",
            "## Conclusion",
        ]
        for heading in expected_headings:
            assert heading in text, f"Missing heading: {heading}"
