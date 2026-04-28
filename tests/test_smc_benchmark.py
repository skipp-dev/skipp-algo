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


# --- D2: stratified FVG report (Plan §2.1) ---


class TestStratifiedFvgReport:
    def _events(self, *triples: tuple[str, str, str, bool]) -> list[dict[str, object]]:
        return [
            {"session": s, "htf_bias": b, "vol_regime": v, "hit": h}
            for (s, b, v, h) in triples
        ]

    def test_empty_input_returns_safe_zero_report(self) -> None:
        from smc_core.benchmark import stratified_fvg_report

        report = stratified_fvg_report([])
        assert report["total_events"] == 0
        assert report["total_buckets"] == 0
        assert report["actionable_bucket_count"] == 0
        assert report["overall_hit_rate"] is None
        assert report["buckets"] == []
        assert report["actionable_buckets"] == []

    def test_bucket_below_floor_is_marked_insufficient(self) -> None:
        from smc_core.benchmark import stratified_fvg_report

        # 4 events in one bucket — under the default floor of 5
        events = self._events(
            ("RTH", "BULL", "NORMAL", True),
            ("RTH", "BULL", "NORMAL", True),
            ("RTH", "BULL", "NORMAL", False),
            ("RTH", "BULL", "NORMAL", True),
        )
        report = stratified_fvg_report(events)
        assert report["total_events"] == 4
        assert len(report["buckets"]) == 1
        bucket = report["buckets"][0]
        assert bucket["insufficient"] is True
        assert bucket["hit_rate"] is None, "must not lie about HR for tiny samples"
        assert bucket["n_events"] == 4
        assert bucket["hits"] == 3
        # Insufficient buckets never count as actionable.
        assert report["actionable_bucket_count"] == 0

    def test_actionable_bucket_requires_floor_and_70pct_hit_rate(self) -> None:
        from smc_core.benchmark import stratified_fvg_report

        # Bucket A: 8 events, 6 hits → 75% HR → actionable.
        # Bucket B: 6 events, 3 hits → 50% HR → not actionable.
        events = self._events(
            *((("RTH", "BULL", "NORMAL", True),) * 6),
            *((("RTH", "BULL", "NORMAL", False),) * 2),
            *((("ETH", "FLAT", "HIGH", True),) * 3),
            *((("ETH", "FLAT", "HIGH", False),) * 3),
        )
        report = stratified_fvg_report(events)
        assert report["total_events"] == 14
        assert report["overall_hit_rate"] == round(9 / 14, 4)
        actionable = report["actionable_buckets"]
        assert len(actionable) == 1
        assert actionable[0]["session"] == "RTH"
        assert actionable[0]["hit_rate"] == 0.75
        # The non-actionable bucket is still in the full bucket list.
        assert any(b["session"] == "ETH" for b in report["buckets"])

    def test_unknown_dimensions_default_to_unknown_bucket(self) -> None:
        from smc_core.benchmark import stratified_fvg_report

        # Missing keys must not crash; they fall back to UNKNOWN so the
        # operator still sees the event count.
        report = stratified_fvg_report([{"hit": True}, {"hit": False, "session": ""}])
        assert report["total_events"] == 2
        assert len(report["buckets"]) == 1
        assert report["buckets"][0]["session"] == "UNKNOWN"
        assert report["buckets"][0]["htf_bias"] == "UNKNOWN"
        assert report["buckets"][0]["vol_regime"] == "UNKNOWN"

    def test_min_events_override_is_respected(self) -> None:
        from smc_core.benchmark import stratified_fvg_report

        events = self._events(
            ("RTH", "BULL", "NORMAL", True),
            ("RTH", "BULL", "NORMAL", True),
        )
        report = stratified_fvg_report(events, min_events=2)
        assert report["buckets"][0]["insufficient"] is False
        assert report["buckets"][0]["hit_rate"] == 1.0

    def test_output_is_deterministic_and_json_serialisable(self) -> None:
        import json

        from smc_core.benchmark import stratified_fvg_report

        events = self._events(
            ("ETH", "BULL", "HIGH", True),
            ("RTH", "BEAR", "NORMAL", False),
            ("RTH", "BULL", "NORMAL", True),
        )
        # Two runs with the same input must produce byte-identical JSON.
        a = json.dumps(stratified_fvg_report(events), sort_keys=True)
        b = json.dumps(stratified_fvg_report(events), sort_keys=True)
        assert a == b
