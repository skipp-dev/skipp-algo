from __future__ import annotations

import json
from pathlib import Path

from scripts.export_smc_snapshot_watchlist_bundles import main as watchlist_main
from tests.helpers.smc_test_artifacts import make_minimal_watchlist_csv


def test_watchlist_export_no_hidden_workspace_dependency(tmp_path: Path, monkeypatch) -> None:
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL"])

    import smc_integration.artifact_resolution as resolution

    monkeypatch.setattr(resolution, "REPO_ROOT", tmp_path / "isolated_repo")

    out_dir = tmp_path / "out"
    rc = watchlist_main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            str(out_dir),
            "--symbols-source",
            str(symbols_source),
            "--structure-artifacts-dir",
            str(tmp_path / "isolated_artifacts"),
            "--allow-missing-structure-inputs",
            "--generated-at",
            "1709254000.0",
        ]
    )

    assert rc == 0
    manifest = json.loads((out_dir / "manifest_15m.json").read_text(encoding="utf-8"))
    assert any(item.get("code") == "MISSING_STRUCTURE_INPUTS" for item in manifest["structure_manifest"].get("errors", []))
    assert manifest["resolution_mode"] in {"missing", "canonical", "explicit"}


def test_failures_are_structured_and_reproducible(tmp_path: Path, monkeypatch) -> None:
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL"])

    import smc_integration.artifact_resolution as resolution

    monkeypatch.setattr(resolution, "REPO_ROOT", tmp_path / "isolated_repo")

    out_dir = tmp_path / "out"
    rc = watchlist_main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            str(out_dir),
            "--symbols-source",
            str(symbols_source),
            "--structure-artifacts-dir",
            str(tmp_path / "isolated_artifacts"),
            "--fail-on-missing-structure-inputs",
            "--generated-at",
            "1709254000.0",
        ]
    )

    assert rc == 2
