from __future__ import annotations

import json

from smc_integration.provider_matrix import (
    build_provider_summary,
    discover_provider_matrix,
    provider_matrix_to_dict,
)


def test_discover_provider_matrix_returns_real_registered_sources_in_order() -> None:
    entries = discover_provider_matrix()
    names = [entry.name for entry in entries]

    assert names == sorted(names)
    assert "databento_watchlist_csv" in names
    assert "structure_artifact_json" in names
    assert "tradingview_watchlist_json" in names
    assert "fmp_watchlist_json" in names
    assert "benzinga_watchlist_json" in names
    assert "ibkr_watchlist_preview_json" not in names


def test_each_matrix_entry_has_required_sections() -> None:
    entries = discover_provider_matrix()
    assert entries

    for entry in entries:
        assert entry.name
        assert entry.source_module
        assert entry.path_hint
        assert entry.source_format in {"csv", "json", "other"}
        assert entry.potential is not None
        assert entry.current is not None
        assert isinstance(entry.known_gaps, list)


def test_current_mapping_honesty_for_technical_news_and_structure() -> None:
    by_name = {entry.name: entry for entry in discover_provider_matrix()}

    structure_artifact = by_name["structure_artifact_json"]
    assert "manifest_{timeframe}.json" in structure_artifact.path_hint
    assert structure_artifact.current.currently_maps_structure is True
    assert structure_artifact.current.snapshot_structure_mode in {"full", "partial"}
    assert any(field.startswith("bos.") for field in structure_artifact.current.mapped_structure_fields)
    assert structure_artifact.current.mapped_structure_categories["bos"] is True
    assert structure_artifact.current.mapped_structure_categories["choch"] is True
    assert isinstance(structure_artifact.current.structure_profile_supported, bool)
    assert isinstance(structure_artifact.current.diagnostics_available, bool)
    assert isinstance(structure_artifact.current.auxiliary_available, bool)
    assert set(structure_artifact.current.mapped_auxiliary_categories.keys()) == {
        "liquidity_lines",
        "session_ranges",
        "session_pivots",
        "ipda_range",
        "htf_fvg_bias",
        "broken_fractal_signals",
    }
    assert isinstance(structure_artifact.current.mapped_structure_categories["orderblocks"], bool)
    assert isinstance(structure_artifact.current.mapped_structure_categories["fvg"], bool)
    assert isinstance(structure_artifact.current.mapped_structure_categories["liquidity_sweeps"], bool)

    assert by_name["tradingview_watchlist_json"].current.currently_maps_technical is True
    assert by_name["tradingview_watchlist_json"].current.currently_maps_news is False
    assert by_name["tradingview_watchlist_json"].current.snapshot_structure_mode == "none"

    assert by_name["fmp_watchlist_json"].current.currently_maps_technical is True
    assert by_name["fmp_watchlist_json"].current.currently_maps_news is False
    assert by_name["fmp_watchlist_json"].current.snapshot_structure_mode == "none"

    assert by_name["benzinga_watchlist_json"].current.currently_maps_technical is False
    assert by_name["benzinga_watchlist_json"].current.currently_maps_news is True
    assert by_name["benzinga_watchlist_json"].current.snapshot_structure_mode == "none"

    # Databento remains a partial-capability candidate, but explicit mapped structure fields are empty.
    databento = by_name["databento_watchlist_csv"]
    assert databento.current.currently_maps_structure is False
    assert databento.current.snapshot_structure_mode in {"partial", "none"}


def test_provider_summary_counts_are_correct() -> None:
    summary = build_provider_summary()
    counts = summary["counts"]

    entries = discover_provider_matrix()
    assert counts["total"] == len(entries)
    assert counts["structure_full"] + counts["structure_partial"] + counts["structure_none"] == len(entries)
    assert counts["meta_full"] + counts["meta_partial"] + counts["meta_none"] == len(entries)


def test_provider_summary_is_conservative() -> None:
    summary = build_provider_summary()

    assert summary["best_current_structure_provider"] == "structure_artifact_json"
    assert summary["best_current_news_candidate"] == "benzinga_watchlist_json"
    assert summary["best_current_technical_candidate"] in {"fmp_watchlist_json", "tradingview_watchlist_json"}
    assert summary["best_current_microstructure_candidate"] in {"databento_watchlist_csv", None}


def test_structure_provider_remains_partial_until_all_categories_exist() -> None:
    by_name = {entry.name: entry for entry in discover_provider_matrix()}
    structure_artifact = by_name["structure_artifact_json"]
    categories = structure_artifact.current.mapped_structure_categories

    if all(categories.values()):
        assert structure_artifact.current.snapshot_structure_mode == "full"
    else:
        assert structure_artifact.current.snapshot_structure_mode in {"partial", "none"}


def test_provider_matrix_to_dict_is_json_serializable_and_stable() -> None:
    one = provider_matrix_to_dict(discover_provider_matrix())
    two = provider_matrix_to_dict(discover_provider_matrix())

    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
