from __future__ import annotations

import json
from pathlib import Path

from scripts.export_smc_snapshot_watchlist_bundles import main


def test_watchlist_export_script_writes_manifest_and_bundles(tmp_path: Path) -> None:
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
            "AAPL,MSFT",
        ]
    )
    assert rc == 0
    manifest_path = output_dir / "manifest_15m.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["counts"]["symbols_requested"] == 2
