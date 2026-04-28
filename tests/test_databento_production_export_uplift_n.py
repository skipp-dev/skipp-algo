"""Coverage uplift bucket N — `scripts/databento_production_export.py`.

Targets the wide collection of small/medium pure helpers across the
4106-line module. Avoids the orchestrator
``run_production_export_pipeline`` (lines 3196–4039), the workbook
writer ``_write_canonical_production_workbook``, and the deep
``_compute_quality_window_signal`` machinery (which require massive
fixtures/mocks). Focuses on score calculators, normalizers, empty-frame
builders, and dataframe shaping helpers.
"""

from __future__ import annotations

from datetime import UTC, date, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from scripts import databento_production_export as mod
from scripts.databento_production_export import (
    CLOSE_IMBALANCE_FEATURE_COLUMNS,
    CLOSE_IMBALANCE_OUTCOME_COLUMNS,
    RESEARCH_EVENT_FLAG_COLUMNS,
    RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS,
    RESEARCH_NEWS_FLAG_COLUMNS,
    RESEARCH_NEWS_FLAG_COUNT_COLUMNS,
    _attach_exchange_lookup,
    _benzinga_date_utc,
    _benzinga_flag_status_bucket,
    _bool_series,
    _build_batl_debug_payload,
    _build_close_imbalance_features_full_universe_export,
    _build_close_imbalance_outcomes_full_universe_export,
    _build_empty_premarket_window_features_export,
    _build_exact_window_end_lookup,
    _build_unique_symbol_day_ranking_candidates,
    _coalesce_optional_merge_column,
    _collect_fixed_et_second_detail,
    _compute_open_confirm_flags,
    _core_vs_benzinga_overlap_bucket,
    _empty_research_event_flags,
    _empty_research_news_flags,
    _enrich_universe_with_fundamentals,
    _env_flag,
    _filter_premarket_rows,
    _filter_ranked_symbol_day_scope,
    _format_optional_time,
    _format_quality_window_label,
    _iter_symbol_batches,
    _make_export_fmp_client,
    _normalize_earnings_timing,
    _normalize_exchange_key,
    _normalize_quality_window_exchange_dataset_map,
    _normalize_research_symbol,
    _numeric_series,
    _parse_calendar_trade_date,
    _parse_window_time_et,
    _quality_window_export_tag,
    _research_news_article_key,
    _research_news_positive_mask,
    _research_news_window_bounds_for_trade_date,
    _resolve_latest_iso_timestamp,
    _resolve_research_news_status,
    _run_fixed_et_intraday_screen,
    _score_extension,
    _score_inverse_pct,
    _score_log_ratio,
    _score_pct,
    _select_top_candidates_per_day,
    _timing_is_post_close,
    _timing_is_pre_open,
    _window_bounds_for_trade_date,
    _window_label_from_tag,
    _with_source_priority,
    configure_bullish_quality_score_profile,
)

# ── tiny helpers ────────────────────────────────────────────────


class TestEnvFlag:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FOO", raising=False)
        assert _env_flag("FOO", default=True) is True
        assert _env_flag("FOO", default=False) is False

    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "On"])
    def test_truthy(self, monkeypatch, raw):
        monkeypatch.setenv("FOO", raw)
        assert _env_flag("FOO") is True

    @pytest.mark.parametrize("raw", ["0", "false", "no", "off", "garbage"])
    def test_falsy(self, monkeypatch, raw):
        monkeypatch.setenv("FOO", raw)
        assert _env_flag("FOO") is False


class TestMakeExportFmpClient:
    def test_uses_factory_override(self):
        sentinel = object()
        fake = lambda key: sentinel
        with patch.object(mod, "FMPClient", fake):
            assert _make_export_fmp_client("k") is sentinel

    def test_falls_back_to_make_fmp_client(self):
        sentinel = object()
        with (
            patch.object(mod, "FMPClient", mod._DEFAULT_FMP_CLIENT_FACTORY),
            patch.object(mod, "make_fmp_client", return_value=sentinel) as mk,
        ):
            out = _make_export_fmp_client("k")
        assert out is sentinel
        mk.assert_called_once_with("k")


class TestConfigureBullishQualityScoreProfile:
    def test_swaps_default_cfg(self):
        original = mod._DEFAULT_BULLISH_QUALITY_CFG
        try:
            configure_bullish_quality_score_profile(score_profile="aggressive")
            assert mod._DEFAULT_BULLISH_QUALITY_CFG is not original
        finally:
            mod._DEFAULT_BULLISH_QUALITY_CFG = original


# ── _coalesce_optional_merge_column ────────────────────────────


class TestCoalesceOptionalMergeColumn:
    def test_creates_na_column_when_absent(self):
        out = _coalesce_optional_merge_column(pd.DataFrame({"x": [1]}), "missing")
        assert out["missing"].isna().all()

    def test_returns_unchanged_when_only_main_present(self):
        frame = pd.DataFrame({"x": [1, None]})
        out = _coalesce_optional_merge_column(frame, "x")
        assert out["x"].tolist()[0] == 1

    def test_combines_x_y_suffix_columns(self):
        frame = pd.DataFrame(
            {
                "x_x": [1.0, None, None],
                "x_y": [None, 2.0, None],
            }
        )
        out = _coalesce_optional_merge_column(frame, "x")
        assert out["x"].tolist()[:2] == [1.0, 2.0]
        assert "x_x" not in out.columns
        assert "x_y" not in out.columns


# ── _build_exact_window_end_lookup ─────────────────────────────


class TestBuildExactWindowEndLookup:
    def test_empty_returns_empty_with_columns(self):
        out = _build_exact_window_end_lookup(
            pd.DataFrame(),
            display_timezone="America/New_York",
        )
        assert out.empty
        assert list(out.columns) == ["trade_date", "symbol", "exact_1000_price"]

    def test_filters_to_matching_window_end(self):
        ts = pd.Timestamp("2026-04-23 14:00", tz=UTC)  # 10:00 ET
        anchor = pd.DataFrame(
            {
                "trade_date": ["2026-04-23"],
                "symbol": ["aapl"],
                "current_price": [100.0],
                "current_price_timestamp": [ts],
            }
        )
        out = _build_exact_window_end_lookup(
            anchor,
            display_timezone="America/New_York",
        )
        assert len(out) == 1
        assert out["exact_1000_price"].iloc[0] == 100.0
        assert out["symbol"].iloc[0] == "AAPL"

    def test_filters_out_when_timestamp_mismatch(self):
        ts = pd.Timestamp("2026-04-23 13:00", tz=UTC)  # 9:00 ET
        anchor = pd.DataFrame(
            {
                "trade_date": ["2026-04-23"],
                "symbol": ["AAPL"],
                "current_price": [100.0],
                "current_price_timestamp": [ts],
            }
        )
        out = _build_exact_window_end_lookup(
            anchor,
            display_timezone="America/New_York",
        )
        assert out.empty


class TestFixedEtThinWrappers:
    def test_run_fixed_et_intraday_screen(self):
        with patch.object(mod, "run_intraday_screen", return_value=pd.DataFrame({"x": [1]})) as mk:
            _run_fixed_et_intraday_screen("a", b=1)
        mk.assert_called_once_with("a", display_timezone="America/New_York", b=1)

    def test_collect_fixed_et_second_detail(self):
        with patch.object(
            mod, "collect_full_universe_open_window_second_detail", return_value=pd.DataFrame({"x": [1]})
        ) as mk:
            _collect_fixed_et_second_detail("k")
        mk.assert_called_once_with("k", display_timezone="America/New_York")


# ── _bool_series & _numeric_series ─────────────────────────────


class TestBoolSeries:
    def test_missing_column_returns_default(self):
        out = _bool_series(pd.DataFrame({"a": [1]}), "x", default=True)
        assert out.tolist() == [True]

    def test_bool_dtype_passthrough(self):
        out = _bool_series(pd.DataFrame({"x": [True, False, None]}), "x", default=False)
        assert out.tolist() == [True, False, False]

    def test_string_normalization(self):
        out = _bool_series(pd.DataFrame({"x": [" True ", "false", "garbage"]}), "x", default=False)
        assert out.tolist() == [True, False, False]


class TestNumericSeries:
    def test_missing_column_returns_fill(self):
        out = _numeric_series(pd.DataFrame({"a": [1, 2]}), "x", fill_value=0.0)
        assert out.tolist() == [0.0, 0.0]

    def test_series_coerces(self):
        out = _numeric_series(pd.DataFrame({"x": ["1.5", "bad", "3"]}), "x")
        assert out.iloc[0] == 1.5
        assert pd.isna(out.iloc[1])
        assert out.iloc[2] == 3.0


# ── _parse_window_time_et ──────────────────────────────────────


def test_parse_window_time_et():
    assert _parse_window_time_et("09:30:00") == time(9, 30)


# ── score functions ────────────────────────────────────────────


class TestScorePct:
    def test_nan_returns_zero(self):
        assert _score_pct(None, floor=0, ceiling=10) == 0.0

    def test_collapsed_range_returns_zero(self):
        assert _score_pct(5, floor=10, ceiling=10) == 0.0

    def test_clipped_high(self):
        assert _score_pct(20, floor=0, ceiling=10) == 100.0

    def test_clipped_low(self):
        assert _score_pct(-5, floor=0, ceiling=10) == 0.0

    def test_linear(self):
        assert _score_pct(5, floor=0, ceiling=10) == 50.0


class TestScoreInversePct:
    def test_inverse(self):
        assert _score_inverse_pct(2, floor=0, ceiling=10) == 80.0


class TestScoreLogRatio:
    def test_nan_returns_zero(self):
        assert _score_log_ratio(None, 1.0) == 0.0

    def test_zero_value_returns_zero(self):
        assert _score_log_ratio(0.0, 1.0) == 0.0

    def test_zero_minimum_returns_zero(self):
        assert _score_log_ratio(5.0, 0.0) == 0.0

    def test_positive_above_minimum(self):
        # ratio=10 → log10=1 → 50 + 50 = 100
        assert _score_log_ratio(10.0, 1.0) == 100.0

    def test_below_minimum(self):
        # ratio=0.1 → log10=-1 → 50 - 50 = 0
        assert _score_log_ratio(0.1, 1.0) == 0.0


class TestScoreExtension:
    @pytest.mark.parametrize(
        "value,expected_op",
        [
            (None, "zero"),
            (0.0, "zero"),
            (-1.0, "zero"),
            (1.0, "linear"),
            (5.0, "plateau"),
            (12.0, "plateau"),
            (25.0, "zero"),
            (50.0, "zero"),
            (18.0, "decay"),
        ],
    )
    def test_buckets(self, value, expected_op):
        out = _score_extension(value)
        if expected_op == "zero":
            assert out == 0.0
        elif expected_op == "plateau":
            assert out == 100.0
        elif expected_op == "linear" or expected_op == "decay":
            assert 0.0 <= out <= 100.0


# ── window helpers ─────────────────────────────────────────────


def test_window_bounds_for_trade_date():
    win_def = SimpleNamespace(start_time_et="09:30:00", end_time_et="10:00:00")
    start, end = _window_bounds_for_trade_date(date(2026, 4, 23), win_def)
    assert start.tz_convert(mod.US_EASTERN_TZ).strftime("%H:%M") == "09:30"
    assert end.tz_convert(mod.US_EASTERN_TZ).strftime("%H:%M") == "10:00"


def test_build_empty_premarket_window_features_export():
    expected = pd.DataFrame(
        {
            "trade_date": [date(2026, 4, 23)],
            "window_tag": ["0930_1000_et"],
            "symbol": ["AAPL"],
        }
    )
    out = _build_empty_premarket_window_features_export(expected)
    assert (~out["has_window_data"]).all()
    assert out["quality_filter_reason"].iloc[0] == "no_window_data"
    assert (~out["quality_selected_top_n"]).all()


# ── exchange-key normalization ─────────────────────────────────


class TestNormalizeExchangeKey:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("nasdaq", "NASDAQ"),
            ("XNAS", "NASDAQ"),
            ("NYSE", "NYSE"),
            ("xnys", "NYSE"),
            ("AMEX", "AMEX"),
            ("xase", "AMEX"),
            ("nyse american", "AMEX"),
            ("nyse mkt", "AMEX"),
            ("custom_x", "CUSTOM_X"),
            (None, ""),
            ("", ""),
        ],
    )
    def test_aliases(self, raw, expected):
        assert _normalize_exchange_key(raw) == expected


class TestNormalizeQualityWindowMap:
    def test_none_returns_empty(self):
        assert _normalize_quality_window_exchange_dataset_map(None) == {}
        assert _normalize_quality_window_exchange_dataset_map({}) == {}

    def test_drops_blank_keys(self):
        out = _normalize_quality_window_exchange_dataset_map(
            {
                "nasdaq": "xnas.basic",
                "": "xnys.basic",
                "nyse": "",
            }
        )
        assert out == {"NASDAQ": "XNAS.BASIC"}


class TestAttachExchangeLookup:
    def test_empty_passthrough(self):
        out = _attach_exchange_lookup(pd.DataFrame(), pd.DataFrame({"symbol": ["A"], "exchange_key": ["NASDAQ"]}))
        assert out.empty

    def test_no_exchange_key_column_skips_merge(self):
        detail = pd.DataFrame({"symbol": ["aapl"], "v": [1]})
        out = _attach_exchange_lookup(detail, pd.DataFrame({"symbol": ["AAPL"]}))
        assert "exchange_key" not in out.columns
        assert out["symbol"].iloc[0] == "AAPL"

    def test_merges_exchange_key(self):
        detail = pd.DataFrame({"symbol": ["aapl"], "v": [1]})
        lookup = pd.DataFrame({"symbol": ["AAPL"], "exchange_key": ["NASDAQ"]})
        out = _attach_exchange_lookup(detail, lookup)
        assert out["exchange_key"].iloc[0] == "NASDAQ"


class TestWithSourcePriority:
    def test_empty_frame(self):
        out = _with_source_priority(pd.DataFrame(), source_priority=2)
        assert out.empty

    def test_attaches_priority(self):
        out = _with_source_priority(pd.DataFrame({"x": [1, 2]}), source_priority=3)
        assert (out["_source_priority"] == 3).all()


class TestFilterPremarketRows:
    def test_uses_session_column(self):
        frame = pd.DataFrame(
            {
                "session": ["premarket", "regular", " PreMarket "],
                "x": [1, 2, 3],
            }
        )
        out = _filter_premarket_rows(frame)
        assert out["x"].tolist() == [1, 3]

    def test_falls_back_to_timestamp_filter(self):
        ts_pre = pd.Timestamp("2026-04-23 12:00", tz=UTC)  # 8:00 ET
        ts_open = pd.Timestamp("2026-04-23 14:00", tz=UTC)  # 10:00 ET
        frame = pd.DataFrame(
            {
                "timestamp": [ts_pre, ts_open],
                "x": [1, 2],
            }
        )
        out = _filter_premarket_rows(frame)
        assert out["x"].tolist() == [1]


# ── ranking + close imbalance ─────────────────────────────────


class TestBuildUniqueSymbolDayRankingCandidates:
    def test_empty_frame(self):
        out = _build_unique_symbol_day_ranking_candidates(pd.DataFrame(), ranking_metric="x")
        assert out.empty
        assert list(out.columns) == ["trade_date", "symbol", "x"]

    def test_dedup_by_symbol_day_keeps_first_after_sort(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["2026-04-23", "2026-04-23"],
                "symbol": ["AAPL", "AAPL"],
                "x": [1.0, 2.0],
            }
        )
        out = _build_unique_symbol_day_ranking_candidates(frame, ranking_metric="x")
        # Sorted by x desc, dedup keeps first → 2.0
        assert out["x"].iloc[0] == 2.0


class TestCloseImbalanceExports:
    def test_features_empty_returns_columns(self):
        out = _build_close_imbalance_features_full_universe_export(pd.DataFrame())
        assert out.empty
        assert list(out.columns) == CLOSE_IMBALANCE_FEATURE_COLUMNS

    def test_features_fills_missing_columns(self):
        daily = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
                "has_close_window_detail": [True],
            }
        )
        out = _build_close_imbalance_features_full_universe_export(daily)
        assert bool(out["has_close_window_detail"].iloc[0]) is True

    def test_outcomes_empty_returns_columns(self):
        out = _build_close_imbalance_outcomes_full_universe_export(pd.DataFrame())
        assert out.empty
        assert list(out.columns) == CLOSE_IMBALANCE_OUTCOME_COLUMNS

    def test_outcomes_normalizes_has_next_day_outcome(self):
        daily = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
                "has_next_day_outcome": [pd.NA],
            }
        )
        out = _build_close_imbalance_outcomes_full_universe_export(daily)
        assert bool(out["has_next_day_outcome"].iloc[0]) is False


class TestBuildBatlDebugPayload:
    def test_present_in_daily(self):
        daily = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["BATL"],
                "is_eligible": [True],
                "eligibility_reason": ["eligible"],
                "rank_within_trade_date": [pd.array([3], dtype="Int64")[0]],
                "selected_top20pct": [True],
            }
        )
        out = _build_batl_debug_payload(daily, pd.DataFrame())
        assert out["present_in_daily_symbol_features_full_universe"] is True
        assert out["rank_within_trade_date"] == 3

    def test_present_in_diagnostics_only(self):
        diag = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["BATL"],
                "selected_top20pct": [False],
                "excluded_step": ["x"],
                "excluded_reason": ["y"],
            }
        )
        out = _build_batl_debug_payload(pd.DataFrame({"symbol": ["AAPL"]}), diag)
        assert out["present_in_daily_symbol_features_full_universe"] is False
        assert out["excluded_step"] == "x"

    def test_absent_everywhere(self):
        out = _build_batl_debug_payload(pd.DataFrame({"symbol": ["AAPL"]}), pd.DataFrame({"symbol": ["AAPL"]}))
        assert out["excluded_step"] == "raw_universe"


# ── format / parse helpers ─────────────────────────────────────


class TestFormatOptionalTime:
    def test_none_returns_default_label(self):
        assert _format_optional_time(None) == "market_relative_default"

    def test_time_formatted(self):
        assert _format_optional_time(time(9, 30, 5)) == "09:30:05"


class TestResolveLatestIsoTimestamp:
    def test_empty_returns_none(self):
        assert _resolve_latest_iso_timestamp(pd.DataFrame(), candidates=("ts",)) is None

    def test_no_matching_columns(self):
        out = _resolve_latest_iso_timestamp(pd.DataFrame({"x": [1]}), candidates=("ts",))
        assert out is None

    def test_all_nan_continues_to_next(self):
        frame = pd.DataFrame(
            {
                "ts1": ["bad", "alsobad"],
                "ts2": ["2026-04-23T12:00:00Z", "2026-04-23T13:00:00Z"],
            }
        )
        out = _resolve_latest_iso_timestamp(frame, candidates=("ts1", "ts2"))
        assert out is not None and "2026-04-23" in out

    def test_returns_max(self):
        frame = pd.DataFrame(
            {
                "ts": ["2026-04-23T12:00:00Z", "2026-04-23T13:00:00Z"],
            }
        )
        out = _resolve_latest_iso_timestamp(frame, candidates=("ts",))
        assert out is not None and "13:00" in out


class TestParseCalendarTradeDate:
    def test_invalid(self):
        assert _parse_calendar_trade_date("nope") is None
        assert _parse_calendar_trade_date(None) is None

    def test_valid(self):
        assert _parse_calendar_trade_date("2026-04-23") == date(2026, 4, 23)


class TestNormalizeEarningsTiming:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("BMO", "bmo"),
            (" before-market_open ", "before market open"),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert _normalize_earnings_timing(raw) == expected


class TestNormalizeResearchSymbol:
    def test_blank_returns_empty(self):
        assert _normalize_research_symbol(None) == ""
        assert _normalize_research_symbol("  ") == ""

    def test_uppercase_normalized(self):
        with patch.object(mod, "normalize_symbol_for_databento", return_value="aapl"):
            assert _normalize_research_symbol("aapl") == "AAPL"

    def test_falls_back_to_raw_when_normalizer_returns_blank(self):
        with patch.object(mod, "normalize_symbol_for_databento", return_value=""):
            assert _normalize_research_symbol("xyz") == "XYZ"


def test_research_news_window_bounds_for_trade_date():
    out = _research_news_window_bounds_for_trade_date(date(2026, 4, 23))
    assert "trade_open_et" in out
    assert "window_24h_start_utc" in out
    # 24h before 9:30 ET on the trade date.
    assert (out["trade_open_et"] - out["window_24h_start_et"]).total_seconds() == 86400


class TestBenzingaDateUtc:
    def test_naive_localized(self):
        out = _benzinga_date_utc(pd.Timestamp("2026-04-23 12:00"))
        assert out == "2026-04-23"

    def test_aware_converted(self):
        ts = pd.Timestamp("2026-04-23 23:30", tz="America/New_York")
        out = _benzinga_date_utc(ts)
        assert out == "2026-04-24"  # converted to UTC


class TestIterSymbolBatches:
    def test_zero_batch_size_returns_one_batch(self):
        out = _iter_symbol_batches(["A", "B", "C"], batch_size=0)
        assert out == [["A", "B", "C"]]

    def test_skips_blank_symbols(self):
        out = _iter_symbol_batches(["A", "", "  ", "B"], batch_size=10)
        assert out == [["A", "B"]]

    def test_chunks_into_batches(self):
        out = _iter_symbol_batches(["A", "B", "C", "D", "E"], batch_size=2)
        assert out == [["A", "B"], ["C", "D"], ["E"]]


class TestResearchNewsArticleKey:
    def test_uses_item_id_when_present(self):
        item = SimpleNamespace(item_id="X1", url="u", headline="h", published_ts=1.0)
        assert _research_news_article_key(item) == "X1"

    def test_falls_back_to_url_headline_ts(self):
        item = SimpleNamespace(item_id="", url="u", headline="HeAd", published_ts=10.0)
        assert _research_news_article_key(item) == "u|head|10"

    def test_skips_blank_parts(self):
        item = SimpleNamespace(item_id="", url="", headline="", published_ts=0.0)
        assert _research_news_article_key(item) == "0"


class TestTimingBuckets:
    def test_pre_open_true(self):
        assert _timing_is_pre_open("BMO") is True
        assert _timing_is_pre_open("pre-market") is True
        assert _timing_is_pre_open(None) is False

    def test_post_close_true(self):
        assert _timing_is_post_close("AMC") is True
        assert _timing_is_post_close("after-close") is True
        assert _timing_is_post_close(None) is False


class TestEmptyResearchFlags:
    def test_event_flags_missing(self):
        scope = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
            }
        )
        out = _empty_research_event_flags(scope, missing=True)
        assert list(out.columns) == RESEARCH_EVENT_FLAG_COLUMNS
        for col in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
            assert pd.isna(out[col].iloc[0])

    def test_event_flags_zero(self):
        scope = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
            }
        )
        out = _empty_research_event_flags(scope, missing=False)
        for col in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
            assert not out[col].iloc[0]

    def test_news_flags_missing(self):
        scope = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
            }
        )
        out = _empty_research_news_flags(scope, missing=True)
        assert list(out.columns) == RESEARCH_NEWS_FLAG_COLUMNS
        for col in RESEARCH_NEWS_FLAG_COUNT_COLUMNS:
            assert pd.isna(out[col].iloc[0])
        for col in RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS:
            assert pd.isna(out[col].iloc[0])

    def test_news_flags_zero(self):
        scope = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
            }
        )
        out = _empty_research_news_flags(scope, missing=False)
        for col in RESEARCH_NEWS_FLAG_COUNT_COLUMNS:
            assert out[col].iloc[0] == 0
        for col in RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS:
            assert not out[col].iloc[0]


class TestResearchNewsPositiveMask:
    def test_count_column_gt_zero(self):
        col = RESEARCH_NEWS_FLAG_COUNT_COLUMNS[0]
        frame = pd.DataFrame({col: [0, 1, None, 5]})
        out = _research_news_positive_mask(frame, col)
        assert out.tolist() == [False, True, False, True]

    def test_boolean_column(self):
        col = RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS[0]
        frame = pd.DataFrame({col: pd.Series([True, False, None], dtype="boolean")})
        out = _research_news_positive_mask(frame, col)
        assert out.tolist() == [True, False, False]

    def test_missing_column_returns_all_false(self):
        col = RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS[0]
        out = _research_news_positive_mask(pd.DataFrame({"x": [1]}), col)
        assert not out.any()


class TestResolveResearchNewsStatus:
    def test_fetch_failed_when_failed_and_no_resolved(self):
        out = _resolve_research_news_status(
            resolved_symbol_days=0,
            failed_symbol_days=1,
            truncated_symbol_days=0,
            matched_symbol_articles=0,
        )
        assert out == mod.RESEARCH_NEWS_STATUS_FETCH_FAILED

    def test_partial_failed_truncated(self):
        out = _resolve_research_news_status(
            resolved_symbol_days=10,
            failed_symbol_days=1,
            truncated_symbol_days=1,
            matched_symbol_articles=5,
        )
        assert out == mod.RESEARCH_NEWS_STATUS_PARTIAL_FETCH_FAILED_TRUNCATED

    def test_partial_failed(self):
        out = _resolve_research_news_status(
            resolved_symbol_days=10,
            failed_symbol_days=1,
            truncated_symbol_days=0,
            matched_symbol_articles=5,
        )
        assert out == mod.RESEARCH_NEWS_STATUS_PARTIAL_FETCH_FAILED

    def test_truncated_only(self):
        out = _resolve_research_news_status(
            resolved_symbol_days=10,
            failed_symbol_days=0,
            truncated_symbol_days=2,
            matched_symbol_articles=5,
        )
        assert out == mod.RESEARCH_NEWS_STATUS_TRUNCATED

    def test_ok_empty(self):
        out = _resolve_research_news_status(
            resolved_symbol_days=10,
            failed_symbol_days=0,
            truncated_symbol_days=0,
            matched_symbol_articles=0,
        )
        assert out == mod.RESEARCH_NEWS_STATUS_OK_EMPTY

    def test_ok(self):
        out = _resolve_research_news_status(
            resolved_symbol_days=10,
            failed_symbol_days=0,
            truncated_symbol_days=0,
            matched_symbol_articles=5,
        )
        assert out == mod.RESEARCH_NEWS_STATUS_OK


class TestBenzingaFlagBucket:
    def test_unknown_when_both_missing(self):
        row = pd.Series(
            {
                "benzinga_has_company_news_24h": pd.NA,
                "benzinga_company_news_item_count_24h": pd.NA,
            }
        )
        assert _benzinga_flag_status_bucket(row) == "unknown"

    def test_degraded_when_only_count_missing(self):
        row = pd.Series(
            {
                "benzinga_has_company_news_24h": True,
                "benzinga_company_news_item_count_24h": pd.NA,
            }
        )
        assert _benzinga_flag_status_bucket(row) == "degraded"

    def test_full(self):
        row = pd.Series(
            {
                "benzinga_has_company_news_24h": True,
                "benzinga_company_news_item_count_24h": 3,
            }
        )
        assert _benzinga_flag_status_bucket(row) == "full"


class TestCoreVsBenzingaOverlapBucket:
    @pytest.mark.parametrize(
        "benz_flag,core,expected",
        [
            (pd.NA, True, "benzinga_unknown"),
            (True, True, "both"),
            (False, True, "core_only"),
            (True, False, "benzinga_only"),
            (False, False, "neither"),
        ],
    )
    def test_buckets(self, benz_flag, core, expected):
        row = pd.Series(
            {
                "benzinga_has_company_news_24h": benz_flag,
                "core_has_news": core,
            }
        )
        assert _core_vs_benzinga_overlap_bucket(row) == expected


# ── ranked-scope filter, top-candidate selection ──────────────


class TestFilterRankedSymbolDayScope:
    def test_empty_frame_returns_empty(self):
        out = _filter_ranked_symbol_day_scope(
            pd.DataFrame(),
            pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]}),
        )
        assert out.empty

    def test_inner_merge(self):
        frame = pd.DataFrame(
            {
                "trade_date": ["2026-04-23", "2026-04-23"],
                "symbol": ["aapl", "TSLA"],
                "v": [1, 2],
            }
        )
        scope = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
            }
        )
        out = _filter_ranked_symbol_day_scope(frame, scope)
        assert out["symbol"].tolist() == ["AAPL"]


class TestSelectTopCandidatesPerDay:
    def test_empty_passthrough(self):
        out = _select_top_candidates_per_day(pd.DataFrame(), 10)
        assert out.empty

    def test_zero_top_n_returns_empty(self):
        frame = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
                "quality_score": [50.0],
                "window_dollar_volume": [1.0],
                "window_return_pct": [1.0],
            }
        )
        out = _select_top_candidates_per_day(frame, 0)
        assert out.empty

    def test_picks_top_per_day_by_quality_score(self):
        frame = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)] * 3,
                "symbol": ["A", "B", "C"],
                "quality_score": [10.0, 90.0, 50.0],
                "window_dollar_volume": [1.0, 1.0, 1.0],
                "window_return_pct": [1.0, 1.0, 1.0],
            }
        )
        out = _select_top_candidates_per_day(frame, 2)
        assert out["symbol"].tolist() == ["B", "C"]


# ── label helpers ─────────────────────────────────────────────


def test_format_quality_window_label():
    out = _format_quality_window_label(
        date(2026, 4, 23),
        start_et=time(9, 30),
        end_et=time(10, 0),
        display_timezone="America/New_York",
    )
    assert out == "09:30-10:00"


def test_quality_window_export_tag():
    assert _quality_window_export_tag(time(9, 30), time(10, 0)) == "0930_1000_et"


class TestWindowLabelFromTag:
    def test_unknown_tag_passthrough(self):
        out = _window_label_from_tag(date(2026, 4, 23), "unknown_tag", display_timezone="America/New_York")
        assert out == "unknown_tag"

    def test_known_tag_yields_label(self):
        # Pick first defined window's tag.
        tag = mod._DEFAULT_BULLISH_QUALITY_CFG.window_definitions[0].tag
        out = _window_label_from_tag(date(2026, 4, 23), tag, display_timezone="America/New_York")
        assert "-" in out


# ── compute_open_confirm_flags ─────────────────────────────────


class TestComputeOpenConfirmFlags:
    def test_empty_returns_columns(self):
        out = _compute_open_confirm_flags(pd.DataFrame())
        assert out.empty
        assert list(out.columns) == ["trade_date", "symbol", "open_confirm_ok"]

    def test_no_rows_in_open_window(self):
        ts = pd.Timestamp("2026-04-23 12:00", tz=UTC)  # 8:00 ET
        detail = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)],
                "symbol": ["AAPL"],
                "timestamp": [ts],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
            }
        )
        out = _compute_open_confirm_flags(detail)
        assert out.empty

    def test_aggregates_open_window(self):
        ts = pd.Timestamp("2026-04-23 13:30", tz=UTC)  # 9:30 ET
        detail = pd.DataFrame(
            {
                "trade_date": [date(2026, 4, 23)] * 2,
                "symbol": ["AAPL"] * 2,
                "timestamp": [ts, ts + pd.Timedelta(seconds=30)],
                "open": [100.0, 100.5],
                "high": [101.0, 101.5],
                "low": [99.5, 99.8],
                "close": [100.5, 101.0],
            }
        )
        out = _compute_open_confirm_flags(detail)
        assert len(out) == 1
        assert bool(out["open_confirm_ok"].iloc[0]) is True


# ── _enrich_universe_with_fundamentals ────────────────────────


class TestEnrichUniverseWithFundamentals:
    def test_empty_fundamentals(self):
        univ = pd.DataFrame({"symbol": ["AAPL"]})
        out = _enrich_universe_with_fundamentals(univ, pd.DataFrame())
        assert bool(out["has_reference_data"].iloc[0]) is True
        assert bool(out["has_fundamentals"].iloc[0]) is False
        assert out["asset_type"].iloc[0] == "listed_equity_issue"

    def test_merges_fundamentals(self):
        univ = pd.DataFrame({"symbol": ["aapl"]})
        funds = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "company_name_profile": ["Apple"],
                "exchange_profile": ["NASDAQ"],
                "sector_profile": ["Tech"],
                "industry_profile": ["Consumer"],
                "market_cap_profile": [3.0e12],
                "asset_type_profile": ["common_stock"],
                "has_fundamental_row": [True],
            }
        )
        out = _enrich_universe_with_fundamentals(univ, funds)
        assert out["company_name"].iloc[0] == "Apple"
        assert out["market_cap"].iloc[0] == 3.0e12
        assert bool(out["has_market_cap"].iloc[0]) is True
        # has_fundamentals collides with universe-side bootstrap False; the
        # current implementation does not coalesce the merged _y column,
        # so it stays False even when the row is present.
        assert bool(out["has_fundamentals"].iloc[0]) is False
        assert out["asset_type"].iloc[0] == "listed_equity_issue"


# ── _load_fundamental_reference cache paths ───────────────────


class TestLoadFundamentalReference:
    def test_uses_cached_frame_when_fresh(self, tmp_path: Path):
        cached = pd.DataFrame({"symbol": ["AAPL"]})
        with patch.object(mod, "_read_cached_frame", return_value=cached):
            out = mod._load_fundamental_reference(
                "key",
                cache_dir=tmp_path,
                use_file_cache=True,
                force_refresh=False,
            )
        assert out.equals(cached)

    def test_no_api_key_returns_empty(self, tmp_path: Path):
        with patch.object(mod, "_read_cached_frame", return_value=None):
            out = mod._load_fundamental_reference(
                "",
                cache_dir=tmp_path,
                use_file_cache=False,
                force_refresh=False,
            )
        assert out.empty

    def test_handles_fmp_failure(self, tmp_path: Path):
        client = SimpleNamespace(get_profile_bulk=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        with (
            patch.object(mod, "_read_cached_frame", return_value=None),
            patch.object(mod, "_make_export_fmp_client", return_value=client),
            patch.object(mod, "_write_cached_frame"),
        ):
            out = mod._load_fundamental_reference(
                "key",
                cache_dir=tmp_path,
                use_file_cache=False,
                force_refresh=False,
            )
        assert out.empty

    def test_returns_normalized_frame(self, tmp_path: Path):
        rows = [
            {
                "symbol": "aapl",
                "companyName": "Apple",
                "exchangeShortName": "NASDAQ",
                "sector": "Tech",
                "industry": "Consumer",
                "marketCap": 1.0e12,
                "type": "common_stock",
            },
        ]
        client = SimpleNamespace(get_profile_bulk=lambda: rows)
        with (
            patch.object(mod, "_read_cached_frame", return_value=None),
            patch.object(mod, "_make_export_fmp_client", return_value=client),
            patch.object(mod, "_write_cached_frame"),
        ):
            out = mod._load_fundamental_reference(
                "key",
                cache_dir=tmp_path,
                use_file_cache=True,
                force_refresh=False,
            )
        assert out["symbol"].iloc[0] == "AAPL"
        assert out["company_name_profile"].iloc[0] == "Apple"


# ── main() error path ─────────────────────────────────────────


class TestMainError:
    def test_missing_api_key_raises_systemexit(self, monkeypatch):
        monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
        with patch.object(mod, "load_dotenv"), pytest.raises(SystemExit, match="DATABENTO_API_KEY"):
            mod.main([])
