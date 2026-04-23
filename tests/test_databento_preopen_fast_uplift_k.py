"""Coverage uplift bucket K — `scripts/databento_preopen_fast.py`.

Targets the small/medium pure helpers and `main()` error path. Avoids
the giant orchestrator block in `run_preopen_fast_refresh` (lines
789-1019) which requires databento client + bundle scaffolding beyond
this bucket's scope.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from scripts import databento_preopen_fast as mod
from scripts.databento_preopen_fast import (
    DEFAULT_FAST_SCOPE_MIN_DAYS,
    DEFAULT_SCOPE_SELECTION_COLUMN,
    EARLY_SCOPE_SELECTION_COLUMN,
    FAST_SCOPE_CALIBRATION_DAYS,
    _aggregate_current_premarket_features,
    _build_current_daily_features,
    _build_current_diagnostics,
    _build_current_second_detail_from_premarket_raw,
    _choose_scope_days,
    _extract_live_license_cutoff_utc,
    _merge_current_structure_features,
    _normalize_exchange_label,
    _normalize_trade_date,
    _recent_scope_symbol_counts,
    _resolve_effective_dataset,
    _resolve_full_history_bundle_input,
    _resolve_premarket_anchor_et,
    _resolve_scope_selection_column,
    _resolve_target_trade_date,
    _select_recent_scope_symbols,
    _target_scope_symbol_count,
)

# ── _normalize_exchange_label ──────────────────────────────────


class TestNormalizeExchangeLabel:
    def test_blank_returns_empty(self):
        assert _normalize_exchange_label(None) == ""
        assert _normalize_exchange_label("") == ""
        assert _normalize_exchange_label("   ") == ""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("nasdaq", "NASDAQ"),
            ("xnas", "NASDAQ"),
            ("nms", "NASDAQ"),
            ("xnys", "NYSE"),
            ("nyse", "NYSE"),
            ("nyse american", "AMEX"),
            ("xase", "AMEX"),
            ("arcx", "AMEX"),
        ],
    )
    def test_known_aliases(self, raw, expected):
        assert _normalize_exchange_label(raw) == expected

    def test_unknown_label_passthrough(self):
        assert _normalize_exchange_label("custom_x") == "CUSTOM_X"


# ── _extract_live_license_cutoff_utc ───────────────────────────


class TestExtractLiveLicenseCutoffUtc:
    def test_returns_none_when_marker_missing(self):
        assert _extract_live_license_cutoff_utc("just an error") is None
        assert _extract_live_license_cutoff_utc("") is None
        assert _extract_live_license_cutoff_utc(None) is None

    def test_returns_none_when_no_after_match(self):
        assert _extract_live_license_cutoff_utc("license_not_found_unauthorized at some place") is None

    def test_returns_none_when_timestamp_unparseable(self):
        assert _extract_live_license_cutoff_utc("license_not_found_unauthorized after garbage-stamp") is None

    def test_returns_one_second_before_after_z(self):
        out = _extract_live_license_cutoff_utc("license_not_found_unauthorized after 2026-04-23T13:00:00Z.")
        assert out == datetime(2026, 4, 23, 12, 59, 59, tzinfo=UTC)

    def test_returns_one_second_before_naive_localized_to_utc(self):
        out = _extract_live_license_cutoff_utc("license_not_found_unauthorized after 2026-04-23T13:00:00")
        assert out == datetime(2026, 4, 23, 12, 59, 59, tzinfo=UTC)


# ── _resolve_effective_dataset ────────────────────────────────


class TestResolveEffectiveDataset:
    def test_returns_requested_when_listing_raises(self):
        with patch.object(mod, "list_accessible_datasets", side_effect=RuntimeError("boom")):
            ds, available = _resolve_effective_dataset("k", "DBEQ.BASIC")
        assert ds == "DBEQ.BASIC"
        assert available == []

    def test_returns_default_when_listing_raises_with_blank_request(self):
        with patch.object(mod, "list_accessible_datasets", side_effect=RuntimeError("boom")):
            ds, _ = _resolve_effective_dataset("k", "")
        assert ds == "DBEQ.BASIC"

    def test_returns_default_when_available_empty(self):
        with patch.object(mod, "list_accessible_datasets", return_value=[]):
            ds, available = _resolve_effective_dataset("k", "DBEQ.BASIC")
        assert ds == "DBEQ.BASIC"
        assert available == []

    def test_uses_choose_default_dataset(self):
        with (
            patch.object(mod, "list_accessible_datasets", return_value=["xnas.basic", "dbeq.basic"]),
            patch.object(mod, "choose_default_dataset", return_value="DBEQ.BASIC") as choose,
        ):
            ds, available = _resolve_effective_dataset("k", "dbeq.basic")
        assert ds == "DBEQ.BASIC"
        assert "DBEQ.BASIC" in available
        choose.assert_called_once()


# ── _resolve_premarket_anchor_et ──────────────────────────────


class TestResolvePremarketAnchorEt:
    def test_default_when_missing(self):
        assert _resolve_premarket_anchor_et({}) == time(4, 0)
        assert _resolve_premarket_anchor_et({"premarket_anchor_et": ""}) == time(4, 0)

    def test_parses_hms_format(self):
        assert _resolve_premarket_anchor_et({"premarket_anchor_et": "04:30:00"}) == time(4, 30, 0)

    def test_parses_hm_format(self):
        assert _resolve_premarket_anchor_et({"premarket_anchor_et": "05:15"}) == time(5, 15)

    def test_invalid_falls_back_to_default(self):
        assert _resolve_premarket_anchor_et({"premarket_anchor_et": "not-a-time"}) == time(4, 0)


# ── _normalize_trade_date ─────────────────────────────────────


class TestNormalizeTradeDate:
    def test_normalizes_dates_and_symbols(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["2026-04-23", "2026-04-22"],
                "symbol": ["aapl", "tsla"],
            }
        )
        out = _normalize_trade_date(frame)
        assert out["trade_date"].tolist() == [date(2026, 4, 23), date(2026, 4, 22)]
        assert out["symbol"].tolist() == ["AAPL", "TSLA"]

    def test_no_symbol_column(self):
        frame = pd.DataFrame({"trade_date": ["2026-04-23"]})
        out = _normalize_trade_date(frame)
        assert "symbol" not in out.columns
        assert out["trade_date"].tolist() == [date(2026, 4, 23)]


# ── _resolve_full_history_bundle_input ─────────────────────────


class TestResolveFullHistoryBundleInput:
    def test_existing_file(self, tmp_path: Path):
        f = tmp_path / "manifest.json"
        f.write_text("{}")
        out = _resolve_full_history_bundle_input(f, tmp_path)
        assert out == f

    def test_existing_dir_with_manifests_picks_latest(self, tmp_path: Path):
        m1 = tmp_path / "databento_volatility_production_old_manifest.json"
        m2 = tmp_path / "databento_volatility_production_new_manifest.json"
        m1.write_text("{}")
        m2.write_text("{}")
        # Touch m2 to be more recent.
        import time as _t

        _t.sleep(0.01)
        m2.touch()
        out = _resolve_full_history_bundle_input(None, tmp_path)
        assert out == m2

    def test_existing_dir_without_manifests_returns_dir(self, tmp_path: Path):
        out = _resolve_full_history_bundle_input(None, tmp_path)
        assert out == tmp_path

    def test_non_existent_returns_path_as_is(self, tmp_path: Path):
        ghost = tmp_path / "ghost"
        out = _resolve_full_history_bundle_input(ghost, tmp_path)
        assert out == ghost


# ── _resolve_target_trade_date ────────────────────────────────


class TestResolveTargetTradeDate:
    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _resolve_target_trade_date([])

    def test_returns_today_if_after_latest_completed(self):
        now_utc = datetime(2026, 4, 23, 14, 0, tzinfo=UTC)
        out = _resolve_target_trade_date([date(2026, 4, 22)], now_utc=now_utc)
        assert out == date(2026, 4, 23)

    def test_returns_latest_completed_when_today_already_in_set(self):
        now_utc = datetime(2026, 4, 23, 14, 0, tzinfo=UTC)
        out = _resolve_target_trade_date([date(2026, 4, 23)], now_utc=now_utc)
        assert out == date(2026, 4, 23)


# ── _target_scope_symbol_count ────────────────────────────────


class TestTargetScopeSymbolCount:
    @pytest.mark.parametrize(
        "hour,minute,expected",
        [
            (8, 0, 3200),
            (8, 29, 3200),
            (8, 30, 2800),
            (8, 59, 2800),
            (9, 0, 2400),
            (9, 19, 2400),
            (9, 20, 2100),
            (9, 29, 2100),
        ],
    )
    def test_buckets(self, hour, minute, expected):
        et_dt = datetime(2026, 4, 23, hour, minute, tzinfo=mod.US_EASTERN_TZ)
        out = _target_scope_symbol_count(now_utc=et_dt.astimezone(UTC))
        assert out == expected


# ── _recent_scope_symbol_counts ───────────────────────────────


def _make_daily_features(rows: list[tuple[str, str, bool]]) -> pd.DataFrame:
    """rows = list of (trade_date, symbol, selected_top20pct)."""
    return pd.DataFrame(
        [{"trade_date": td, "symbol": sym, DEFAULT_SCOPE_SELECTION_COLUMN: sel} for td, sym, sel in rows]
    )


class TestRecentScopeSymbolCounts:
    def test_no_selected_returns_zero_per_window(self):
        frame = _make_daily_features(
            [
                ("2026-04-22", "AAPL", False),
            ]
        )
        out = _recent_scope_symbol_counts(frame)
        assert out == {int(d): 0 for d in FAST_SCOPE_CALIBRATION_DAYS}

    def test_counts_unique_symbols_per_window(self):
        rows = []
        for i in range(15):
            (date(2026, 4, 1) + pd.Timedelta(days=i)).date() if False else None
        # Build 15 days of selected rows (1 symbol per day for clarity).
        rows = [(f"2026-04-{i + 1:02d}", f"S{i}", True) for i in range(15)]
        frame = _make_daily_features(rows)
        out = _recent_scope_symbol_counts(frame)
        assert out[5] == 5
        assert out[15] == 15


# ── _resolve_scope_selection_column ───────────────────────────


class TestResolveScopeSelectionColumn:
    def test_default_when_now_after_anchor(self):
        frame = _make_daily_features([("2026-04-23", "AAPL", True)])
        # Build now_utc such that ET time is 05:00 (after anchor 04:00)
        now_et = datetime(2026, 4, 23, 5, 0, tzinfo=mod.US_EASTERN_TZ)
        out = _resolve_scope_selection_column(
            frame,
            premarket_anchor_et=time(4, 0),
            now_utc=now_et.astimezone(UTC),
        )
        assert out == DEFAULT_SCOPE_SELECTION_COLUMN

    def test_early_when_before_anchor_and_column_present(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["2026-04-23"],
                "symbol": ["AAPL"],
                DEFAULT_SCOPE_SELECTION_COLUMN: [False],
                EARLY_SCOPE_SELECTION_COLUMN: [True],
            }
        )
        now_et = datetime(2026, 4, 23, 3, 0, tzinfo=mod.US_EASTERN_TZ)
        out = _resolve_scope_selection_column(
            frame,
            premarket_anchor_et=time(4, 0),
            now_utc=now_et.astimezone(UTC),
        )
        assert out == EARLY_SCOPE_SELECTION_COLUMN

    def test_default_when_early_column_present_but_empty(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["2026-04-23"],
                "symbol": ["AAPL"],
                DEFAULT_SCOPE_SELECTION_COLUMN: [True],
                EARLY_SCOPE_SELECTION_COLUMN: [False],
            }
        )
        now_et = datetime(2026, 4, 23, 3, 0, tzinfo=mod.US_EASTERN_TZ)
        out = _resolve_scope_selection_column(
            frame,
            premarket_anchor_et=time(4, 0),
            now_utc=now_et.astimezone(UTC),
        )
        assert out == DEFAULT_SCOPE_SELECTION_COLUMN


# ── _choose_scope_days ────────────────────────────────────────


class TestChooseScopeDays:
    def test_invalid_min_raises(self):
        with pytest.raises(ValueError, match="min_scope_days"):
            _choose_scope_days(_make_daily_features([]), min_scope_days=0)

    def test_invalid_max_raises(self):
        with pytest.raises(ValueError, match="max_scope_days"):
            _choose_scope_days(_make_daily_features([]), min_scope_days=5, max_scope_days=3)

    def test_empty_returns_min_zero(self):
        out = _choose_scope_days(
            _make_daily_features(
                [
                    ("2026-04-22", "AAPL", False),
                ]
            )
        )
        assert out == (DEFAULT_FAST_SCOPE_MIN_DAYS, 0)

    def test_meets_target_count(self):
        rows = [(f"2026-04-{i + 1:02d}", f"S{i}", True) for i in range(15)]
        frame = _make_daily_features(rows)
        days, count = _choose_scope_days(
            frame,
            min_scope_days=5,
            max_scope_days=15,
            target_symbol_count=5,
        )
        assert days == 5
        assert count == 5

    def test_grows_until_max(self):
        rows = [(f"2026-04-{i + 1:02d}", f"S{i}", True) for i in range(15)]
        frame = _make_daily_features(rows)
        days, count = _choose_scope_days(
            frame,
            min_scope_days=5,
            max_scope_days=15,
            target_symbol_count=999,
        )
        assert days == 15
        assert count == 15


# ── _select_recent_scope_symbols ──────────────────────────────


class TestSelectRecentScopeSymbols:
    def test_invalid_scope_raises(self):
        with pytest.raises(ValueError, match="scope_days"):
            _select_recent_scope_symbols(_make_daily_features([]), scope_days=0)

    def test_no_selected_returns_empty_with_columns(self):
        frame = _make_daily_features([("2026-04-22", "AAPL", False)])
        out = _select_recent_scope_symbols(frame, scope_days=5)
        assert out.empty

    def test_returns_latest_per_symbol_with_marker_columns(self):
        rows = [
            ("2026-04-21", "AAPL", True),
            ("2026-04-22", "AAPL", True),
            ("2026-04-22", "TSLA", True),
        ]
        frame = _make_daily_features(rows)
        out = _select_recent_scope_symbols(frame, scope_days=5)
        symbols = sorted(out["symbol"].tolist())
        assert symbols == ["AAPL", "TSLA"]
        assert out["is_eligible"].all()
        assert out[DEFAULT_SCOPE_SELECTION_COLUMN].all()

    def test_uses_early_selection_column_marker(self):
        rows = [
            {
                "trade_date": "2026-04-22",
                "symbol": "AAPL",
                DEFAULT_SCOPE_SELECTION_COLUMN: False,
                EARLY_SCOPE_SELECTION_COLUMN: True,
            },
        ]
        frame = pd.DataFrame(rows)
        out = _select_recent_scope_symbols(
            frame,
            scope_days=5,
            selection_column=EARLY_SCOPE_SELECTION_COLUMN,
        )
        assert out[EARLY_SCOPE_SELECTION_COLUMN].all()
        assert not out[DEFAULT_SCOPE_SELECTION_COLUMN].any()


# ── _build_current_daily_features ─────────────────────────────


class TestBuildCurrentDailyFeatures:
    def test_empty_scope_returns_empty_with_columns(self):
        out = _build_current_daily_features(
            pd.DataFrame(),
            pd.DataFrame({"trade_date": [date(2026, 4, 22)], "symbol": ["AAPL"], "close": [100.0]}),
            target_trade_date=date(2026, 4, 23),
        )
        assert out.empty
        assert "previous_close" in out.columns or "symbol" in out.columns

    def test_merges_previous_close_and_marks_eligibility(self):
        scope = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 22), date(2026, 4, 22)],
                "symbol": ["AAPL", "MISSING"],
                DEFAULT_SCOPE_SELECTION_COLUMN: [True, True],
                EARLY_SCOPE_SELECTION_COLUMN: [False, False],
            }
        )
        bars = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 22)],
                "symbol": ["AAPL"],
                "close": [100.0],
            }
        )
        out = _build_current_daily_features(
            scope,
            bars,
            target_trade_date=date(2026, 4, 23),
        )
        out_by_symbol = out.set_index("symbol")
        assert out_by_symbol.loc["AAPL", "previous_close"] == 100.0
        assert bool(out_by_symbol.loc["AAPL", "is_eligible"]) is True
        assert bool(out_by_symbol.loc["MISSING", "is_eligible"]) is False
        assert out_by_symbol.loc["MISSING", "eligibility_reason"] == "missing_latest_close"


# ── _aggregate_current_premarket_features ─────────────────────


class TestAggregateCurrentPremarketFeatures:
    def test_empty_frame_returns_no_premarket_data(self):
        prev = {"AAPL": 100.0, "TSLA": 200.0}
        out = _aggregate_current_premarket_features(
            pd.DataFrame(),
            prev,
            target_trade_date=date(2026, 4, 23),
            premarket_start_utc=datetime(2026, 4, 23, 8, 0, tzinfo=UTC),
        )
        assert (out["has_premarket_data"] == False).all()  # noqa: E712
        assert sorted(out["symbol"]) == ["AAPL", "TSLA"]

    def test_filters_out_pre_anchor_bars(self):
        prev = {"AAPL": 100.0}
        anchor = datetime(2026, 4, 23, 8, 0, tzinfo=UTC)
        # Single bar before anchor → recursion to empty branch.
        frame = pd.DataFrame(
            {
                "ts": [anchor - pd.Timedelta(seconds=10)],
                "symbol": ["AAPL"],
                "open": [99.0],
                "high": [99.5],
                "low": [98.5],
                "close": [99.2],
                "volume": [10],
            }
        )
        out = _aggregate_current_premarket_features(
            frame,
            prev,
            target_trade_date=date(2026, 4, 23),
            premarket_start_utc=anchor,
        )
        assert (out["has_premarket_data"] == False).all()  # noqa: E712

    def test_aggregates_metrics_with_actual_trade_count(self):
        prev = {"AAPL": 100.0}
        anchor = datetime(2026, 4, 23, 8, 0, tzinfo=UTC)
        rows = [
            {
                "ts": anchor + pd.Timedelta(seconds=1),
                "symbol": "AAPL",
                "open": 99.0,
                "high": 99.5,
                "low": 98.5,
                "close": 99.2,
                "volume": 100,
                "trade_count": 5,
            },
            {
                "ts": anchor + pd.Timedelta(seconds=2),
                "symbol": "AAPL",
                "open": 99.2,
                "high": 99.6,
                "low": 99.0,
                "close": 99.4,
                "volume": 200,
                "trade_count": 10,
            },
        ]
        out = _aggregate_current_premarket_features(
            pd.DataFrame(rows),
            prev,
            target_trade_date=date(2026, 4, 23),
            premarket_start_utc=anchor,
        )
        row = out.set_index("symbol").loc["AAPL"]
        assert row["has_premarket_data"]
        assert row["premarket_volume"] == 300
        assert row["premarket_trade_count"] == 15
        assert row["premarket_trade_count_source"] == "actual"

    def test_proxy_active_seconds_when_no_trade_count(self):
        prev = {"AAPL": 100.0}
        anchor = datetime(2026, 4, 23, 8, 0, tzinfo=UTC)
        rows = [
            {
                "ts": anchor + pd.Timedelta(seconds=1),
                "symbol": "AAPL",
                "open": 99.0,
                "high": 99.5,
                "low": 98.5,
                "close": 99.2,
                "volume": 100,
            },
            {
                "ts": anchor + pd.Timedelta(seconds=2),
                "symbol": "AAPL",
                "open": 99.2,
                "high": 99.6,
                "low": 99.0,
                "close": 99.4,
                "volume": 0,
            },  # not active
        ]
        out = _aggregate_current_premarket_features(
            pd.DataFrame(rows),
            prev,
            target_trade_date=date(2026, 4, 23),
            premarket_start_utc=anchor,
        )
        row = out.set_index("symbol").loc["AAPL"]
        assert row["premarket_trade_count_source"] == "proxy_active_seconds"
        assert row["premarket_trade_count"] == 1


# ── _build_current_diagnostics ────────────────────────────────


class TestBuildCurrentDiagnostics:
    def test_empty_returns_columns(self):
        out = _build_current_diagnostics(pd.DataFrame())
        assert out.empty
        assert "trade_date" in out.columns

    def test_maps_columns_from_daily_current(self):
        daily = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
                "exchange": ["NASDAQ"],
                "asset_type": ["stock"],
                "is_eligible": [True],
                "eligibility_reason": ["ok"],
                "selected_top20pct": [True],
                "selected_top20pct_0400": [False],
                "has_reference_data": [True],
                "has_fundamentals": [True],
                "has_daily_bars": [True],
                "has_market_cap": [True],
            }
        )
        out = _build_current_diagnostics(daily)
        assert out["excluded_step"].iloc[0] == "preopen_fast_scope"
        assert bool(out["present_in_eligible"].iloc[0]) is True
        assert bool(out["has_intraday"].iloc[0]) is False


# ── _build_current_second_detail_from_premarket_raw ───────────


class TestBuildCurrentSecondDetail:
    def test_empty_returns_columns(self):
        out = _build_current_second_detail_from_premarket_raw(
            pd.DataFrame(),
            target_trade_date=date(2026, 4, 23),
        )
        assert out.empty
        assert "trade_date" in out.columns
        assert "session" in out.columns

    def test_inserts_trade_date_and_session(self):
        frame = pd.DataFrame(
            {
                "ts": [datetime(2026, 4, 23, 8, 1, tzinfo=UTC)],
                "symbol": ["aapl"],
                "open": [99.0],
                "high": [99.5],
                "low": [98.5],
                "close": [99.2],
                "volume": [100],
            }
        )
        out = _build_current_second_detail_from_premarket_raw(
            frame,
            target_trade_date=date(2026, 4, 23),
        )
        assert out["session"].iloc[0] == "premarket"
        assert out["symbol"].iloc[0] == "AAPL"
        assert out["trade_date"].iloc[0] == date(2026, 4, 23)


# ── _merge_current_structure_features ─────────────────────────


class TestMergeCurrentStructureFeatures:
    def test_empty_daily_returns_copy(self):
        out = _merge_current_structure_features(pd.DataFrame(), pd.DataFrame())
        assert out.empty

    def test_empty_detail_returns_daily_copy(self):
        daily = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]})
        out = _merge_current_structure_features(daily, pd.DataFrame())
        assert out.equals(daily)

    def test_returns_daily_when_structure_features_empty(self):
        daily = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]})
        detail = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]})
        with patch.object(mod, "build_market_structure_feature_frame", return_value=pd.DataFrame()):
            out = _merge_current_structure_features(daily, detail)
        assert out.equals(daily)

    def test_merges_structure_features_dropping_overlap(self):
        daily = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"], "structure_x": [9.0]})
        detail = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]})
        struct = pd.DataFrame(
            {"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"], "structure_x": [1.0], "structure_y": [2.0]}
        )
        with patch.object(mod, "build_market_structure_feature_frame", return_value=struct):
            out = _merge_current_structure_features(daily, detail)
        assert out["structure_x"].iloc[0] == 1.0
        assert out["structure_y"].iloc[0] == 2.0


# ── main() error path ─────────────────────────────────────────


class TestMainError:
    def test_missing_api_key_returns_2(self, monkeypatch, capsys):
        monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
        monkeypatch.setattr("sys.argv", ["databento_preopen_fast"])
        # Avoid loading project .env which may set DATABENTO_API_KEY.
        with patch.object(mod, "load_dotenv"):
            ret = mod.main()
        assert ret == 2
        printed = capsys.readouterr().out
        payload = json.loads(printed)
        assert payload["error"] == "DATABENTO_API_KEY missing"

    def test_invokes_orchestrator_when_key_present(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABENTO_API_KEY", "test-key")
        monkeypatch.setattr("sys.argv", ["databento_preopen_fast"])
        fake_result = {
            "manifest": {"basename": "x"},
            "paths": {"daily": Path("/tmp/d")},
            "daily_current": pd.DataFrame({"a": [1]}),
            "premarket_current": pd.DataFrame({"a": [1, 2]}),
        }
        with (
            patch.object(mod, "load_dotenv"),
            patch.object(mod, "run_preopen_fast_refresh", return_value=fake_result) as run_mock,
        ):
            ret = mod.main()
        assert ret == 0
        assert run_mock.called
        payload = json.loads(capsys.readouterr().out)
        assert payload["daily_rows"] == 1
        assert payload["premarket_rows"] == 2
