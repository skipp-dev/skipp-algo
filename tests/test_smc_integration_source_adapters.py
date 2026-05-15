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

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="not present"):
            mod.load_raw_meta_input("MSFT", "15m")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", tmp_path / "nonexistent.json"), pytest.raises(FileNotFoundError):
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

    def test_invalid_payload_type_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        source_path = tmp_path / "bz.json"
        source_path.write_text("[1,2,3]", encoding="utf-8")

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="must be an object"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_no_symbol_rows_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        payload = {"other_key": "value"}
        source_path = tmp_path / "bz.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="no symbol rows"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_payload_key_alternatives(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        for key in ("watchlist", "items", "data"):
            payload = {key: [_BENZINGA_ROW]}
            source_path = tmp_path / "bz.json"
            _write_json(source_path, payload)

            with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
                result = mod.load_raw_meta_input("AAPL", "15m")

            assert result["symbol"] == "AAPL"

    def test_missing_both_asof_and_trade_date_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        row = {"symbol": "AAPL", "volume_regime": "NORMAL", "news": {"strength": 0.5, "bias": "NEUTRAL", "asof_ts": 1.0}}
        payload = {"symbols": [row]}
        source_path = tmp_path / "bz.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="missing both"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_coerce_helpers(self) -> None:
        from smc_integration.sources.benzinga_watchlist_json import (
            _coerce_bias,
            _coerce_optional_bool,
            _coerce_optional_float,
        )

        assert _coerce_optional_float("3.14") == 3.14
        assert _coerce_optional_float("bad") is None
        assert _coerce_optional_float(None) is None
        assert _coerce_optional_bool("true") is True
        assert _coerce_optional_bool("false") is False
        assert _coerce_optional_bool("maybe") is None
        assert _coerce_optional_bool(True) is True
        assert _coerce_bias("BULLISH") == "BULLISH"
        assert _coerce_bias("bearish") == "BEARISH"
        assert _coerce_bias("neutral") == "NEUTRAL"
        assert _coerce_bias("UNKNOWN") is None
        assert _coerce_bias(42) is None

    def test_invalid_regime_defaults_to_normal(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        row = {**_BENZINGA_ROW, "volume_regime": "SUPER_HIGH"}
        payload = {"symbols": [row]}
        source_path = tmp_path / "bz.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["volume"]["value"]["regime"] == "NORMAL"

    def test_flat_news_field_fallback(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        row = {
            "symbol": "TSLA",
            "trade_date": "2025-01-15",
            "asof_ts": 1736899200.0,
            "volume_regime": "NORMAL",
            "news_strength": "0.8",
            "news_bias": "BULLISH",
        }
        payload = {"symbols": [row]}
        source_path = tmp_path / "bz.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("TSLA", "15m")

        assert result["news"]["value"]["strength"] == 0.8
        assert result["news"]["value"]["bias"] == "BULLISH"

    def test_empty_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        payload = {"symbols": [_BENZINGA_ROW]}
        source_path = tmp_path / "bz.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="must not be empty"):
            mod.load_raw_meta_input("", "15m")

    def test_thin_fraction_coercion(self, tmp_path: Path) -> None:
        from smc_integration.sources import benzinga_watchlist_json as mod

        row = {**_BENZINGA_ROW, "thin_fraction": "bad_value"}
        payload = {"symbols": [row]}
        source_path = tmp_path / "bz.json"
        _write_json(source_path, payload)

        with patch.object(mod, "BENZINGA_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["volume"]["value"]["thin_fraction"] == 0.0


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

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        with patch.object(mod, "FMP_WATCHLIST_JSON", tmp_path / "nope.json"), pytest.raises(FileNotFoundError):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_invalid_payload_type_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        source_path = tmp_path / "fmp.json"
        source_path.write_text("[1,2,3]", encoding="utf-8")

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="must be an object"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_missing_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        payload = {"symbols": [_FMP_ROW]}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="not present"):
            mod.load_raw_meta_input("MSFT", "15m")

    def test_no_symbol_rows_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        payload = {"other_key": "value"}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="no symbol rows"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_payload_key_alternatives(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        for key in ("watchlist", "items", "data"):
            payload = {key: [_FMP_ROW]}
            source_path = tmp_path / "fmp.json"
            _write_json(source_path, payload)

            with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
                result = mod.load_raw_meta_input("AAPL", "15m")

            assert result["symbol"] == "AAPL"

    def test_trade_date_fallback_for_asof_ts(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        row = {**_FMP_ROW}
        del row["asof_ts"]
        payload = {"symbols": [row]}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert isinstance(result["asof_ts"], float)
        assert result["asof_ts"] > 0

    def test_missing_both_asof_and_trade_date_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        row = {"symbol": "AAPL", "volume_regime": "NORMAL", "technical": {"strength": 0.5, "bias": "NEUTRAL", "asof_ts": 1.0}}
        payload = {"symbols": [row]}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="missing both"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_coerce_helpers(self) -> None:
        from smc_integration.sources.fmp_watchlist_json import (
            _coerce_bias,
            _coerce_optional_bool,
            _coerce_optional_float,
        )

        assert _coerce_optional_float("3.14") == 3.14
        assert _coerce_optional_float("bad") is None
        assert _coerce_optional_float(None) is None
        assert _coerce_optional_bool("true") is True
        assert _coerce_optional_bool("false") is False
        assert _coerce_optional_bool("maybe") is None
        assert _coerce_optional_bool(True) is True
        assert _coerce_bias("BULLISH") == "BULLISH"
        assert _coerce_bias("bearish") == "BEARISH"
        assert _coerce_bias("neutral") == "NEUTRAL"
        assert _coerce_bias("UNKNOWN") is None
        assert _coerce_bias(42) is None

    def test_flat_field_fallback(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        row = {
            "symbol": "TSLA",
            "trade_date": "2025-01-15",
            "asof_ts": 1736899200.0,
            "volume_regime": "NORMAL",
            "technical_strength": "0.8",
            "technical_bias": "BULLISH",
        }
        payload = {"symbols": [row]}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("TSLA", "15m")

        assert result["technical"]["value"]["strength"] == 0.8
        assert result["technical"]["value"]["bias"] == "BULLISH"

    def test_empty_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        payload = {"symbols": [_FMP_ROW]}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="must not be empty"):
            mod.load_raw_meta_input("", "15m")

    def test_thin_fraction_coercion(self, tmp_path: Path) -> None:
        from smc_integration.sources import fmp_watchlist_json as mod

        row = {**_FMP_ROW, "thin_fraction": "bad_value"}
        payload = {"symbols": [row]}
        source_path = tmp_path / "fmp.json"
        _write_json(source_path, payload)

        with patch.object(mod, "FMP_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["volume"]["value"]["thin_fraction"] == 0.0


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

        with patch.object(mod, "WATCHLIST_CSV", csv_path), pytest.raises(ValueError, match="not present"):
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

        with patch.object(mod, "WATCHLIST_CSV", csv_path), pytest.raises(ValueError, match="empty"):
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

    def test_load_raw_structure_no_artifact_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "artifacts"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path), pytest.raises(FileNotFoundError, match="no structure artifact"):
            mod.load_raw_structure_input("AAPL", "15m")

    def test_validate_contract_identity_symbol_mismatch(self, tmp_path: Path) -> None:
        from smc_integration.sources.structure_artifact_json import _validate_contract_identity

        with pytest.raises(ValueError, match="symbol mismatch"):
            _validate_contract_identity({"symbol": "MSFT", "timeframe": "15m"}, symbol="AAPL", timeframe="15m", path=tmp_path / "x.json")

    def test_validate_contract_identity_timeframe_mismatch(self, tmp_path: Path) -> None:
        from smc_integration.sources.structure_artifact_json import _validate_contract_identity

        with pytest.raises(ValueError, match="timeframe mismatch"):
            _validate_contract_identity({"symbol": "AAPL", "timeframe": "1D"}, symbol="AAPL", timeframe="15m", path=tmp_path / "x.json")

    def test_legacy_artifact_has_symbol(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        _write_json(legacy, {"entries": [{"symbol": "AAPL"}, {"symbol": "MSFT"}]})

        with patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy):
            assert mod._legacy_artifact_has_symbol("AAPL") is True
            assert mod._legacy_artifact_has_symbol("TSLA") is False

    def test_legacy_artifact_has_symbol_bad_entries(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        _write_json(legacy, {"entries": "not_a_list"})

        with patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy):
            assert mod._legacy_artifact_has_symbol("AAPL") is False

    def test_legacy_artifact_corrupted_returns_false(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        legacy.write_text("{{bad json", encoding="utf-8")

        with patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy):
            assert mod._legacy_artifact_has_symbol("AAPL") is False

    def test_select_symbol_entry_basic(self) -> None:
        from smc_integration.sources.structure_artifact_json import _select_symbol_entry

        payload = {
            "entries": [
                {"symbol": "AAPL", "timeframe": "15m", "data": 1},
                {"symbol": "MSFT", "timeframe": "15m", "data": 2},
            ],
        }
        entry = _select_symbol_entry(payload, "AAPL", "15m")
        assert entry["data"] == 1

    def test_select_symbol_entry_timeframe_fallback(self) -> None:
        from smc_integration.sources.structure_artifact_json import _select_symbol_entry

        payload = {
            "entries": [
                {"symbol": "AAPL", "timeframe": "1D", "data": 1},
            ],
        }
        entry = _select_symbol_entry(payload, "AAPL", "15m")
        assert entry["data"] == 1

    def test_select_symbol_entry_missing_symbol_raises(self) -> None:
        from smc_integration.sources.structure_artifact_json import _select_symbol_entry

        payload = {"entries": [{"symbol": "AAPL", "timeframe": "15m"}]}
        with pytest.raises(ValueError, match="not present"):
            _select_symbol_entry(payload, "MSFT", "15m")

    def test_select_symbol_entry_empty_symbol_raises(self) -> None:
        from smc_integration.sources.structure_artifact_json import _select_symbol_entry

        payload = {"entries": [{"symbol": "AAPL"}]}
        with pytest.raises(ValueError, match="must not be empty"):
            _select_symbol_entry(payload, "", "15m")

    def test_select_symbol_entry_no_entries_key_raises(self) -> None:
        from smc_integration.sources.structure_artifact_json import _select_symbol_entry

        with pytest.raises(ValueError, match="no entries"):
            _select_symbol_entry({}, "AAPL", "15m")

    def test_has_artifact_legacy_fallback(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        _write_json(legacy, {"entries": [{"symbol": "AAPL"}]})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.has_artifact_for_symbol_timeframe("AAPL", "15m") is True
            assert mod.has_artifact_for_symbol_timeframe("TSLA", "15m") is False

    def test_resolve_artifact_mode_legacy(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        _write_json(legacy, {"entries": [{"symbol": "AAPL"}]})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.resolve_artifact_mode("AAPL", "15m") == "legacy_single"
            assert mod.resolve_artifact_mode("TSLA", "15m") == "none"

    def test_resolve_artifact_mode_deterministic(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        artifact = artifacts_dir / "AAPL_15m.structure.json"
        _write_json(artifact, {"symbol": "AAPL", "timeframe": "15m"})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.resolve_artifact_mode("AAPL", "15m") == "deterministic"

    def test_resolve_artifact_mode_manifest(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        artifact = artifacts_dir / "AAPL_15m.structure.json"
        _write_json(artifact, {"symbol": "AAPL", "timeframe": "15m",
                               "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}})
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "artifacts/AAPL_15m.structure.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.resolve_artifact_mode("AAPL", "15m") == "manifest"

    def test_has_any_structure_artifact_manifest(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        _write_json(artifacts_dir / "manifest_15m.json", {"artifacts": []})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"):
            assert mod.has_any_structure_artifact() is True

    def test_has_any_structure_artifact_deterministic(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        _write_json(artifacts_dir / "AAPL_15m.structure.json", {"symbol": "AAPL"})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"):
            assert mod.has_any_structure_artifact() is True

    def test_iter_manifest_artifacts_invalid_json(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "manifest_15m.json").write_text("{{bad", encoding="utf-8")

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            _paths, issues = mod._iter_manifest_artifacts()

        assert len(issues) == 1
        assert issues[0]["code"] == "INVALID_MANIFEST_JSON"

    def test_iter_manifest_artifacts_invalid_shape(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        _write_json(artifacts_dir / "manifest_15m.json", {"artifacts": "bad"})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            _paths, issues = mod._iter_manifest_artifacts()

        assert len(issues) == 1
        assert issues[0]["code"] == "INVALID_MANIFEST_SHAPE"

    def test_iter_manifest_artifacts_missing_path(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "nope/x.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            _paths, issues = mod._iter_manifest_artifacts()

        assert any(i["code"] == "MISSING_ARTIFACT_PATH" for i in issues)

    def test_discover_normalized_contract_summary_with_contracts(self, tmp_path: Path) -> None:
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
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "artifacts/AAPL_15m.structure.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            summary = mod.discover_normalized_contract_summary()

        assert summary["health"]["contracts_loaded"] >= 1

    def test_discover_category_coverage(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"):
            coverage = mod.discover_category_coverage()

        assert isinstance(coverage, dict)
        assert "bos" in coverage

    def test_entry_matches_timeframe(self) -> None:
        from smc_integration.sources.structure_artifact_json import _entry_matches_timeframe

        assert _entry_matches_timeframe({"timeframe": "15m"}, "15m") is True
        assert _entry_matches_timeframe({"timeframe": "15M"}, "15m") is True
        assert _entry_matches_timeframe({"timeframe": "1D"}, "15m") is False
        assert _entry_matches_timeframe({}, "15m") is False

    def test_health_issue_with_and_without_path(self) -> None:
        from smc_integration.sources.structure_artifact_json import _health_issue

        issue = _health_issue("TEST_CODE", "test message")
        assert issue["code"] == "TEST_CODE"
        assert "path" not in issue

        issue2 = _health_issue("TEST_CODE", "test message", path=Path("/some/path"))
        assert "path" in issue2

    def test_resolve_from_manifest_missing_artifact_path(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": ""}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path), pytest.raises(ValueError, match="missing artifact_path"):
            mod._resolve_from_manifest("AAPL", "15m")

    def test_resolve_from_manifest_path_not_exists(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "nope/x.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path), pytest.raises(ValueError, match="does not exist"):
            mod._resolve_from_manifest("AAPL", "15m")

    def test_load_json_non_dict_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources.structure_artifact_json import _load_json

        path = tmp_path / "test.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")

        with pytest.raises(ValueError, match="must be an object"):
            _load_json(path)

    def test_optional_path_empty(self) -> None:
        from smc_integration.sources.structure_artifact_json import _optional_path

        assert _optional_path(None) is None
        assert _optional_path("") is None
        assert _optional_path("  ") is None

    def test_optional_path_valid(self) -> None:
        from smc_integration.sources.structure_artifact_json import _optional_path

        result = _optional_path("/some/path")
        # _optional_path calls .resolve() which on Windows prepends the current
        # drive letter.  Compare against the resolved form of the same path so
        # the assertion holds on both POSIX and Windows.
        assert result == Path("/some/path").resolve()

    def test_iter_manifest_artifacts_deterministic_fallback(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        # No manifests, but deterministic artifacts exist
        _write_json(artifacts_dir / "AAPL_15m.structure.json", {"symbol": "AAPL", "timeframe": "15m"})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            paths, _issues = mod._iter_manifest_artifacts()

        assert len(paths) == 1
        assert paths[0].name == "AAPL_15m.structure.json"

    def test_iter_manifest_artifacts_no_dir(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"):
            paths, issues = mod._iter_manifest_artifacts()

        assert paths == []
        assert issues == []

    def test_iter_manifest_artifacts_skips_non_dict_rows(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        manifest = {"artifacts": ["not_a_dict", {"symbol": "AAPL", "timeframe": "15m", "artifact_path": ""}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            paths, _issues = mod._iter_manifest_artifacts()

        # No valid artifact paths — non-dict and empty path both skipped
        assert paths == []

    def test_iter_manifest_artifacts_empty_manifests_returns_empty(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        _write_json(artifacts_dir / "manifest_15m.json", {"artifacts": []})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            paths, _issues = mod._iter_manifest_artifacts()

        # manifests exist but have no artifacts → return empty (no deterministic fallback)
        assert paths == []

    def test_iter_normalized_contracts_from_manifest(self, tmp_path: Path) -> None:
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
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "artifacts/AAPL_15m.structure.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            contracts, _issues = mod._iter_normalized_contracts()

        assert len(contracts) >= 1

    def test_iter_normalized_contracts_invalid_artifact(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        (artifacts_dir / "AAPL_15m.structure.json").write_text("{{bad", encoding="utf-8")
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "artifacts/AAPL_15m.structure.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            contracts, issues = mod._iter_normalized_contracts()

        assert contracts == []
        assert any(i["code"] == "INVALID_STRUCTURE_ARTIFACT" for i in issues)

    def test_iter_normalized_contracts_legacy_fallback(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        _write_json(legacy, {
            "entries": [{
                "symbol": "AAPL",
                "timeframe": "15m",
                "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
            }],
        })

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            contracts, _issues = mod._iter_normalized_contracts()

        assert len(contracts) >= 1

    def test_iter_normalized_contracts_legacy_invalid(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        legacy.write_text("{{bad json", encoding="utf-8")

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            contracts, issues = mod._iter_normalized_contracts()

        assert contracts == []
        assert any(i["code"] == "INVALID_LEGACY_STRUCTURE_ARTIFACT" for i in issues)

    def test_load_structure_context_input(self, tmp_path: Path) -> None:
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

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            ctx = mod.load_structure_context_input("AAPL", "15m")

        assert isinstance(ctx, dict)

    def test_load_structure_context_input_none(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.load_structure_context_input("AAPL", "15m") is None

    def test_discover_contract_capabilities(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"):
            caps = mod.discover_contract_capabilities()

        assert isinstance(caps, dict)
        assert "mapped_structure_categories" in caps

    def test_load_normalized_structure_contract_from_deterministic(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        artifact_data = {
            "symbol": "AAPL",
            "timeframe": "15m",
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        }
        _write_json(artifacts_dir / "AAPL_15m.structure.json", artifact_data)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            result = mod.load_normalized_structure_contract_input("AAPL", "15m")

        assert result is not None
        assert result["symbol"] == "AAPL"

    def test_load_normalized_structure_contract_legacy(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        legacy = tmp_path / "artifact.json"
        _write_json(legacy, {
            "entries": [{
                "symbol": "AAPL",
                "timeframe": "15m",
                "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
            }],
        })

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", legacy), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            result = mod.load_normalized_structure_contract_input("AAPL", "15m")

        assert result is not None

    def test_load_normalized_structure_contract_none(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod.load_normalized_structure_contract_input("AAPL", "15m") is None

    def test_manifest_repo_state_health_missing_provenance(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        manifest_path = tmp_path / "manifest.json"
        payload: dict[str, Any] = {}

        with patch.object(mod, "_repo_state_paths_match_defaults", return_value=True), \
             patch("smc_integration.artifact_resolution.resolve_production_workbook_path", return_value=tmp_path / "wb.xlsx"):
            issues = mod._manifest_repo_state_health_issues(payload, manifest_path=manifest_path)

        assert any(i["code"] == "MISSING_MANIFEST_WORKBOOK_PROVENANCE" for i in issues)

    def test_manifest_repo_state_health_noncanonical(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        manifest_path = tmp_path / "manifest.json"
        wb = tmp_path / "wrong_wb.xlsx"
        wb.touch()
        payload: dict[str, Any] = {"resolved_inputs": {"workbook_path": str(wb)}}

        with patch.object(mod, "_repo_state_paths_match_defaults", return_value=True), \
             patch("smc_integration.artifact_resolution.resolve_production_workbook_path", return_value=tmp_path / "correct_wb.xlsx"):
            issues = mod._manifest_repo_state_health_issues(payload, manifest_path=manifest_path)

        assert any(i["code"] == "NONCANONICAL_MANIFEST_WORKBOOK_PATH" for i in issues)

    def test_manifest_repo_state_health_inconsistent(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        manifest_path = tmp_path / "manifest.json"
        wb_a = tmp_path / "a.xlsx"
        wb_b = tmp_path / "b.xlsx"
        wb_a.touch()
        wb_b.touch()
        payload: dict[str, Any] = {
            "resolved_inputs": {"workbook_path": str(wb_a)},
            "producer": {"upstream": str(wb_b)},
        }

        with patch.object(mod, "_repo_state_paths_match_defaults", return_value=True), \
             patch("smc_integration.artifact_resolution.resolve_production_workbook_path", return_value=wb_a):
            issues = mod._manifest_repo_state_health_issues(payload, manifest_path=manifest_path)

        assert any(i["code"] == "INCONSISTENT_MANIFEST_WORKBOOK_PROVENANCE" for i in issues)

    def test_manifest_repo_state_health_paths_not_default(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "_repo_state_paths_match_defaults", return_value=False):
            issues = mod._manifest_repo_state_health_issues({}, manifest_path=tmp_path / "m.json")

        assert issues == []

    def test_manifest_repo_state_health_no_workbook(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "_repo_state_paths_match_defaults", return_value=True), \
             patch("smc_integration.artifact_resolution.resolve_production_workbook_path", return_value=None):
            issues = mod._manifest_repo_state_health_issues({}, manifest_path=tmp_path / "m.json")

        assert issues == []

    def test_assert_manifest_repo_state_provenance_ok_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        _write_json(artifacts_dir / "manifest_15m.json", {})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path), \
             patch.object(mod, "_manifest_repo_state_health_issues", return_value=[
                 {"code": "MISSING_MANIFEST_WORKBOOK_PROVENANCE", "message": "no provenance"}
             ]), pytest.raises(ValueError, match="provenance check failed"):
            mod._assert_manifest_repo_state_provenance_ok("15m")

    def test_assert_manifest_repo_state_provenance_ok_no_manifest(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"):
            # Should not raise when manifest doesn't exist
            mod._assert_manifest_repo_state_provenance_ok("15m")

    def test_iter_manifest_artifacts_repo_state_only(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        artifact_data = {
            "symbol": "AAPL",
            "timeframe": "15m",
            "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        }
        artifact_path = artifacts_dir / "AAPL_15m.structure.json"
        _write_json(artifact_path, artifact_data)
        manifest = {"artifacts": [{"symbol": "AAPL", "timeframe": "15m", "artifact_path": "artifacts/AAPL_15m.structure.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        # repo_state_only with issues → skip that manifest
        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path), \
             patch.object(mod, "_manifest_repo_state_health_issues", return_value=[
                 {"code": "MISSING_MANIFEST_WORKBOOK_PROVENANCE", "message": "test"}
             ]):
            paths, issues = mod._iter_manifest_artifacts(repo_state_only=True)

        assert paths == []
        assert any(i["code"] == "MISSING_MANIFEST_WORKBOOK_PROVENANCE" for i in issues)

    def test_resolve_from_manifest_non_list_artifacts_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        _write_json(artifacts_dir / "manifest_15m.json", {"artifacts": "bad"})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path), pytest.raises(ValueError, match="must be a list"):
            mod._resolve_from_manifest("AAPL", "15m")

    def test_resolve_from_manifest_no_manifest(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"):
            assert mod._resolve_from_manifest("AAPL", "15m") is None

    def test_resolve_from_manifest_symbol_not_found(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        manifest = {"artifacts": [{"symbol": "MSFT", "timeframe": "15m", "artifact_path": "nope.json"}]}
        _write_json(artifacts_dir / "manifest_15m.json", manifest)

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod._resolve_from_manifest("AAPL", "15m") is None

    def test_resolve_artifact_file(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        artifact = artifacts_dir / "AAPL_15m.structure.json"
        _write_json(artifact, {"symbol": "AAPL"})

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", artifacts_dir), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            result = mod._resolve_artifact_file("AAPL", "15m")

        assert result is not None

    def test_resolve_artifact_file_none(self, tmp_path: Path) -> None:
        from smc_integration.sources import structure_artifact_json as mod

        with patch.object(mod, "STRUCTURE_ARTIFACTS_DIR", tmp_path / "nope"), \
             patch.object(mod, "STRUCTURE_ARTIFACT_JSON", tmp_path / "nope.json"), \
             patch.object(mod, "REPO_ROOT", tmp_path):
            assert mod._resolve_artifact_file("AAPL", "15m") is None


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

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path), pytest.raises(ValueError, match="not present"):
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

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", tmp_path / "nonexistent.json"), pytest.raises(FileNotFoundError):
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


# ── tradingview_watchlist_json pure helper coverage ──────────────


class TestTradingviewHelpers:
    def test_load_raw_structure_returns_canonical(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        payload = {"symbols": [_TV_ROW]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_structure_input("AAPL", "15m")

        for key in ("bos", "orderblocks", "fvg", "liquidity_sweeps"):
            assert result[key] == []

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", tmp_path / "nope.json"), pytest.raises(FileNotFoundError):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_invalid_payload_type_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        source_path = tmp_path / "tv.json"
        source_path.write_text("[1,2,3]", encoding="utf-8")

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="must be an object"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_missing_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        payload = {"symbols": [_TV_ROW]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="not present"):
            mod.load_raw_meta_input("MSFT", "15m")

    def test_empty_symbol_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        payload = {"symbols": [_TV_ROW]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="must not be empty"):
            mod.load_raw_meta_input("", "15m")

    def test_no_symbol_rows_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        payload = {"other_key": "value"}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="no symbol rows"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_invalid_regime_defaults_to_normal(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        row = {**_TV_ROW, "volume_regime": "SUPER_HIGH"}
        payload = {"symbols": [row]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert result["volume"]["value"]["regime"] == "NORMAL"

    def test_missing_technical_drops_domain(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        row = {
            "symbol": "AAPL",
            "trade_date": "2025-01-15",
            "asof_ts": 1736899200.0,
            "volume_regime": "NORMAL",
        }
        payload = {"symbols": [row]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert "technical" not in result
        assert result.get("_meta_domain_statuses", {}).get("technical") == "domain_fields_incomplete"

    def test_trade_date_fallback_for_asof_ts(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        row = {**_TV_ROW}
        del row["asof_ts"]
        payload = {"symbols": [row]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path):
            result = mod.load_raw_meta_input("AAPL", "15m")

        assert isinstance(result["asof_ts"], float)

    def test_missing_both_asof_and_trade_date_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import tradingview_watchlist_json as mod

        row = {"symbol": "AAPL", "volume_regime": "NORMAL"}
        payload = {"symbols": [row]}
        source_path = tmp_path / "tv.json"
        _write_json(source_path, payload)

        with patch.object(mod, "TRADINGVIEW_WATCHLIST_JSON", source_path), pytest.raises(ValueError, match="missing both"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_coerce_helpers(self) -> None:
        from smc_integration.sources.tradingview_watchlist_json import (
            _coerce_bias,
            _coerce_optional_bool,
            _coerce_optional_float,
        )

        assert _coerce_optional_float("3.14") == 3.14
        assert _coerce_optional_float("bad") is None
        assert _coerce_optional_float(None) is None
        assert _coerce_optional_bool("true") is True
        assert _coerce_optional_bool("false") is False
        assert _coerce_optional_bool("maybe") is None
        assert _coerce_optional_bool(True) is True
        assert _coerce_bias("BULLISH") == "BULLISH"
        assert _coerce_bias("bearish") == "BEARISH"
        assert _coerce_bias("neutral") == "NEUTRAL"
        assert _coerce_bias("UNKNOWN") is None
        assert _coerce_bias(42) is None


# ── live_news_snapshot_json pure helper coverage ─────────────────


class TestLiveNewsHelpers:
    def test_invalid_payload_type_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        source_path = tmp_path / "snap.json"
        source_path.write_text("[1,2,3]", encoding="utf-8")

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path), pytest.raises(ValueError, match="must be an object"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_no_stories_key_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {"generated_at": 1736899200.0, "symbols": ["AAPL"]}
        source_path = tmp_path / "snap.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path), pytest.raises(ValueError, match="no story rows"):
            mod.load_raw_meta_input("AAPL", "15m")

    def test_parse_generated_at_iso(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _parse_generated_at

        assert _parse_generated_at(1736899200.0) == 1736899200.0
        assert _parse_generated_at(1736899200) == 1736899200.0
        assert isinstance(_parse_generated_at("2025-01-15T00:00:00Z"), float)
        assert _parse_generated_at("") is None
        assert _parse_generated_at(None) is None
        assert _parse_generated_at({"bad": True}) is None

    def test_score_for_symbol_from_heat_map(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _score_for_symbol

        scored = {"ticker_heat_map": "AAPL:0.8,MSFT:0.3"}
        assert _score_for_symbol(scored, "AAPL") == 0.8
        assert _score_for_symbol(scored, "MSFT") == 0.3
        assert _score_for_symbol(scored, "TSLA") is None

    def test_score_for_symbol_from_bullish_list(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _score_for_symbol

        scored = {"bullish_tickers": ["AAPL"], "news_heat_global": 0.5}
        assert _score_for_symbol(scored, "AAPL") == 0.5

    def test_score_for_symbol_from_bearish_list(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _score_for_symbol

        scored = {"bearish_tickers": ["AAPL"], "news_heat_global": -0.4}
        assert _score_for_symbol(scored, "AAPL") == -0.4

    def test_score_for_symbol_from_neutral_list(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _score_for_symbol

        scored = {"neutral_tickers": ["AAPL"]}
        assert _score_for_symbol(scored, "AAPL") == 0.0

    def test_score_for_symbol_heat_map_bad_float(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _score_for_symbol

        scored = {"ticker_heat_map": "AAPL:bad"}
        assert _score_for_symbol(scored, "AAPL") is None

    def test_matching_story_articles_extracts_providers(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _matching_story_articles

        payload = {
            "stories": [
                {
                    "headline": "Test",
                    "tickers": ["AAPL"],
                    "published_ts": 1736899200.0,
                    "provider_names": ["benzinga"],
                    "first_provider": "newsapi",
                },
            ],
        }
        articles, providers, ts = _matching_story_articles(payload, "AAPL")
        assert len(articles) == 1
        assert "benzinga" in providers
        assert "newsapi" in providers
        assert ts == 1736899200.0

    def test_matching_story_articles_no_match(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _matching_story_articles

        payload = {"stories": [{"headline": "Test", "tickers": ["MSFT"]}]}
        articles, providers, ts = _matching_story_articles(payload, "AAPL")
        assert articles == []
        assert providers == []
        assert ts is None

    def test_snapshot_mentions_symbol_from_stories(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _snapshot_mentions_symbol

        payload = {
            "symbols": [],
            "stories": [{"tickers": ["AAPL"]}],
        }
        assert _snapshot_mentions_symbol(payload, "AAPL") is True
        assert _snapshot_mentions_symbol(payload, "MSFT") is False

    def test_snapshot_mentions_symbol_from_list(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _snapshot_mentions_symbol

        payload = {"symbols": ["AAPL"], "stories": []}
        assert _snapshot_mentions_symbol(payload, "AAPL") is True

    def test_snapshot_mentions_empty_symbol(self) -> None:
        from smc_integration.sources.live_news_snapshot_json import _snapshot_mentions_symbol

        payload = {"symbols": ["AAPL"], "stories": []}
        assert _snapshot_mentions_symbol(payload, "") is False

    def test_load_raw_meta_missing_timestamps_raises(self, tmp_path: Path) -> None:
        from smc_integration.sources import live_news_snapshot_json as mod

        payload = {"symbols": ["AAPL"], "stories": [{"tickers": ["AAPL"]}]}
        source_path = tmp_path / "snap.json"
        _write_json(source_path, payload)

        with patch.object(mod, "LIVE_NEWS_SNAPSHOT_JSON", source_path), pytest.raises(ValueError, match="missing both"):
            mod.load_raw_meta_input("AAPL", "15m")
