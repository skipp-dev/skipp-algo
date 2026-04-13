from __future__ import annotations

import json
from pathlib import Path

from smc_integration.sources import benzinga_watchlist_json, databento_watchlist_csv, fmp_watchlist_json, tradingview_watchlist_json


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"symbols": rows}, indent=2), encoding="utf-8")


def _write_watchlist_csv(path: Path, rows: list[dict[str, object]]) -> None:
    header = ["symbol", "trade_date", "watchlist_rank", "premarket_volume", "premarket_trade_count"]
    extra_fields = sorted(
        {
            str(key)
            for row in rows
            for key in row.keys()
            if str(key) not in header
        }
    )
    header.extend(extra_fields)
    lines = [",".join(header)]
    for row in rows:
        lines.append(
            ",".join(str(row.get(column, "")) for column in header)
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
            {
                "symbol": "AAPL",
                "trade_date": "2026-03-01",
                "asof_ts": 1709254000.0,
                "volume_regime": "NORMAL",
                "thin_fraction": 0.1,
                "technical_strength": 0.81,
                "technical_bias": "BULLISH",
            },
            {"symbol": "MSFT", "trade_date": "2026-03-01", "asof_ts": 1709254001.0, "volume_regime": "LOW_VOLUME", "thin_fraction": 0.2},
        ],
    )
    monkeypatch.setattr(tradingview_watchlist_json, "TRADINGVIEW_WATCHLIST_JSON", source_path)

    structure = tradingview_watchlist_json.load_raw_structure_input("AAPL", "15m")
    meta = tradingview_watchlist_json.load_raw_meta_input("AAPL", "15m")

    assert structure == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    _assert_common_payload(meta, "AAPL", "15m")
    assert meta["technical"]["value"]["bias"] == "BULLISH"
    assert float(meta["technical"]["value"]["strength"]) == 0.81


def test_databento_source_derives_low_volume_from_same_day_liquidity(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "premarket_volume": 2500, "premarket_trade_count": 30},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "premarket_volume": 5000, "premarket_trade_count": 50},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3, "premarket_volume": 5000, "premarket_trade_count": 50},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    _assert_common_payload(meta, "AAPL", "15m")
    assert meta["volume"]["value"]["regime"] == "LOW_VOLUME"
    assert meta["volume"]["value"]["thin_fraction"] == 0.5


def test_databento_source_derives_holiday_suspect_from_same_day_liquidity(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "premarket_volume": 1000, "premarket_trade_count": 10},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "premarket_volume": 5000, "premarket_trade_count": 50},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3, "premarket_volume": 5000, "premarket_trade_count": 50},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    _assert_common_payload(meta, "AAPL", "15m")
    assert meta["volume"]["value"]["regime"] == "HOLIDAY_SUSPECT"
    assert meta["volume"]["value"]["thin_fraction"] == 0.8


def test_databento_source_surfaces_unknown_without_liquidity_evidence(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    assert meta["symbol"] == "AAPL"
    assert meta["timeframe"] == "15m"
    assert meta["volume"]["value"]["regime"] == "UNKNOWN"
    assert meta["volume"]["value"]["thin_fraction"] is None
    assert "smc_integration:volume_regime_unknown_no_premarket_liquidity" in meta["provenance"]


def test_databento_source_prefers_rvol_when_available(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {
                "symbol": "AAPL",
                "trade_date": "2026-03-01",
                "watchlist_rank": 1,
                "premarket_volume": 1000,
                "premarket_trade_count": 10,
                "day_volume_rvol_20d": 1.6,
            },
            {
                "symbol": "MSFT",
                "trade_date": "2026-03-01",
                "watchlist_rank": 2,
                "premarket_volume": 5000,
                "premarket_trade_count": 50,
                "day_volume_rvol_20d": 0.4,
            },
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    _assert_common_payload(meta, "AAPL", "15m")
    assert meta["volume"]["value"]["regime"] == "NORMAL"
    assert meta["volume"]["value"]["rvol"] == 1.6
    assert "smc_integration:volume_regime_derived_from_rvol" in meta["provenance"]
    assert "smc_integration:volume_regime_rvol_field=day_volume_rvol_20d" in meta["provenance"]


def test_fmp_source_loads_meta_and_structure(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "fmp_watchlist_snapshot.json"
    _write_rows(
        source_path,
        [
            {
                "symbol": "NVDA",
                "trade_date": "2026-03-02",
                "asof_ts": 1709255000.0,
                "volume_regime": "HOLIDAY_SUSPECT",
                "thin_fraction": 0.05,
                "technical": {
                    "strength": 0.4,
                    "bias": "NEUTRAL",
                    "stale": True,
                },
            },
        ],
    )
    monkeypatch.setattr(fmp_watchlist_json, "FMP_WATCHLIST_JSON", source_path)

    structure = fmp_watchlist_json.load_raw_structure_input("NVDA", "1h")
    meta = fmp_watchlist_json.load_raw_meta_input("NVDA", "1h")

    assert structure == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    _assert_common_payload(meta, "NVDA", "1h")
    assert meta["technical"]["value"]["bias"] == "NEUTRAL"
    assert bool(meta["technical"]["stale"]) is True


def test_benzinga_source_loads_meta_and_structure(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "benzinga_watchlist_snapshot.json"
    _write_rows(
        source_path,
        [
            {
                "symbol": "TSLA",
                "trade_date": "2026-03-03",
                "asof_ts": 1709256000.0,
                "volume_regime": "NORMAL",
                "thin_fraction": 0.0,
                "news_strength": 0.55,
                "news_bias": "BEARISH",
            },
        ],
    )
    monkeypatch.setattr(benzinga_watchlist_json, "BENZINGA_WATCHLIST_JSON", source_path)

    structure = benzinga_watchlist_json.load_raw_structure_input("TSLA", "4h")
    meta = benzinga_watchlist_json.load_raw_meta_input("TSLA", "4h")

    assert structure == {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}
    _assert_common_payload(meta, "TSLA", "4h")
    assert meta["news"]["value"]["bias"] == "BEARISH"
    assert float(meta["news"]["value"]["strength"]) == 0.55
