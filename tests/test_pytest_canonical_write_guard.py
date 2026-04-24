"""Regression tests for the canonical-write pytest guard.

The guard exists because production write-paths in
``smc_integration/batch.py``, ``smc_integration/structure_batch.py``
(via PR #33) and ``smc_core/benchmark.py`` will silently overwrite the
real repo's artifact tree if a test forgets to redirect ``output_dir``.
The poisoned manifests then leak ``pytest-of-<user>`` provenance into
downstream measurement-benchmark runs and trip the rolling-bench
fail-loud guard.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from smc_core._pytest_canonical_write_guard import (
    REPO_ROOT,
    guard_against_canonical_repo_write_under_pytest,
)


def test_guard_no_op_outside_pytest(tmp_path: Path) -> None:
    canonical = REPO_ROOT / "reports" / "smc_snapshot_bundles"
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        guard_against_canonical_repo_write_under_pytest(
            canonical,
            canonical_relative_paths=("reports/smc_snapshot_bundles",),
            caller="noop",
        )


def test_guard_blocks_exact_canonical_path(tmp_path: Path) -> None:
    canonical = REPO_ROOT / "reports" / "smc_snapshot_bundles"
    with pytest.raises(RuntimeError, match="canonical repo path"):
        guard_against_canonical_repo_write_under_pytest(
            canonical,
            canonical_relative_paths=("reports/smc_snapshot_bundles",),
            caller="caller_x",
        )


def test_guard_blocks_subdirectory(tmp_path: Path) -> None:
    canonical_sub = REPO_ROOT / "artifacts" / "ci" / "measurement_benchmark" / "AAPL" / "5m"
    with pytest.raises(RuntimeError, match="caller_y"):
        guard_against_canonical_repo_write_under_pytest(
            canonical_sub,
            canonical_relative_paths=("artifacts/ci/measurement_benchmark",),
            caller="caller_y",
        )


def test_guard_allows_sibling_with_shared_prefix(tmp_path: Path) -> None:
    sibling = REPO_ROOT / "artifacts" / "ci" / "measurement_benchmark_combined_2026-04-23"
    guard_against_canonical_repo_write_under_pytest(
        sibling,
        canonical_relative_paths=("artifacts/ci/measurement_benchmark",),
        caller="caller_z",
    )


def test_guard_allows_tmp_path(tmp_path: Path) -> None:
    guard_against_canonical_repo_write_under_pytest(
        tmp_path / "smc_snapshot_bundles",
        canonical_relative_paths=("reports/smc_snapshot_bundles",),
        caller="caller_tmp",
    )


def test_write_snapshot_bundles_for_symbols_blocks_canonical_dir() -> None:
    """smc_integration.batch must refuse the canonical default under pytest."""
    from smc_integration import batch

    canonical = REPO_ROOT / "reports" / "smc_snapshot_bundles"
    with pytest.raises(RuntimeError, match="write_snapshot_bundles_for_symbols"):
        batch.write_snapshot_bundles_for_symbols(
            ["AAPL"], "5m", output_dir=canonical
        )


def test_export_benchmark_artifacts_blocks_canonical_dir(tmp_path: Path) -> None:
    """smc_core.benchmark must refuse a canonical-tree write under pytest."""
    from smc_core import benchmark as bench

    canonical = REPO_ROOT / "artifacts" / "ci" / "measurement_benchmark" / "AAPL" / "5m"
    fake_result = mock.Mock(spec=bench.BenchmarkResult)
    fake_result.symbol = "AAPL"
    fake_result.timeframe = "5m"
    fake_result.schema_version = "test"
    fake_result.generated_at = 0.0
    fake_result.kpis = []
    fake_result.stratified = {}
    with pytest.raises(RuntimeError, match="export_benchmark_artifacts"):
        bench.export_benchmark_artifacts(fake_result, canonical)


def test_export_benchmark_artifacts_allows_sibling_dir(tmp_path: Path) -> None:
    """The sibling evidence dir (e.g. measurement_benchmark_combined_*) is allowed."""
    from dataclasses import dataclass

    from smc_core import benchmark as bench

    sibling = tmp_path / "measurement_benchmark_combined_2026-04-23" / "AAPL" / "5m"

    @dataclass
    class _R:
        symbol: str = "AAPL"
        timeframe: str = "5m"
        schema_version: str = "test"
        generated_at: float = 0.0
        kpis: list = None  # type: ignore[assignment]
        stratified: dict = None  # type: ignore[assignment]

        def __post_init__(self) -> None:
            self.kpis = []
            self.stratified = {}

    manifest = bench.export_benchmark_artifacts(_R(), sibling)  # type: ignore[arg-type]
    assert (sibling / "manifest.json").exists()
    assert manifest.artifacts == ["benchmark_AAPL_5m.json"]


# Silence unused import warnings — pd reserved for richer follow-up tests.
_ = pd
