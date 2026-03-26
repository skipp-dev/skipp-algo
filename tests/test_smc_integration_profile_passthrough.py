from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.export_smc_structure_artifact import build_structure_artifact_payload
from smc_integration.structure_batch import write_structure_artifacts_from_workbook

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "databento_volatility_production_20260307_114724.xlsx"


def _sample_symbols(limit: int = 1) -> list[str]:
    daily = pd.read_excel(WORKBOOK, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    return symbols[:limit]


def test_single_export_profile_passthrough_and_default() -> None:
    payload_default = build_structure_artifact_payload(workbook=WORKBOOK, generated_at=1709253600.0)
    assert payload_default["source"]["structure_profile"] == "hybrid_default"
    assert payload_default["entries"][0]["diagnostics"]["structure_profile_used"] == "hybrid_default"

    payload_conservative = build_structure_artifact_payload(
        workbook=WORKBOOK,
        generated_at=1709253600.0,
        structure_profile="conservative",
    )
    assert payload_conservative["source"]["structure_profile"] == "conservative"
    assert payload_conservative["entries"][0]["diagnostics"]["structure_profile_used"] == "conservative"


def test_batch_export_profile_passthrough_and_default() -> None:
    symbol = _sample_symbols(1)
    output_dir = ROOT / "reports" / "_tmp_structure_profile_passthrough"
    output_dir.mkdir(parents=True, exist_ok=True)

    default_manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbol,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )
    assert default_manifest["artifacts"][0]["structure_profile_used"] == "hybrid_default"

    explicit_manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbol,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="session_liquidity",
    )
    assert explicit_manifest["artifacts"][0]["structure_profile_used"] == "session_liquidity"


def test_unknown_profile_fails_fast() -> None:
    with pytest.raises(ValueError, match="unknown structure profile"):
        build_structure_artifact_payload(
            workbook=WORKBOOK,
            generated_at=1709253600.0,
            structure_profile="not_a_profile",
        )

    with pytest.raises(ValueError, match="unknown structure profile"):
        write_structure_artifacts_from_workbook(
            workbook=WORKBOOK,
            timeframe="15m",
            symbols=_sample_symbols(1),
            output_dir=ROOT / "reports" / "_tmp_structure_profile_unknown",
            generated_at=1709254000.0,
            structure_profile="not_a_profile",
        )
