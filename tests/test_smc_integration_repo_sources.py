from __future__ import annotations

import csv
import time as _time
from pathlib import Path

import pytest

from smc_adapters import build_meta_from_raw, build_structure_from_raw
from smc_integration.repo_sources import (
    _SOURCE_PROVIDERS,
    _SourceProvider,
    _can_supply_domain,
    _finalize_composite_meta,
    _resolve_provider,
    _select_best_source_for_domain,
    _try_load_meta_domain,
    discover_composite_source_plan,
    discover_repo_source_paths,
    discover_repo_sources,
    load_raw_meta_input,
    load_raw_structure_input,
    select_best_news_source,
    select_best_source,
    select_best_structure_source,
    select_best_technical_source,
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


# ── pure helper coverage ───────────────────────────────────────────────────────────
# _source_priority_key was removed in the 2026-06-10 silent-fallback
# audit: it was production-dead (only this test imported it) and its
# ranking contradicted the authoritative _DOMAIN_SOURCE_ORDER.


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


class TestResolveAutoStructureSourceForSymbolTimeframe:
    def test_returns_source_name(self) -> None:
        from smc_integration.repo_sources import _resolve_auto_structure_source_for_symbol_timeframe

        name = _resolve_auto_structure_source_for_symbol_timeframe("AAPL", "15m")
        assert isinstance(name, str)
        assert name

    def test_nonexistent_symbol_falls_through(self) -> None:
        from smc_integration.repo_sources import _resolve_auto_structure_source_for_symbol_timeframe

        # Even with a bogus symbol, should still find a provider that can supply structure
        name = _resolve_auto_structure_source_for_symbol_timeframe("__ZZZZ_NONEXISTENT__", "15m")
        assert isinstance(name, str)


class TestLoadRawStructureAutoErrors:
    def test_auto_with_missing_symbol_raises(self) -> None:
        with pytest.raises(ValueError):
            load_raw_structure_input("__COMPLETELY_MISSING_XYZ__", "15m", source="auto")


# ---------------------------------------------------------------------------
# Coverage-boost tests — targeted at uncovered lines
# ---------------------------------------------------------------------------


class TestFinalizeCompositeMetaMissingDomains:
    """Cover lines 568-570: domain_meta is None diagnostics."""

    def _volume_meta(self, asof_ts: float | None = None) -> dict:
        ts = asof_ts or _time.time()
        return {
            "symbol": "AAPL",
            "timeframe": "15m",
            "volume": {
                "value": {"regime": "NORMAL", "thin_fraction": 0.1},
                "asof_ts": ts,
                "stale": False,
            },
            "asof_ts": ts,
            "provenance": ["test"],
        }

    def test_missing_technical_and_news_marks_stale(self) -> None:
        now = _time.time()
        result = _finalize_composite_meta(
            symbol="AAPL",
            timeframe="15m",
            reference_time=now,
            structure_source="structure_artifact_json",
            planned_volume_source="databento_watchlist_csv",
            volume_meta=self._volume_meta(now),
            volume_domain_status="present",
            actual_volume_source="databento_watchlist_csv",
            volume_fallback_used=False,
            planned_technical_source="fmp_watchlist_json",
            technical_meta=None,
            technical_domain_status="source_file_not_found",
            actual_technical_source="fmp_watchlist_json",
            technical_fallback_used=False,
            planned_news_source="benzinga_watchlist_json",
            news_meta=None,
            news_domain_status="source_file_not_found",
            actual_news_source="benzinga_watchlist_json",
            news_fallback_used=False,
            relax_missing_optional_domains=False,
        )
        diag = result["meta_domain_diagnostics"]
        assert diag["technical_asof_ts"] is None
        assert diag["technical_stale"] is True
        assert diag["news_asof_ts"] is None
        assert diag["news_stale"] is True

    def test_relax_missing_optional_not_stale(self) -> None:
        """Cover line 570: relax_missing_optional_domains=True for technical/news."""
        now = _time.time()
        result = _finalize_composite_meta(
            symbol="AAPL",
            timeframe="15m",
            reference_time=now,
            structure_source="structure_artifact_json",
            planned_volume_source="databento_watchlist_csv",
            volume_meta=self._volume_meta(now),
            volume_domain_status="present",
            actual_volume_source="databento_watchlist_csv",
            volume_fallback_used=False,
            planned_technical_source="fmp_watchlist_json",
            technical_meta=None,
            technical_domain_status="source_file_not_found",
            actual_technical_source="fmp_watchlist_json",
            technical_fallback_used=False,
            planned_news_source="benzinga_watchlist_json",
            news_meta=None,
            news_domain_status="source_file_not_found",
            actual_news_source="benzinga_watchlist_json",
            news_fallback_used=False,
            relax_missing_optional_domains=True,
        )
        diag = result["meta_domain_diagnostics"]
        assert diag["technical_stale"] is False
        assert diag["news_stale"] is False


class TestFinalizeCompositeMetaInvalidAsofTs:
    """Cover line 577-578: merged asof_ts NaN → invalid value."""

    def test_nan_asof_ts_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid asof_ts"):
            _finalize_composite_meta(
                symbol="AAPL",
                timeframe="15m",
                reference_time=_time.time(),
                structure_source="structure_artifact_json",
                planned_volume_source="databento_watchlist_csv",
                volume_meta={
                    "symbol": "AAPL",
                    "timeframe": "15m",
                    "volume": {
                        "value": {"regime": "NORMAL", "thin_fraction": 0.1},
                        "asof_ts": float("nan"),
                        "stale": False,
                    },
                    "asof_ts": float("nan"),
                    "provenance": ["test"],
                },
                volume_domain_status="present",
                actual_volume_source="databento_watchlist_csv",
                volume_fallback_used=False,
                planned_technical_source="fmp_watchlist_json",
                technical_meta=None,
                technical_domain_status="missing",
                actual_technical_source="fmp_watchlist_json",
                technical_fallback_used=False,
                planned_news_source="benzinga_watchlist_json",
                news_meta=None,
                news_domain_status="missing",
                actual_news_source="benzinga_watchlist_json",
                news_fallback_used=False,
                relax_missing_optional_domains=False,
            )


class TestFinalizeCompositeMetaStaleProvenance:
    """Cover line 585: provenance is not a list → coerce to []."""

    def test_non_list_provenance_coerced(self) -> None:
        very_old = 1.0  # 1970-01-01
        result = _finalize_composite_meta(
            symbol="AAPL",
            timeframe="15m",
            reference_time=_time.time(),
            structure_source="structure_artifact_json",
            planned_volume_source="databento_watchlist_csv",
            volume_meta={
                "symbol": "AAPL",
                "timeframe": "15m",
                "volume": {"value": {"regime": "NORMAL", "thin_fraction": 0.1}, "asof_ts": very_old, "stale": False},
                "asof_ts": very_old,
                "provenance": "not_a_list",
            },
            volume_domain_status="present",
            actual_volume_source="databento_watchlist_csv",
            volume_fallback_used=False,
            planned_technical_source="fmp_watchlist_json",
            technical_meta=None,
            technical_domain_status="missing",
            actual_technical_source="fmp_watchlist_json",
            technical_fallback_used=False,
            planned_news_source="benzinga_watchlist_json",
            news_meta=None,
            news_domain_status="missing",
            actual_news_source="benzinga_watchlist_json",
            news_fallback_used=False,
            relax_missing_optional_domains=True,
        )
        assert isinstance(result["provenance"], list)
        assert "smc_integration:warning:stale_meta_asof_ts" in result["provenance"]


class TestTryLoadMetaDomainEdges:
    """Cover lines 410, 415, 420: non-auto mode raises, domain status hint."""

    def test_non_auto_value_error_raises(self) -> None:
        """Cover line 415: ValueError re-raised in non-auto mode."""
        with pytest.raises(ValueError):
            _try_load_meta_domain(
                "volume",
                "__MISSING__",
                "15m",
                "databento_watchlist_csv",
                auto_mode=False,
            )

    def test_auto_mode_returns_none_on_missing(self) -> None:
        meta, status, _source = _try_load_meta_domain(
            "volume",
            "__MISSING__",
            "15m",
            "databento_watchlist_csv",
            auto_mode=True,
        )
        assert meta is None
        assert status in {
            "source_file_not_found",
            "source_validation_error",
            "domain_key_absent",
            "not_attempted_no_candidates",
        }

    def test_auto_mode_catches_generic_exception(self, monkeypatch) -> None:
        """Verify that generic exceptions are caught in auto_mode and it falls back."""
        primary = "databento_watchlist_csv"
        secondary = "fmp_watchlist_json"

        # Mock primary to raise RuntimeError
        def _raise_generic_err(symbol, timeframe, reference_time=None):
            raise RuntimeError("corrupted json or something")

        orig_primary = _SOURCE_PROVIDERS[primary]
        fake_primary = _SourceProvider(
            descriptor=orig_primary.descriptor,
            load_structure=orig_primary.load_structure,
            load_meta=_raise_generic_err,
        )
        monkeypatch.setitem(_SOURCE_PROVIDERS, primary, fake_primary)

        # Mock secondary to return valid volume metadata
        orig_secondary = _SOURCE_PROVIDERS[secondary]
        def _load_success(symbol, timeframe, reference_time=None):
            return {"volume": {"some_field": 123}}

        fake_secondary = _SourceProvider(
            descriptor=orig_secondary.descriptor,
            load_structure=orig_secondary.load_structure,
            load_meta=_load_success,
        )
        monkeypatch.setitem(_SOURCE_PROVIDERS, secondary, fake_secondary)

        meta, status, source = _try_load_meta_domain(
            "volume",
            "AAPL",
            "15m",
            primary,
            auto_mode=True,
        )
        assert meta == {"volume": {"some_field": 123}}
        assert status == "present"
        assert source == secondary

    def test_non_auto_mode_raises_generic_exception(self, monkeypatch) -> None:
        """Verify that generic exceptions are not caught in non-auto_mode."""
        primary = "databento_watchlist_csv"
        orig = _SOURCE_PROVIDERS[primary]

        def _raise_generic_err(symbol, timeframe, reference_time=None):
            raise RuntimeError("corrupted json or something")

        fake = _SourceProvider(
            descriptor=orig.descriptor,
            load_structure=orig.load_structure,
            load_meta=_raise_generic_err,
        )
        monkeypatch.setitem(_SOURCE_PROVIDERS, primary, fake)

        with pytest.raises(RuntimeError, match="corrupted json or something"):
            _try_load_meta_domain(
                "volume",
                "AAPL",
                "15m",
                primary,
                auto_mode=False,
            )


class TestLoadRawStructureAutoFileNotFoundContinues:
    """Cover lines 349-350: auto structure FileNotFoundError caught and continued."""

    def test_auto_structure_catches_and_continues(self, monkeypatch) -> None:
        import smc_integration.repo_sources as rs
        from smc_integration.repo_sources import _SourceProvider

        def _raise_fnf(symbol, timeframe):
            raise FileNotFoundError("forced")

        for name in list(rs._SOURCE_PROVIDERS):
            orig = rs._SOURCE_PROVIDERS[name]
            fake = _SourceProvider(descriptor=orig.descriptor, load_structure=_raise_fnf, load_meta=orig.load_meta)
            monkeypatch.setitem(rs._SOURCE_PROVIDERS, name, fake)

        with pytest.raises(FileNotFoundError, match="forced"):
            load_raw_structure_input("AAPL", "15m", source="auto")
