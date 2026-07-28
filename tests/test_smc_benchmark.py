"""Tests for smc_core.benchmark — standardized benchmark artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from smc_core.benchmark import (
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
        # Truth-audit E12: time_to_mitigation_mean is the mean over the
        # events that mitigated (hits). Real misses carry ttm=0.0; here the
        # miss's ttm is ignored regardless, so the mean is just the hit's 5.
        events = [
            {"hit": True, "time_to_mitigation": 5, "invalidated": False, "mae": 0.02, "mfe": 0.05},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0.03, "mfe": 0.01},
        ]
        kpi = compute_event_family_kpi(events, "OB")
        assert kpi.n_events == 2
        assert kpi.hit_rate == 0.5
        assert kpi.invalidation_rate == 0.5
        assert kpi.time_to_mitigation_mean == 5.0
        assert kpi.family == "OB"

    def test_time_to_mitigation_mean_is_over_hits_only(self) -> None:
        # E12: two hits (ttm 4 and 8) + one miss => mean 6.0, not scaled by
        # the miss (which would give 12/3 = 4.0 under the old ÷n).
        events = [
            {"hit": True, "time_to_mitigation": 4},
            {"hit": True, "time_to_mitigation": 8},
            {"hit": False, "time_to_mitigation": 0},
        ]
        kpi = compute_event_family_kpi(events, "OB")
        assert kpi.hit_rate == round(2 / 3, 4)
        assert kpi.time_to_mitigation_mean == 6.0

    def test_time_to_mitigation_mean_zero_when_no_hits(self) -> None:
        events = [{"hit": False, "time_to_mitigation": 0}]
        kpi = compute_event_family_kpi(events, "OB")
        assert kpi.time_to_mitigation_mean == 0.0

    def test_all_hits(self) -> None:
        events = [{"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0.01, "mfe": 0.04}]
        kpi = compute_event_family_kpi(events, "BOS")
        assert kpi.hit_rate == 1.0
        assert kpi.invalidation_rate == 0.0

    def test_partial_fill_pct_mean_for_misses(self) -> None:
        """R3: partial_fill_pct_mean should average over misses only."""
        events = [
            {"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0, "mfe": 0, "partial_fill_pct": 1.0},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0, "mfe": 0, "partial_fill_pct": 0.4},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0, "mfe": 0, "partial_fill_pct": 0.6},
        ]
        kpi = compute_event_family_kpi(events, "FVG")
        # Misses have partial_fill_pct 0.4 and 0.6 → mean 0.5
        assert kpi.partial_fill_pct_mean == 0.5

    def test_partial_fill_pct_all_hits(self) -> None:
        """R3: When all events are hits, partial_fill_pct_mean should be 0.0."""
        events = [
            {"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0, "mfe": 0, "partial_fill_pct": 1.0},
        ]
        kpi = compute_event_family_kpi(events, "FVG")
        assert kpi.partial_fill_pct_mean == 0.0

    def test_partial_50_hit_rate_aggregates_strict_label(self) -> None:
        """D1 bridge: features.label_partial_50 should aggregate into a strict HR."""
        events = [
            {"hit": True, "time_to_mitigation": 1, "invalidated": False, "mae": 0, "mfe": 0,
             "features": {"label_partial_50": True}},
            {"hit": True, "time_to_mitigation": 1, "invalidated": False, "mae": 0, "mfe": 0,
             "features": {"label_partial_50": False}},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0, "mfe": 0,
             "features": {"label_partial_50": False}},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0, "mfe": 0,
             "features": {"label_partial_50": True}},
        ]
        kpi = compute_event_family_kpi(events, "FVG")
        assert kpi.partial_50_n_events == 4
        assert kpi.partial_50_hit_rate == 0.5
        # Lenient hit_rate stays 2/4 = 0.5 from the ``hit`` field —
        # strict rate must coexist with it without overwriting.
        assert kpi.hit_rate == 0.5

    def test_partial_50_hit_rate_aggregates_flat_payload_key(self) -> None:
        """D1 bridge: payload from ``_evaluate_zone_event`` carries the
        label as a flat ``label_partial_50`` key (no nested ``features``
        dict). The KPI reader must accept that shape."""
        events = [
            {"hit": True, "time_to_mitigation": 1, "invalidated": False, "mae": 0, "mfe": 0,
             "label_partial_50": True},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0, "mfe": 0,
             "label_partial_50": False},
            {"hit": False, "time_to_mitigation": 0, "invalidated": True, "mae": 0, "mfe": 0,
             "label_partial_50": True},
        ]
        kpi = compute_event_family_kpi(events, "FVG")
        assert kpi.partial_50_n_events == 3
        assert kpi.partial_50_hit_rate == round(2 / 3, 4)

    def test_partial_50_absent_when_label_missing(self) -> None:
        """Backward compat: events without features.label_partial_50 -> None."""
        events = [
            {"hit": True, "time_to_mitigation": 3, "invalidated": False, "mae": 0, "mfe": 0},
            {"hit": False, "time_to_mitigation": 5, "invalidated": True, "mae": 0, "mfe": 0},
        ]
        kpi = compute_event_family_kpi(events, "OB")
        assert kpi.partial_50_n_events == 0
        assert kpi.partial_50_hit_rate is None

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


# D2 stratified-FVG report tests removed 2026-07-28 with the stranded chain
# (see smc_core/benchmark.py tombstone note).
