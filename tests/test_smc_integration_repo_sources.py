from __future__ import annotations

import csv
from pathlib import Path

import pytest

from smc_adapters import build_meta_from_raw, build_structure_from_raw
from smc_integration.repo_sources import (
    discover_repo_sources,
    discover_repo_source_paths,
    load_raw_meta_input,
    load_raw_structure_input,
)


def _first_symbol_from_watchlist(csv_path: Path) -> str:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader, None)
    if row is None or not row.get("symbol"):
        raise AssertionError("watchlist CSV must contain at least one symbol row for integration tests")
    return str(row["symbol"]).strip().upper()


def test_discover_repo_source_paths_returns_transparent_mapping() -> None:
    info = discover_repo_source_paths()

    assert "selected_source" in info
    assert "sources" in info
    assert info["selected_source"]["name"] == "structure_artifact_json"



def test_load_raw_structure_input_is_ingest_compatible() -> None:
    info = discover_repo_source_paths()
    selected = info["selected_source"]
    symbol = "AAPL"

    raw_structure = load_raw_structure_input(symbol, "15m")
    structure = build_structure_from_raw(raw_structure)

    assert set(raw_structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert isinstance(structure.bos, list)
    assert structure.orderblocks == []
    assert structure.fvg == []
    assert structure.liquidity_sweeps == []



def test_load_raw_meta_input_is_ingest_compatible() -> None:
    csv_path = Path(__file__).resolve().parents[1] / "reports" / "databento_watchlist_top5_pre1530.csv"
    symbol = _first_symbol_from_watchlist(csv_path)

    raw_meta = load_raw_meta_input(symbol, "15m")
    meta = build_meta_from_raw(raw_meta)

    assert meta.symbol == symbol
    assert meta.timeframe == "15m"
    assert meta.volume.value.regime in {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}
    assert isinstance(raw_meta.get("provenance"), list)



def test_missing_symbol_and_missing_source_fail_loudly() -> None:
    with pytest.raises(ValueError, match="not present"):
        load_raw_structure_input("__MISSING__", "15m")

    with pytest.raises(ValueError, match="unknown source"):
        load_raw_meta_input("AAPL", "15m", source="does_not_exist")


def test_discover_repo_sources_returns_descriptors() -> None:
    sources = discover_repo_sources()
    assert sources
    assert all(source.name for source in sources)
