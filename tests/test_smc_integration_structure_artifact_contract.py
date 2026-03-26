from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema
import pandas as pd

from smc_integration.structure_batch import write_structure_artifacts_from_workbook

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "databento_volatility_production_20260307_114724.xlsx"


def _sample_symbol() -> str:
    daily = pd.read_excel(WORKBOOK, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    return symbols[0]


def _schema(path: str) -> dict:
    return cast(dict, json.loads((ROOT / path).read_text(encoding="utf-8")))


def test_structure_artifact_contract_is_schema_valid_and_consistent() -> None:
    symbol = _sample_symbol()
    output_dir = ROOT / "reports" / "_tmp_structure_contract"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=[symbol],
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="hybrid_default",
    )

    path = ROOT / manifest["artifacts"][0]["artifact_path"]
    payload = json.loads(path.read_text(encoding="utf-8"))

    schema = _schema("spec/smc_structure_artifact.schema.json")
    jsonschema.validate(instance=payload, schema=schema)

    assert set(payload["structure"].keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert "liquidity_lines" not in payload["structure"]
    assert "session_ranges" not in payload["structure"]
    assert "session_pivots" not in payload["structure"]
    assert "ipda_range" not in payload["structure"]
    assert "htf_fvg_bias" not in payload["structure"]
    assert "broken_fractal_signals" not in payload["structure"]

    assert set(payload["auxiliary"].keys()) == {
        "liquidity_lines",
        "session_ranges",
        "session_pivots",
        "ipda_range",
        "htf_fvg_bias",
        "broken_fractal_signals",
    }

    diagnostics = payload["diagnostics"]
    assert diagnostics["structure_profile_used"] == "hybrid_default"
    assert diagnostics["event_logic_version"] == "v2"

    counts = diagnostics["counts"]
    assert counts["bos"] == len(payload["structure"]["bos"])
    assert counts["orderblocks"] == len(payload["structure"]["orderblocks"])
    assert counts["fvg"] == len(payload["structure"]["fvg"])
    assert counts["liquidity_sweeps"] == len(payload["structure"]["liquidity_sweeps"])
    assert counts["liquidity_lines"] == len(payload["auxiliary"].get("liquidity_lines", []))
    assert counts["session_ranges"] == len(payload["auxiliary"].get("session_ranges", []))
    assert counts["session_pivots"] == len(payload["auxiliary"].get("session_pivots", []))
    assert counts["broken_fractal_signals"] == len(payload["auxiliary"].get("broken_fractal_signals", []))
