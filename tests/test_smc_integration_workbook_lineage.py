from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.databento_production_workbook import resolve_production_workbook_path
from smc_integration.repo_sources import discover_repo_sources
from smc_integration.structure_batch import write_structure_artifacts_from_workbook


def _write_minimal_production_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    daily_bars = pd.DataFrame(
        [
            {"trade_date": "2026-03-05", "symbol": "AAPL", "open": 178.0, "high": 181.0, "low": 177.5, "close": 180.0, "volume": 1000},
            {"trade_date": "2026-03-06", "symbol": "AAPL", "open": 180.0, "high": 183.0, "low": 179.0, "close": 182.5, "volume": 1200},
            {"trade_date": "2026-03-05", "symbol": "MSFT", "open": 400.0, "high": 402.0, "low": 398.0, "close": 401.0, "volume": 900},
            {"trade_date": "2026-03-06", "symbol": "MSFT", "open": 401.0, "high": 404.0, "low": 399.5, "close": 403.5, "volume": 1100},
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        daily_bars.to_excel(writer, sheet_name="daily_bars", index=False)



def test_structure_batch_accepts_canonical_workbook_lineage(tmp_path: Path) -> None:
    canonical_workbook = tmp_path / "artifacts" / "smc_microstructure_exports" / "databento_volatility_production_workbook.xlsx"
    _write_minimal_production_workbook(canonical_workbook)

    resolved = resolve_production_workbook_path(workbook=canonical_workbook, repo_root=tmp_path)
    assert resolved == canonical_workbook

    output_dir = tmp_path / "reports" / "smc_structure_artifacts"
    manifest = write_structure_artifacts_from_workbook(
        workbook=canonical_workbook,
        timeframe="1D",
        output_dir=output_dir,
    )

    assert manifest["counts"]["artifacts_written"] >= 1
    assert (output_dir / "manifest_1D.json").exists()



def test_repo_sources_do_not_enable_ibkr_or_l2_dom_as_data_providers() -> None:
    names = [source.name for source in discover_repo_sources()]
    assert all("ibkr" not in name.lower() for name in names)

    notes = "\n".join(note for source in discover_repo_sources() for note in source.notes)
    assert "l2" not in notes.lower()
    assert "dom" not in notes.lower()
