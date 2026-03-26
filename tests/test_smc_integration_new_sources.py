from __future__ import annotations

import json
from pathlib import Path

from smc_integration.sources import benzinga_watchlist_json, fmp_watchlist_json, tradingview_watchlist_json


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"symbols": rows}, indent=2), encoding="utf-8")


def _assert_common_payload(payload: dict, symbol: str, timeframe: str) -> None:
    assert payload["symbol"] == symbol
    assert payload["timeframe"] == timeframe
    assert isinstance(payload["asof_ts"], float)
    assert payload["volume"]["value"]["regime"] in {"NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"}
    assert isinstance(payload["provenance"], list)


def test_tradingview_source_loads_meta_and_structure(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "tradingview_watchlist_snapshot.json"
    _write_rows(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "asof_ts": 1709254000.0, "volume_regime": "NORMAL", "thin_fraction": 0.1},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "asof_ts": 1709254001.0, "volume_regime": "LOW_VOLUME", "thin_fraction": 0.2},
        ],
    )
    monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", source_path)

    structure = tradingview_watchlist_json.load_raw_structure_input("AAPL", "15m")
    meta = tradingview_watchlist_json.load_raw_meta_input("AAPL", "15m")

    assert structure == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    _assert_common_payload(meta, "AAPL", "15m")


def test_fmp_source_loads_meta_and_structure(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "fmp_watchlist_snapshot.json"
    _write_rows(
        source_path,
        [
            {"symbol": "NVDA", "trade_date": "2026-03-02", "asof_ts": 1709255000.0, "volume_regime": "HOLIDAY_SUSPECT", "thin_fraction": 0.05},
        ],
    )
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", source_path)

    structure = fmp_watchlist_json.load_raw_structure_input("NVDA", "1h")
    meta = fmp_watchlist_json.load_raw_meta_input("NVDA", "1h")

    assert structure == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    _assert_common_payload(meta, "NVDA", "1h")


def test_benzinga_source_loads_meta_and_structure(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "benzinga_watchlist_snapshot.json"
    _write_rows(
        source_path,
        [
            {"symbol": "TSLA", "trade_date": "2026-03-03", "asof_ts": 1709256000.0, "volume_regime": "NORMAL", "thin_fraction": 0.0},
        ],
    )
    monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", source_path)

    structure = benzinga_watchlist_json.load_raw_structure_input("TSLA", "4h")
    meta = benzinga_watchlist_json.load_raw_meta_input("TSLA", "4h")

    assert structure == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    _assert_common_payload(meta, "TSLA", "4h")
