"""Paket B – Provider-Mehrwert: acceptance tests covering B1-B4.

B1: Domain-aware fallback chain (_try_load_meta_domain).
B2: Technical dual-source (FMP → TradingView fallback).
B3: Enhanced diagnostics (actual source + fallback_used flag).
B4: No false fallbacks (domain_key_absent triggers next provider).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from smc_integration.repo_sources import (
    _try_load_meta_domain,
    load_raw_meta_input_composite,
)
from smc_integration.sources import (
    benzinga_watchlist_json,
    databento_watchlist_csv,
    fmp_watchlist_json,
    tradingview_watchlist_json,
)


def _write_source(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"symbols": rows}, indent=2), encoding="utf-8")


def _write_volume_csv(path: Path, symbol: str = "AAPL") -> None:
    """Write a minimal databento-compatible watchlist CSV."""
    path.write_text(
        f"symbol,trade_date,watchlist_rank\n{symbol},2026-03-01,1\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Fixtures for provider data
# ---------------------------------------------------------------------------

def _fmp_row_with_technical(symbol: str = "AAPL") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trade_date": "2026-03-01",
        "asof_ts": 1709254000.0,
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.81,
        "technical_bias": "BULLISH",
    }


def _fmp_row_without_technical(symbol: str = "AAPL") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trade_date": "2026-03-01",
        "asof_ts": 1709254000.0,
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
    }


def _tv_row_with_technical(symbol: str = "AAPL") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trade_date": "2026-03-01",
        "asof_ts": 1709254001.0,
        "volume_regime": "NORMAL",
        "thin_fraction": 0.05,
        "technical_strength": 0.72,
        "technical_bias": "BEARISH",
    }


def _benzinga_row_with_news(symbol: str = "AAPL") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trade_date": "2026-03-01",
        "asof_ts": 1709254002.0,
        "volume_regime": "NORMAL",
        "thin_fraction": 0.0,
        "news_strength": 0.55,
        "news_bias": "BEARISH",
    }


# ---------------------------------------------------------------------------
# B1: _try_load_meta_domain fallback behavior
# ---------------------------------------------------------------------------

class TestB1DomainFallbackChain:
    def test_primary_succeeds_no_fallback(self, monkeypatch, tmp_path: Path) -> None:
        fmp_path = tmp_path / "fmp.json"
        _write_source(fmp_path, [_fmp_row_with_technical()])
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

        meta, status, actual = _try_load_meta_domain(
            "technical", "AAPL", "15m", "fmp_watchlist_json", auto_mode=True,
        )
        assert status == "present"
        assert actual == "fmp_watchlist_json"
        assert meta is not None
        assert meta["technical"]["value"]["bias"] == "BULLISH"

    def test_fallback_to_secondary_on_file_not_found(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")

        tv_path = tmp_path / "tv.json"
        _write_source(tv_path, [_tv_row_with_technical()])
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

        meta, status, actual = _try_load_meta_domain(
            "technical", "AAPL", "15m", "fmp_watchlist_json", auto_mode=True,
        )
        assert status == "present"
        assert actual == "tradingview_watchlist_json"
        assert meta["technical"]["value"]["bias"] == "BEARISH"

    def test_no_fallback_in_explicit_mode(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")

        tv_path = tmp_path / "tv.json"
        _write_source(tv_path, [_tv_row_with_technical()])
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

        with pytest.raises(FileNotFoundError):
            _try_load_meta_domain(
                "technical", "AAPL", "15m", "fmp_watchlist_json", auto_mode=False,
            )

    def test_all_providers_exhausted(self, monkeypatch, tmp_path: Path) -> None:
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tmp_path / "also_missing.json")

        meta, status, actual = _try_load_meta_domain(
            "technical", "AAPL", "15m", "fmp_watchlist_json", auto_mode=True,
        )
        assert meta is None
        assert status == "source_file_not_found"


# ---------------------------------------------------------------------------
# B2: Technical dual-source (FMP → TradingView)
# ---------------------------------------------------------------------------

class TestB2TechnicalDualSource:
    def test_fmp_primary_used_when_available(self, monkeypatch, tmp_path: Path) -> None:
        vol_csv = tmp_path / "vol.csv"
        _write_volume_csv(vol_csv)
        monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

        fmp_path = tmp_path / "fmp.json"
        _write_source(fmp_path, [_fmp_row_with_technical()])
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

        tv_path = tmp_path / "tv.json"
        _write_source(tv_path, [_tv_row_with_technical()])
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

        bz_path = tmp_path / "bz.json"
        _write_source(bz_path, [_benzinga_row_with_news()])
        monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", bz_path)

        merged = load_raw_meta_input_composite("AAPL", "15m")
        diag = merged["meta_domain_diagnostics"]
        assert diag["technical"] == "present"
        assert diag["technical_source"] == "fmp_watchlist_json"
        assert diag["technical_fallback_used"] is False
        assert merged["technical"]["value"]["bias"] == "BULLISH"

    def test_tradingview_fallback_when_fmp_missing(self, monkeypatch, tmp_path: Path) -> None:
        vol_csv = tmp_path / "vol.csv"
        _write_volume_csv(vol_csv)
        monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")

        tv_path = tmp_path / "tv.json"
        _write_source(tv_path, [_tv_row_with_technical()])
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

        bz_path = tmp_path / "bz.json"
        _write_source(bz_path, [_benzinga_row_with_news()])
        monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", bz_path)

        merged = load_raw_meta_input_composite("AAPL", "15m")
        diag = merged["meta_domain_diagnostics"]
        assert diag["technical"] == "present"
        assert diag["technical_source"] == "tradingview_watchlist_json"
        assert diag["technical_fallback_used"] is True
        assert merged["technical"]["value"]["bias"] == "BEARISH"


# ---------------------------------------------------------------------------
# B3: Enhanced diagnostics
# ---------------------------------------------------------------------------

class TestB3EnhancedDiagnostics:
    def test_diagnostics_include_source_and_fallback_flags(self, monkeypatch, tmp_path: Path) -> None:
        vol_csv = tmp_path / "vol.csv"
        _write_volume_csv(vol_csv)
        monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

        fmp_path = tmp_path / "fmp.json"
        _write_source(fmp_path, [_fmp_row_with_technical()])
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

        bz_path = tmp_path / "bz.json"
        _write_source(bz_path, [_benzinga_row_with_news()])
        monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", bz_path)

        merged = load_raw_meta_input_composite("AAPL", "15m")
        diag = merged["meta_domain_diagnostics"]

        assert "technical_source" in diag
        assert "technical_fallback_used" in diag
        assert "news_source" in diag
        assert "news_fallback_used" in diag
        assert diag["volume"] == "present"

    def test_diagnostics_show_exhausted_when_all_fail(self, monkeypatch, tmp_path: Path) -> None:
        vol_csv = tmp_path / "vol.csv"
        _write_volume_csv(vol_csv)
        monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tmp_path / "missing2.json")
        monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", tmp_path / "missing3.json")

        merged = load_raw_meta_input_composite("AAPL", "15m")
        diag = merged["meta_domain_diagnostics"]
        assert diag["technical"] == "source_file_not_found"
        assert diag["technical_fallback_used"] is False
        assert diag["news"] == "source_file_not_found"
        assert diag["news_fallback_used"] is False


# ---------------------------------------------------------------------------
# B4: No false fallbacks (domain_key_absent triggers next provider)
# ---------------------------------------------------------------------------

class TestB4NoFalseFallbacks:
    def test_domain_key_absent_triggers_fallback(self, monkeypatch, tmp_path: Path) -> None:
        """FMP file exists but has no technical fields → must fall through to TradingView."""
        fmp_path = tmp_path / "fmp.json"
        _write_source(fmp_path, [_fmp_row_without_technical()])
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

        tv_path = tmp_path / "tv.json"
        _write_source(tv_path, [_tv_row_with_technical()])
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

        meta, status, actual = _try_load_meta_domain(
            "technical", "AAPL", "15m", "fmp_watchlist_json", auto_mode=True,
        )
        assert status == "present"
        assert actual == "tradingview_watchlist_json"
        assert meta["technical"]["value"]["bias"] == "BEARISH"

    def test_domain_key_absent_end_to_end(self, monkeypatch, tmp_path: Path) -> None:
        """Full composite loader: FMP present but no technical key → TradingView supplies it."""
        vol_csv = tmp_path / "vol.csv"
        _write_volume_csv(vol_csv)
        monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

        fmp_path = tmp_path / "fmp.json"
        _write_source(fmp_path, [_fmp_row_without_technical()])
        monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

        tv_path = tmp_path / "tv.json"
        _write_source(tv_path, [_tv_row_with_technical()])
        monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

        bz_path = tmp_path / "bz.json"
        _write_source(bz_path, [_benzinga_row_with_news()])
        monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", bz_path)

        merged = load_raw_meta_input_composite("AAPL", "15m")
        diag = merged["meta_domain_diagnostics"]

        assert diag["technical"] == "present"
        assert diag["technical_source"] == "tradingview_watchlist_json"
        assert diag["technical_fallback_used"] is True
        assert merged["technical"]["value"]["strength"] == 0.72
