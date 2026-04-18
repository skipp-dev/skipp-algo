"""Tests for scripts/run_freeze_exit_check.py (WP-16)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.run_freeze_exit_check import (
    BRIER_CEILING,
    ECE_CEILING,
    MIN_BENCHMARK_REPORTS,
    SMOKE_MIN_SCORE,
    CriterionResult,
    FreezeExitVerdict,
    run_freeze_exit_check,
    write_verdict_markdown,
)


def _setup_artifacts(
    tmp_path: Path,
    *,
    benchmark_runs: int = 3,
    brier: float = 0.25,
    ece: float = 0.10,
    smoke_score: int = 8,
    gate_status: str = "ok",
) -> Path:
    """Create a minimal artifacts/ci tree for testing."""
    ci = tmp_path / "ci"

    # Benchmark manifest
    bm = ci / "measurement_benchmark"
    bm.mkdir(parents=True)
    runs = [{"id": i} for i in range(benchmark_runs)]
    (bm / "benchmark_run_manifest.json").write_text(
        json.dumps({"runs": runs}), encoding="utf-8"
    )

    # Benchmark summary CSV
    header = "symbol,timeframe,brier_score,ece\n"
    rows = f"AAPL,15m,{brier},{ece}\nMSFT,15m,{brier},{ece}\n"
    (bm / "benchmark_run_summary.csv").write_text(header + rows, encoding="utf-8")

    # Smoke report
    smoke = ci / "smoke_test"
    smoke.mkdir(parents=True)
    (smoke / "smoke_report.json").write_text(
        json.dumps({"score": smoke_score}), encoding="utf-8"
    )

    # Release gates baseline report
    (ci / "smc_release_gates_baseline_report.json").write_text(
        json.dumps({"status": gate_status}), encoding="utf-8"
    )

    return ci


class TestFreezeExitReady:
    def test_all_criteria_met(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is True
        assert verdict.blocking_reasons == []

    def test_verdict_has_checked_at(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.checked_at != ""


class TestBenchmarkBlocking:
    def test_insufficient_benchmark_runs(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path, benchmark_runs=1)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is False
        assert any("benchmark_reports" in r for r in verdict.blocking_reasons)

    def test_brier_exceeded(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path, brier=0.75)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is False
        assert any("benchmark_metrics" in r for r in verdict.blocking_reasons)

    def test_ece_exceeded(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path, ece=0.45)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is False
        assert any("benchmark_metrics" in r for r in verdict.blocking_reasons)


class TestSmokeBlocking:
    def test_low_smoke_score(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path, smoke_score=5)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is False
        assert any("smoke_test" in r for r in verdict.blocking_reasons)


class TestReleaseGateBlocking:
    def test_failed_gate_status(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path, gate_status="fail")
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is False
        assert any("release_gates" in r for r in verdict.blocking_reasons)


class TestMissingArtifacts:
    def test_empty_dir_blocks(self, tmp_path: Path) -> None:
        ci = tmp_path / "empty"
        ci.mkdir()
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        assert verdict.freeze_exit_ready is False
        assert len(verdict.blocking_reasons) >= 3


class TestMarkdownOutput:
    def test_write_verdict_markdown(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        md_path = tmp_path / "verdict.md"
        write_verdict_markdown(verdict, md_path)
        content = md_path.read_text(encoding="utf-8")
        assert "READY" in content
        assert "benchmark_reports" in content


class TestVerdictSerialization:
    def test_to_dict(self, tmp_path: Path) -> None:
        ci = _setup_artifacts(tmp_path)
        verdict = run_freeze_exit_check(artifacts_dir=ci)
        d = verdict.to_dict()
        assert isinstance(d, dict)
        assert "freeze_exit_ready" in d
        assert "criteria" in d
        json.dumps(d)  # must be JSON-serializable
