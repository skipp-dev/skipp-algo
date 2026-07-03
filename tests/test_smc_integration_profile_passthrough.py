from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.export_smc_structure_artifact import build_structure_artifact_payload
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook

ROOT = Path(__file__).resolve().parents[1]


def _sample_symbols(workbook: Path, limit: int = 1) -> list[str]:
    daily = pd.read_excel(workbook, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    return symbols[:limit]


def test_single_export_profile_passthrough_and_default(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    payload_default = build_structure_artifact_payload(workbook=workbook, generated_at=1709253600.0)
    assert payload_default["source"]["structure_profile"] == "hybrid_default"
    assert payload_default["entries"][0]["diagnostics"]["structure_profile_used"] == "hybrid_default"

    payload_conservative = build_structure_artifact_payload(
        workbook=workbook,
        generated_at=1709253600.0,
        structure_profile="conservative",
    )
    assert payload_conservative["source"]["structure_profile"] == "conservative"
    assert payload_conservative["entries"][0]["diagnostics"]["structure_profile_used"] == "conservative"


def test_batch_export_profile_passthrough_and_default(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbol = _sample_symbols(workbook, 1)
    output_dir = tmp_path / "reports" / "_tmp_structure_profile_passthrough"
    output_dir.mkdir(parents=True, exist_ok=True)

    # NOTE: timeframe="1D" because the production workbook only ships the
    # `daily_bars` sheet. Intraday timeframes are rejected by the workbook
    # fallback gate (see smc_integration/structure_batch.py).
    default_manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbol,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )
    assert default_manifest["artifacts"][0]["structure_profile_used"] == "hybrid_default"

    explicit_manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbol,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="session_liquidity",
    )
    assert explicit_manifest["artifacts"][0]["structure_profile_used"] == "session_liquidity"


def test_unknown_profile_fails_fast(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    with pytest.raises(ValueError, match="unknown structure profile"):
        build_structure_artifact_payload(
            workbook=workbook,
            generated_at=1709253600.0,
            structure_profile="not_a_profile",
        )

    with pytest.raises(ValueError, match="unknown structure profile"):
        write_structure_artifacts_from_workbook(
            workbook=workbook,
            timeframe="1D",
            symbols=_sample_symbols(workbook, 1),
            output_dir=tmp_path / "reports" / "_tmp_structure_profile_unknown",
            generated_at=1709254000.0,
            structure_profile="not_a_profile",
        )
