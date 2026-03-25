from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import scripts.smc_microstructure_base_runtime as runtime
from scripts.smc_microstructure_base_runtime import (
    _consistency_score,
    _setup_decay_half_life_30m_buckets,
    build_base_snapshot_from_bundle_payload,
    build_symbol_day_microstructure_feature_frame,
    collect_full_universe_session_minute_detail,
    infer_asset_type,
    write_base_manifest,
)


SCHEMA_PATH = Path("schema/schema.json")


def _make_bundle_payload(tmp_path: Path) -> tuple[dict[str, object], pd.DataFrame]:
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "exchange": "NASDAQ",
                "company_name": "Alpha Holdings",
                "asset_type": "stock",
                "market_cap": 3_200_000_000,
                "day_open": 10.0,
                "day_high": 10.8,
                "day_low": 9.7,
                "day_close": 10.5,
                "day_volume": 1_500_000,
                "previous_close": 9.8,
                "close_trade_hygiene_score": 0.82,
                "reclaimed_start_price_within_30s": True,
                "early_dip_pct_10s": -0.8,
                "open_to_current_pct": 1.6,
                "window_return_pct": 1.6,
                "close_preclose_return_pct": 0.4,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "exchange": "NASDAQ",
                "company_name": "Alpha Holdings",
                "asset_type": "stock",
                "market_cap": 3_200_000_000,
                "day_open": 10.7,
                "day_high": 11.2,
                "day_low": 10.1,
                "day_close": 10.4,
                "day_volume": 1_900_000,
                "previous_close": 10.5,
                "close_trade_hygiene_score": 0.76,
                "reclaimed_start_price_within_30s": False,
                "early_dip_pct_10s": -1.0,
                "open_to_current_pct": -0.5,
                "window_return_pct": -0.5,
                "close_preclose_return_pct": -0.3,
            },
        ]
    )
    session_minute_detail = pd.DataFrame(
        [
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": "2026-03-19T08:00:00Z", "session": "premarket", "open": 9.9, "high": 10.0, "low": 9.8, "close": 9.95, "volume": 20_000, "trade_count": 40},
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": "2026-03-19T13:30:00Z", "session": "regular", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 50_000, "trade_count": 75},
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": "2026-03-19T13:45:00Z", "session": "regular", "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.3, "volume": 70_000, "trade_count": 85},
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": "2026-03-19T16:15:00Z", "session": "regular", "open": 10.2, "high": 10.5, "low": 10.1, "close": 10.4, "volume": 45_000, "trade_count": 65},
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": "2026-03-19T19:45:00Z", "session": "regular", "open": 10.45, "high": 10.6, "low": 10.35, "close": 10.5, "volume": 55_000, "trade_count": 80},
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": "2026-03-19T21:10:00Z", "session": "afterhours", "open": 10.5, "high": 10.55, "low": 10.45, "close": 10.48, "volume": 18_000, "trade_count": 20},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": "2026-03-20T08:15:00Z", "session": "premarket", "open": 10.55, "high": 10.6, "low": 10.45, "close": 10.5, "volume": 22_000, "trade_count": 35},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": "2026-03-20T13:30:00Z", "session": "regular", "open": 10.7, "high": 10.8, "low": 10.5, "close": 10.6, "volume": 80_000, "trade_count": 95},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": "2026-03-20T13:50:00Z", "session": "regular", "open": 10.6, "high": 10.9, "low": 10.4, "close": 10.5, "volume": 85_000, "trade_count": 100},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": "2026-03-20T16:20:00Z", "session": "regular", "open": 10.45, "high": 10.55, "low": 10.3, "close": 10.4, "volume": 40_000, "trade_count": 55},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": "2026-03-20T19:50:00Z", "session": "regular", "open": 10.42, "high": 10.48, "low": 10.25, "close": 10.35, "volume": 60_000, "trade_count": 90},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": "2026-03-20T21:25:00Z", "session": "afterhours", "open": 10.35, "high": 10.4, "low": 10.2, "close": 10.28, "volume": 21_000, "trade_count": 22},
        ]
    )
    session_minute_detail["timestamp"] = pd.to_datetime(session_minute_detail["timestamp"], utc=True)
    bundle_payload: dict[str, object] = {
        "manifest_path": tmp_path / "fake_manifest.json",
        "bundle_dir": tmp_path,
        "base_prefix": "databento_volatility_production_fake",
        "manifest": {"trade_dates_covered": ["2026-03-19", "2026-03-20"]},
        "frames": {
            "daily_bars": daily_features[
                ["trade_date", "symbol", "day_open", "day_high", "day_low", "day_close", "day_volume", "previous_close"]
            ].rename(
                columns={
                    "day_open": "open",
                    "day_high": "high",
                    "day_low": "low",
                    "day_close": "close",
                    "day_volume": "volume",
                }
            ),
            "daily_symbol_features_full_universe": daily_features,
        },
    }
    return bundle_payload, session_minute_detail


def test_setup_decay_half_life_30m_buckets_returns_zero_for_empty_frame() -> None:
    frame = pd.DataFrame(columns=["minutes_from_open", "dollar_volume"])

    assert _setup_decay_half_life_30m_buckets(frame) == 0.0


def test_setup_decay_half_life_30m_buckets_returns_zero_when_first_bucket_zero() -> None:
    frame = pd.DataFrame(
        [
            {"minutes_from_open": 0, "dollar_volume": 0.0},
            {"minutes_from_open": 30, "dollar_volume": 10.0},
        ]
    )

    assert _setup_decay_half_life_30m_buckets(frame) == 0.0


def test_build_base_snapshot_from_bundle_payload_warns_when_asof_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)

    class FakeDate(date):
        @classmethod
        def today(cls) -> "FakeDate":
            return cls(2026, 3, 27)

    monkeypatch.setattr(runtime, "date", FakeDate)

    with pytest.warns(UserWarning, match=r"Bundle asof_date is 8 days old \(2026-03-19\)"):
        output, payload, _ = build_base_snapshot_from_bundle_payload(
            bundle_payload,
            schema_path=SCHEMA_PATH,
            session_minute_detail=session_minute_detail,
            asof_date="2026-03-19",
        )

    assert payload["asof_date"] == "2026-03-19"
    assert list(output["symbol"]) == ["AAA"]
    assert "only 1 trading days in trailing window" in caplog.text


def test_infer_asset_type_excludes_prefix_only_etf_names() -> None:
    assert infer_asset_type("ETFMG PRIME CYBER", None) == "stock"


def test_infer_asset_type_detects_spelled_out_etf_names() -> None:
    assert infer_asset_type("SPDR S&P 500 ETF TRUST", None) == "etf"


def test_consistency_score_single_row_group_returns_one() -> None:
    group = pd.DataFrame(
        [
            {
                "daily_clean_intraday_score": 0.8,
                "daily_open_30m_dollar_share": 0.3,
                "daily_close_60m_dollar_share": 0.2,
                "daily_midday_efficiency": 0.6,
                "daily_close_hygiene": 0.9,
            }
        ]
    )

    assert _consistency_score(group) == pytest.approx(1.0)


def test_write_base_manifest_persists_core_ready_false(tmp_path: Path) -> None:
    manifest_path = tmp_path / "base_manifest.json"
    write_base_manifest(
        manifest_path,
        bundle_manifest_path=tmp_path / "bundle_manifest.json",
        asof_date="2026-03-20",
        base_csv_path=tmp_path / "base.csv",
        base_xlsx_path=None,
        micro_day_parquet_path=tmp_path / "micro.parquet",
        mapping_md_path=tmp_path / "mapping.md",
        mapping_json_path=tmp_path / "mapping.json",
        library_owner="preuss_steffen",
        library_version=1,
        core_ready=False,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["core_ready"] is False
    assert "base snapshot artifact state" in payload["core_ready_note"]


def test_build_symbol_day_microstructure_feature_frame_marks_null_activity_day_inactive(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundle_payload, _ = _make_bundle_payload(tmp_path)
    daily_features = bundle_payload["frames"]["daily_symbol_features_full_universe"].copy()
    session_minute_detail = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": np.nan,
                "volume": 0.0,
                "trade_count": np.nan,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T13:31:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": np.nan,
                "volume": 0.0,
                "trade_count": np.nan,
            },
        ]
    )

    with caplog.at_level("WARNING"):
        output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    assert output.loc[0, "daily_rth_active_minutes_share"] == pytest.approx(0.0)
    assert output.loc[0, "daily_rth_dollar_volume"] == pytest.approx(0.0)
    assert "marking all minute bars inactive" in caplog.text


def test_collect_full_universe_session_minute_detail_returns_empty_frame_for_empty_universe() -> None:
    output = collect_full_universe_session_minute_detail(
        "dummy-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 3, 20)],
        universe_symbols=set(),
        display_timezone="UTC",
    )

    assert output.empty
    assert list(output.columns) == [
        "trade_date",
        "symbol",
        "timestamp",
        "session",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
    ]