from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pandas as pd

from smc_integration import structure_batch
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
        timeframe="1D",
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
    assert "rejection_blocks" not in payload["structure"]

    assert set(payload["auxiliary"].keys()) == {
        "liquidity_lines",
        "session_ranges",
        "session_pivots",
        "ipda_range",
        "htf_fvg_bias",
        "broken_fractal_signals",
        "rejection_blocks",
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


def test_explicit_workbook_does_not_use_inferred_canonical_export_bundle(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "reports" / "smc_structure_artifacts"
    inferred_bundle_root = tmp_path / "artifacts" / "smc_microstructure_exports"
    inferred_bundle_root.mkdir(parents=True, exist_ok=True)
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        structure_batch,
        "resolve_structure_artifact_inputs",
        lambda **kwargs: {
            "workbook_path": WORKBOOK,
            "export_bundle_root": inferred_bundle_root,
            "structure_artifacts_dir": output_dir,
            "single_structure_artifact_path": None,
            "resolution_mode": "explicit",
            "errors": [],
            "warnings": [],
            "resolution_detail": {
                "workbook": "explicit",
                "export_bundle_root": "canonical",
            },
        },
    )

    def fake_build_single_symbol_structure_artifact(
        *,
        workbook: Path | None,
        export_bundle_root: Path | None,
        symbol: str,
        timeframe: str,
        generated_at: float,
        structure_profile: str = "hybrid_default",
    ) -> dict[str, Any]:
        captured["workbook"] = workbook
        captured["export_bundle_root"] = export_bundle_root
        return {
            "schema_version": "3.0.0",
            "generated_at": generated_at,
            "symbol": symbol,
            "timeframe": timeframe,
            "producer": {},
            "source": {},
            "coverage_mode": "none",
            "coverage": {
                "mode": "none",
                "has_bos": False,
                "has_orderblocks": False,
                "has_fvg": False,
                "has_liquidity_sweeps": False,
            },
            "event_evidence": {
                "last_event": "none",
                "trend_state": 0,
                "reference_close": 0.0,
            },
            "structure": {
                "bos": [],
                "orderblocks": [],
                "fvg": [],
                "liquidity_sweeps": [],
            },
            "auxiliary": {
                "liquidity_lines": [],
                "session_ranges": [],
                "session_pivots": [],
                "ipda_range": {},
                "htf_fvg_bias": {},
                "broken_fractal_signals": [],
            },
            "diagnostics": {
                "structure_profile_used": structure_profile,
                "event_logic_version": "v2",
                "counts": {
                    "bos": 0,
                    "orderblocks": 0,
                    "fvg": 0,
                    "liquidity_sweeps": 0,
                    "liquidity_lines": 0,
                    "session_ranges": 0,
                    "session_pivots": 0,
                    "broken_fractal_signals": 0,
                },
                "warnings": [],
            },
        }

    monkeypatch.setattr(
        structure_batch,
        "build_single_symbol_structure_artifact",
        fake_build_single_symbol_structure_artifact,
    )

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=["AAPL"],
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["counts"]["artifacts_written"] == 1
    assert captured["workbook"] == WORKBOOK
    assert captured["export_bundle_root"] is None


def test_explicit_workbook_does_not_use_inferred_canonical_workbook(
    monkeypatch,
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "reports" / "smc_structure_artifacts"
    canonical_workbook = tmp_path / "artifacts" / "smc_microstructure_exports" / "databento_volatility_production_workbook.xlsx"
    canonical_workbook.parent.mkdir(parents=True, exist_ok=True)
    canonical_workbook.write_text("placeholder", encoding="utf-8")
    captured: dict[str, Any] = {}

    monkeypatch.setattr(
        structure_batch,
        "resolve_structure_artifact_inputs",
        lambda **kwargs: {
            "workbook_path": canonical_workbook,
            "export_bundle_root": None,
            "structure_artifacts_dir": output_dir,
            "single_structure_artifact_path": None,
            "resolution_mode": "explicit",
            "errors": [],
            "warnings": [],
            "resolution_detail": {
                "workbook": "canonical",
                "export_bundle_root": "missing",
            },
        },
    )

    def fake_build_single_symbol_structure_artifact(
        *,
        workbook: Path | None,
        export_bundle_root: Path | None,
        symbol: str,
        timeframe: str,
        generated_at: float,
        structure_profile: str = "hybrid_default",
    ) -> dict[str, Any]:
        captured["workbook"] = workbook
        captured["export_bundle_root"] = export_bundle_root
        return {
            "schema_version": "3.0.0",
            "generated_at": generated_at,
            "symbol": symbol,
            "timeframe": timeframe,
            "producer": {},
            "source": {},
            "coverage_mode": "none",
            "coverage": {
                "mode": "none",
                "has_bos": False,
                "has_orderblocks": False,
                "has_fvg": False,
                "has_liquidity_sweeps": False,
            },
            "event_evidence": {
                "last_event": "none",
                "trend_state": 0,
                "reference_close": 0.0,
            },
            "structure": {
                "bos": [],
                "orderblocks": [],
                "fvg": [],
                "liquidity_sweeps": [],
            },
            "auxiliary": {
                "liquidity_lines": [],
                "session_ranges": [],
                "session_pivots": [],
                "ipda_range": {},
                "htf_fvg_bias": {},
                "broken_fractal_signals": [],
            },
            "diagnostics": {
                "structure_profile_used": structure_profile,
                "event_logic_version": "v2",
                "counts": {
                    "bos": 0,
                    "orderblocks": 0,
                    "fvg": 0,
                    "liquidity_sweeps": 0,
                    "liquidity_lines": 0,
                    "session_ranges": 0,
                    "session_pivots": 0,
                    "broken_fractal_signals": 0,
                },
                "warnings": [],
            },
        }

    monkeypatch.setattr(
        structure_batch,
        "build_single_symbol_structure_artifact",
        fake_build_single_symbol_structure_artifact,
    )

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=["AAPL"],
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["counts"]["artifacts_written"] == 1
    assert captured["workbook"] == WORKBOOK
    assert captured["export_bundle_root"] is None
