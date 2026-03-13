from __future__ import annotations

from datetime import UTC, date, datetime, time

import pandas as pd

from scripts.databento_preopen_fast import (
    _choose_scope_days,
    _aggregate_current_premarket_features,
    _build_current_daily_features,
    _resolve_effective_dataset,
    _resolve_premarket_anchor_et,
    _resolve_scope_selection_column,
    _resolve_target_trade_date,
    _select_recent_scope_symbols,
    _write_fast_outputs,
    _target_scope_symbol_count,
)


def test_resolve_target_trade_date_advances_to_current_et_day() -> None:
    completed = [date(2026, 3, 5), date(2026, 3, 6)]
    now_utc = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
    assert _resolve_target_trade_date(completed, now_utc=now_utc) == date(2026, 3, 9)


def test_select_recent_scope_symbols_uses_recent_selected_days() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 5)],
            "symbol": ["AAA", "BBB", "CCC", "AAA"],
            "selected_top20pct": [True, True, False, True],
            "exchange": ["NYSE"] * 4,
            "asset_type": ["listed_equity_issue"] * 4,
            "is_eligible": [True] * 4,
            "eligibility_reason": ["eligible"] * 4,
        }
    )

    result = _select_recent_scope_symbols(frame, scope_days=1)

    assert sorted(result["symbol"].tolist()) == ["AAA"]
    assert bool(result.iloc[0]["selected_top20pct"])


def test_resolve_scope_selection_column_prefers_0400_scope_before_anchor() -> None:
    frame = pd.DataFrame(
        {
            "selected_top20pct": [True, False],
            "selected_top20pct_0400": [False, True],
        }
    )

    result = _resolve_scope_selection_column(
        frame,
        premarket_anchor_et=time(4, 0),
        now_utc=datetime(2026, 3, 9, 7, 30, tzinfo=UTC),
    )

    assert result == "selected_top20pct_0400"


def test_target_scope_symbol_count_varies_by_time() -> None:
    assert _target_scope_symbol_count(now_utc=datetime(2026, 3, 9, 12, 0, tzinfo=UTC)) == 3200
    assert _target_scope_symbol_count(now_utc=datetime(2026, 3, 9, 13, 5, tzinfo=UTC)) == 2400


def test_choose_scope_days_expands_until_target_symbol_count() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)],
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "selected_top20pct": [True, True, True, True],
        }
    )

    scope_days, symbol_count = _choose_scope_days(
        frame,
        min_scope_days=1,
        max_scope_days=4,
        target_symbol_count=3,
        now_utc=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
    )

    assert scope_days == 3
    assert symbol_count == 3


def test_build_current_daily_features_uses_latest_close_as_previous_close() -> None:
    scope_rows = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6)],
            "symbol": ["AAA"],
            "exchange": ["NYSE"],
            "asset_type": ["listed_equity_issue"],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
            "window_range_pct": [4.2],
            "window_return_pct": [2.1],
            "realized_vol_pct": [1.3],
            "selected_top20pct": [True],
            "has_reference_data": [True],
            "has_fundamentals": [False],
            "has_daily_bars": [True],
            "has_intraday": [True],
            "has_market_cap": [False],
        }
    )
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAA", "AAA"],
            "close": [10.0, 11.0],
        }
    )

    result = _build_current_daily_features(scope_rows, daily_bars, target_trade_date=date(2026, 3, 9))

    assert result.iloc[0]["trade_date"] == date(2026, 3, 9)
    assert result.iloc[0]["previous_close"] == 11.0
    assert bool(result.iloc[0]["selected_top20pct"])


def test_build_current_daily_features_preserves_0400_scope_metadata() -> None:
    scope_rows = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6)],
            "symbol": ["AAA"],
            "exchange": ["NYSE"],
            "asset_type": ["listed_equity_issue"],
            "is_eligible": [True],
            "eligibility_reason": ["historical_selected_top20pct_0400_scope"],
            "window_range_pct": [4.2],
            "window_return_pct": [2.1],
            "realized_vol_pct": [1.3],
            "selected_top20pct": [False],
            "selected_top20pct_0400": [True],
            "has_reference_data": [True],
            "has_fundamentals": [False],
            "has_daily_bars": [True],
            "has_intraday": [True],
            "has_market_cap": [False],
        }
    )
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAA", "AAA"],
            "close": [10.0, 11.0],
        }
    )

    result = _build_current_daily_features(scope_rows, daily_bars, target_trade_date=date(2026, 3, 9))

    assert result.iloc[0]["previous_close"] == 11.0
    assert bool(result.iloc[0]["selected_top20pct"]) is False
    assert bool(result.iloc[0]["selected_top20pct_0400"]) is True
    assert result.iloc[0]["eligibility_reason"] == "historical_selected_top20pct_0400_scope"


def test_aggregate_current_premarket_features_computes_gap_metrics() -> None:
    frame = pd.DataFrame(
        {
            "ts": [
                datetime(2026, 3, 9, 13, 0, tzinfo=UTC),
                datetime(2026, 3, 9, 13, 0, 1, tzinfo=UTC),
            ],
            "symbol": ["AAA", "AAA"],
            "open": [10.0, 10.2],
            "high": [10.2, 10.5],
            "low": [9.9, 10.1],
            "close": [10.2, 10.5],
            "volume": [100, 150],
        }
    )

    result = _aggregate_current_premarket_features(
        frame,
        {"AAA": 10.0},
        target_trade_date=date(2026, 3, 9),
        premarket_start_utc=datetime(2026, 3, 9, 13, 0, tzinfo=UTC),
    )

    assert bool(result.iloc[0]["has_premarket_data"])
    assert result.iloc[0]["premarket_last"] == 10.5
    assert round(float(result.iloc[0]["prev_close_to_premarket_pct"]), 4) == 5.0


def test_resolve_effective_dataset_uses_available_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.databento_preopen_fast.list_accessible_datasets",
        lambda api_key: ["XNAS.BASIC", "DBEQ.BASIC"],
    )

    resolved, available = _resolve_effective_dataset("test-key", "unknown.dataset")

    assert resolved == "DBEQ.BASIC"
    assert available == ["XNAS.BASIC", "DBEQ.BASIC"]


def test_resolve_effective_dataset_gracefully_handles_dataset_listing_errors(monkeypatch) -> None:
    def fail_list(api_key):
        raise RuntimeError("401 unauthorized")

    monkeypatch.setattr("scripts.databento_preopen_fast.list_accessible_datasets", fail_list)

    resolved, available = _resolve_effective_dataset("test-key", "xnas.basic")

    assert resolved == "XNAS.BASIC"
    assert available == []


def test_resolve_premarket_anchor_et_parses_manifest_or_defaults() -> None:
    assert _resolve_premarket_anchor_et({"premarket_anchor_et": "04:00:00"}) == time(4, 0)
    assert _resolve_premarket_anchor_et({"premarket_anchor_et": "04:15"}) == time(4, 15)
    assert _resolve_premarket_anchor_et({"premarket_anchor_et": "invalid"}) == time(4, 0)
    assert _resolve_premarket_anchor_et({}) == time(4, 0)


def test_run_preopen_fast_refresh_raises_when_all_batches_fail(monkeypatch, tmp_path) -> None:
    from scripts.databento_preopen_fast import run_preopen_fast_refresh

    trade_day = date(2026, 3, 6)
    payload = {
        "manifest": {"premarket_anchor_et": "04:00:00"},
        "manifest_path": tmp_path / "baseline_manifest.json",
        "base_prefix": "baseline",
        "frames": {
            "daily_symbol_features_full_universe": pd.DataFrame(
                {
                    "trade_date": [trade_day],
                    "symbol": ["AAA"],
                    "selected_top20pct": [True],
                    "exchange": ["NYSE"],
                    "asset_type": ["listed_equity_issue"],
                    "is_eligible": [True],
                    "eligibility_reason": ["eligible"],
                    "has_fundamentals": [False],
                    "has_reference_data": [True],
                    "has_market_cap": [False],
                    "window_range_pct": [1.0],
                    "window_return_pct": [1.0],
                    "realized_vol_pct": [1.0],
                }
            ),
            "daily_bars": pd.DataFrame(
                {
                    "trade_date": [trade_day],
                    "symbol": ["AAA"],
                    "close": [10.0],
                }
            ),
        },
    }

    class _FailingTimeseries:
        def get_range(self, **kwargs):
            raise RuntimeError("simulated fetch failure")

    class _FailingMetadata:
        def get_dataset_range(self, **kwargs):
            return None

    class _FailingClient:
        timeseries = _FailingTimeseries()
        metadata = _FailingMetadata()

    monkeypatch.setattr("scripts.databento_preopen_fast.load_export_bundle", lambda bundle, **kwargs: payload)
    monkeypatch.setattr("scripts.databento_preopen_fast.list_accessible_datasets", lambda api_key: ["DBEQ.BASIC"])
    monkeypatch.setattr("scripts.databento_preopen_fast._make_databento_client", lambda api_key: _FailingClient())

    try:
        run_preopen_fast_refresh(
            databento_api_key="test-key",
            dataset="DBEQ.BASIC",
            export_dir=tmp_path,
            bundle=tmp_path,
            scope_days=1,
        )
    except RuntimeError as exc:
        assert "Premarket fetch failed for all symbol batches" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when all premarket fetch batches fail")


def test_run_preopen_fast_refresh_skips_fetch_when_dataset_not_available(monkeypatch, tmp_path) -> None:
    """When the dataset available_end is before premarket start, no fetch is
    attempted and no RuntimeError is raised (graceful empty result)."""
    from scripts.databento_preopen_fast import run_preopen_fast_refresh

    trade_day = date(2026, 3, 10)
    payload = {
        "manifest": {"premarket_anchor_et": "08:00:00"},
        "manifest_path": tmp_path / "baseline_manifest.json",
        "base_prefix": "baseline",
        "frames": {
            "daily_symbol_features_full_universe": pd.DataFrame(
                {
                    "trade_date": [trade_day - pd.Timedelta(days=1)],
                    "symbol": ["AAA"],
                    "selected_top20pct": [True],
                    "exchange": ["NYSE"],
                    "asset_type": ["listed_equity_issue"],
                    "is_eligible": [True],
                    "eligibility_reason": ["eligible"],
                    "has_fundamentals": [False],
                    "has_reference_data": [True],
                    "has_market_cap": [False],
                    "window_range_pct": [1.0],
                    "window_return_pct": [1.0],
                    "realized_vol_pct": [1.0],
                }
            ),
            "daily_bars": pd.DataFrame(
                {
                    "trade_date": [trade_day - pd.Timedelta(days=1)],
                    "symbol": ["AAA"],
                    "close": [10.0],
                }
            ),
        },
    }

    class _NeverCalledTimeseries:
        def get_range(self, **kwargs):
            raise AssertionError("get_range should not be called when dataset is unavailable")

    class _EarlyEndMetadata:
        def get_dataset_range(self, **kwargs):
            # available_end is midnight of trade_day — earlier than premarket start
            return {"end": f"{trade_day.isoformat()}T00:00:00+00:00"}

    class _MockClient:
        timeseries = _NeverCalledTimeseries()
        metadata = _EarlyEndMetadata()

    monkeypatch.setattr("scripts.databento_preopen_fast.load_export_bundle", lambda bundle, **kwargs: payload)
    monkeypatch.setattr("scripts.databento_preopen_fast.list_accessible_datasets", lambda api_key: ["DBEQ.BASIC"])
    monkeypatch.setattr("scripts.databento_preopen_fast._make_databento_client", lambda api_key: _MockClient())

    result = run_preopen_fast_refresh(
        databento_api_key="test-key",
        dataset="DBEQ.BASIC",
        export_dir=tmp_path,
        bundle=tmp_path,
        scope_days=1,
    )
    # Should succeed without error — the fetch is skipped because the
    # clamped end is before the premarket start.
    assert result is not None


def test_write_fast_outputs_preserves_existing_when_current_frame_empty(tmp_path) -> None:
    trade_day = date(2026, 3, 10)
    existing_daily = pd.DataFrame({"trade_date": [trade_day], "symbol": ["AAA"]})
    existing_daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)

    existing_premarket = pd.DataFrame({"trade_date": [trade_day], "symbol": ["AAA"], "has_premarket_data": [True]})
    existing_premarket.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    existing_diag = pd.DataFrame({"trade_date": [trade_day], "symbol": ["AAA"]})
    existing_diag.to_parquet(tmp_path / "symbol_day_diagnostics.parquet", index=False)

    existing_window = pd.DataFrame({"trade_date": [trade_day], "symbol": ["AAA"], "window_tag": ["pm_0800_0900"]})
    existing_window.to_parquet(tmp_path / "premarket_window_features_full_universe.parquet", index=False)

    existing_status = pd.DataFrame({"symbol": ["AAA"], "quality_open_drive_window_latest_berlin": ["14:00-15:00"]})
    existing_status.to_parquet(tmp_path / "quality_window_status_latest.parquet", index=False)

    manifest = {"basename": "databento_preopen_fast_test"}
    _write_fast_outputs(
        tmp_path,
        daily_current=pd.DataFrame(),
        premarket_current=pd.DataFrame(),
        diagnostics_current=pd.DataFrame(),
        premarket_window_current=pd.DataFrame(),
        quality_window_status_latest=pd.DataFrame(),
        manifest=manifest,
    )

    assert pd.read_parquet(tmp_path / "daily_symbol_features_full_universe.parquet").equals(existing_daily)
    assert pd.read_parquet(tmp_path / "premarket_features_full_universe.parquet").equals(existing_premarket)
    assert pd.read_parquet(tmp_path / "symbol_day_diagnostics.parquet").equals(existing_diag)
    assert pd.read_parquet(tmp_path / "premarket_window_features_full_universe.parquet").equals(existing_window)
    assert pd.read_parquet(tmp_path / "quality_window_status_latest.parquet").equals(existing_status)