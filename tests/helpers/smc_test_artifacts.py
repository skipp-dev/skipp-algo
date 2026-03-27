from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from smc_core.schema_version import SCHEMA_VERSION


def make_minimal_workbook(tmp_path: Path, *, symbols: list[str] | None = None) -> Path:
    values = symbols or ["AAPL", "MSFT"]
    rows: list[dict] = []
    for idx, symbol in enumerate(values):
        rows.append(
            {
                "trade_date": f"2026-03-0{idx + 5}",
                "symbol": symbol,
                "open": 100.0 + idx,
                "high": 101.0 + idx,
                "low": 99.0 + idx,
                "close": 100.5 + idx,
                "volume": 1000 + idx,
            }
        )
        rows.append(
            {
                "trade_date": f"2026-03-0{idx + 6}",
                "symbol": symbol,
                "open": 100.5 + idx,
                "high": 102.0 + idx,
                "low": 99.5 + idx,
                "close": 101.2 + idx,
                "volume": 1200 + idx,
            }
        )

    workbook = tmp_path / "artifacts" / "smc_microstructure_exports" / "databento_volatility_production_workbook.xlsx"
    workbook.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="daily_bars", index=False)
    return workbook


def make_minimal_structure_artifact(tmp_path: Path, *, symbol: str = "AAPL", timeframe: str = "15m") -> Path:
    out_dir = tmp_path / "reports" / "smc_structure_artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": 1709253600.0,
        "symbol": symbol,
        "timeframe": timeframe,
        "coverage_mode": "partial",
        "coverage": {
            "mode": "partial",
            "has_bos": True,
            "has_orderblocks": False,
            "has_fvg": False,
            "has_liquidity_sweeps": False,
        },
        "structure": {
            "bos": [{"id": f"bos:{symbol}:{timeframe}:1:BOS:UP:101.0", "time": 1.0, "price": 101.0, "kind": "BOS", "dir": "UP"}],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    }
    artifact_path = out_dir / f"{symbol}_{timeframe}.structure.json"
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": 1709253600.0,
        "timeframe": timeframe,
        "counts": {"symbols_requested": 1, "artifacts_written": 1, "errors": 0},
        "artifacts": [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "artifact_path": str(artifact_path),
                "coverage_mode": "partial",
                "has_bos": True,
                "has_orderblocks": False,
                "has_fvg": False,
                "has_liquidity_sweeps": False,
            }
        ],
        "errors": [],
    }
    (out_dir / f"manifest_{timeframe}.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return artifact_path


def make_minimal_watchlist_csv(tmp_path: Path, *, symbols: list[str] | None = None) -> Path:
    values = symbols or ["AAPL", "MSFT"]
    path = tmp_path / "reports" / "watchlist.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ["symbol"] + values
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path
