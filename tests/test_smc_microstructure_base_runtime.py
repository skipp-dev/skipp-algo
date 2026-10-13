from __future__ import annotations

import json
import warnings
from datetime import date
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

import scripts.smc_databento_session_detail as session_detail
import scripts.smc_microstructure_base_runtime as runtime
from scripts.smc_microstructure_base_runtime import (
    _abs_return_series_for_index,
    _clip01,
    _clip01_series,
    _coerce_bool,
    _coerce_bool_series,
    _coerce_trade_date_series,
    _column_nanmeans_or_zero,
    _consistency_score,
    _consistency_score_from_numeric_values,
    _et_minutes_since_midnight,
    _grouped_setup_decay_half_life_30m_buckets,
    _mean_or_default,
    _nanquantile_or_default,
    _quantile_or_default,
    _safe_float,
    _safe_ratio,
    _safe_ratio_series_for_index,
    _safe_ratio_to_constant_series,
    _setup_decay_half_life_30m_buckets,
    build_base_snapshot_from_bundle_payload,
    build_symbol_day_microstructure_feature_frame,
    collect_full_universe_session_minute_detail,
    infer_asset_type,
    write_base_manifest,
)
from scripts.smc_schema_resolver import resolve_microstructure_schema_path

SCHEMA_PATH = resolve_microstructure_schema_path()


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


def test_setup_decay_half_life_30m_buckets_returns_bucket_count_when_threshold_not_hit() -> None:
    frame = pd.DataFrame(
        [
            {"minutes_from_open": 0, "dollar_volume": 10.0},
            {"minutes_from_open": 30, "dollar_volume": 9.0},
            {"minutes_from_open": 60, "dollar_volume": 8.0},
        ]
    )

    assert _setup_decay_half_life_30m_buckets(frame) == 3.0


def test_grouped_setup_decay_half_life_matches_scalar_helper() -> None:
    frame = pd.DataFrame(
        [
            {"trade_date": "2026-03-20", "symbol": "AAA", "minutes_from_open": 0, "dollar_volume": 10.0},
            {"trade_date": "2026-03-20", "symbol": "AAA", "minutes_from_open": 30, "dollar_volume": 4.0},
            {"trade_date": "2026-03-20", "symbol": "BBB", "minutes_from_open": 0, "dollar_volume": 10.0},
            {"trade_date": "2026-03-20", "symbol": "BBB", "minutes_from_open": 30, "dollar_volume": 9.0},
            {"trade_date": "2026-03-20", "symbol": "BBB", "minutes_from_open": 60, "dollar_volume": 8.0},
        ]
    )

    grouped = _grouped_setup_decay_half_life_30m_buckets(frame, group_columns=["trade_date", "symbol"])

    assert grouped.loc[("2026-03-20", "AAA")] == pytest.approx(1.0)
    assert grouped.loc[("2026-03-20", "BBB")] == pytest.approx(3.0)


def test_safe_float_handles_scalar_strings_and_missing_values() -> None:
    assert _safe_float(" 1.25 ") == pytest.approx(1.25)
    assert _safe_float(pd.NA, default=7.0) == pytest.approx(7.0)
    assert _safe_float("not-a-number", default=3.0) == pytest.approx(3.0)


def test_clip01_clamps_invalid_and_out_of_range_scalars() -> None:
    assert _clip01("1.5") == pytest.approx(1.0)
    assert _clip01("-0.2") == pytest.approx(0.0)
    assert _clip01(pd.NA) == pytest.approx(0.0)


def test_clip01_series_matches_map_semantics() -> None:
    series = pd.Series([1.5, "0.4", -0.2, pd.NA, "bad"], index=["AAA", "BBB", "CCC", "DDD", "EEE"])

    expected = series.map(_clip01).astype(float)
    result = _clip01_series(series)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_coerce_bool_series_matches_map_semantics() -> None:
    series = pd.Series([True, False, 2, 0, " yes ", "false", pd.NA, None], index=list("ABCDEFGH"))

    expected = series.map(_coerce_bool).astype(bool)
    result = _coerce_bool_series(series)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_coerce_trade_date_series_matches_pandas_semantics() -> None:
    series = pd.Series(
        [
            "2026-03-20",
            "2026-03-20",
            date(2026, 3, 21),
            pd.Timestamp("2026-03-24T12:00:00Z"),
            "bad-date",
            None,
            pd.NA,
        ]
    )

    expected = series.map(
        lambda value: (
            pd.NaT
            if pd.isna(pd.to_datetime(pd.Index([value]), errors="coerce")[0])
            else pd.to_datetime(pd.Index([value]), errors="coerce")[0].date()
        )
    )
    result = _coerce_trade_date_series(series)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_mean_or_default_matches_previous_pandas_semantics() -> None:
    series = pd.Series([1.0, "2.5", pd.NA, "bad", np.nan])

    expected_numeric = pd.to_numeric(series, errors="coerce")
    expected = 0.0 if expected_numeric.dropna().empty else float(expected_numeric.mean())

    assert _mean_or_default(series, default=0.0) == pytest.approx(expected)
    assert _mean_or_default(pd.Series([pd.NA, "bad"]), default=7.0) == pytest.approx(7.0)


def test_quantile_or_default_matches_previous_pandas_semantics() -> None:
    series = pd.Series([1.0, "2.5", pd.NA, "bad", 5.0])

    expected_numeric = pd.to_numeric(series, errors="coerce").dropna()
    expected = 0.0 if expected_numeric.empty else float(expected_numeric.quantile(0.75))

    assert _quantile_or_default(series, 0.75, default=0.0) == pytest.approx(expected)
    assert _quantile_or_default(pd.Series([pd.NA, "bad"]), 0.5, default=9.0) == pytest.approx(9.0)


def test_consistency_score_matches_previous_pandas_semantics() -> None:
    group = pd.DataFrame(
        {
            "daily_clean_intraday_score": [0.6, "0.8", pd.NA],
            "daily_open_30m_dollar_share": [0.2, 0.25, 0.3],
            "daily_close_60m_dollar_share": [0.15, 0.12, "bad"],
            "daily_midday_efficiency": [0.4, 0.5, 0.45],
            "daily_close_hygiene": [0.9, 0.7, 0.8],
        }
    )

    score_columns = [
        "daily_clean_intraday_score",
        "daily_open_30m_dollar_share",
        "daily_close_60m_dollar_share",
        "daily_midday_efficiency",
        "daily_close_hygiene",
    ]
    expected_components: list[float] = []
    for column in score_columns:
        numeric = pd.to_numeric(group.get(column), errors="coerce").dropna()
        if numeric.empty:
            continue
        baseline = max(float(abs(numeric.mean())), 0.01)
        cv = float(numeric.std(ddof=0) / baseline)
        expected_components.append(1.0 / (1.0 + cv))

    expected = 0.0 if not expected_components else float(np.clip(np.mean(expected_components), 0.0, 1.0))

    assert _consistency_score(group) == pytest.approx(expected)


def test_column_nanmeans_or_zero_matches_per_column_mean_defaults() -> None:
    frame = pd.DataFrame(
        {
            "alpha": [1.0, np.nan, 3.0],
            "beta": [np.nan, np.nan, np.nan],
            "gamma": [1, 0, 1],
        }
    )

    result = _column_nanmeans_or_zero(frame, ["alpha", "beta", "gamma"])

    assert result.tolist() == pytest.approx([
        _mean_or_default(frame["alpha"], default=0.0),
        0.0,
        _mean_or_default(frame["gamma"], default=0.0),
    ])


def test_nanquantile_or_default_matches_series_helper_semantics() -> None:
    values = np.array([1.0, 2.5, np.nan, 5.0])

    assert _nanquantile_or_default(values, 0.75, default=0.0) == pytest.approx(
        _quantile_or_default(pd.Series(values), 0.75, default=0.0)
    )
    assert _nanquantile_or_default(np.array([np.nan, np.nan]), 0.5, default=9.0) == pytest.approx(9.0)


def test_consistency_score_from_numeric_values_matches_generic_helper() -> None:
    group = pd.DataFrame(
        {
            "daily_clean_intraday_score": [0.6, 0.8, np.nan],
            "daily_open_30m_dollar_share": [0.2, 0.25, 0.3],
            "daily_close_60m_dollar_share": [0.15, 0.12, np.nan],
            "daily_midday_efficiency": [0.4, 0.5, 0.45],
            "daily_close_hygiene": [0.9, 0.7, 0.8],
        }
    )

    values = group[
        [
            "daily_clean_intraday_score",
            "daily_open_30m_dollar_share",
            "daily_close_60m_dollar_share",
            "daily_midday_efficiency",
            "daily_close_hygiene",
        ]
    ].to_numpy(dtype=float, copy=False)

    assert _consistency_score_from_numeric_values(values) == pytest.approx(_consistency_score(group))


def test_safe_ratio_series_for_index_matches_combine_semantics() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("2026-03-20", "AAA"),
            ("2026-03-20", "BBB"),
            ("2026-03-20", "CCC"),
        ],
        names=["trade_date", "symbol"],
    )
    numerator = pd.Series([6.0, 0.25], index=index[:2])
    denominator = pd.Series([12.0, 0.0, 2.0], index=index)

    expected = numerator.combine(
        denominator,
        lambda left, right: _safe_ratio(left, right, default=0.0),
    ).reindex(index).fillna(0.0)

    result = _safe_ratio_series_for_index(numerator, denominator, index=index, default=0.0)

    pd.testing.assert_series_equal(result, expected, check_names=False)

    expected_with_floor = numerator.combine(
        denominator,
        lambda left, right: _safe_ratio(left, max(right, 1e-6), default=0.0),
    ).reindex(index).fillna(0.0)

    result_with_floor = _safe_ratio_series_for_index(
        numerator,
        denominator,
        index=index,
        default=0.0,
        minimum_denominator=1e-6,
    )

    pd.testing.assert_series_equal(result_with_floor, expected_with_floor, check_names=False)


def test_safe_ratio_to_constant_series_matches_map_semantics() -> None:
    series = pd.Series([6.0, "3.0", pd.NA, "bad"], index=["AAA", "BBB", "CCC", "DDD"])

    expected = series.map(lambda value: _safe_ratio(value, 12.0, default=0.0)).astype(float)
    result = _safe_ratio_to_constant_series(series, denominator=12.0, default=0.0)

    pd.testing.assert_series_equal(result, expected, check_names=False)

    zero_denominator = _safe_ratio_to_constant_series(series, denominator=0.0, default=0.0)
    pd.testing.assert_series_equal(
        zero_denominator,
        pd.Series(0.0, index=series.index, dtype=float),
        check_names=False,
    )


def test_abs_return_series_for_index_matches_combine_semantics() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("2026-03-20", "AAA"),
            ("2026-03-20", "BBB"),
            ("2026-03-20", "CCC"),
        ],
        names=["trade_date", "symbol"],
    )
    close_price = pd.Series([10.5, 11.0], index=index[:2])
    open_price = pd.Series([10.0, 0.0, 4.0], index=index)

    expected = close_price.combine(
        open_price,
        lambda close_value, open_value: abs((close_value / open_value) - 1.0)
        if np.isfinite(open_value) and open_value > 0 and np.isfinite(close_value)
        else 0.0,
    ).reindex(index).fillna(0.0)

    result = _abs_return_series_for_index(close_price, open_price, index=index)

    pd.testing.assert_series_equal(result, expected, check_names=False)


def test_et_minutes_since_midnight_preserves_eastern_clock_minutes_across_dst() -> None:
    timestamps = pd.Series(
        [
            pd.Timestamp("2026-03-06T14:30:00Z"),
            pd.Timestamp("2026-03-09T13:30:00Z"),
            pd.Timestamp("2026-03-09T20:25:00Z"),
        ]
    )

    result = _et_minutes_since_midnight(timestamps)

    assert result.tolist() == [570, 570, 985]


def test_et_minutes_since_midnight_reuses_repeated_timestamp_minutes() -> None:
    timestamps = pd.Series(
        [
            pd.Timestamp("2026-03-09T13:30:00Z"),
            pd.Timestamp("2026-03-09T13:30:00Z"),
            pd.Timestamp("2026-03-09T20:25:00Z"),
            pd.Timestamp("2026-03-09T20:25:00Z"),
        ]
    )

    result = _et_minutes_since_midnight(timestamps)

    assert result.tolist() == [570, 570, 985, 985]


def test_build_base_snapshot_from_bundle_payload_warns_when_asof_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)

    monkeypatch.setattr(runtime, "_today_et", lambda: date(2026, 3, 27))

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


def test_build_base_snapshot_from_bundle_payload_uses_legacy_volume_fallback(
    tmp_path: Path,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    legacy_daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"]).copy()
    legacy_daily_features["volume"] = legacy_daily_features["day_volume"]
    legacy_daily_features = legacy_daily_features.drop(columns=["day_volume"])
    frames["daily_symbol_features_full_universe"] = legacy_daily_features

    output, payload, _ = build_base_snapshot_from_bundle_payload(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        session_minute_detail=session_minute_detail,
    )

    assert payload["row_count"] == 1
    assert output.loc[0, "adv_dollar_rth_20d"] > 0.0


def test_incremental_base_seed_roundtrip(tmp_path: Path) -> None:
    daily_bars = pd.DataFrame(
        [
            {"trade_date": "2026-03-19", "symbol": "AAA", "open": 10.0, "high": 10.8, "low": 9.7, "close": 10.5, "volume": 1_500_000, "previous_close": 9.8},
            {"trade_date": "2026-03-20", "symbol": "AAA", "open": 10.7, "high": 11.2, "low": 10.1, "close": 10.4, "volume": 1_900_000, "previous_close": 10.5},
        ]
    )
    daily_features = pd.DataFrame(
        [
            {"trade_date": "2026-03-19", "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.5, "day_volume": 1_500_000},
            {"trade_date": "2026-03-20", "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.4, "day_volume": 1_900_000},
        ]
    )
    symbol_day_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "exchange": "NASDAQ",
                "company_name": "Alpha Holdings",
                "asset_type": "stock",
                "market_cap": 3_200_000_000,
                "day_close": 10.4,
                "day_volume": 1_900_000,
                "minute_detail_missing": False,
                "missing_regular_session_detail": False,
                "missing_midday_detail": False,
                "daily_rth_dollar_volume": 19_760_000.0,
                "daily_avg_spread_bps_rth": 1.2,
                "daily_rth_active_minutes_share": 0.8,
                "daily_open_30m_dollar_share": 0.2,
                "daily_close_60m_dollar_share": 0.3,
                "daily_clean_intraday_score": 0.7,
                "daily_rth_wickiness": 0.1,
                "daily_pm_dollar_share": 0.05,
                "daily_pm_trades_share": 0.05,
                "daily_pm_active_minutes_share": 0.2,
                "daily_pm_spread_bps": 1.0,
                "daily_pm_wickiness": 0.1,
                "daily_midday_dollar_share": 0.2,
                "daily_midday_trades_share": 0.2,
                "daily_midday_active_minutes_share": 0.5,
                "daily_midday_spread_bps": 1.0,
                "daily_midday_efficiency": 0.6,
                "daily_ah_dollar_share": 0.05,
                "daily_ah_trades_share": 0.05,
                "daily_ah_active_minutes_share": 0.1,
                "daily_ah_spread_bps": 1.0,
                "daily_ah_wickiness": 0.1,
                "daily_setup_decay_half_life_bars": 2.0,
                "daily_early_vs_late_followthrough_ratio": 1.1,
                "daily_close_hygiene": 0.8,
                "daily_reclaim_respect_flag": 1.0,
                "daily_reclaim_failure_flag": 0.0,
                "daily_reclaim_followthrough_r": 0.4,
                "daily_ob_sweep_reversal_flag": 0.0,
                "daily_fvg_sweep_reversal_flag": 0.0,
                "daily_stop_hunt_flag": 0.0,
                "daily_stale_fail_flag": 0.0,
                "daily_ob_sweep_depth": 0.0,
                "daily_fvg_sweep_depth": 0.0,
            }
        ]
    )
    diagnostics = pd.DataFrame([{"trade_date": "2026-03-20", "symbol": "AAA", "excluded_reason": ""}])

    runtime._write_incremental_base_seed(
        tmp_path,
        bundle_manifest_path=tmp_path / "bundle_manifest.json",
        asof_date="2026-03-20",
        trade_dates_covered=["2026-03-19", "2026-03-20"],
        daily_bars=daily_bars,
        daily_features=daily_features,
        symbol_day_features=symbol_day_features,
        symbol_day_diagnostics=diagnostics,
    )

    seed = runtime._load_incremental_base_seed(tmp_path)

    assert seed is not None
    assert seed["manifest"]["asof_date"] == "2026-03-20"
    pd.testing.assert_frame_equal(seed["daily_bars"], daily_bars)
    pd.testing.assert_frame_equal(seed["daily_features"], daily_features)
    pd.testing.assert_frame_equal(seed["symbol_day_features"], symbol_day_features)
    pd.testing.assert_frame_equal(seed["symbol_day_diagnostics"], diagnostics)


def test_build_base_snapshot_from_symbol_day_features_matches_bundle_builder(tmp_path: Path) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"])
    symbol_day_features = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    expected_snapshot, expected_payload, _ = build_base_snapshot_from_bundle_payload(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        session_minute_detail=session_minute_detail,
    )
    actual_snapshot, actual_payload = runtime._build_base_snapshot_from_symbol_day_features(
        symbol_day_features,
        schema_path=SCHEMA_PATH,
    )

    pd.testing.assert_frame_equal(actual_snapshot, expected_snapshot)
    assert actual_payload["asof_date"] == expected_payload["asof_date"]
    assert actual_payload["row_count"] == expected_payload["row_count"]


def test_build_symbol_day_microstructure_feature_frame_mutate_input_matches_copy_mode(tmp_path: Path) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"])

    expected = build_symbol_day_microstructure_feature_frame(session_minute_detail.copy(), daily_features)
    telemetry: list[str] = []
    actual = build_symbol_day_microstructure_feature_frame(
        session_minute_detail.copy(),
        daily_features,
        telemetry_callback=telemetry.append,
        mutate_input=True,
    )

    pd.testing.assert_frame_equal(actual, expected)
    assert any("session_minute_detail_input mutate_input=True" in message for message in telemetry)
    assert any("minute_frame_sorted" in message for message in telemetry)
    assert any("symbol_day_features_output" in message for message in telemetry)


def test_build_symbol_day_microstructure_feature_frame_batched_matches_unbatched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"])

    expected = build_symbol_day_microstructure_feature_frame(session_minute_detail.copy(), daily_features)
    telemetry: list[str] = []
    monkeypatch.setattr(runtime, "SYMBOL_DAY_FEATURE_BATCH_ROW_THRESHOLD", 1)

    actual = build_symbol_day_microstructure_feature_frame(
        session_minute_detail.copy(),
        daily_features,
        telemetry_callback=telemetry.append,
        mutate_input=True,
    )

    pd.testing.assert_frame_equal(actual, expected)
    assert any("minute_frame_batching" in message for message in telemetry)
    assert any("minute_frame_batch_start" in message for message in telemetry)
    assert any("minute_metrics_batched_output" in message for message in telemetry)


def test_generate_base_from_bundle_uses_precomputed_symbol_day_features(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_payload, session_minute_detail = _make_bundle_payload(tmp_path)
    frames = cast(dict[str, Any], bundle_payload["frames"])
    daily_features = cast(pd.DataFrame, frames["daily_symbol_features_full_universe"])
    symbol_day_features = build_symbol_day_microstructure_feature_frame(session_minute_detail.copy(), daily_features)

    monkeypatch.setattr(
        runtime,
        "build_base_snapshot_from_bundle_payload",
        lambda *args, **kwargs: pytest.fail("precomputed symbol-day features should bypass bundle minute rebuild"),
    )

    result = runtime.generate_base_from_bundle(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        output_dir=tmp_path,
        write_xlsx=False,
        symbol_day_features=symbol_day_features,
    )

    output_paths = result["output_paths"]
    assert output_paths["base_csv"].exists()
    assert output_paths["micro_day_parquet"].exists()
    assert output_paths["mapping_md"].exists()
    assert output_paths["mapping_json"].exists()
    assert output_paths["base_manifest"].exists()


def test_run_databento_base_scan_pipeline_incremental_reuses_seed_and_limits_trade_day_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trade_days = [date(2026, 3, 18), date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 21)]
    seed_daily_bars = pd.DataFrame(
        [
            {"trade_date": trade_days[0], "symbol": "AAA", "open": 10.0, "high": 10.4, "low": 9.8, "close": 10.1, "volume": 1000, "previous_close": 9.9},
            {"trade_date": trade_days[1], "symbol": "AAA", "open": 10.2, "high": 10.5, "low": 10.0, "close": 10.3, "volume": 1100, "previous_close": 10.1},
            {"trade_date": trade_days[2], "symbol": "AAA", "open": 10.4, "high": 10.7, "low": 10.2, "close": 10.5, "volume": 1200, "previous_close": 10.3},
        ]
    )
    seed_daily_features = pd.DataFrame(
        [
            {"trade_date": trade_days[0], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_volume": 1000, "open_1m_volume": 100.0, "open_5m_volume": 200.0, "day_close": 10.1, "has_intraday": True},
            {"trade_date": trade_days[1], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_volume": 1100, "open_1m_volume": 110.0, "open_5m_volume": 210.0, "day_close": 10.3, "has_intraday": True},
            {"trade_date": trade_days[2], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_volume": 1200, "open_1m_volume": 120.0, "open_5m_volume": 220.0, "day_close": 10.5, "has_intraday": True},
        ]
    )
    seed_symbol_day_features = pd.DataFrame(
        [
            {"trade_date": trade_days[0], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.1, "day_volume": 1000, "minute_detail_missing": False, "missing_regular_session_detail": False, "missing_midday_detail": False, "daily_rth_dollar_volume": 10100.0, "daily_avg_spread_bps_rth": 1.0, "daily_rth_active_minutes_share": 0.8, "daily_open_30m_dollar_share": 0.2, "daily_close_60m_dollar_share": 0.3, "daily_clean_intraday_score": 0.7, "daily_rth_wickiness": 0.1, "daily_pm_dollar_share": 0.05, "daily_pm_trades_share": 0.05, "daily_pm_active_minutes_share": 0.2, "daily_pm_spread_bps": 1.0, "daily_pm_wickiness": 0.1, "daily_midday_dollar_share": 0.2, "daily_midday_trades_share": 0.2, "daily_midday_active_minutes_share": 0.5, "daily_midday_spread_bps": 1.0, "daily_midday_efficiency": 0.6, "daily_ah_dollar_share": 0.05, "daily_ah_trades_share": 0.05, "daily_ah_active_minutes_share": 0.1, "daily_ah_spread_bps": 1.0, "daily_ah_wickiness": 0.1, "daily_setup_decay_half_life_bars": 2.0, "daily_early_vs_late_followthrough_ratio": 1.0, "daily_close_hygiene": 0.8, "daily_reclaim_respect_flag": 1.0, "daily_reclaim_failure_flag": 0.0, "daily_reclaim_followthrough_r": 0.4, "daily_ob_sweep_reversal_flag": 0.0, "daily_fvg_sweep_reversal_flag": 0.0, "daily_stop_hunt_flag": 0.0, "daily_stale_fail_flag": 0.0, "daily_ob_sweep_depth": 0.0, "daily_fvg_sweep_depth": 0.0},
            {"trade_date": trade_days[1], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.3, "day_volume": 1100, "minute_detail_missing": False, "missing_regular_session_detail": False, "missing_midday_detail": False, "daily_rth_dollar_volume": 11330.0, "daily_avg_spread_bps_rth": 1.0, "daily_rth_active_minutes_share": 0.8, "daily_open_30m_dollar_share": 0.2, "daily_close_60m_dollar_share": 0.3, "daily_clean_intraday_score": 0.7, "daily_rth_wickiness": 0.1, "daily_pm_dollar_share": 0.05, "daily_pm_trades_share": 0.05, "daily_pm_active_minutes_share": 0.2, "daily_pm_spread_bps": 1.0, "daily_pm_wickiness": 0.1, "daily_midday_dollar_share": 0.2, "daily_midday_trades_share": 0.2, "daily_midday_active_minutes_share": 0.5, "daily_midday_spread_bps": 1.0, "daily_midday_efficiency": 0.6, "daily_ah_dollar_share": 0.05, "daily_ah_trades_share": 0.05, "daily_ah_active_minutes_share": 0.1, "daily_ah_spread_bps": 1.0, "daily_ah_wickiness": 0.1, "daily_setup_decay_half_life_bars": 2.0, "daily_early_vs_late_followthrough_ratio": 1.0, "daily_close_hygiene": 0.8, "daily_reclaim_respect_flag": 1.0, "daily_reclaim_failure_flag": 0.0, "daily_reclaim_followthrough_r": 0.4, "daily_ob_sweep_reversal_flag": 0.0, "daily_fvg_sweep_reversal_flag": 0.0, "daily_stop_hunt_flag": 0.0, "daily_stale_fail_flag": 0.0, "daily_ob_sweep_depth": 0.0, "daily_fvg_sweep_depth": 0.0},
            {"trade_date": trade_days[2], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.5, "day_volume": 1200, "minute_detail_missing": False, "missing_regular_session_detail": False, "missing_midday_detail": False, "daily_rth_dollar_volume": 12600.0, "daily_avg_spread_bps_rth": 1.0, "daily_rth_active_minutes_share": 0.8, "daily_open_30m_dollar_share": 0.2, "daily_close_60m_dollar_share": 0.3, "daily_clean_intraday_score": 0.7, "daily_rth_wickiness": 0.1, "daily_pm_dollar_share": 0.05, "daily_pm_trades_share": 0.05, "daily_pm_active_minutes_share": 0.2, "daily_pm_spread_bps": 1.0, "daily_pm_wickiness": 0.1, "daily_midday_dollar_share": 0.2, "daily_midday_trades_share": 0.2, "daily_midday_active_minutes_share": 0.5, "daily_midday_spread_bps": 1.0, "daily_midday_efficiency": 0.6, "daily_ah_dollar_share": 0.05, "daily_ah_trades_share": 0.05, "daily_ah_active_minutes_share": 0.1, "daily_ah_spread_bps": 1.0, "daily_ah_wickiness": 0.1, "daily_setup_decay_half_life_bars": 2.0, "daily_early_vs_late_followthrough_ratio": 1.0, "daily_close_hygiene": 0.8, "daily_reclaim_respect_flag": 1.0, "daily_reclaim_failure_flag": 0.0, "daily_reclaim_followthrough_r": 0.4, "daily_ob_sweep_reversal_flag": 0.0, "daily_fvg_sweep_reversal_flag": 0.0, "daily_stop_hunt_flag": 0.0, "daily_stale_fail_flag": 0.0, "daily_ob_sweep_depth": 0.0, "daily_fvg_sweep_depth": 0.0},
        ]
    )
    runtime._write_incremental_base_seed(
        tmp_path,
        bundle_manifest_path=tmp_path / "prev_manifest.json",
        asof_date=trade_days[2].isoformat(),
        trade_dates_covered=[item.isoformat() for item in trade_days[:3]],
        daily_bars=seed_daily_bars,
        daily_features=seed_daily_features,
        symbol_day_features=seed_symbol_day_features,
        symbol_day_diagnostics=pd.DataFrame(),
    )

    captured: dict[str, Any] = {}

    monkeypatch.setattr(runtime, "list_recent_trading_days", lambda *args, **kwargs: trade_days)

    def fake_run_production_export_pipeline(**kwargs: Any) -> dict[str, Any]:
        captured["trading_days_override"] = kwargs.get("trading_days_override")
        delta_day = trade_days[-1]
        return {
            "exported_paths": {"manifest": str(tmp_path / "delta_manifest.json")},
            "daily_bars": pd.DataFrame(
                [
                    {"trade_date": delta_day, "symbol": "AAA", "open": 10.6, "high": 10.9, "low": 10.3, "close": 10.8, "volume": 1300, "previous_close": 10.5},
                ]
            ),
            "daily_symbol_features_full_universe": pd.DataFrame(
                [
                    {"trade_date": delta_day, "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_volume": 1300, "open_1m_volume": 130.0, "open_5m_volume": 230.0, "day_close": 10.8, "has_intraday": True},
                ]
            ),
            "symbol_day_diagnostics": pd.DataFrame([{"trade_date": delta_day, "symbol": "AAA", "excluded_reason": ""}]),
        }

    monkeypatch.setattr(runtime, "run_production_export_pipeline", fake_run_production_export_pipeline)

    def fake_collect(*args: Any, **kwargs: Any) -> pd.DataFrame:
        captured["session_trade_days"] = kwargs.get("trading_days")
        return pd.DataFrame(
            [
                {
                    "trade_date": trade_days[-1],
                    "symbol": "AAA",
                    "timestamp": pd.Timestamp("2026-03-21T13:30:00Z"),
                    "session": "regular",
                    "open": 10.6,
                    "high": 10.8,
                    "low": 10.5,
                    "close": 10.7,
                    "volume": 100,
                    "trade_count": 10,
                }
            ]
        )

    monkeypatch.setattr(runtime, "collect_full_universe_session_minute_detail", fake_collect)
    monkeypatch.setattr(
        runtime,
        "build_symbol_day_microstructure_feature_frame",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {"trade_date": trade_days[-1], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.8, "day_volume": 1300, "minute_detail_missing": False, "missing_regular_session_detail": False, "missing_midday_detail": False, "daily_rth_dollar_volume": 14040.0, "daily_avg_spread_bps_rth": 1.0, "daily_rth_active_minutes_share": 0.8, "daily_open_30m_dollar_share": 0.2, "daily_close_60m_dollar_share": 0.3, "daily_clean_intraday_score": 0.7, "daily_rth_wickiness": 0.1, "daily_pm_dollar_share": 0.05, "daily_pm_trades_share": 0.05, "daily_pm_active_minutes_share": 0.2, "daily_pm_spread_bps": 1.0, "daily_pm_wickiness": 0.1, "daily_midday_dollar_share": 0.2, "daily_midday_trades_share": 0.2, "daily_midday_active_minutes_share": 0.5, "daily_midday_spread_bps": 1.0, "daily_midday_efficiency": 0.6, "daily_ah_dollar_share": 0.05, "daily_ah_trades_share": 0.05, "daily_ah_active_minutes_share": 0.1, "daily_ah_spread_bps": 1.0, "daily_ah_wickiness": 0.1, "daily_setup_decay_half_life_bars": 2.0, "daily_early_vs_late_followthrough_ratio": 1.0, "daily_close_hygiene": 0.8, "daily_reclaim_respect_flag": 1.0, "daily_reclaim_failure_flag": 0.0, "daily_reclaim_followthrough_r": 0.4, "daily_ob_sweep_reversal_flag": 0.0, "daily_fvg_sweep_reversal_flag": 0.0, "daily_stop_hunt_flag": 0.0, "daily_stale_fail_flag": 0.0, "daily_ob_sweep_depth": 0.0, "daily_fvg_sweep_depth": 0.0},
            ]
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_build_base_snapshot_from_symbol_day_features",
        lambda *args, **kwargs: (
            pd.DataFrame([{column: 0.0 for column in json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))["required_columns"]}]),
            {"bundle_manifest_path": "incremental_seed", "asof_date": trade_days[-1].isoformat(), "row_count": 1, "direct_fields": [], "derived_fields": [], "missing_fields": [], "mapping_status": []},
        ),
    )

    result = runtime.run_databento_base_scan_pipeline(
        databento_api_key="dummy-db",
        fmp_api_key="",
        dataset="DBEQ.BASIC",
        export_dir=tmp_path,
        schema_path=SCHEMA_PATH,
        lookback_days=4,
        smc_base_only=True,
        incremental_base_only=True,
        write_xlsx=False,
    )

    assert captured["trading_days_override"] == trade_days[1:]
    assert captured["session_trade_days"] == trade_days[1:]
    assert result["export_result"]["daily_symbol_features_full_universe"]["trade_date"].isin(trade_days).all()
    assert (tmp_path / runtime.INCREMENTAL_BASE_SEED_DIR_NAME / runtime.INCREMENTAL_BASE_SEED_MANIFEST_NAME).exists()


def test_run_databento_base_scan_pipeline_incremental_keeps_has_intraday_false_symbol_days_in_fetch_scope_but_not_hard_coverage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    trade_days = [date(2026, 3, 18), date(2026, 3, 19), date(2026, 3, 20), date(2026, 3, 21)]
    seed_daily_bars = pd.DataFrame(
        [
            {"trade_date": trade_days[2], "symbol": "AAA", "open": 10.4, "high": 10.7, "low": 10.2, "close": 10.5, "volume": 1200, "previous_close": 10.3},
        ]
    )
    seed_daily_features = pd.DataFrame(
        [
            {"trade_date": trade_days[2], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_volume": 1200, "open_1m_volume": 120.0, "open_5m_volume": 220.0, "day_close": 10.5, "has_intraday": True},
        ]
    )
    seed_symbol_day_features = pd.DataFrame(
        [
            {"trade_date": trade_days[2], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_close": 10.5, "day_volume": 1200, "minute_detail_missing": False, "missing_regular_session_detail": False, "missing_midday_detail": False, "daily_rth_dollar_volume": 12600.0, "daily_avg_spread_bps_rth": 1.0, "daily_rth_active_minutes_share": 0.8, "daily_open_30m_dollar_share": 0.2, "daily_close_60m_dollar_share": 0.3, "daily_clean_intraday_score": 0.7, "daily_rth_wickiness": 0.1, "daily_pm_dollar_share": 0.05, "daily_pm_trades_share": 0.05, "daily_pm_active_minutes_share": 0.2, "daily_pm_spread_bps": 1.0, "daily_pm_wickiness": 0.1, "daily_midday_dollar_share": 0.2, "daily_midday_trades_share": 0.2, "daily_midday_active_minutes_share": 0.5, "daily_midday_spread_bps": 1.0, "daily_midday_efficiency": 0.6, "daily_ah_dollar_share": 0.05, "daily_ah_trades_share": 0.05, "daily_ah_active_minutes_share": 0.1, "daily_ah_spread_bps": 1.0, "daily_ah_wickiness": 0.1, "daily_setup_decay_half_life_bars": 2.0, "daily_early_vs_late_followthrough_ratio": 1.0, "daily_close_hygiene": 0.8, "daily_reclaim_respect_flag": 1.0, "daily_reclaim_failure_flag": 0.0, "daily_reclaim_followthrough_r": 0.4, "daily_ob_sweep_reversal_flag": 0.0, "daily_fvg_sweep_reversal_flag": 0.0, "daily_stop_hunt_flag": 0.0, "daily_stale_fail_flag": 0.0, "daily_ob_sweep_depth": 0.0, "daily_fvg_sweep_depth": 0.0},
        ]
    )
    runtime._write_incremental_base_seed(
        tmp_path,
        bundle_manifest_path=tmp_path / "prev_manifest.json",
        asof_date=trade_days[2].isoformat(),
        trade_dates_covered=[trade_days[2].isoformat()],
        daily_bars=seed_daily_bars,
        daily_features=seed_daily_features,
        symbol_day_features=seed_symbol_day_features,
        symbol_day_diagnostics=pd.DataFrame(),
    )

    captured: dict[str, Any] = {}

    monkeypatch.setattr(runtime, "list_recent_trading_days", lambda *args, **kwargs: trade_days)
    monkeypatch.setattr(
        runtime,
        "run_production_export_pipeline",
        lambda **kwargs: {
            "exported_paths": {"manifest": str(tmp_path / "delta_manifest.json")},
            "daily_bars": pd.DataFrame(
                [
                    {"trade_date": trade_days[3], "symbol": "AAA", "open": 10.6, "high": 10.9, "low": 10.3, "close": 10.8, "volume": 1300, "previous_close": 10.5},
                ]
            ),
            "daily_symbol_features_full_universe": pd.DataFrame(
                [
                    {"trade_date": trade_days[3], "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_volume": 1300, "open_1m_volume": 130.0, "open_5m_volume": 230.0, "day_close": 10.8, "has_intraday": False},
                ]
            ),
            "symbol_day_diagnostics": pd.DataFrame([{"trade_date": trade_days[3], "symbol": "AAA", "excluded_reason": ""}]),
        },
    )

    def fake_collect(*args: Any, **kwargs: Any) -> pd.DataFrame:
        captured["session_trade_days"] = kwargs.get("trading_days")
        captured["expected_symbols_by_trade_day"] = kwargs.get("expected_symbols_by_trade_day")
        captured["required_symbols_by_trade_day"] = kwargs.get("required_symbols_by_trade_day")
        return pd.DataFrame()

    monkeypatch.setattr(runtime, "collect_full_universe_session_minute_detail", fake_collect)
    monkeypatch.setattr(runtime, "build_symbol_day_microstructure_feature_frame", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(
        runtime,
        "_build_base_snapshot_from_symbol_day_features",
        lambda *args, **kwargs: (
            pd.DataFrame([{column: 0.0 for column in json.loads(Path(SCHEMA_PATH).read_text(encoding="utf-8"))["required_columns"]}]),
            {"bundle_manifest_path": "incremental_seed", "asof_date": trade_days[-1].isoformat(), "row_count": 1, "direct_fields": [], "derived_fields": [], "missing_fields": [], "mapping_status": []},
        ),
    )

    runtime.run_databento_base_scan_pipeline(
        databento_api_key="dummy-db",
        fmp_api_key="",
        dataset="DBEQ.BASIC",
        export_dir=tmp_path,
        schema_path=SCHEMA_PATH,
        lookback_days=2,
        smc_base_only=True,
        incremental_base_only=True,
        write_xlsx=False,
    )

    expected = cast(dict[date, set[str]], captured["expected_symbols_by_trade_day"])
    required_symbols = cast(dict[date, set[str]], captured["required_symbols_by_trade_day"])
    assert captured["session_trade_days"] == trade_days[1:]
    assert expected == {trade_days[2]: {"AAA"}, trade_days[3]: {"AAA"}}
    assert required_symbols == {trade_days[2]: {"AAA"}, trade_days[3]: set()}


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
        production_workbook_path=None,
        library_owner="preuss_steffen",
        library_version=1,
        core_ready=False,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["core_ready"] is False
    assert payload["production_workbook_path"] is None
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


def test_build_symbol_day_microstructure_feature_frame_preserves_input_order_for_duplicate_timestamps() -> None:
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
                "day_high": 10.4,
                "day_low": 9.9,
                "day_close": 10.2,
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
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.05,
                "volume": 100,
                "trade_count": 10,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.05,
                "high": 10.2,
                "low": 10.0,
                "close": 10.15,
                "volume": 200,
                "trade_count": 20,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T19:50:00Z"),
                "session": "regular",
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 300,
                "trade_count": 30,
            },
        ]
    )

    output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    row = output.iloc[0]
    expected_early_return = abs((10.15 / 10.0) - 1.0)
    expected_late_return = abs((10.2 / 10.1) - 1.0)
    assert row["daily_early_vs_late_followthrough_ratio"] == pytest.approx(expected_early_return / expected_late_return)


def test_build_symbol_day_microstructure_feature_frame_keeps_partial_ohlc_null_day_usable() -> None:
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
                "day_high": 10.4,
                "day_low": 9.9,
                "day_close": 10.2,
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
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": None,
                "low": None,
                "close": None,
                "volume": 100,
                "trade_count": 10,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T19:50:00Z"),
                "session": "regular",
                "open": 10.2,
                "high": 10.3,
                "low": 10.1,
                "close": 10.25,
                "volume": 200,
                "trade_count": 20,
            },
        ]
    )

    output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    row = output.iloc[0]
    assert bool(row["minute_detail_missing"]) is False
    assert row["daily_rth_dollar_volume"] == pytest.approx(10.25 * 200.0)
    assert row["daily_rth_active_minutes_share"] > 0.0
    assert 0.0 <= float(row["daily_rth_efficiency"]) <= 1.0


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
        warnings.warn("The streaming request had one or more symbols which did not resolve: AACB", stacklevel=2)
        return FakeStore()

    monkeypatch.setattr(session_detail, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(session_detail, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(session_detail, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(session_detail, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

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

    monkeypatch.setattr(session_detail, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(session_detail, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(session_detail, "_databento_get_range_with_retry", lambda *args, **kwargs: FakeStore())
    monkeypatch.setattr(session_detail, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

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


def test_collect_full_universe_session_minute_detail_skips_hard_coverage_when_required_scope_is_empty(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class EmptyStore:
        def to_df(self, count: int = 250_000) -> pd.DataFrame:
            return pd.DataFrame(columns=["symbol", "ts", "open", "high", "low", "close", "volume", "trade_count"])

    monkeypatch.setattr(session_detail, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(session_detail, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(session_detail, "_databento_get_range_with_retry", lambda *args, **kwargs: EmptyStore())
    monkeypatch.setattr(session_detail, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

    with caplog.at_level("INFO"):
        output = collect_full_universe_session_minute_detail(
            "dummy-key",
            dataset="DBEQ.BASIC",
            trading_days=[date(2026, 2, 10)],
            universe_symbols={"AAA"},
            expected_symbols_by_trade_day={date(2026, 2, 10): {"AAA"}},
            required_symbols_by_trade_day={},
            display_timezone="America/New_York",
            use_file_cache=False,
        )

    assert output.empty
    assert "required symbol scope is empty" in caplog.text


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
            warnings.warn("The streaming request had one or more symbols which did not resolve: AACB", stacklevel=2)
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

    monkeypatch.setattr(session_detail, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(session_detail, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-12T03:00:00Z"))
    monkeypatch.setattr(session_detail, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(session_detail, "_store_to_frame", lambda store, count, context: store.to_df(count=count))

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


def test_run_databento_base_scan_pipeline_keeps_has_intraday_false_symbol_days_in_fetch_scope_but_not_hard_coverage(
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
        captured["required_symbols_by_trade_day"] = kwargs.get("required_symbols_by_trade_day")
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
    required_symbols = cast(dict[date, set[str]], captured["required_symbols_by_trade_day"])
    assert expected == {date(2026, 2, 10): {"AAA"}}
    assert required_symbols == {date(2026, 2, 10): set()}


def test_run_databento_base_scan_pipeline_full_step12_reuses_precomputed_symbol_day_features(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-02-10",
                "symbol": "AAA",
                "has_intraday": True,
            }
        ]
    )
    precomputed_symbol_day_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-02-10",
                "symbol": "AAA",
                "exchange": "NASDAQ",
                "asset_type": "stock",
                "universe_bucket": "us_midcap",
                "history_coverage_days_20d": 1,
                "adv_dollar_rth_20d": 1000.0,
                "avg_spread_bps_rth_20d": 1.0,
                "rth_active_minutes_share_20d": 1.0,
                "open_30m_dollar_share_20d": 0.1,
                "close_60m_dollar_share_20d": 0.2,
                "clean_intraday_score_20d": 0.5,
                "consistency_score_20d": 0.5,
                "close_hygiene_20d": 0.5,
                "wickiness_20d": 0.1,
                "pm_dollar_share_20d": 0.0,
                "pm_trades_share_20d": 0.0,
                "pm_active_minutes_share_20d": 0.0,
                "pm_spread_bps_20d": 0.0,
                "pm_wickiness_20d": 0.0,
                "midday_dollar_share_20d": 0.0,
                "midday_trades_share_20d": 0.0,
                "midday_active_minutes_share_20d": 0.0,
                "midday_spread_bps_20d": 0.0,
                "midday_efficiency_20d": 0.0,
                "ah_dollar_share_20d": 0.0,
                "ah_trades_share_20d": 0.0,
                "ah_active_minutes_share_20d": 0.0,
                "ah_spread_bps_20d": 0.0,
                "ah_wickiness_20d": 0.0,
                "reclaim_respect_rate_20d": 0.0,
                "reclaim_failure_rate_20d": 0.0,
                "reclaim_followthrough_r_20d": 0.0,
                "ob_sweep_reversal_rate_20d": 0.0,
                "ob_sweep_depth_p75_20d": 0.0,
                "fvg_sweep_reversal_rate_20d": 0.0,
                "fvg_sweep_depth_p75_20d": 0.0,
                "stop_hunt_rate_20d": 0.0,
                "setup_decay_half_life_bars_20d": 0.0,
                "early_vs_late_followthrough_ratio_20d": 0.0,
                "stale_fail_rate_20d": 0.0,
            }
        ]
    )

    monkeypatch.setattr(
        runtime,
        "run_production_export_pipeline",
        lambda **kwargs: {
            "exported_paths": {
                "manifest": str(tmp_path / "fake_manifest.json"),
                "canonical_production_workbook": str(tmp_path / "canonical.xlsx"),
            },
            "symbol_day_diagnostics": pd.DataFrame(),
        },
    )
    monkeypatch.setattr(
        runtime,
        "load_export_bundle",
        lambda *args, **kwargs: {
            "manifest": {"trade_dates_covered": ["2026-02-10"]},
            "manifest_path": tmp_path / "fake_manifest.json",
            "frames": {
                "daily_symbol_features_full_universe": daily_features,
                "daily_bars": pd.DataFrame(),
            },
            "base_prefix": "databento_volatility_production_fake",
        },
    )
    monkeypatch.setattr(
        runtime,
        "collect_full_universe_session_minute_detail",
        lambda *args, **kwargs: pd.DataFrame(
            [
                {
                    "trade_date": date(2026, 2, 10),
                    "symbol": "AAA",
                    "timestamp": pd.Timestamp("2026-02-10T14:30:00Z"),
                    "session": "regular",
                    "open": 10.0,
                    "high": 10.1,
                    "low": 9.9,
                    "close": 10.05,
                    "volume": 100,
                    "trade_count": 10,
                }
            ]
        ),
    )

    def fake_build_symbol_day(*args: Any, **kwargs: Any) -> pd.DataFrame:
        captured["build_kwargs"] = kwargs
        return precomputed_symbol_day_features

    def fake_generate_base_from_bundle(*args: Any, **kwargs: Any) -> dict[str, Any]:
        captured["generate_kwargs"] = kwargs
        return {
            "output_paths": {},
            "base_snapshot": pd.DataFrame([{"symbol": "AAA"}]),
            "symbol_day_features": kwargs["symbol_day_features"],
        }

    monkeypatch.setattr(runtime, "build_symbol_day_microstructure_feature_frame", fake_build_symbol_day)
    monkeypatch.setattr(runtime, "generate_base_from_bundle", fake_generate_base_from_bundle)
    monkeypatch.setattr(runtime, "_write_incremental_base_seed", lambda *args, **kwargs: None)

    runtime.run_databento_base_scan_pipeline(
        databento_api_key="dummy-db",
        fmp_api_key="",
        dataset="DBEQ.BASIC",
        export_dir=tmp_path,
        schema_path=SCHEMA_PATH,
        lookback_days=2,
        display_timezone="America/New_York",
        write_xlsx=False,
    )

    assert captured["build_kwargs"]["mutate_input"] is True
    assert callable(captured["build_kwargs"]["telemetry_callback"])
    assert captured["generate_kwargs"]["symbol_day_features"] is precomputed_symbol_day_features
    assert captured["generate_kwargs"]["session_minute_detail"] is None


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
        captured["required_symbols_by_trade_day"] = kwargs.get("required_symbols_by_trade_day")
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
    required_symbols = cast(dict[date, set[str]], captured["required_symbols_by_trade_day"])
    assert expected == {date(2026, 2, 10): {"AAA", "BBB"}}
    assert required_symbols == {date(2026, 2, 10): {"AAA", "BBB"}}


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


def test_build_symbol_day_microstructure_feature_frame_warns_when_midday_detail_is_missing_with_regular_session_activity(
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
                "timestamp": pd.Timestamp("2026-03-20T19:50:00Z"),
                "session": "regular",
                "open": 10.42,
                "high": 10.48,
                "low": 10.25,
                "close": 10.35,
                "volume": 60_000,
                "trade_count": 90,
            },
        ]
    )

    with caplog.at_level("WARNING"):
        output = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)

    row = output.iloc[0]
    assert bool(row["missing_midday_detail"]) is True
    assert "no midday bars" in caplog.text


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


def test_build_base_snapshot_from_bundle_payload_excludes_missing_regular_session_rows_from_minute_derived_20d_means(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
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
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T08:15:00Z"),
                "session": "premarket",
                "open": 10.55,
                "high": 10.6,
                "low": 10.45,
                "close": 10.5,
                "volume": 22_000,
                "trade_count": 35,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T21:25:00Z"),
                "session": "afterhours",
                "open": 10.35,
                "high": 10.4,
                "low": 10.2,
                "close": 10.28,
                "volume": 21_000,
                "trade_count": 22,
            },
        ]
    )

    with caplog.at_level("WARNING"):
        base_snapshot, _, symbol_day = build_base_snapshot_from_bundle_payload(
            bundle_payload,
            schema_path=SCHEMA_PATH,
            session_minute_detail=session_minute_detail,
            asof_date="2026-03-20",
        )

    day_rows = symbol_day.loc[symbol_day["symbol"] == "AAA"].sort_values("trade_date").reset_index(drop=True)
    assert bool(day_rows.loc[1, "missing_regular_session_detail"]) is True

    expected_rth_share = float(day_rows.loc[0, "daily_rth_active_minutes_share"])
    actual_rth_share = float(base_snapshot.loc[0, "rth_active_minutes_share_20d"])
    assert actual_rth_share == pytest.approx(expected_rth_share)
    assert "excluded 1 symbol-day rows from minute-derived 20d aggregation" in caplog.text


def test_build_base_snapshot_from_bundle_payload_excludes_missing_midday_rows_from_minute_derived_20d_means(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
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
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 50_000,
                "trade_count": 75,
            },
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-19T16:15:00Z"),
                "session": "regular",
                "open": 10.2,
                "high": 10.5,
                "low": 10.1,
                "close": 10.4,
                "volume": 45_000,
                "trade_count": 65,
            },
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-19T19:45:00Z"),
                "session": "regular",
                "open": 10.45,
                "high": 10.6,
                "low": 10.35,
                "close": 10.5,
                "volume": 55_000,
                "trade_count": 80,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.7,
                "high": 10.8,
                "low": 10.5,
                "close": 10.6,
                "volume": 80_000,
                "trade_count": 95,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T19:50:00Z"),
                "session": "regular",
                "open": 10.42,
                "high": 10.48,
                "low": 10.25,
                "close": 10.35,
                "volume": 60_000,
                "trade_count": 90,
            },
        ]
    )

    with caplog.at_level("WARNING"):
        base_snapshot, _, symbol_day = build_base_snapshot_from_bundle_payload(
            bundle_payload,
            schema_path=SCHEMA_PATH,
            session_minute_detail=session_minute_detail,
            asof_date="2026-03-20",
        )

    day_rows = symbol_day.loc[symbol_day["symbol"] == "AAA"].sort_values("trade_date").reset_index(drop=True)
    assert bool(day_rows.loc[1, "missing_midday_detail"]) is True

    expected_midday_efficiency = float(day_rows.loc[0, "daily_midday_efficiency"])
    actual_midday_efficiency = float(base_snapshot.loc[0, "midday_efficiency_20d"])
    assert actual_midday_efficiency == pytest.approx(expected_midday_efficiency)
    assert "no midday bars" in caplog.text


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

    monkeypatch.setattr(session_detail, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(session_detail, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(session_detail, "build_cache_path", lambda *args, **kwargs: cache_path)
    monkeypatch.setattr(session_detail, "_read_cached_frame", lambda *args, **kwargs: cached_frame.copy())

    def fail_fetch(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("fetch should not run when cache coverage passes with unresolved sidecar")

    monkeypatch.setattr(session_detail, "_databento_get_range_with_retry", fail_fetch)

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
        warnings.warn("The streaming request had one or more symbols which did not resolve: AACB", stacklevel=2)
        return EmptyStore()

    monkeypatch.setattr(session_detail, "_make_databento_client", lambda api_key: object())
    monkeypatch.setattr(session_detail, "_get_schema_available_end", lambda client, dataset, schema: pd.Timestamp("2026-02-11T03:00:00Z"))
    monkeypatch.setattr(session_detail, "build_cache_path", lambda *args, **kwargs: cache_path)
    monkeypatch.setattr(session_detail, "_read_cached_frame", lambda *args, **kwargs: None)
    monkeypatch.setattr(session_detail, "_databento_get_range_with_retry", fake_get_range)
    monkeypatch.setattr(session_detail, "_store_to_frame", lambda store, count, context: store.to_df(count=count))
    monkeypatch.setattr(
        session_detail,
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
