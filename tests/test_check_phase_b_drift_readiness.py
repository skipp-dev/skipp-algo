"""Tests for ``scripts/check_phase_b_drift_readiness.py``.

Deep-Review 2026-04-27 follow-up: verify the CI gate that blocks
Phase-B promotion when the live drift artifact still uses
``slippage_ks_reference_type == "synthetic_normal"`` (or is missing
the field entirely).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_phase_b_drift_readiness as mod


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_backtest_samples_passes(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "drift.json",
        {"variant": "v1", "slippage_ks_reference_type": "backtest_samples"},
    )
    assert mod.main([str(p)]) == mod.EXIT_OK


def test_synthetic_normal_blocks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    p = _write(
        tmp_path,
        "drift.json",
        {"variant": "v1", "slippage_ks_reference_type": "synthetic_normal"},
    )
    assert mod.main([str(p)]) == mod.EXIT_NOT_READY
    err = capsys.readouterr().err
    assert "synthetic_normal" in err


def test_unavailable_blocks(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "drift.json",
        {"variant": "v1", "slippage_ks_reference_type": "unavailable"},
    )
    assert mod.main([str(p)]) == mod.EXIT_NOT_READY


def test_missing_field_blocks_legacy_artifact(tmp_path: Path) -> None:
    """Legacy artifacts predating the field must NOT silently pass."""
    p = _write(tmp_path, "drift.json", {"variant": "v1"})
    assert mod.main([str(p)]) == mod.EXIT_NOT_READY


def test_unknown_reference_type_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Typos / new categories must fail closed (Copilot review #331)."""
    p = _write(
        tmp_path,
        "drift.json",
        {"variant": "v1", "slippage_ks_reference_type": "backtest_sample"},  # typo
    )
    assert mod.main([str(p)]) == mod.EXIT_NOT_READY
    err = capsys.readouterr().err
    assert "not whitelisted" in err


def test_nested_variants_list(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "drift.json",
        {
            "variants": [
                {"variant": "a", "slippage_ks_reference_type": "backtest_samples"},
                {"variant": "b", "slippage_ks_reference_type": "synthetic_normal"},
            ]
        },
    )
    assert mod.main([str(p)]) == mod.EXIT_NOT_READY


def test_per_variant_mapping(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        "drift.json",
        {
            "per_variant": {
                "a": {"slippage_ks_reference_type": "backtest_samples"},
                "b": {"slippage_ks_reference_type": "backtest_samples"},
            }
        },
    )
    assert mod.main([str(p)]) == mod.EXIT_OK


def test_no_files_returns_usage_error(tmp_path: Path) -> None:
    assert mod.main([str(tmp_path / "nope-*.json")]) == mod.EXIT_USAGE


def test_glob_aggregates_across_files(tmp_path: Path) -> None:
    _write(tmp_path, "ok.json", {"variant": "v1", "slippage_ks_reference_type": "backtest_samples"})
    _write(tmp_path, "bad.json", {"variant": "v2", "slippage_ks_reference_type": "synthetic_normal"})
    assert mod.main([str(tmp_path / "*.json")]) == mod.EXIT_NOT_READY
