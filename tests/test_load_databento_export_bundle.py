from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.load_databento_export_bundle import load_export_bundle


def _write_bundle(export_dir: Path, basename: str, frames: dict[str, pd.DataFrame]) -> Path:
    manifest_path = export_dir / f"{basename}_manifest.json"
    manifest_path.write_text(json.dumps({"basename": basename}), encoding="utf-8")
    for name, frame in frames.items():
        frame.to_parquet(export_dir / f"{basename}__{name}.parquet", index=False)
    return manifest_path


def test_load_export_bundle_prefers_newest_valid_manifest_by_mtime(tmp_path: Path) -> None:
    required = ("daily_symbol_features_full_universe", "premarket_features_full_universe")

    older = _write_bundle(
        tmp_path,
        "databento_volatility_production_20260310_090000",
        {
            "daily_symbol_features_full_universe": pd.DataFrame({"symbol": ["AAA"]}),
            "premarket_features_full_universe": pd.DataFrame({"symbol": ["AAA"]}),
        },
    )
    newer_invalid = _write_bundle(
        tmp_path,
        "databento_volatility_production_20260310_091000",
        {
            "daily_symbol_features_full_universe": pd.DataFrame({"symbol": ["BBB"]}),
        },
    )

    older.touch()
    newer_invalid.touch()

    payload = load_export_bundle(
        tmp_path,
        required_frames=required,
        manifest_prefix="databento_volatility_production_",
    )

    assert payload["manifest_path"].name == older.name
    assert set(payload["frames"].keys()) >= set(required)


def test_load_export_bundle_rejects_explicit_manifest_missing_required_frames(tmp_path: Path) -> None:
    manifest_path = _write_bundle(
        tmp_path,
        "databento_volatility_production_20260310_092000",
        {
            "daily_symbol_features_full_universe": pd.DataFrame({"symbol": ["AAA"]}),
        },
    )

    try:
        load_export_bundle(
            manifest_path,
            required_frames=("daily_symbol_features_full_universe", "premarket_features_full_universe"),
        )
    except ValueError as exc:
        assert "missing required bundle frames" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing required frame(s)")


def test_load_export_bundle_manifest_prefix_excludes_fast_manifests(tmp_path: Path) -> None:
    _write_bundle(
        tmp_path,
        "databento_preopen_fast_20260310_093000",
        {
            "daily_symbol_features_full_universe": pd.DataFrame({"symbol": ["FAST"]}),
            "premarket_features_full_universe": pd.DataFrame({"symbol": ["FAST"]}),
        },
    )
    prod_manifest = _write_bundle(
        tmp_path,
        "databento_volatility_production_20260310_093100",
        {
            "daily_symbol_features_full_universe": pd.DataFrame({"symbol": ["PROD"]}),
            "premarket_features_full_universe": pd.DataFrame({"symbol": ["PROD"]}),
        },
    )

    payload = load_export_bundle(
        tmp_path,
        required_frames=("daily_symbol_features_full_universe", "premarket_features_full_universe"),
        manifest_prefix="databento_volatility_production_",
    )

    assert payload["manifest_path"].name == prod_manifest.name
    assert payload["frames"]["daily_symbol_features_full_universe"].iloc[0]["symbol"] == "PROD"
