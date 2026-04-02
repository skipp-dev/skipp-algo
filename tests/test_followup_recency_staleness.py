"""Follow-up PR – Recency/staleness hardening for meta-domain fallback results.

Tests:
  1. Primary provider delivers fresh technical → not stale
  2. Fallback provider delivers fresh technical → not stale, fallback_used=True
  3. Fallback provider delivers stale technical → stale=True
  4. News domain: fresh vs stale
  5. Missing asof_ts → stale=True
  6. New recency fields are consistent with existing diagnostics
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from smc_integration.repo_sources import (
    _META_DOMAIN_STALE_HOURS,
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
    path.write_text(
        f"symbol,trade_date,watchlist_rank\n{symbol},2026-03-01,1\n",
        encoding="utf-8",
    )


def _fresh_ts() -> float:
    """Epoch timestamp that is clearly within the staleness window."""
    return time.time() - 3600.0  # 1 hour ago


def _stale_ts() -> float:
    """Epoch timestamp that is clearly outside the staleness window."""
    return time.time() - (_META_DOMAIN_STALE_HOURS + 24) * 3600.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_volume(monkeypatch, tmp_path: Path) -> None:
    vol_csv = tmp_path / "vol.csv"
    _write_volume_csv(vol_csv)
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)


def _setup_news(monkeypatch, tmp_path: Path, *, asof_ts: float) -> None:
    bz_path = tmp_path / "bz.json"
    _write_source(bz_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": asof_ts,
        "volume_regime": "NORMAL",
        "thin_fraction": 0.0,
        "news_strength": 0.55,
        "news_bias": "BEARISH",
    }])
    monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", bz_path)


# ---------------------------------------------------------------------------
# 1. Primary provider delivers fresh technical → not stale
# ---------------------------------------------------------------------------

def test_primary_fresh_technical_not_stale(monkeypatch, tmp_path: Path) -> None:
    _setup_volume(monkeypatch, tmp_path)

    fmp_path = tmp_path / "fmp.json"
    _write_source(fmp_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.81,
        "technical_bias": "BULLISH",
    }])
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["technical_stale"] is False
    assert diag["technical_asof_ts"] is not None
    assert isinstance(diag["technical_age_hours"], float)
    assert diag["technical_age_hours"] < _META_DOMAIN_STALE_HOURS
    assert diag["technical_fallback_used"] is False


# ---------------------------------------------------------------------------
# 2. Fallback provider delivers fresh technical → not stale, fallback used
# ---------------------------------------------------------------------------

def test_fallback_fresh_technical_not_stale(monkeypatch, tmp_path: Path) -> None:
    _setup_volume(monkeypatch, tmp_path)

    # FMP missing → fallback to TradingView
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")

    tv_path = tmp_path / "tv.json"
    _write_source(tv_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.05,
        "technical_strength": 0.72,
        "technical_bias": "BEARISH",
    }])
    monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["technical_stale"] is False
    assert diag["technical_fallback_used"] is True
    assert diag["technical_source"] == "tradingview_watchlist_json"


# ---------------------------------------------------------------------------
# 3. Fallback provider delivers stale technical → stale=True
# ---------------------------------------------------------------------------

def test_fallback_stale_technical_flagged(monkeypatch, tmp_path: Path) -> None:
    _setup_volume(monkeypatch, tmp_path)

    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")

    tv_path = tmp_path / "tv.json"
    _write_source(tv_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": _stale_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.05,
        "technical_strength": 0.72,
        "technical_bias": "BEARISH",
    }])
    monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tv_path)

    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["technical_stale"] is True
    assert diag["technical_fallback_used"] is True
    assert diag["technical_age_hours"] > _META_DOMAIN_STALE_HOURS


# ---------------------------------------------------------------------------
# 4. News domain: fresh vs stale
# ---------------------------------------------------------------------------

def test_news_fresh_not_stale(monkeypatch, tmp_path: Path) -> None:
    _setup_volume(monkeypatch, tmp_path)

    fmp_path = tmp_path / "fmp.json"
    _write_source(fmp_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.81,
        "technical_bias": "BULLISH",
    }])
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["news_stale"] is False
    assert diag["news_asof_ts"] is not None
    assert diag["news_age_hours"] < _META_DOMAIN_STALE_HOURS


def test_news_stale_flagged(monkeypatch, tmp_path: Path) -> None:
    _setup_volume(monkeypatch, tmp_path)

    fmp_path = tmp_path / "fmp.json"
    _write_source(fmp_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.81,
        "technical_bias": "BULLISH",
    }])
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

    _setup_news(monkeypatch, tmp_path, asof_ts=_stale_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["news_stale"] is True
    assert diag["news_age_hours"] > _META_DOMAIN_STALE_HOURS


# ---------------------------------------------------------------------------
# 5. Missing domain → stale=True, asof_ts=None
# ---------------------------------------------------------------------------

def test_missing_domain_marked_stale(monkeypatch, tmp_path: Path) -> None:
    _setup_volume(monkeypatch, tmp_path)

    # Both technical providers missing
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", tmp_path / "missing2.json")
    # News also missing
    monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", tmp_path / "missing3.json")

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["technical_asof_ts"] is None
    assert diag["technical_age_hours"] is None
    assert diag["technical_stale"] is True

    assert diag["news_asof_ts"] is None
    assert diag["news_age_hours"] is None
    assert diag["news_stale"] is True


# ---------------------------------------------------------------------------
# 6. New fields are consistent with existing diagnostics
# ---------------------------------------------------------------------------

def test_diagnostics_consistency(monkeypatch, tmp_path: Path) -> None:
    """All existing Paket B fields plus new recency fields are present."""
    _setup_volume(monkeypatch, tmp_path)

    fmp_path = tmp_path / "fmp.json"
    _write_source(fmp_path, [{
        "symbol": "AAPL",
        "trade_date": "2026-03-01",
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.81,
        "technical_bias": "BULLISH",
    }])
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)

    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    # Existing Paket B fields
    assert "volume" in diag
    assert "technical" in diag
    assert "technical_source" in diag
    assert "technical_fallback_used" in diag
    assert "news" in diag
    assert "news_source" in diag
    assert "news_fallback_used" in diag

    # New recency fields
    assert "technical_asof_ts" in diag
    assert "technical_age_hours" in diag
    assert "technical_stale" in diag
    assert "news_asof_ts" in diag
    assert "news_age_hours" in diag
    assert "news_stale" in diag

    # Volume recency fields (symmetric)
    assert "volume_source" in diag
    assert "volume_fallback_used" in diag
    assert "volume_asof_ts" in diag
    assert "volume_age_hours" in diag
    assert "volume_stale" in diag


# ---------------------------------------------------------------------------
# 7. Volume diagnostics – fresh / stale / missing asof_ts
# ---------------------------------------------------------------------------

def test_volume_fresh_not_stale(monkeypatch, tmp_path: Path) -> None:
    """A recent volume CSV → volume_stale=False."""
    vol_csv = tmp_path / "vol.csv"
    fresh_trade_date = time.strftime("%Y-%m-%d", time.gmtime(_fresh_ts()))
    # trade_date is recent → asof_ts will be fresh
    vol_csv.write_text(
        f"symbol,trade_date,watchlist_rank\nAAPL,{fresh_trade_date},1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

    fmp_path = tmp_path / "fmp.json"
    _write_source(fmp_path, [{
        "symbol": "AAPL",
        "trade_date": fresh_trade_date,
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.8,
        "technical_bias": "BULLISH",
    }])
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)
    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["volume_stale"] is False
    assert diag["volume_asof_ts"] is not None
    assert isinstance(diag["volume_age_hours"], float)
    assert diag["volume_source"] is not None
    assert diag["volume_fallback_used"] is False


def test_volume_stale_flagged(monkeypatch, tmp_path: Path) -> None:
    """An old volume CSV → volume_stale=True."""
    vol_csv = tmp_path / "vol.csv"
    vol_csv.write_text(
        "symbol,trade_date,watchlist_rank\nAAPL,2025-01-01,1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", vol_csv)

    fmp_path = tmp_path / "fmp.json"
    _write_source(fmp_path, [{
        "symbol": "AAPL",
        "trade_date": "2025-01-01",
        "asof_ts": _fresh_ts(),
        "volume_regime": "NORMAL",
        "thin_fraction": 0.1,
        "technical_strength": 0.8,
        "technical_bias": "BULLISH",
    }])
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", fmp_path)
    _setup_news(monkeypatch, tmp_path, asof_ts=_fresh_ts())

    merged = load_raw_meta_input_composite("AAPL", "15m")
    diag = merged["meta_domain_diagnostics"]

    assert diag["volume_stale"] is True
    assert diag["volume_age_hours"] > _META_DOMAIN_STALE_HOURS
    assert diag["volume_fallback_used"] is False

    # Consistency: if domain present and not stale, age must be below threshold
    if diag["technical"] == "present" and not diag["technical_stale"]:
        assert diag["technical_age_hours"] < _META_DOMAIN_STALE_HOURS
    if diag["news"] == "present" and not diag["news_stale"]:
        assert diag["news_age_hours"] < _META_DOMAIN_STALE_HOURS
