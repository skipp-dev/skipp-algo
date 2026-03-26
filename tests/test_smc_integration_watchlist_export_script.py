from __future__ import annotations

import json
from pathlib import Path

from scripts.export_smc_snapshot_watchlist_bundles import main
from tests.helpers.smc_test_artifacts import make_minimal_watchlist_csv, make_minimal_workbook


def test_watchlist_export_script_writes_manifest_and_bundles(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    watchlist = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL", "MSFT"])
    output_dir = tmp_path / "smc"
    rc = main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            str(output_dir),
            "--generated-at",
            "1709254000.0",
            "--workbook-path",
            str(workbook),
            "--symbols-source",
            str(watchlist),
            "--structure-artifacts-dir",
            str(tmp_path / "reports" / "smc_structure_artifacts"),
        ]
    )
    assert rc == 0
    manifest_path = output_dir / "manifest_15m.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["counts"]["symbols_requested"] == 2
    assert "coverage_summary" in payload
    assert set(payload["coverage_summary"].keys()) == {
        "symbols_with_bos",
        "symbols_with_orderblocks",
        "symbols_with_fvg",
        "symbols_with_liquidity_sweeps",
    }
    assert "structure_manifest" in payload
    assert payload["structure_manifest"]["counts"]["symbols_requested"] == 2
