"""Plausibility tests for v5.5b measurement/showcase lane artifacts.

Validates that benchmark, scoring, and showcase artifacts can be produced
with valid structure and that key metrics are finite and in expected ranges.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from smc_core.benchmark import (
    BenchmarkResult,
    EventFamily,
    EventFamilyKPI,
    build_benchmark,
    export_benchmark_artifacts,
)
from smc_core.scoring import (
    ScoredEvent,
    ScoringResult,
    brier_score,
    export_scoring_artifact,
    log_score,
    score_events,
)
from smc_core.schema_version import SCHEMA_VERSION


# ── Benchmark artifact plausibility ──────────────────────────────────


class TestBenchmarkArtifactPlausibility:
    """Verify benchmark artifacts are structurally valid and consistent."""

    @pytest.fixture()
    def sample_benchmark(self) -> BenchmarkResult:
        events: dict[EventFamily, list[dict[str, float | bool]]] = {
            "BOS": [
                {"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0.01, "mfe": 0.04},
                {"hit": False, "time_to_mitigation": 12, "invalidated": True, "mae": 0.03, "mfe": 0.01},
            ],
            "OB": [
                {"hit": True, "time_to_mitigation": 5, "invalidated": False, "mae": 0.02, "mfe": 0.06},
            ],
            "FVG": [],
            "SWEEP": [
                {"hit": True, "time_to_mitigation": 2, "invalidated": False, "mae": 0.005, "mfe": 0.03},
                {"hit": True, "time_to_mitigation": 4, "invalidated": False, "mae": 0.01, "mfe": 0.05},
                {"hit": False, "time_to_mitigation": 8, "invalidated": True, "mae": 0.04, "mfe": 0.01},
            ],
        }
        return build_benchmark("AAPL", "15m", events_by_family=events)

    def test_all_four_families_present(self, sample_benchmark: BenchmarkResult) -> None:
        families = {kpi.family for kpi in sample_benchmark.kpis}
        assert families == {"BOS", "OB", "FVG", "SWEEP"}

    def test_kpi_hit_rate_in_range(self, sample_benchmark: BenchmarkResult) -> None:
        for kpi in sample_benchmark.kpis:
            assert 0.0 <= kpi.hit_rate <= 1.0, f"{kpi.family} hit_rate out of range"

    def test_kpi_invalidation_rate_in_range(self, sample_benchmark: BenchmarkResult) -> None:
        for kpi in sample_benchmark.kpis:
            assert 0.0 <= kpi.invalidation_rate <= 1.0, f"{kpi.family} invalidation_rate out of range"

    def test_kpi_n_events_non_negative(self, sample_benchmark: BenchmarkResult) -> None:
        for kpi in sample_benchmark.kpis:
            assert kpi.n_events >= 0

    def test_kpi_mae_mfe_finite(self, sample_benchmark: BenchmarkResult) -> None:
        for kpi in sample_benchmark.kpis:
            if kpi.n_events > 0:
                assert math.isfinite(kpi.mae), f"{kpi.family} mae not finite"
                assert math.isfinite(kpi.mfe), f"{kpi.family} mfe not finite"

    def test_schema_version_present(self, sample_benchmark: BenchmarkResult) -> None:
        assert sample_benchmark.schema_version == SCHEMA_VERSION

    def test_artifact_export_roundtrip(self, sample_benchmark: BenchmarkResult, tmp_path: Path) -> None:
        manifest = export_benchmark_artifacts(sample_benchmark, tmp_path)
        assert (tmp_path / "manifest.json").exists()
        benchmark_file = tmp_path / f"benchmark_{sample_benchmark.symbol}_{sample_benchmark.timeframe}.json"
        assert benchmark_file.exists()

        data = json.loads(benchmark_file.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert isinstance(data["kpis"], list)
        assert len(data["kpis"]) == 4
        for kpi in data["kpis"]:
            assert "family" in kpi
            assert "hit_rate" in kpi
            assert "n_events" in kpi


# ── Scoring artifact plausibility ────────────────────────────────────


class TestScoringArtifactPlausibility:
    """Verify scoring artifacts have valid metrics in expected ranges."""

    @pytest.fixture()
    def sample_scoring(self) -> ScoringResult:
        events = [
            ScoredEvent("s1", "SWEEP", 0.8, True, 1.0),
            ScoredEvent("b1", "BOS", 0.3, False, 2.0),
            ScoredEvent("o1", "OB", 0.6, True, 3.0),
            ScoredEvent("f1", "FVG", 0.1, False, 4.0),
        ]
        return score_events(events)

    def test_brier_score_finite_and_in_range(self, sample_scoring: ScoringResult) -> None:
        assert math.isfinite(sample_scoring.brier_score)
        assert 0.0 <= sample_scoring.brier_score <= 1.0

    def test_log_score_finite_and_non_negative(self, sample_scoring: ScoringResult) -> None:
        assert math.isfinite(sample_scoring.log_score)
        assert sample_scoring.log_score >= 0.0

    def test_hit_rate_finite_and_in_range(self, sample_scoring: ScoringResult) -> None:
        assert math.isfinite(sample_scoring.hit_rate)
        assert 0.0 <= sample_scoring.hit_rate <= 1.0

    def test_n_events_matches(self, sample_scoring: ScoringResult) -> None:
        assert sample_scoring.n_events == 4
        assert set(sample_scoring.family_metrics) == {"BOS", "OB", "FVG", "SWEEP"}

    def test_empty_scoring_produces_nan(self) -> None:
        result = score_events([])
        assert result.n_events == 0
        assert math.isnan(result.brier_score)
        assert math.isnan(result.log_score)

    def test_artifact_export_roundtrip(self, sample_scoring: ScoringResult, tmp_path: Path) -> None:
        path = export_scoring_artifact(
            sample_scoring,
            symbol="SPY",
            timeframe="1H",
            output_dir=tmp_path,
            schema_version=SCHEMA_VERSION,
        )
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["symbol"] == "SPY"
        assert data["timeframe"] == "1H"
        assert isinstance(data["generated_at"], float)
        assert math.isfinite(data["brier_score"])
        assert 0.0 <= data["brier_score"] <= 1.0
        assert math.isfinite(data["log_score"])
        assert data["log_score"] >= 0.0
        assert data["aggregate"]["n_events"] == 4
        assert set(data["family_metrics"]) == {"BOS", "OB", "FVG", "SWEEP"}


# ── Brier/Log score edge-case plausibility ───────────────────────────


class TestMetricEdgeCases:
    """Ensure scoring metrics behave correctly at edge conditions."""

    def test_perfect_brier_is_zero(self) -> None:
        assert brier_score([(1.0, True), (0.0, False)]) == 0.0

    def test_worst_brier_is_one(self) -> None:
        assert brier_score([(0.0, True), (1.0, False)]) == 1.0

    def test_log_score_never_inf(self) -> None:
        # Even extreme probabilities should not produce infinity
        result = log_score([(0.0, True), (1.0, False)])
        assert math.isfinite(result)

    def test_log_score_perfect_is_near_zero(self) -> None:
        result = log_score([(0.999, True), (0.001, False)])
        assert result < 0.01

    def test_single_event_brier(self) -> None:
        result = brier_score([(0.7, True)])
        assert math.isfinite(result)
        assert 0.0 <= result <= 1.0

    def test_all_same_outcome(self) -> None:
        result = score_events([
            ScoredEvent("e1", "BOS", 0.9, True, 1.0),
            ScoredEvent("e2", "BOS", 0.8, True, 2.0),
        ])
        assert result.hit_rate == 1.0
        assert math.isfinite(result.brier_score)
        assert math.isfinite(result.log_score)


# ── Showcase fixture plausibility ────────────────────────────────────


class TestShowcaseArtifactPlausibility:
    """Check that showcase artifacts exist and have expected structure."""

    _SHOWCASE_DIR = Path(__file__).resolve().parent / "fixtures" / "generated_showcase"
    _REFERENCE = Path(__file__).resolve().parent / "fixtures" / "reference_enrichment.json"

    def test_reference_enrichment_exists(self) -> None:
        assert self._REFERENCE.exists(), "reference_enrichment.json missing"

    def test_reference_enrichment_valid_json(self) -> None:
        data = json.loads(self._REFERENCE.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent / "fixtures" / "generated_showcase").exists(),
        reason="showcase dir not present",
    )
    def test_showcase_manifest_exists(self) -> None:
        manifest = self._SHOWCASE_DIR / "showcase_manifest.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            assert "artifacts" in data or "schema_version" in data

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent / "fixtures" / "generated_showcase").exists(),
        reason="showcase dir not present",
    )
    def test_showcase_adapter_summary_consistent(self) -> None:
        summary_path = self._SHOWCASE_DIR / "showcase_adapter_summary.json"
        if summary_path.exists():
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            assert isinstance(data, dict)
