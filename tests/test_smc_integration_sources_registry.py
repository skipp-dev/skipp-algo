from __future__ import annotations

from smc_integration.repo_sources import (
    discover_repo_source_paths,
    discover_repo_sources,
    load_raw_meta_input,
    load_raw_structure_input,
)


def test_discover_repo_sources_includes_watchlist_csv_source() -> None:
    sources = discover_repo_sources()
    names = [item.name for item in sources]
    assert "databento_watchlist_csv" in names


def test_discover_repo_sources_names_are_unique() -> None:
    sources = discover_repo_sources()
    names = [item.name for item in sources]
    assert len(names) == len(set(names))


def test_source_auto_selection_is_deterministic() -> None:
    one = discover_repo_source_paths()
    two = discover_repo_source_paths()
    assert one["selected_source"]["name"] == two["selected_source"]["name"]



def test_explicit_source_selection_works_for_structure_and_meta() -> None:
    structure = load_raw_structure_input("IBG", "15m", source="databento_watchlist_csv")
    meta = load_raw_meta_input("IBG", "15m", source="databento_watchlist_csv")

    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert meta["symbol"] == "IBG"



def test_unknown_source_raises_clear_error() -> None:
    try:
        _ = load_raw_meta_input("IBG", "15m", source="does_not_exist")
    except ValueError as exc:
        assert "unknown source" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown source")



def test_source_capabilities_are_set_and_traceable() -> None:
    sources = discover_repo_sources()
    by_name = {item.name: item for item in sources}

    watchlist = by_name["databento_watchlist_csv"]
    assert watchlist.capabilities.has_meta is True
    assert watchlist.capabilities.structure_mode in {"full", "partial", "none"}
    assert isinstance(watchlist.notes, list)
