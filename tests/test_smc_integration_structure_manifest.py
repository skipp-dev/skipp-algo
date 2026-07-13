from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from smc_integration.structure_batch import _input_fingerprint, write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook

ROOT = Path(__file__).resolve().parents[1]


def _sample_symbols(workbook: Path, limit: int = 2) -> list[str]:
    daily = pd.read_excel(workbook, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    return symbols[:limit]


def test_structure_manifest_contains_required_keys(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=2)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_keys"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert set(["schema_version", "generated_at", "timeframe", "producer", "counts", "artifacts", "errors"]).issubset(set(manifest.keys()))
    assert "coverage_summary" in manifest
    assert "profile_summary" in manifest
    assert "event_logic_versions" in manifest
    assert "provenance" in manifest


def test_structure_manifest_carries_generator_provenance(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_provenance"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    provenance = manifest["provenance"]
    assert provenance["generator_path"] == "smc_integration/structure_batch.py"
    # In CI/GITHUB_SHA or any git checkout this resolves; None only without git.
    assert provenance["source_commit"] is None or (
        isinstance(provenance["source_commit"], str) and provenance["source_commit"]
    )
    fingerprint = provenance["input_fingerprint"]
    assert provenance["source_modes"] == ["workbook_fallback"]
    assert fingerprint["kind"] == "workbook_sha256"
    assert fingerprint["path"] == workbook.as_posix()
    assert fingerprint["sha256"] == hashlib.sha256(workbook.read_bytes()).hexdigest()
    # The persisted manifest carries the same block.
    persisted = json.loads((output_dir / "manifest_1D.json").read_text(encoding="utf-8"))
    assert persisted["provenance"] == provenance


def test_input_fingerprint_tracks_actual_and_mixed_sources(tmp_path: Path, monkeypatch) -> None:
    workbook = tmp_path / "input.xlsx"
    workbook.write_bytes(b"workbook")
    bundle_root = tmp_path / "bundle"
    bundle_root.mkdir()
    bundle_manifest = bundle_root / "producer_manifest.json"
    bundle_manifest.write_bytes(b"bundle")
    monkeypatch.setattr(
        "smc_integration.structure_batch.resolve_manifest_path",
        lambda _root: bundle_manifest,
    )

    bundle_only = _input_fingerprint(
        workbook, bundle_root, {"canonical_export_bundle"}
    )
    assert bundle_only is not None
    assert bundle_only["kind"] == "export_bundle_manifest_sha256"
    assert bundle_only["sha256"] == hashlib.sha256(b"bundle").hexdigest()

    mixed = _input_fingerprint(
        workbook, bundle_root, {"canonical_export_bundle", "workbook_fallback"}
    )
    assert mixed is not None and mixed["kind"] == "mixed"
    assert {source["kind"] for source in mixed["sources"]} == {
        "export_bundle_manifest_sha256",
        "workbook_sha256",
    }


def test_structure_manifest_counts_and_flags_are_correct(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=2)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_counts"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["counts"]["symbols_requested"] == 2
    assert manifest["counts"]["artifacts_written"] == 2
    assert manifest["counts"]["errors"] == len(manifest["errors"])

    assert [row["symbol"] for row in manifest["artifacts"]] == sorted(symbols)
    for row in manifest["artifacts"]:
        assert row["coverage_mode"] in {"full", "partial", "none"}
        assert row["structure_profile_used"] == "hybrid_default"
        assert row["event_logic_version"] == "v2"
        assert isinstance(row["has_orderblocks"], bool)
        assert isinstance(row["has_fvg"], bool)
        assert isinstance(row["has_liquidity_sweeps"], bool)
        assert isinstance(row["bos_count"], int)
        assert isinstance(row["warnings_count"], int)

    assert set(manifest["coverage_summary"].keys()) == {
        "symbols_with_bos",
        "symbols_with_orderblocks",
        "symbols_with_fvg",
        "symbols_with_liquidity_sweeps",
    }
    assert manifest["profile_summary"] == {"hybrid_default": 2}
    assert manifest["event_logic_versions"] == ["v2"]


def test_structure_manifest_category_flags_match_artifact_payload(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_match"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    row = manifest["artifacts"][0]
    payload = json.loads((tmp_path / row["artifact_path"]).read_text(encoding="utf-8"))
    coverage = payload["coverage"]

    assert row["coverage_mode"] == coverage["mode"]
    assert row["has_bos"] == coverage["has_bos"]
    assert row["has_orderblocks"] == coverage["has_orderblocks"]
    assert row["has_fvg"] == coverage["has_fvg"]
    assert row["has_liquidity_sweeps"] == coverage["has_liquidity_sweeps"]
    assert row["bos_count"] == payload["diagnostics"]["counts"]["bos"]
    assert row["orderblocks_count"] == payload["diagnostics"]["counts"]["orderblocks"]
    assert row["fvg_count"] == payload["diagnostics"]["counts"]["fvg"]
    assert row["liquidity_sweeps_count"] == payload["diagnostics"]["counts"]["liquidity_sweeps"]


def test_structure_manifest_paths_are_deterministic(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_paths"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["artifacts"][0]["artifact_path"].endswith(f"{symbols[0]}_1D.structure.json")
    assert str(manifest["manifest_path"]).endswith("manifest_1D.json")


def test_structure_manifest_is_json_stable(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, limit=1)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_stable"
    output_dir.mkdir(parents=True, exist_ok=True)

    one = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )
    two = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
