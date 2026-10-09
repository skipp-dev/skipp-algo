"""Audit guard: every priority workflow-invoked entry-point script must
configure root logging at startup so its ``logger.info(...)`` progress
messages reach the GHA log stream.

This pins F-V5-A1-2: a file may satisfy the contract by either calling
the shared ``init_cli_logging()`` helper from ``scripts._logging_init``
(preferred) or by configuring the root logger directly with
``logging.basicConfig`` / ``logging.config.dictConfig``.

Audit marker: F-V5-A1-2 / F-CI-O1 (2026-05-01).
"""
from __future__ import annotations

import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Priority entry points: scripts directly invoked from .github/workflows/*
# either as `python -m scripts.X` or `python scripts/X.py`. Curated
# 2026-05-01 (V5 audit). New entry points added to a workflow MUST be
# added here.
_PRIORITY_ENTRY_POINTS = [
    # NEED-migrated in this PR (20)
    "scripts/run_drift_watchdog.py",
    "scripts/g23_ab_watchdog.py",
    "scripts/compute_live_drift.py",
    "scripts/emit_public_calibration_report.py",
    "scripts/build_backtest_reference.py",
    "scripts/build_families_telemetry.py",
    "scripts/backfill_live_outcomes.py",
    "scripts/check_phase_b_drift_readiness.py",
    "scripts/emit_fvg_context_pine.py",
    "scripts/fvg_quality_quartile_gate.py",
    "scripts/generate_smc_micro_base_from_databento.py",
    "scripts/fvg_quality_recalibration.py",
    "scripts/run_smc_pre_release_artifact_refresh.py",
    "scripts/run_smc_release_gates.py",
    "scripts/collect_smc_gate_evidence.py",
    "scripts/f2_run_promotion_gate.py",
    "scripts/f2_weekly_digest.py",
    "scripts/check_library_release_manifest_drift.py",
    "scripts/check_pine_legacy_drift.py",
    "scripts/e2e_smoke_ci.py",
    # Already had basicConfig before this PR (kept under guard so they
    # don't silently regress to no-config in the future) (3)
    "open_prep/feature_importance_report.py",
    "open_prep/outcome_backfill.py",
    "open_prep/run_open_prep.py",
    # Note: scripts/databento_production_export.py is pinned separately by
    # tests/test_databento_production_export_logging.py (shipped via the
    # F-V5-A1 / #2008 PR). Not duplicated here to avoid a cross-PR
    # dependency in the audit ledger.
]


@pytest.mark.parametrize("rel_path", _PRIORITY_ENTRY_POINTS)
def test_entry_point_configures_root_logging(rel_path: str) -> None:
    src = (_REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert (
        "init_cli_logging" in src
        or "basicConfig" in src
        or "dictConfig" in src
    ), (
        f"{rel_path}: missing root logger configuration. Either call "
        "`init_cli_logging()` from `scripts._logging_init` (preferred) "
        "or configure the root logger directly. Without this, "
        "logger.info(...) progress is dropped silently in CI. "
        "(F-V5-A1-2 / F-CI-O1)"
    )
