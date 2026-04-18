"""Unit tests for ``smc_integration.sources`` adapters.

Each adapter exposes:
- ``describe_source()`` → ``SourceDescriptor``
- ``load_raw_structure_input(symbol, timeframe)`` → dict with canonical keys
- ``load_raw_meta_input(symbol, timeframe)`` → dict with domain payload

Tests exercise the contract surface using synthetic on-disk fixtures
so no real data files are required.
"""
from __future__ import annotations

import csv
import json
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from smc_integration.sources.base import SourceCapabilities, SourceDescriptor


# ── base.py ──────────────────────────────────────────────────────


class TestSourceCapabilities:
    def test_to_dict_roundtrips(self) -> None:
        cap = SourceCapabilities(
            has_structure=True,
            has_meta=False,
            structure_mode="full",
            meta_mode="none",
        )
        d = cap.to_dict()
        assert d["has_structure"] is True
        assert d["meta_mode"] == "none"

    def test_frozen(self) -> None:
        cap = SourceCapabilities(True, True, "full", "full")
        with pytest.raises(AttributeError):
            cap.has_structure = False  # type: ignore[misc]


class TestSourceDescriptor:
    def test_to_dict_shape(self) -> None:
        desc = SourceDescriptor(
            name="test_source",
            path_hint="reports/test.json",
            capabilities=SourceCapabilities(False, True, "none", "partial"),
            notes=["note1"],
        )
        d = desc.to_dict()
        assert d["name"] == "test_source"
        assert isinstance(d["capabilities"], dict)
        assert d["notes"] == ["note1"]


# ── helpers ──────────────────────────────────────────────────────


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


_BENZINGA_ROW = {
    "symbol": "AAPL",
    "trade_date": "2025-01-15",
    "asof_ts": 1736899200.0,
    "volume_regime": "NORMAL",
    "thin_fraction": 0.1,
    "news": {"strength": 0.7, "bias": "BULLISH", "asof_ts": 1736899200.0},
}

_FMP_ROW = {
    "symbol": "AAPL",
    "trade_date": "2025-01-15",
    "asof_ts": 1736899200.0,
    "volume_regime": "NORMAL",
    "thin_fraction": 0.1,
    "technical": {"strength": 0.6, "bias": "BEARISH", "asof_ts": 1736899200.0},
}

_TV_ROW = {
    "symbol": "AAPL",
    "trade_date": "2025-01-15",
    "asof_ts": 1736899200.0,
    "volume_regime": "LOW_VOLUME",
    "thin_fraction": 0.4,
    "technical": {"strength": 0.5, "bias": "NEUTRAL", "asof_ts": 1736899200.0},
}


# ── benzinga_watchlist_json ──────────────────────────────────────


class TestBenzingaWatchlistJson:
    def test_describe_source(self) -> None:
        from smc_integration.sources.benzinga_watchlist_json import describe_source

        desc = describe_source()
        assert isinstance(desc, SourceDescriptor)
        assert desc.name == "benzinga_watchlist_json"
        assert desc.capabilities.has_structure is False
        assert desc.capabilities.has_meta is True

    def test_load_raw_structure_returns_empty_canonical_keys(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        payload = {"symbols": [_BENZINGA_ROW]}
        source_path = tmp_path / "benzinga_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_structure_input("AAPL", "15m")

        for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
            assert result[key] == []

    def test_load_raw_meta_returns_volume_and_news(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        payload = {"symbols": [_BENZINGA_ROW]}
        source_path = tmp_path / "benzinga_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["symbol"] == "AAPL"
        assert result["timeframe"] == "15m"
        assert result["volume"]["value"]["regime"] == "NORMAL"
        assert result["news"]["value"]["strength"] == 0.7
        assert result["news"]["value"]["bias"] == "BULLISH"
        assert "provenance" in result

    def test_missing_news_fields_drops_news_domain(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        row = {**_BENZINGA_ROW, "news": {"strength": 0.5}}  # missing bias
        payload = {"symbols": [row]}
        source_path = tmp_path / "benzinga_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert "news" not in result
        assert result.get("_meta_domain_statuses", {}).get("news") == "domain_fields_incomplete"

    def test_missing_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        payload = {"symbols": [_BENZINGA_ROW]}
        source_path = tmp_path / "benzinga_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            with pytest.raises(ValueError, match="not present"):
                mod.load_raw_meta_input("MSFT", "15m")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", tmp_path / "nonexistent.json"):
            with pytest.raises(FileNotFoundError):
                mod.load_raw_meta_input("AAPL", "15m")

    def test_symbol_case_insensitive(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        payload = {"symbols": [_BENZINGA_ROW]}
        source_path = tmp_path / "benzinga_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("aapl", "15m")

        assert result["symbol"] == "AAPL"

    def test_trade_date_fallback_for_asof_ts(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        row = {**_BENZINGA_ROW}
        del row["asof_ts"]
        payload = {"symbols": [row]}
        source_path = tmp_path / "benzinga_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert isinstance(result["asof_ts"], float)
        assert result["asof_ts"] > 0


# ── fmp_watchlist_json ───────────────────────────────────────────


class TestFmpWatchlistJson:
    def test_describe_source(self) -> None:
        from smc_integration.sources.fmp_watchlist_json import describe_source

        desc = describe_source()
        assert desc.name == "fmp_watchlist_json"
        assert desc.capabilities.has_meta is True

    def test_load_raw_meta_returns_volume_and_technical(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        payload = {"symbols": [_FMP_ROW]}
        source_path = tmp_path / "fmp_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["symbol"] == "AAPL"
        assert result["volume"]["value"]["regime"] == "NORMAL"
        assert result["technical"]["value"]["strength"] == 0.6
        assert result["technical"]["value"]["bias"] == "BEARISH"

    def test_missing_technical_drops_domain(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        row = {**_FMP_ROW, "technical": {"strength": 0.5}}  # missing bias
        payload = {"symbols": [row]}
        source_path = tmp_path / "fmp_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert "technical" not in result
        assert result.get("_meta_domain_statuses", {}).get("technical") == "domain_fields_incomplete"

    def test_load_raw_structure_returns_empty_lists(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        payload = {"symbols": [_FMP_ROW]}
        source_path = tmp_path / "fmp_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_structure_input("AAPL", "15m")

        for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
            assert result[key] == []

    def test_invalid_regime_defaults_to_normal(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        row = {**_FMP_ROW, "volume_regime": "SUPER_HIGH"}
        payload = {"symbols": [row]}
        source_path = tmp_path / "fmp_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["volume"]["value"]["regime"] == "NORMAL"


# ── tradingview_watchlist_json ───────────────────────────────────


class TestTradingviewWatchlistJson:
    def test_describe_source(self) -> None:
        from smc_integration.sources.tradingview_watchlist_json import describe_source

        desc = describe_source()
        assert desc.name == "tradingview_watchlist_json"
        assert desc.capabilities.has_meta is True
        assert desc.capabilities.structure_mode == "none"

    def test_load_raw_meta_with_technical(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        payload = {"symbols": [_TV_ROW]}
        source_path = tmp_path / "tradingview_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["volume"]["value"]["regime"] == "LOW_VOLUME"
        assert result["technical"]["value"]["bias"] == "NEUTRAL"

    def test_flat_field_fallback(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        row = {
            "symbol": "TSLA",
            "trade_date": "2025-01-15",
            "asof_ts": 1736899200.0,
            "volume_regime": "NORMAL",
            "technical_strength": "0.8",
            "technical_bias": "BULLISH",
        }
        payload = {"symbols": [row]}
        source_path = tmp_path / "tradingview_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("TSLA", "15m")

        assert result["technical"]["value"]["strength"] == 0.8
        assert result["technical"]["value"]["bias"] == "BULLISH"

    def test_payload_key_alternatives(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        payload = {"watchlist": [_TV_ROW]}
        source_path = tmp_path / "tradingview_watchlist_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["symbol"] == "AAPL"


# ── databento_watchlist_csv ──────────────────────────────────────


class TestDabentoWatchlistCsv:
    def test_describe_source(self) -> None:
        from smc_integration.sources.databento_watchlist_csv import describe_source

        desc = describe_source()
        assert desc.name == "databento_watchlist_csv"
        assert desc.capabilities.has_structure is True
        assert desc.capabilities.has_meta is True

    def test_load_raw_meta_rvol_regime(self, tmp_path: Path) -> None:
        from smc_integration.sources import databento_watchlist_csv as mod

        rows = [
            {
                "symbol": "AAPL",
                "trade_date": "2025-01-15",
                "watchlist_rank": "1",
                "day_volume_rvol_20d": "1.5",
            },
            {
                "symbol": "MSFT",
                "trade_date": "2025-01-15",
                "watchlist_rank": "2",
                "day_volume_rvol_20d": "0.8",
            },
        ]
        csv_path = tmp_path / "databento_watchlist_top5_pre1530.csv"
        _write_csv(csv_path, rows)

        with patch.object(mod, "WATCHLIST_CSV", csv_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["symbol"] == "AAPL"
        assert result["volume"]["value"]["regime"] != "UNKNOWN"
        assert isinstance(result["volume"]["value"]["thin_fraction"], float)
        assert any("rvol" in p for p in result["provenance"])

    def test_load_raw_structure_returns_empty_canonical(self, tmp_path: Path) -> None:
        from smc_integration.sources import databento_watchlist_csv as mod

        rows = [
            {"symbol": "AAPL", "trade_date": "2025-01-15", "watchlist_rank": "1"},
        ]
        csv_path = tmp_path / "databento_watchlist_top5_pre1530.csv"
        _write_csv(csv_path, rows)

        with patch.object(mod, "WATCHLIST_CSV", csv_path):
            result = mod.load_raw_structure_input("AAPL", "15m")

        for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
            assert result[key] == []

    def test_missing_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import databento_watchlist_csv as mod

        rows = [
            {"symbol": "AAPL", "trade_date": "2025-01-15", "watchlist_rank": "1"},
        ]
        csv_path = tmp_path / "databento_watchlist_top5_pre1530.csv"
        _write_csv(csv_path, rows)

        with patch.object(mod, "WATCHLIST_CSV", csv_path):
            with pytest.raises(ValueError, match="not present"):
                mod.load_raw_meta_input("NVDA", "15m")

    def test_peer_median_volume_regime(self, tmp_path: Path) -> None:
        from smc_integration.sources import databento_watchlist_csv as mod

        rows = [
            {
                "symbol": "AAPL",
                "trade_date": "2025-01-15",
                "watchlist_rank": "1",
                "current_volume": "50000",
                "avg_daily_volume": "100000",
            },
            {
                "symbol": "MSFT",
                "trade_date": "2025-01-15",
                "watchlist_rank": "2",
                "current_volume": "80000",
                "avg_daily_volume": "90000",
            },
        ]
        csv_path = tmp_path / "databento_watchlist_top5_pre1530.csv"
        _write_csv(csv_path, rows)

        with patch.object(mod, "WATCHLIST_CSV", csv_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        volume = result["volume"]["value"]
        assert volume["regime"] in ("NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT")
        assert "contract_version" in volume

    def test_selects_latest_trade_date(self, tmp_path: Path) -> None:
        from smc_integration.sources import databento_watchlist_csv as mod

        rows = [
            {
                "symbol": "AAPL",
                "trade_date": "2025-01-14",
                "watchlist_rank": "1",
                "day_volume_rvol_20d": "1.0",
            },
            {
                "symbol": "AAPL",
                "trade_date": "2025-01-15",
                "watchlist_rank": "1",
                "day_volume_rvol_20d": "2.0",
            },
        ]
        csv_path = tmp_path / "databento_watchlist_top5_pre1530.csv"
        _write_csv(csv_path, rows)

        with patch.object(mod, "WATCHLIST_CSV", csv_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        # The rvol from the latest trade_date (2.0) should be used
        assert result["volume"]["value"]["rvol"] == 2.0

    def test_empty_csv_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import databento_watchlist_csv as mod

        csv_path = tmp_path / "databento_watchlist_top5_pre1530.csv"
        csv_path.write_text("symbol,trade_date\n", encoding="utf-8")

        with patch.object(mod, "WATCHLIST_CSV", csv_path):
            with pytest.raises(ValueError, match="empty"):
                mod.load_raw_meta_input("AAPL", "15m")


# ── structure_artifact_json ──────────────────────────────────────


class TestStructureArtifactJson:
    def test_describe_source(self) -> None:
        from smc_integration.sources.structure_artifact_json import describe_source

        desc = describe_source()
        assert desc.name == "structure_artifact_json"
        assert desc.capabilities.has_structure is True
        assert desc.capabilities.has_meta is False

    def test_has_any_structure_artifact_false_on_empty(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "artifacts"):
            assert mod.has_any_structure_artifact() is False

    def test_has_any_structure_artifact_true_for_legacy(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "smc_structure_artifact.json"
        _write_json(legacy, {"entries": []})

        with patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy), \
             patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "artifacts"):
            assert mod.has_any_structure_artifact() is True

    def test_has_artifact_for_symbol_timeframe_deterministic(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        artifact = artifacts_dir / "AAPL_15m.structure.json"
        _write_json(artifact, {
            "symbol": "AAPL",
            "timeframe": "15m",
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        })

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.has_artifact_for_symbol_timeframe("AAPL", "15m") is True
            assert mod.has_artifact_for_symbol_timeframe("MSFT", "15m") is False

    def test_resolve_artifact_mode_values(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "artifacts"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.resolve_artifact_mode("AAPL", "15m") == "none"

    def test_load_raw_meta_input_raises(self) -> None:
        from smc_integration.sources.structure_artifact_json import load_raw_meta_input

        with pytest.raises(ValueError, match="does not provide"):
            load_raw_meta_input("AAPL", "15m")

    def test_manifest_resolution(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        artifact_data = {
            "symbol": "AAPL",
            "timeframe": "15m",
            "structure": {"bos": [{"dir": "up"}], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        }
        artifact_path = artifacts_dir / "AAPL_15m.structure.json"
        _write_json(artifact_path, artifact_data)

        manifest = {
            "artifacts": [
                {"symbol": "AAPL", "timeframe": "15m", "artifact_path": "artifacts/AAPL_15m.structure.json"}
            ]
        }
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            result = mod.load_raw_structure_input("AAPL", "15m")

        assert isinstance(result["bos"], list)

    def test_discover_contract_health_empty(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "artifacts"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"):
            health = mod.discover_contract_health()

        assert health["contracts_loaded"] == 0
        assert isinstance(health["issues"], list)


# ── live_news_snapshot_json ──────────────────────────────────────


class TestLiveNewsSnapshotJson:
    def test_describe_source(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import describe_source

        desc = describe_source()
        assert desc.name == "live_news_snapshot_json"
        assert desc.capabilities.has_meta is True
        assert desc.capabilities.has_structure is False

    def test_load_raw_structure_raises_for_unknown_symbol(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {
            "generated_at": 1736899200.0,
            "symbols": ["AAPL"],
            "stories": [
                {"headline": "Apple rises", "tickers": ["AAPL"], "published_ts": 1736899200.0},
            ],
        }
        source_path = tmp_path / "smc_live_news_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path):
            with pytest.raises(ValueError, match="not present"):
                mod.load_raw_structure_input("MSFT", "15m")

    def test_load_raw_structure_returns_empty_for_known_symbol(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {
            "generated_at": 1736899200.0,
            "symbols": ["AAPL"],
            "stories": [],
        }
        source_path = tmp_path / "smc_live_news_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path):
            result = mod.load_raw_structure_input("AAPL", "15m")

        for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
            assert result[key] == []

    def test_load_raw_meta_with_stories(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {
            "generated_at": 1736899200.0,
            "symbols": ["AAPL"],
            "stories": [
                {
                    "headline": "Apple beats earnings",
                    "tickers": ["AAPL"],
                    "published_ts": 1736899200.0,
                    "provider_names": ["benzinga"],
                },
            ],
        }
        source_path = tmp_path / "smc_live_news_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["symbol"] == "AAPL"
        assert result["timeframe"] == "15m"
        assert isinstance(result["asof_ts"], float)
        assert any("live_news_snapshot" in p for p in result["provenance"])

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", tmp_path / "nonexistent.json"):
            with pytest.raises(FileNotFoundError):
                mod.load_raw_meta_input("AAPL", "15m")

    def test_no_stories_returns_no_news_domain(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {
            "generated_at": 1736899200.0,
            "symbols": ["AAPL"],
            "stories": [],
        }
        source_path = tmp_path / "smc_live_news_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert "news" not in result

    def test_symbol_in_stories_but_not_symbols_list(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {
            "generated_at": 1736899200.0,
            "symbols": [],
            "stories": [
                {"headline": "Test", "tickers": ["TSLA"], "published_ts": 1736899200.0},
            ],
        }
        source_path = tmp_path / "smc_live_news_snapshot.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path):
            result = mod.load_raw_structure_input("TSLA", "15m")

        assert result["bos"] == []


# ── cross-adapter contract tests ─────────────────────────────────


class TestCrossAdapterContract:
    """Verify that all describe_source() exports have consistent shape."""

    def test_all_describe_sources_return_source_descriptor(self) -> None:
        from smc_integration.sources import (
            describe_benzinga_watchlist_json_source,
            describe_databento_watchlist_csv_source,
            describe_fmp_watchlist_json_source,
            describe_live_news_snapshot_json_source,
            describe_structure_artifact_json_source,
            describe_tradingview_watchlist_json_source,
        )

        descriptors = [
            describe_benzinga_watchlist_json_source(),
            describe_databento_watchlist_csv_source(),
            describe_fmp_watchlist_json_source(),
            describe_live_news_snapshot_json_source(),
            describe_structure_artifact_json_source(),
            describe_tradingview_watchlist_json_source(),
        ]

        names = set()
        for desc in descriptors:
            assert isinstance(desc, SourceDescriptor)
            assert desc.name
            assert desc.path_hint
            assert isinstance(desc.capabilities, SourceCapabilities)
            assert desc.capabilities.structure_mode in ("full", "partial", "none")
            assert desc.capabilities.meta_mode in ("full", "partial", "none")
            d = desc.to_dict()
            assert isinstance(d, dict)
            names.add(desc.name)

        assert len(names) == 6, "all sources must have unique names"

    def test_structure_sources_claim_has_structure(self) -> None:
        from smc_integration.sources import (
            describe_databento_watchlist_csv_source,
            describe_structure_artifact_json_source,
        )

        for fn in (describe_databento_watchlist_csv_source, describe_structure_artifact_json_source):
            desc = fn()
            assert desc.capabilities.has_structure is True, f"{desc.name} should have structure"

    def test_meta_only_sources_claim_no_structure(self) -> None:
        from smc_integration.sources import (
            describe_benzinga_watchlist_json_source,
            describe_fmp_watchlist_json_source,
            describe_live_news_snapshot_json_source,
            describe_tradingview_watchlist_json_source,
        )

        for fn in (
            describe_benzinga_watchlist_json_source,
            describe_fmp_watchlist_json_source,
            describe_live_news_snapshot_json_source,
            describe_tradingview_watchlist_json_source,
        ):
            desc = fn()
            assert desc.capabilities.has_structure is False, f"{desc.name} should NOT have structure"
            assert desc.capabilities.structure_mode == "none"
