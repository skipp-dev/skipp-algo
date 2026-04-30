"""Tests for the FVG label audit script (D1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.fvg_label_audit import (
    _derive_findings,
    _derive_recommendations,
    _fvg_context_breakdown,
    _fvg_per_pair_breakdown,
    _fvg_vs_family_comparison,
    _load_benchmark_kpis,
    _load_scored_events,
    render_audit_report,
    run_fvg_audit,
    to_json,
)

# ── Fixtures ────────────────────────────────────────────────────


def _make_benchmark_json(kpis: list[dict], stratified: dict | None = None) -> str:
    return json.dumps({
        "kpis": kpis,
        "stratified": stratified or {},
    })


def _make_scoring_json(family_metrics: dict) -> str:
    return json.dumps({
        "family_metrics": family_metrics,
    })


def _make_kpi(family: str, *, n_events: int = 10, hit_rate: float = 0.5,
              ttm: float = 3.0, inv_rate: float = 0.3, mae: float = 0.02, mfe: float = 0.04) -> dict:
    return {
        "family": family,
        "n_events": n_events,
        "hit_rate": hit_rate,
        "time_to_mitigation_mean": ttm,
        "invalidation_rate": inv_rate,
        "mae": mae,
        "mfe": mfe,
    }


@pytest.fixture
def benchmark_tree(tmp_path: Path) -> Path:
    """Create a minimal benchmark directory tree with 2 symbol×tf pairs."""
    for symbol, tf in [("AAA", "15m"), ("BBB", "1H")]:
        pair_dir = tmp_path / symbol / tf
        pair_dir.mkdir(parents=True)

        # Benchmark file with KPIs
        kpis = [
            _make_kpi("BOS", n_events=5, hit_rate=0.90, ttm=2.0, inv_rate=0.2),
            _make_kpi("OB", n_events=4, hit_rate=0.85, ttm=1.5, inv_rate=0.25),
            _make_kpi("FVG", n_events=8, hit_rate=0.50, ttm=5.0, inv_rate=0.65),
            _make_kpi("SWEEP", n_events=6, hit_rate=0.80, ttm=3.0, inv_rate=0.4),
        ]
        stratified = {
            "session:RTH": [
                _make_kpi("FVG", n_events=5, hit_rate=0.70, ttm=4.0, inv_rate=0.5),
            ],
            "session:ETH": [
                _make_kpi("FVG", n_events=3, hit_rate=0.33, ttm=7.0, inv_rate=0.8),
            ],
        }
        (pair_dir / f"benchmark_{symbol}_{tf}.json").write_text(
            _make_benchmark_json(kpis, stratified), encoding="utf-8"
        )

        # Scoring file with family metrics
        fm = {
            "BOS": {"n_events": 5, "hit_rate": 0.90, "brier_score": 0.15},
            "OB": {"n_events": 4, "hit_rate": 0.85, "brier_score": 0.18},
            "FVG": {"n_events": 8, "hit_rate": 0.50, "brier_score": 0.30},
            "SWEEP": {"n_events": 6, "hit_rate": 0.80, "brier_score": 0.20},
        }
        (pair_dir / f"scoring_{symbol}_{tf}.json").write_text(
            _make_scoring_json(fm), encoding="utf-8"
        )

    return tmp_path


# ── Unit tests ──────────────────────────────────────────────────


class TestLoadBenchmarkKpis:
    def test_loads_aggregate_kpis(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        aggregate = [k for k in kpis if not k.get("bucket")]
        families = {k["family"] for k in aggregate}
        assert families == {"BOS", "OB", "FVG", "SWEEP"}

    def test_loads_stratified_kpis(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        stratified = [k for k in kpis if k.get("bucket")]
        assert len(stratified) >= 4  # 2 buckets × 2 pairs

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        pair_dir = tmp_path / "BAD" / "5m"
        pair_dir.mkdir(parents=True)
        (pair_dir / "benchmark_BAD_5m.json").write_text("{invalid json", encoding="utf-8")
        kpis = _load_benchmark_kpis(tmp_path)
        assert kpis == []


class TestLoadScoredEvents:
    def test_loads_all_families(self, benchmark_tree: Path) -> None:
        events = _load_scored_events(benchmark_tree)
        families = {e["family"] for e in events}
        assert "FVG" in families
        assert len(events) == 8  # 4 families × 2 pairs


class TestFamilyComparison:
    def test_fvg_lowest_hit_rate(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        fvg_hr = comparison["FVG"]["hit_rate"]
        for family in ("BOS", "OB", "SWEEP"):
            assert comparison[family]["hit_rate"] > fvg_hr

    def test_event_counts_aggregate(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        assert comparison["FVG"]["total_events"] == 16  # 8 × 2 pairs

    def test_invalidation_rate(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        assert comparison["FVG"]["avg_invalidation_rate"] == 0.65


class TestPerPairBreakdown:
    def test_two_pairs(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        per_pair = _fvg_per_pair_breakdown(kpis)
        assert len(per_pair) == 2
        assert "AAA/15m" in per_pair
        assert "BBB/1H" in per_pair

    def test_hit_rate_per_pair(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        per_pair = _fvg_per_pair_breakdown(kpis)
        assert per_pair["AAA/15m"]["hit_rate"] == 0.5


class TestContextBreakdown:
    def test_session_buckets(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        context = _fvg_context_breakdown(kpis)
        assert "session:RTH" in context
        assert "session:ETH" in context

    def test_rth_better_than_eth(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        context = _fvg_context_breakdown(kpis)
        assert context["session:RTH"]["hit_rate"] > context["session:ETH"]["hit_rate"]


class TestFindings:
    def test_generates_findings(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        per_pair = _fvg_per_pair_breakdown(kpis)
        context = _fvg_context_breakdown(kpis)
        findings = _derive_findings(comparison, per_pair, context)
        assert len(findings) >= 2
        assert any("hit rate" in f.lower() for f in findings)

    def test_invalidation_finding(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        per_pair = _fvg_per_pair_breakdown(kpis)
        context = _fvg_context_breakdown(kpis)
        findings = _derive_findings(comparison, per_pair, context)
        assert any("invalidation" in f.lower() for f in findings)


class TestRecommendations:
    def test_generates_recommendations(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        per_pair = _fvg_per_pair_breakdown(kpis)
        context = _fvg_context_breakdown(kpis)
        recs = _derive_recommendations(comparison, per_pair, context, [])
        assert len(recs) >= 2

    def test_lookahead_recommendation(self, benchmark_tree: Path) -> None:
        kpis = _load_benchmark_kpis(benchmark_tree)
        comparison = _fvg_vs_family_comparison(kpis)
        per_pair = _fvg_per_pair_breakdown(kpis)
        context = _fvg_context_breakdown(kpis)
        recs = _derive_recommendations(comparison, per_pair, context, [])
        assert any("lookahead" in r.lower() for r in recs)


class TestEndToEnd:
    def test_run_fvg_audit(self, benchmark_tree: Path) -> None:
        audit = run_fvg_audit(benchmark_tree)
        assert audit.total_fvg_events == 16
        assert audit.hit_rate_12 == 0.5
        assert audit.invalidation_rate == 0.65
        assert len(audit.findings) >= 2
        assert len(audit.recommendations) >= 2

    def test_render_report(self, benchmark_tree: Path) -> None:
        audit = run_fvg_audit(benchmark_tree)
        report = render_audit_report(audit)
        assert "FVG Label Audit Report" in report
        assert "Family Comparison" in report
        assert "Per-Pair Breakdown" in report
        assert "Recommendations" in report

    def test_to_json_roundtrip(self, benchmark_tree: Path) -> None:
        audit = run_fvg_audit(benchmark_tree)
        data = to_json(audit)
        assert data["total_fvg_events"] == 16
        assert isinstance(data["findings"], list)
        assert isinstance(data["recommendations"], list)
        # JSON serializable
        json.dumps(data)

    def test_cli(self, benchmark_tree: Path, tmp_path: Path) -> None:
        from scripts.fvg_label_audit import main

        output = tmp_path / "out.json"
        main(["--benchmark-dir", str(benchmark_tree), "--output-path", str(output)])
        assert output.exists()
        assert output.with_suffix(".md").exists()
        data = json.loads(output.read_text())
        assert data["total_fvg_events"] == 16


class TestEmptyBenchmark:
    def test_empty_dir(self, tmp_path: Path) -> None:
        audit = run_fvg_audit(tmp_path)
        assert audit.total_fvg_events == 0
        assert audit.findings == []
