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
    csv_path = Path(__file__).resolve().parents[1] / "reports" / "databento_watchlist_top5_pre1530.csv"
    symbol = _first_symbol_from_watchlist(csv_path)

    raw_structure = load_raw_structure_input(symbol, "15m", source="databento_watchlist_csv")
    structure = build_structure_from_raw(raw_structure)

    assert set(raw_structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert isinstance(structure.bos, list)
    assert isinstance(structure.orderblocks, list)
    assert isinstance(structure.fvg, list)
    assert isinstance(structure.liquidity_sweeps, list)



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


# ── pure helper coverage ─────────────────────────────────────────

from smc_integration.repo_sources import (
    _can_supply_domain,
    _resolve_provider,
    _select_best_source_for_domain,
    _source_priority_key,
    _SOURCE_PROVIDERS,
    select_best_structure_source,
    select_best_volume_source,
    select_best_technical_source,
    select_best_news_source,
    select_best_source,
    discover_composite_source_plan,
)


class TestSourcePriorityKey:
    def test_returns_tuple(self) -> None:
        desc = discover_repo_sources()[0]
        key = _source_priority_key(desc)
        assert isinstance(key, tuple)
        assert len(key) == 4

    def test_structure_source_ranks_higher(self) -> None:
        sources = discover_repo_sources()
        with_structure = [s for s in sources if s.capabilities.has_structure]
        without_structure = [s for s in sources if not s.capabilities.has_structure]
        if with_structure and without_structure:
            assert _source_priority_key(with_structure[0]) > _source_priority_key(without_structure[0])


class TestCanSupplyDomain:
    def test_structure_domain(self) -> None:
        provider = _SOURCE_PROVIDERS["structure_artifact_json"]
        assert _can_supply_domain(provider, "structure") is True

    def test_volume_domain(self) -> None:
        provider = _SOURCE_PROVIDERS["databento_watchlist_csv"]
        assert _can_supply_domain(provider, "volume") is True

    def test_technical_domain_fmp(self) -> None:
        provider = _SOURCE_PROVIDERS["fmp_watchlist_json"]
        assert _can_supply_domain(provider, "technical") is True

    def test_news_domain_benzinga(self) -> None:
        provider = _SOURCE_PROVIDERS["benzinga_watchlist_json"]
        assert _can_supply_domain(provider, "news") is True

    def test_unknown_domain_returns_false(self) -> None:
        provider = _SOURCE_PROVIDERS["fmp_watchlist_json"]
        assert _can_supply_domain(provider, "cosmic") is False


class TestSelectBestSourceForDomain:
    def test_unknown_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown domain"):
            _select_best_source_for_domain("nonexistent_domain")

    def test_structure_returns_descriptor(self) -> None:
        desc = _select_best_source_for_domain("structure")
        assert desc.name == "structure_artifact_json"

    def test_volume_returns_descriptor(self) -> None:
        desc = _select_best_source_for_domain("volume")
        assert desc.capabilities.has_meta is True

    def test_technical_returns_descriptor(self) -> None:
        desc = _select_best_source_for_domain("technical")
        assert desc.name in {"fmp_watchlist_json", "tradingview_watchlist_json"}

    def test_news_returns_descriptor(self) -> None:
        desc = _select_best_source_for_domain("news")
        assert desc.name in {"live_news_snapshot_json", "benzinga_watchlist_json"}


class TestSelectBestAliases:
    def test_select_best_source_alias(self) -> None:
        assert select_best_source().name == select_best_structure_source().name

    def test_select_best_technical(self) -> None:
        desc = select_best_technical_source()
        assert desc.name in {"fmp_watchlist_json", "tradingview_watchlist_json"}

    def test_select_best_news(self) -> None:
        desc = select_best_news_source()
        assert desc.name in {"live_news_snapshot_json", "benzinga_watchlist_json"}


class TestResolveProvider:
    def test_auto_structure(self) -> None:
        provider = _resolve_provider("auto", domain="structure")
        assert provider.descriptor.capabilities.has_structure is True

    def test_auto_meta(self) -> None:
        provider = _resolve_provider("auto", domain="meta")
        assert provider.descriptor.capabilities.has_meta is True

    def test_auto_unknown_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown resolve domain"):
            _resolve_provider("auto", domain="cosmic")

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown source"):
            _resolve_provider("nonexistent_provider", domain="structure")

    def test_explicit_source(self) -> None:
        provider = _resolve_provider("fmp_watchlist_json", domain="structure")
        assert provider.descriptor.name == "fmp_watchlist_json"


class TestDiscoverCompositeSourcePlan:
    def test_explicit_source(self) -> None:
        plan = discover_composite_source_plan(source="fmp_watchlist_json")
        assert plan["structure"] == "fmp_watchlist_json"
        assert plan["volume"] == "fmp_watchlist_json"
        assert plan["technical"] == "fmp_watchlist_json"
        assert plan["news"] == "fmp_watchlist_json"

    def test_unknown_source_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown source"):
            discover_composite_source_plan(source="does_not_exist")

    def test_explicit_structure_artifact_resolves_mode(self) -> None:
        plan = discover_composite_source_plan(source="structure_artifact_json", symbol="AAPL", timeframe="15m")
        assert "structure_resolution_mode" in plan
