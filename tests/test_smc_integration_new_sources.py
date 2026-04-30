from __future__ import annotations

import json
from pathlib import Path

from smc_adapters import build_meta_from_raw, build_volume_provenance_from_raw
from smc_integration.sources import (
    benzinga_watchlist_json,
    databento_watchlist_csv,
    fmp_watchlist_json,
    tradingview_watchlist_json,
)


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"symbols": rows}, indent=2), encoding="utf-8")


def _write_watchlist_csv(path: Path, rows: list[dict[str, object]]) -> None:
    header = ["symbol", "trade_date", "watchlist_rank", "premarket_volume", "premarket_trade_count"]
    extra_fields = sorted(
        {
            str(key)
            for row in rows
            for key in row
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


def _assert_databento_volume_contract(value: dict, *, model_source: str, selected_baseline: str) -> None:
    assert value["contract_version"] == "1"
    assert value["baseline_priority_order"] == [
        "rvol",
        "explicit_average_volume",
        "peer_median_same_trade_date",
        "premarket_liquidity",
    ]
    assert value["model_source"] == model_source
    assert value["selected_baseline"] == selected_baseline
    assert value["peer_median_rollout"] == "always_on"


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
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="premarket_liquidity_peer_median",
        selected_baseline="premarket_liquidity",
    )


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
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="premarket_liquidity_peer_median",
        selected_baseline="premarket_liquidity",
    )


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
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="missing_baseline",
        selected_baseline="none",
    )
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
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="explicit_rvol",
        selected_baseline="rvol",
    )
    assert "smc_integration:volume_regime_derived_from_rvol" in meta["provenance"]
    assert "smc_integration:volume_regime_rvol_field=day_volume_rvol_20d" in meta["provenance"]


def test_databento_source_uses_daily_bar_rvol_from_explicit_average_volume(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {
                "symbol": "AAPL",
                "trade_date": "2026-03-01",
                "watchlist_rank": 1,
                "current_volume": 2400000,
                "avg_daily_volume": 1600000,
            },
            {
                "symbol": "MSFT",
                "trade_date": "2026-03-01",
                "watchlist_rank": 2,
                "current_volume": 1200000,
                "avg_daily_volume": 1500000,
            },
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    _assert_common_payload(meta, "AAPL", "15m")
    assert meta["volume"]["value"]["source"] == "daily_bar_rvol"
    assert meta["volume"]["value"]["rvol"] == 1.5
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="daily_bar_rvol_explicit_average",
        selected_baseline="explicit_average_volume",
    )
    assert "smc_integration:volume_regime_derived_from_daily_bar_rvol" in meta["provenance"]
    assert "smc_integration:volume_regime_daily_volume_field=current_volume" in meta["provenance"]
    assert "smc_integration:volume_regime_daily_volume_baseline=avg_daily_volume" in meta["provenance"]


def test_databento_source_uses_daily_bar_rvol_from_peer_median(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "day_volume": 900000},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "day_volume": 1200000},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3, "day_volume": 1500000},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    _assert_common_payload(meta, "AAPL", "15m")
    assert meta["volume"]["value"]["source"] == "daily_bar_rvol"
    assert meta["volume"]["value"]["rvol"] == 0.6667
    assert meta["volume"]["value"]["peer_count"] == 2
    assert meta["volume"]["value"]["peer_scope"] == "same_trade_date_excluding_symbol"
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="daily_bar_rvol_peer_median",
        selected_baseline="peer_median_same_trade_date",
    )
    assert "smc_integration:volume_regime_daily_volume_baseline=peer_median:day_volume" in meta["provenance"]


def test_databento_source_handles_zero_peer_median_without_division(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "day_volume": 900000},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "day_volume": 0},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3, "day_volume": 0},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    assert meta["volume"]["value"]["regime"] == "UNKNOWN"
    assert meta["volume"]["value"]["thin_fraction"] is None
    _assert_databento_volume_contract(
        meta["volume"]["value"],
        model_source="missing_baseline",
        selected_baseline="none",
    )


def test_databento_source_handles_sparse_peers_deterministically(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "day_volume": 900000},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "day_volume": 1200000},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")

    assert meta["volume"]["value"]["source"] == "daily_bar_rvol"
    assert meta["volume"]["value"]["rvol"] == 0.75
    assert meta["volume"]["value"]["peer_count"] == 1
    assert meta["volume"]["value"]["peer_scope"] == "same_trade_date_excluding_symbol"


def test_databento_volume_meta_exposes_contractually_supported_traceability_fields(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "day_volume": 900000},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "day_volume": 1200000},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3, "day_volume": 1500000},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")
    volume_value = meta["volume"]["value"]

    assert volume_value["contract_version"] == "1"
    assert volume_value["model_source"] == "daily_bar_rvol_peer_median"
    assert volume_value["selected_baseline"] == "peer_median_same_trade_date"
    assert volume_value["peer_median_rollout"] == "always_on"
    assert volume_value["peer_scope"] == "same_trade_date_excluding_symbol"
    assert "smc_integration:volume_regime_contract_version=1" in meta["provenance"]
    assert "smc_integration:volume_regime_model_source=daily_bar_rvol_peer_median" in meta["provenance"]
    assert "smc_integration:volume_regime_selected_baseline=peer_median_same_trade_date" in meta["provenance"]


def test_databento_volume_contract_survives_adapter_ingest(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "databento_watchlist.csv"
    _write_watchlist_csv(
        source_path,
        [
            {"symbol": "AAPL", "trade_date": "2026-03-01", "watchlist_rank": 1, "day_volume": 900000},
            {"symbol": "MSFT", "trade_date": "2026-03-01", "watchlist_rank": 2, "day_volume": 1200000},
            {"symbol": "NVDA", "trade_date": "2026-03-01", "watchlist_rank": 3, "day_volume": 1500000},
        ],
    )
    monkeypatch.setattr(databento_watchlist_csv, "WATCHLIST_CSV", source_path)

    raw_meta = databento_watchlist_csv.load_raw_meta_input("AAPL", "15m")
    meta = build_meta_from_raw(raw_meta)
    volume_provenance = build_volume_provenance_from_raw(raw_meta)

    assert not hasattr(meta.volume.value, "contract_version")
    assert volume_provenance["contract_version"] == "1"
    assert volume_provenance["baseline_priority_order"] == [
        "rvol",
        "explicit_average_volume",
        "peer_median_same_trade_date",
        "premarket_liquidity",
    ]
    assert volume_provenance["model_source"] == "daily_bar_rvol_peer_median"
    assert volume_provenance["selected_baseline"] == "peer_median_same_trade_date"
    assert volume_provenance["peer_median_rollout"] == "always_on"
    assert volume_provenance["peer_scope"] == "same_trade_date_excluding_symbol"
    assert volume_provenance["peer_count"] == 2
    assert "smc_integration:volume_regime_contract_version=1" in meta.provenance
    assert (
        "smc_integration:volume_regime_baseline_priority_order="
        "rvol,explicit_average_volume,peer_median_same_trade_date,premarket_liquidity"
    ) in meta.provenance


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
