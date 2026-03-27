from __future__ import annotations

import json
from pathlib import Path

from smc_core.schema_version import SCHEMA_VERSION
from scripts import export_smc_snapshot_watchlist_bundles as module
from tests.helpers.smc_test_artifacts import (
    make_minimal_structure_artifact,
    make_minimal_watchlist_csv,
    make_minimal_workbook,
)


def _fake_snapshot_batch(symbols, timeframe, *, source, output_dir, generated_at):
    del source, generated_at
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "timeframe": timeframe,
        "counts": {"symbols_requested": len(symbols), "symbols_built": len(symbols), "errors": 0},
        "coverage_summary": {
            "symbols_with_bos": 0,
            "symbols_with_orderblocks": 0,
            "symbols_with_fvg": 0,
            "symbols_with_liquidity_sweeps": 0,
        },
        "bundles": [],
        "errors": [],
        "manifest_path": str(out / f"manifest_{timeframe}.json"),
    }
    Path(manifest["manifest_path"]).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def test_watchlist_export_works_with_temp_workbook_fixture(tmp_path: Path, monkeypatch) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL", "MSFT"])
    monkeypatch.setattr(module, "write_snapshot_bundles_for_symbols", _fake_snapshot_batch)

    out_dir = tmp_path / "out"
    rc = module.main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            str(out_dir),
            "--workbook-path",
            str(workbook),
            "--symbols-source",
            str(symbols_source),
            "--structure-artifacts-dir",
            str(tmp_path / "reports" / "smc_structure_artifacts"),
            "--generated-at",
            "1709254000.0",
        ]
    )
    assert rc == 0
    payload = json.loads((out_dir / "manifest_15m.json").read_text(encoding="utf-8"))
    assert payload["resolution_mode"] in {"explicit", "canonical"}


def test_watchlist_export_works_with_temp_structure_artifact_fixture(tmp_path: Path, monkeypatch) -> None:
    make_minimal_structure_artifact(tmp_path, symbol="AAPL", timeframe="15m")
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL"])
    monkeypatch.setattr(module, "write_snapshot_bundles_for_symbols", _fake_snapshot_batch)

    out_dir = tmp_path / "out"
    rc = module.main(
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
            str(tmp_path / "reports" / "smc_structure_artifacts"),
            "--allow-missing-structure-inputs",
            "--generated-at",
            "1709254000.0",
        ]
    )
    assert rc == 0
    payload = json.loads((out_dir / "manifest_15m.json").read_text(encoding="utf-8"))
    assert payload["structure_source_mode"] in {"preexisting_artifacts", "explicit", "canonical", "missing"}


def test_missing_workbook_produces_structured_manifest_error_not_raw_file_error(tmp_path: Path, monkeypatch) -> None:
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL"])
    monkeypatch.setattr(module, "write_snapshot_bundles_for_symbols", _fake_snapshot_batch)

    import smc_integration.artifact_resolution as resolution

    monkeypatch.setattr(resolution, "REPO_ROOT", tmp_path / "isolated_repo")

    out_dir = tmp_path / "out"
    rc = module.main(
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
            str(tmp_path / "reports" / "missing_artifacts"),
            "--allow-missing-structure-inputs",
            "--generated-at",
            "1709254000.0",
        ]
    )
    assert rc == 0
    payload = json.loads((out_dir / "manifest_15m.json").read_text(encoding="utf-8"))
    assert any(item.get("code") == "MISSING_STRUCTURE_INPUTS" for item in payload["structure_manifest"].get("errors", []))


def test_explicit_cli_path_overrides_resolver_default(tmp_path: Path, monkeypatch) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL"])
    monkeypatch.setattr(module, "write_snapshot_bundles_for_symbols", _fake_snapshot_batch)

    out_dir = tmp_path / "out"
    rc = module.main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            str(out_dir),
            "--workbook-path",
            str(workbook),
            "--symbols-source",
            str(symbols_source),
            "--structure-artifacts-dir",
            str(tmp_path / "reports" / "smc_structure_artifacts"),
            "--generated-at",
            "1709254000.0",
        ]
    )
    assert rc == 0
    payload = json.loads((out_dir / "manifest_15m.json").read_text(encoding="utf-8"))
    assert payload["resolved_inputs"]["workbook_path"] == str(workbook)


def test_resolution_metadata_appears_in_output_manifest(tmp_path: Path, monkeypatch) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols_source = make_minimal_watchlist_csv(tmp_path, symbols=["AAPL"])
    monkeypatch.setattr(module, "write_snapshot_bundles_for_symbols", _fake_snapshot_batch)

    out_dir = tmp_path / "out"
    rc = module.main(
        [
            "--timeframe",
            "15m",
            "--source",
            "auto",
            "--output-dir",
            str(out_dir),
            "--workbook-path",
            str(workbook),
            "--symbols-source",
            str(symbols_source),
            "--generated-at",
            "1709254000.0",
        ]
    )
    assert rc == 0
    payload = json.loads((out_dir / "manifest_15m.json").read_text(encoding="utf-8"))
    assert "resolved_inputs" in payload
    assert "resolution_mode" in payload
    assert "warnings" in payload
