from __future__ import annotations

import json
import csv
from pathlib import Path

from scripts.export_smc_snapshot_watchlist_bundles import main


def _watchlist_symbols(limit: int = 2) -> list[str]:
    csv_path = Path(__file__).resolve().parents[1] / "reports" / "databento_watchlist_top5_pre1530.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        symbols = []
        for row in reader:
            value = str(row.get("symbol", "")).strip().upper()
            if value:
                symbols.append(value)
            if len(symbols) >= limit:
                break
    if len(symbols) < limit:
        raise AssertionError("watchlist CSV must include at least two symbols")
    return symbols


def test_watchlist_export_script_writes_manifest_and_bundles(tmp_path: Path) -> None:
    symbols = _watchlist_symbols(limit=2)
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
            "--symbols",
            ",".join(symbols),
        ]
    )
    assert rc == 0
    manifest_path = output_dir / "manifest_15m.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["counts"]["symbols_requested"] == 2
    assert "structure_manifest" in payload
    assert payload["structure_manifest"]["counts"]["symbols_requested"] == 2
