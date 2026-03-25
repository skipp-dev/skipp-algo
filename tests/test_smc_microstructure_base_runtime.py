from __future__ import annotations

import json
import warnings
from typing import Any, cast
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

    with pytest.warns(UserWarning, match=r"Microstructure base asof_date is 8 days old; results may be stale\."):
        output, payload, _ = build_base_snapshot_from_bundle_payload(
            bundle_payload,
            schema_path=SCHEMA_PATH,
            session_minute_detail=session_minute_detail,
            asof_date="2026-03-19",
        )

    assert payload["asof_date"] == "2026-03-19"
    assert list(output["symbol"]) == ["AAA"]
    assert "coverage quality is limited" in caplog.text


def test_build_base_snapshot_from_bundle_payload_warns_when_symbol_coverage_is_thin(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"]).copy()
    daily_features = pd.concat(
        [
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-03-18",
                        "symbol": "AAA",
                        "exchange": "NASDAQ",
                        "company_name": "Alpha Holdings",
                        "asset_type": "stock",
                        "market_cap": 3_200_000_000,
                        "day_open": 9.8,
                        "day_high": 10.1,
                        "day_low": 9.6,
                        "day_close": 9.9,
                        "day_volume": 1_200_000,
                        "previous_close": 9.7,
                        "close_trade_hygiene_score": 0.75,
                        "reclaimed_start_price_within_30s": True,
                        "early_dip_pct_10s": -0.6,
                        "open_to_current_pct": 1.0,
                        "window_return_pct": 1.0,
                        "close_preclose_return_pct": 0.2,
                    }
                ]
            ),
            daily_features,
        ],
        ignore_index=True,
    )
    frames["daily_symbol_features_full_universe"] = daily_features
    frames["daily_bars"] = daily_features[
        ["trade_date", "symbol", "day_open", "day_high", "day_low", "day_close", "day_volume", "previous_close"]
    ].rename(
        columns={
            "day_open": "open",
            "day_high": "high",
            "day_low": "low",
            "day_close": "close",
            "day_volume": "volume",
        }
    )
    session_minute_detail = pd.concat(
        [
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-03-18",
                        "symbol": "AAA",
                        "timestamp": pd.Timestamp("2026-03-18T13:30:00Z"),
                        "session": "regular",
                        "open": 9.8,
                        "high": 9.95,
                        "low": 9.75,
                        "close": 9.9,
                        "volume": 42_000,
                        "trade_count": 60,
                    },
                    {
                        "trade_date": "2026-03-18",
                        "symbol": "AAA",
                        "timestamp": pd.Timestamp("2026-03-18T19:50:00Z"),
                        "session": "regular",
                        "open": 9.92,
                        "high": 10.0,
                        "low": 9.88,
                        "close": 9.94,
                        "volume": 38_000,
                        "trade_count": 55,
                    },
                ]
            ),
            session_minute_detail,
        ],
        ignore_index=True,
    )

    with caplog.at_level("WARNING"):
        output, payload, _ = build_base_snapshot_from_bundle_payload(
            bundle_payload,
            schema_path=SCHEMA_PATH,
            session_minute_detail=session_minute_detail,
            asof_date="2026-03-20",
        )

    assert payload["asof_date"] == "2026-03-20"
    assert output.loc[0, "history_coverage_days_20d"] == 3
    assert "Symbol AAA has only 3 trading days in trailing window" in caplog.text


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
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"]).copy()
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


def test_collect_full_universe_session_minute_detail_excludes_runtime_unsupported_symbols_from_coverage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeStore:
        def to_df(self, count: int = 250_000) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": "AAA",
                        "ts": pd.Timestamp("2026-02-10T13:30:00Z"),
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "volume": 1000,
                        "trade_count": 25,
                    }
                ]
            )

    def fake_get_range(*args: Any, **kwargs: Any) -> FakeStore:
        warnings.warn("The streaming request had one or more symbols which did not resolve: AACB")
        return FakeStore()

    monkeypatch.setattr(runtime, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(runtime, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(runtime, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(runtime, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

    with caplog.at_level("WARNING"):
        output = collect_full_universe_session_minute_detail(
            "dummy-key",
            dataset="DBEQ.BASIC",
            trading_days=[date(2026, 2, 10)],
            universe_symbols={"AAA", "AACB"},
            display_timezone="America/New_York",
            use_file_cache=False,
        )

    assert set(output["symbol"].unique()) == {"AAA"}
    assert "excluded 1 runtime-unsupported symbols from completeness checks" in caplog.text


def test_collect_full_universe_session_minute_detail_uses_day_specific_expected_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStore:
        def to_df(self, count: int = 250_000) -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        "symbol": "AAA",
                        "ts": pd.Timestamp("2026-02-10T13:30:00Z"),
                        "open": 10.0,
                        "high": 10.2,
                        "low": 9.9,
                        "close": 10.1,
                        "volume": 1000,
                        "trade_count": 25,
                    }
                ]
            )

    monkeypatch.setattr(runtime, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(runtime, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(runtime, "_databento_get_range_with_retry", lambda *args, **kwargs: FakeStore())
    monkeypatch.setattr(runtime, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

    output = collect_full_universe_session_minute_detail(
        "dummy-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 2, 10)],
        universe_symbols={"AAA", "BBB"},
        expected_symbols_by_trade_day={date(2026, 2, 10): {"AAA"}},
        display_timezone="America/New_York",
        use_file_cache=False,
    )

    assert set(output["symbol"].unique()) == {"AAA"}


def test_collect_full_universe_session_minute_detail_runtime_unsupported_symbols_do_not_leak_across_trade_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStore:
        def __init__(self, frame: pd.DataFrame) -> None:
            self._frame = frame

        def to_df(self, count: int = 250_000) -> pd.DataFrame:
            return self._frame.copy()

    requested_batches: list[list[str]] = []
    call_count = 0

    def fake_get_range(*args: Any, **kwargs: Any) -> FakeStore:
        nonlocal call_count
        call_count += 1
        symbols = [str(value).upper() for value in kwargs.get("symbols", [])]
        requested_batches.append(symbols)
        if call_count == 1:
            warnings.warn("The streaming request had one or more symbols which did not resolve: AACB")
            return FakeStore(pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume", "trade_count"]))
        return FakeStore(
            pd.DataFrame(
                [
                    {
                        "symbol": "AACB",
                        "ts": pd.Timestamp("2026-02-11T13:30:00Z"),
                        "open": 5.0,
                        "high": 5.1,
                        "low": 4.9,
                        "close": 5.05,
                        "volume": 1500,
                        "trade_count": 12,
                    }
                ]
            )
        )

    monkeypatch.setattr(runtime, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(runtime, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-12T03:00:00Z"))
    monkeypatch.setattr(runtime, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(runtime, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

    output = collect_full_universe_session_minute_detail(
        "dummy-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 2, 10), date(2026, 2, 11)],
        universe_symbols={"AACB"},
        display_timezone="America/New_York",
        use_file_cache=False,
    )

    assert len(requested_batches) == 2
    assert set(requested_batches[0]) == {"AACB"}
    assert set(requested_batches[1]) == {"AACB"}
    assert set(output["symbol"].unique()) == {"AACB"}
    assert set(pd.to_datetime(output["trade_date"]).dt.date.unique()) == {date(2026, 2, 11)}


def test_run_databento_base_scan_pipeline_does_not_skip_symbol_days_just_because_has_intraday_is_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-02-10",
                "symbol": "AAA",
                "has_intraday": False,
            }
        ]
    )

    monkeypatch.setattr(
        runtime,
        "run_production_export_pipeline",
        lambda **kwargs: {"exported_paths": {"manifest": str(tmp_path / "fake_manifest.json")}},
    )
    monkeypatch.setattr(
        runtime,
        "load_export_bundle",
        lambda *args, **kwargs: {
            "manifest": {"trade_dates_covered": ["2026-02-10"]},
            "frames": {
                "daily_symbol_features_full_universe": daily_features,
                "daily_bars": pd.DataFrame(),
            },
            "base_prefix": "databento_volatility_production_fake",
        },
    )

    def fake_collect(*args: Any, **kwargs: Any) -> pd.DataFrame:
        captured["expected_symbols_by_trade_day"] = kwargs.get("expected_symbols_by_trade_day")
        return pd.DataFrame()

    monkeypatch.setattr(runtime, "collect_full_universe_session_minute_detail", fake_collect)
    monkeypatch.setattr(
        runtime,
        "generate_base_from_bundle",
        lambda *args, **kwargs: {"warnings": [], "output_paths": {}, "base_snapshot": pd.DataFrame(), "symbol_day_features": pd.DataFrame()},
    )

    runtime.run_databento_base_scan_pipeline(
        databento_api_key="dummy-db",
        fmp_api_key="",
        dataset="DBEQ.BASIC",
        export_dir=tmp_path,
        schema_path=SCHEMA_PATH,
        lookback_days=2,
        display_timezone="America/New_York",
    )

    expected = cast(dict[date, set[str]], captured["expected_symbols_by_trade_day"])
    assert expected == {date(2026, 2, 10): {"AAA"}}


def test_run_databento_base_scan_pipeline_handles_missing_has_intraday_column_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-02-10",
                "symbol": "AAA",
            },
            {
                "trade_date": "2026-02-10",
                "symbol": "BBB",
            },
        ]
    )

    monkeypatch.setattr(
        runtime,
        "run_production_export_pipeline",
        lambda **kwargs: {"exported_paths": {"manifest": str(tmp_path / "fake_manifest.json")}},
    )
    monkeypatch.setattr(
        runtime,
        "load_export_bundle",
        lambda *args, **kwargs: {
            "manifest": {"trade_dates_covered": ["2026-02-10"]},
            "frames": {
                "daily_symbol_features_full_universe": daily_features,
                "daily_bars": pd.DataFrame(),
            },
            "base_prefix": "databento_volatility_production_fake",
        },
    )

    def fake_collect(*args: Any, **kwargs: Any) -> pd.DataFrame:
        captured["expected_symbols_by_trade_day"] = kwargs.get("expected_symbols_by_trade_day")
        return pd.DataFrame()

    monkeypatch.setattr(runtime, "collect_full_universe_session_minute_detail", fake_collect)
    monkeypatch.setattr(
        runtime,
        "generate_base_from_bundle",
        lambda *args, **kwargs: {"warnings": [], "output_paths": {}, "base_snapshot": pd.DataFrame(), "symbol_day_features": pd.DataFrame()},
    )

    runtime.run_databento_base_scan_pipeline(
        databento_api_key="dummy-db",
        fmp_api_key="",
        dataset="DBEQ.BASIC",
        export_dir=tmp_path,
        schema_path=SCHEMA_PATH,
        lookback_days=2,
        display_timezone="America/New_York",
    )

    expected = cast(dict[date, set[str]], captured["expected_symbols_by_trade_day"])
    assert expected == {date(2026, 2, 10): {"AAA", "BBB"}}


def test_build_symbol_day_microstructure_feature_frame_warns_when_minute_detail_is_missing_for_symbol_day(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"]).copy()
    daily_features = pd.concat(
        [
            daily_features,
            pd.DataFrame(
                [
                    {
                        "trade_date": "2026-03-20",
                        "symbol": "BBB",
                        "exchange": "NASDAQ",
                        "company_name": "Beta Holdings",
                        "asset_type": "stock",
                        "market_cap": 2_100_000_000,
                        "day_open": 8.0,
                        "day_high": 8.3,
                        "day_low": 7.8,
                        "day_close": 8.1,
                        "day_volume": 900_000,
                        "previous_close": 7.9,
                        "close_trade_hygiene_score": 0.70,
                        "reclaimed_start_price_within_30s": False,
                        "early_dip_pct_10s": -0.5,
                        "open_to_current_pct": 0.1,
                        "window_return_pct": 0.1,
                        "close_preclose_return_pct": -0.1,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    with caplog.at_level("WARNING"):
        output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    trade_dates = pd.to_datetime(output["trade_date"], errors="coerce").dt.date
    bbb_row = output.loc[(trade_dates == date(2026, 3, 20)) & (output["symbol"] == "BBB")].iloc[0]
    assert bbb_row["daily_rth_dollar_volume"] == pytest.approx(0.0)
    assert "Session minute detail missing for" in caplog.text
    assert "BBB" in caplog.text


def test_build_symbol_day_microstructure_feature_frame_warns_when_regular_session_detail_is_missing_but_other_sessions_exist(
    caplog: pytest.LogCaptureFixture,
) -> None:
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-20",
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
            }
        ]
    )
    session_minute_detail = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T08:15:00Z"),
                "session": "premarket",
                "open": 10.0,
                "high": 10.1,
                "low": 9.95,
                "close": 10.05,
                "volume": 12000,
                "trade_count": 15,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T21:10:00Z"),
                "session": "afterhours",
                "open": 10.04,
                "high": 10.06,
                "low": 10.0,
                "close": 10.02,
                "volume": 8000,
                "trade_count": 10,
            },
        ]
    )

    with caplog.at_level("WARNING"):
        output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    row = output.iloc[0]
    assert bool(row["missing_regular_session_detail"]) is True
    assert bool(row["missing_premarket_detail"]) is False
    assert bool(row["missing_afterhours_detail"]) is False
    assert "no regular-session bars" in caplog.text


def test_build_symbol_day_microstructure_feature_frame_falls_back_to_window_return_when_open_to_current_missing() -> None:
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-20",
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
                "window_return_pct": 1.6,
                "close_preclose_return_pct": 0.4,
            }
        ]
    )
    session_minute_detail = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 50_000,
                "trade_count": 75,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T19:45:00Z"),
                "session": "regular",
                "open": 10.45,
                "high": 10.6,
                "low": 10.35,
                "close": 10.5,
                "volume": 55_000,
                "trade_count": 80,
            },
        ]
    )

    output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    row = output.iloc[0]
    assert row["daily_reclaim_respect_flag"] == 1
    assert row["daily_reclaim_failure_flag"] == 0
    assert row["daily_reclaim_followthrough_r"] == pytest.approx(2.0)


def test_build_base_snapshot_from_bundle_payload_excludes_missing_minute_detail_rows_from_minute_derived_20d_means(
    tmp_path: Path,
) -> None:
    bundle_payload, _ = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
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
    frames["daily_symbol_features_full_universe"] = daily_features
    frames["daily_bars"] = daily_features[
        ["trade_date", "symbol", "day_open", "day_high", "day_low", "day_close", "day_volume", "previous_close"]
    ].rename(
        columns={
            "day_open": "open",
            "day_high": "high",
            "day_low": "low",
            "day_close": "close",
            "day_volume": "volume",
        }
    )

    session_minute_detail = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-19T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.1,
                "low": 9.95,
                "close": 10.05,
                "volume": 1000,
                "trade_count": 10,
            }
        ]
    )

    base_snapshot, _, symbol_day = build_base_snapshot_from_bundle_payload(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        session_minute_detail=session_minute_detail,
        asof_date="2026-03-20",
    )

    day_rows = symbol_day.loc[symbol_day["symbol"] == "AAA"].sort_values("trade_date").reset_index(drop=True)
    assert bool(day_rows.loc[0, "minute_detail_missing"]) is False
    assert bool(day_rows.loc[1, "minute_detail_missing"]) is True

    expected_single_day_ratio = float(day_rows.loc[0, "daily_open_30m_dollar_share"])
    actual_ratio = float(base_snapshot.loc[0, "open_30m_dollar_share_20d"])
    assert actual_ratio == pytest.approx(expected_single_day_ratio)


def test_collect_full_universe_session_minute_detail_cache_coverage_uses_runtime_unsupported_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "session_minute.parquet"
    cache_meta_path = tmp_path / "session_minute.parquet.meta.json"
    cache_meta_path.write_text(
        json.dumps({"trade_day": "2026-02-10", "runtime_unsupported_symbols": ["AACB"]}),
        encoding="utf-8",
    )

    cached_frame = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 2, 10),
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-02-10T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 1000,
                "trade_count": 20,
            }
        ]
    )

    monkeypatch.setattr(runtime, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(runtime, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(runtime, "build_cache_path", lambda *args, **kwargs: cache_path)
    monkeypatch.setattr(runtime, "_read_cached_frame", lambda *args, **kwargs: cached_frame.copy())

    def fail_fetch(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("fetch should not run when cache coverage passes with unresolved sidecar")

    monkeypatch.setattr(runtime, "_databento_get_range_with_retry", fail_fetch)

    output = collect_full_universe_session_minute_detail(
        "dummy-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 2, 10)],
        universe_symbols={"AAA", "AACB"},
        display_timezone="America/New_York",
        use_file_cache=True,
        force_refresh=False,
    )

    assert set(output["symbol"].unique()) == {"AAA"}


def test_build_base_snapshot_from_bundle_payload_preserves_adv_dollar_daily_fallback_when_minute_detail_is_missing(
    tmp_path: Path,
) -> None:
    bundle_payload, _ = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"]).copy()
    frames["daily_symbol_features_full_universe"] = daily_features
    frames["daily_bars"] = daily_features[
        ["trade_date", "symbol", "day_open", "day_high", "day_low", "day_close", "day_volume", "previous_close"]
    ].rename(
        columns={
            "day_open": "open",
            "day_high": "high",
            "day_low": "low",
            "day_close": "close",
            "day_volume": "volume",
        }
    )

    session_minute_detail = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-19T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.1,
                "low": 9.95,
                "close": 10.05,
                "volume": 1000,
                "trade_count": 10,
            }
        ]
    )

    base_snapshot, _, symbol_day = build_base_snapshot_from_bundle_payload(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        session_minute_detail=session_minute_detail,
        asof_date="2026-03-20",
    )

    day_rows = symbol_day.loc[symbol_day["symbol"] == "AAA"].sort_values("trade_date").reset_index(drop=True)
    assert bool(day_rows.loc[0, "minute_detail_missing"]) is False
    assert bool(day_rows.loc[1, "minute_detail_missing"]) is True

    day1_adv_from_minute = 10.05 * 1000.0
    day2_adv_from_daily_fallback = 10.4 * 1_900_000.0
    expected_adv = (day1_adv_from_minute + day2_adv_from_daily_fallback) / 2.0
    actual_adv = float(base_snapshot.loc[0, "adv_dollar_rth_20d"])

    assert actual_adv == pytest.approx(expected_adv)


def test_collect_full_universe_session_minute_detail_writes_unresolved_cache_sidecar_even_when_day_frame_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "session_minute.parquet"
    cache_meta_path = tmp_path / "session_minute.parquet.meta.json"
    wrote_parquet: dict[str, bool] = {"value": False}

    class EmptyStore:
        def to_df(self, count: int = 250_000) -> pd.DataFrame:
            return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume", "trade_count"])

    def fake_get_range(*args: Any, **kwargs: Any) -> EmptyStore:
        warnings.warn("The streaming request had one or more symbols which did not resolve: AACB")
        return EmptyStore()

    monkeypatch.setattr(runtime, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(runtime, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(runtime, "build_cache_path", lambda *args, **kwargs: cache_path)
    monkeypatch.setattr(runtime, "_read_cached_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(runtime, "_store_to_frame", lambda store, count, context: store.to_df(count=count))
    monkeypatch.setattr(
        runtime,
        "_write_cached_frame",
        lambda *args, **kwargs: wrote_parquet.__setitem__("value", True),
    )

    output = collect_full_universe_session_minute_detail(
        "dummy-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 2, 10)],
        universe_symbols={"AACB"},
        display_timezone="America/New_York",
        use_file_cache=True,
        force_refresh=False,
    )

    assert output.empty
    assert wrote_parquet["value"] is False
    assert cache_meta_path.exists()
    payload = json.loads(cache_meta_path.read_text(encoding="utf-8"))
    assert payload["trade_day"] == "2026-02-10"
    assert payload["runtime_unsupported_symbols"] == ["AACB"]