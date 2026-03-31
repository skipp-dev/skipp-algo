"""Tests for smc_core.benchmark — standardized benchmark artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from smc_core.benchmark import (
    BenchmarkResult,
    EventFamilyKPI,
    build_benchmark,
    compute_event_family_kpi,
    export_benchmark_artifacts,
)
from smc_core.schema_version import SCHEMA_VERSION


# --- EventFamilyKPI ---


class TestEventFamilyKPI:
    def test_empty_events(self) -> None:
        kpi = compute_event_family_kpi([], "SWEEP")
        assert kpi.n_events == 0
        assert kpi.hit_rate == 0.0

    def test_basic_kpis(self) -> None:
        events = [
            {"hit": True, "time_to_mitigation": 5, "invalidated": False, "mae": 0.02, "mfe": 0.05},
            {"hit": False, "time_to_mitigation": 10, "invalidated": True, "mae": 0.03, "mfe": 0.01},
        ]
        kpi = compute_event_family_kpi(events, "OB")
        assert kpi.n_events == 2
        assert kpi.hit_rate == 0.5
        assert kpi.invalidation_rate == 0.5
        assert kpi.time_to_mitigation_mean == 7.5
        assert kpi.family == "OB"

    def test_all_hits(self) -> None:
        events = [{"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0.01, "mfe": 0.04}]
        kpi = compute_event_family_kpi(events, "BOS")
        assert kpi.hit_rate == 1.0
        assert kpi.invalidation_rate == 0.0


# --- build_benchmark ---


class TestBuildBenchmark:
    def test_basic_benchmark(self) -> None:
        events = {
            "SWEEP": [
                {"hit": True, "time_to_mitigation": 5, "invalidated": False, "mae": 0.02, "mfe": 0.05},
            ],
            "OB": [],
        }
        result = build_benchmark("AAPL", "15m", events_by_family=events)
        assert result.symbol == "AAPL"
        assert result.timeframe == "15m"
        assert len(result.kpis) == 2

    def test_with_stratification(self) -> None:
        events = {"SWEEP": [{"hit": True, "time_to_mitigation": 5, "invalidated": False, "mae": 0, "mfe": 0}]}
        strat = {"session:NY_AM": {"SWEEP": [{"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0, "mfe": 0}]}}
        result = build_benchmark("AAPL", "15m", events_by_family=events, stratified_events=strat)
        assert "session:NY_AM" in result.stratified
        assert len(result.stratified["session:NY_AM"]) == 1


# --- export artifacts ---


class TestExportBenchmarkArtifacts:
    def test_writes_artifacts(self, tmp_path: Path) -> None:
        events = {"SWEEP": [{"hit": True, "time_to_mitigation": 5, "invalidated": False, "mae": 0, "mfe": 0}]}
        result = build_benchmark("AAPL", "15m", events_by_family=events)
        manifest = export_benchmark_artifacts(result, tmp_path)

        assert (tmp_path / "manifest.json").exists()
        assert (tmp_path / "benchmark_AAPL_15m.json").exists()
        assert manifest.schema_version == SCHEMA_VERSION
        assert len(manifest.artifacts) == 1

    def test_manifest_machine_readable(self, tmp_path: Path) -> None:
        events = {"SWEEP": []}
        result = build_benchmark("TEST", "5m", events_by_family=events)
        export_benchmark_artifacts(result, tmp_path)

        data = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert "schema_version" in data
        assert "artifacts" in data
        assert isinstance(data["artifacts"], list)

    def test_kpi_artifact_content(self, tmp_path: Path) -> None:
        events = {
            "OB": [
                {"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0.01, "mfe": 0.04},
                {"hit": False, "time_to_mitigation": 8, "invalidated": True, "mae": 0.05, "mfe": 0.01},
            ]
        }
        result = build_benchmark("SPY", "1H", events_by_family=events)
        export_benchmark_artifacts(result, tmp_path)

        data = json.loads((tmp_path / "benchmark_SPY_1H.json").read_text(encoding="utf-8"))
        assert data["symbol"] == "SPY"
        assert data["timeframe"] == "1H"
        assert len(data["kpis"]) == 1
        assert data["kpis"][0]["hit_rate"] == 0.5
