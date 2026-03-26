from __future__ import annotations

from datetime import UTC, date, datetime
import warnings

import pandas as pd
import scripts.databento_production_export as export_mod

from newsstack_fmp.common_types import NewsItem
from scripts.databento_production_export import (
    _coalesce_optional_merge_column,
    _build_core_vs_benzinga_news_side_by_side,
    _build_research_news_flag_coverage,
    _build_research_news_flag_outcome_slices,
    _build_research_news_flag_trade_date_distribution,
    _build_research_news_flags_full_universe_export,
)

def test_coalesce_optional_merge_column_handles_missing_and_suffix_columns() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "is_earnings_day_x": [pd.NA, True],
            "is_earnings_day_y": [False, pd.NA],
        }
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        frame = _coalesce_optional_merge_column(frame, "is_earnings_day")
        frame = _coalesce_optional_merge_column(frame, "earnings_timing_pre_open")

    assert list(frame["is_earnings_day"]) == [False, True]
    assert "is_earnings_day_x" not in frame.columns
    assert "is_earnings_day_y" not in frame.columns
    assert "earnings_timing_pre_open" in frame.columns
    assert frame["earnings_timing_pre_open"].isna().all()

def _news_item(item_id: str, created_at: str, tickers: list[str]) -> NewsItem:
    published_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(UTC)
    published_ts = published_dt.timestamp()
    return NewsItem(
        provider="benzinga_rest",
        item_id=item_id,
        published_ts=published_ts,
        updated_ts=published_ts,
        headline=f"Headline {item_id}",
        snippet="",
        tickers=tickers,
        url=f"https://example.test/{item_id}",
        source="Benzinga",
        raw={},
    )


def test_build_research_news_flags_full_universe_export_dedupes_symbol_day_articles_and_respects_et_boundaries(monkeypatch) -> None:
    daily_features = pd.DataFrame(
        [
            {"trade_date": date(2026, 3, 20), "symbol": "AAA"},
            {"trade_date": date(2026, 3, 20), "symbol": "BBB"},
            {"trade_date": date(2026, 3, 21), "symbol": "AAA"},
        ]
    )

    class FakeBenzingaRestAdapter:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def fetch_news(self, **kwargs):
            if kwargs["tickers"] == "AAA,BBB":
                assert kwargs["date_from"] == "2026-03-19"
                assert kwargs["date_to"] == "2026-03-20"
                return [
                    _news_item("dup-1", "2026-03-19T13:30:00Z", ["AAA"]),
                    _news_item("dup-1", "2026-03-19T13:30:00Z", ["AAA"]),
                    _news_item("pre-1", "2026-03-20T08:00:00Z", ["AAA"]),
                    _news_item("multi-1", "2026-03-20T10:00:00Z", ["AAA", "BBB"]),
                    _news_item("end-excluded", "2026-03-20T13:30:00Z", ["AAA"]),
                ] if kwargs["page"] == 0 else []
            assert kwargs["tickers"] == "AAA"
            assert kwargs["date_from"] == "2026-03-20"
            assert kwargs["date_to"] == "2026-03-21"
            return []

        def close(self) -> None:
            return None

    monkeypatch.setattr(export_mod, "BenzingaRestAdapter", FakeBenzingaRestAdapter)

    flags, metadata = _build_research_news_flags_full_universe_export(
        daily_features=daily_features,
        benzinga_api_key="demo-key",
    )

    assert metadata["status"] == "ok"
    aaa_day1 = flags[(flags["trade_date"] == date(2026, 3, 20)) & (flags["symbol"] == "AAA")].iloc[0]
    bbb_day1 = flags[(flags["trade_date"] == date(2026, 3, 20)) & (flags["symbol"] == "BBB")].iloc[0]
    aaa_day2 = flags[(flags["trade_date"] == date(2026, 3, 21)) & (flags["symbol"] == "AAA")].iloc[0]

    assert bool(aaa_day1["has_company_news_24h"]) is True
    assert int(aaa_day1["company_news_item_count_24h"]) == 3
    assert bool(aaa_day1["has_company_news_preopen_window"]) is True
    assert bool(bbb_day1["has_company_news_24h"]) is True
    assert int(bbb_day1["company_news_item_count_24h"]) == 1
    assert bool(bbb_day1["has_company_news_preopen_window"]) is True
    assert bool(aaa_day2["has_company_news_24h"]) is False
    assert int(aaa_day2["company_news_item_count_24h"]) == 0
    assert bool(aaa_day2["has_company_news_preopen_window"]) is False


def test_build_research_news_flags_full_universe_export_marks_failed_symbol_days_missing(monkeypatch) -> None:
    daily_features = pd.DataFrame(
        [
            {"trade_date": date(2026, 3, 20), "symbol": "AAA"},
            {"trade_date": date(2026, 3, 20), "symbol": "BBB"},
        ]
    )

    class FakeBenzingaRestAdapter:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def fetch_news(self, **kwargs):
            if kwargs["tickers"] == "AAA":
                return [_news_item("aaa-1", "2026-03-20T12:00:00Z", ["AAA"])] if kwargs["page"] == 0 else []
            raise RuntimeError("provider timeout")

        def close(self) -> None:
            return None

    monkeypatch.setattr(export_mod, "BenzingaRestAdapter", FakeBenzingaRestAdapter)

    flags, metadata = _build_research_news_flags_full_universe_export(
        daily_features=daily_features,
        benzinga_api_key="demo-key",
        symbol_batch_size=1,
    )

    aaa_row = flags[flags["symbol"] == "AAA"].iloc[0]
    bbb_row = flags[flags["symbol"] == "BBB"].iloc[0]

    assert metadata["status"] == "partial_fetch_failed"
    assert bool(aaa_row["has_company_news_24h"]) is True
    assert int(aaa_row["company_news_item_count_24h"]) == 1
    assert pd.isna(bbb_row["has_company_news_24h"])
    assert pd.isna(bbb_row["company_news_item_count_24h"])
    assert pd.isna(bbb_row["has_company_news_preopen_window"])


def test_build_research_news_flags_full_universe_export_marks_truncated_symbol_days_degraded(monkeypatch) -> None:
    daily_features = pd.DataFrame(
        [
            {"trade_date": date(2026, 3, 20), "symbol": "AAA"},
        ]
    )

    class FakeBenzingaRestAdapter:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def fetch_news(self, **kwargs):
            assert kwargs["tickers"] == "AAA"
            return [_news_item("aaa-1", "2026-03-19T20:00:00Z", ["AAA"])]

        def close(self) -> None:
            return None

    monkeypatch.setattr(export_mod, "BenzingaRestAdapter", FakeBenzingaRestAdapter)

    flags, metadata = _build_research_news_flags_full_universe_export(
        daily_features=daily_features,
        benzinga_api_key="demo-key",
        max_pages_per_request=1,
        page_size=1,
    )

    row = flags.iloc[0]
    assert metadata["status"] == "truncated"
    assert metadata["truncated_symbol_days"] == 1
    assert bool(row["has_company_news_24h"]) is True
    assert pd.isna(row["company_news_item_count_24h"])
    assert pd.isna(row["has_company_news_preopen_window"])


def test_build_core_vs_benzinga_news_side_by_side_uses_current_core_path(monkeypatch) -> None:
    daily_features = pd.DataFrame(
        [
            {"trade_date": date(2026, 3, 20), "symbol": "AAA", "selected_top20pct": True},
            {"trade_date": date(2026, 3, 20), "symbol": "BBB", "selected_top20pct": False},
            {"trade_date": date(2026, 3, 19), "symbol": "ZZZ", "selected_top20pct": False},
        ]
    )
    research_flags = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 3, 20),
                "symbol": "AAA",
                "has_company_news_24h": True,
                "company_news_item_count_24h": 2,
                "has_company_news_preopen_window": True,
            },
            {
                "trade_date": date(2026, 3, 20),
                "symbol": "BBB",
                "has_company_news_24h": False,
                "company_news_item_count_24h": 0,
                "has_company_news_preopen_window": False,
            },
        ]
    )

    class FakeFMPClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

    def fake_fetch_news_context(*, client, symbols):
        assert client.api_key == "demo-fmp"
        assert symbols == ["AAA", "BBB"]
        return (
            {"AAA": 0.8, "BBB": 0.0},
            {
                "AAA": {
                    "event_class": "EARNINGS",
                    "materiality": "HIGH",
                    "recency_bucket": "LT_2H",
                    "source_tier": "TIER_1",
                },
                "BBB": {
                    "event_class": "NONE",
                    "materiality": "LOW",
                    "recency_bucket": "STALE",
                    "source_tier": "TIER_3",
                },
            },
            None,
        )

    monkeypatch.setattr(export_mod, "FMPClient", FakeFMPClient)
    monkeypatch.setattr("open_prep.run_open_prep._fetch_news_context", fake_fetch_news_context)

    side_by_side, overlap_stats, metadata = _build_core_vs_benzinga_news_side_by_side(
        daily_features=daily_features,
        research_news_flags=research_flags,
        fmp_api_key="demo-fmp",
    )

    assert metadata["status"] == "ok"
    assert list(side_by_side["symbol"]) == ["AAA", "BBB"]
    assert list(side_by_side["overlap_bucket"]) == ["both", "neither"]
    assert overlap_stats.set_index("overlap_bucket").loc["both", "symbol_day_rows"] == 1
    assert overlap_stats.set_index("overlap_bucket").loc["neither", "symbol_day_rows"] == 1


def test_build_research_news_flag_coverage_distribution_and_outcome_slices() -> None:
    flags = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 3, 20),
                "symbol": "AAA",
                "has_company_news_24h": True,
                "company_news_item_count_24h": 2,
                "has_company_news_preopen_window": True,
            },
            {
                "trade_date": date(2026, 3, 20),
                "symbol": "BBB",
                "has_company_news_24h": False,
                "company_news_item_count_24h": 0,
                "has_company_news_preopen_window": False,
            },
            {
                "trade_date": date(2026, 3, 21),
                "symbol": "AAA",
                "has_company_news_24h": pd.NA,
                "company_news_item_count_24h": pd.NA,
                "has_company_news_preopen_window": pd.NA,
            },
        ]
    )
    daily_features = pd.DataFrame(
        [
            {
                "trade_date": date(2026, 3, 20),
                "symbol": "AAA",
                "selected_top20pct": True,
                "has_company_news_24h": True,
                "company_news_item_count_24h": 2,
                "has_company_news_preopen_window": True,
                "window_range_pct": 5.0,
                "realized_vol_pct": 2.0,
                "close_trade_hygiene_score": 0.8,
                "close_last_1m_volume_share": 0.2,
                "close_to_next_open_return_pct": 1.0,
            },
            {
                "trade_date": date(2026, 3, 20),
                "symbol": "BBB",
                "selected_top20pct": False,
                "has_company_news_24h": False,
                "company_news_item_count_24h": 0,
                "has_company_news_preopen_window": False,
                "window_range_pct": 2.0,
                "realized_vol_pct": 1.0,
                "close_trade_hygiene_score": 0.5,
                "close_last_1m_volume_share": 0.1,
                "close_to_next_open_return_pct": -0.5,
            },
        ]
    )

    coverage = _build_research_news_flag_coverage(flags)
    distribution = _build_research_news_flag_trade_date_distribution(flags)
    slices = _build_research_news_flag_outcome_slices(daily_features, flags)

    count_row = coverage[coverage["flag_name"] == "company_news_item_count_24h"].iloc[0]
    dist_row = distribution[
        (distribution["flag_name"] == "has_company_news_24h")
        & (distribution["trade_date"] == date(2026, 3, 20))
    ].iloc[0]
    selected_true = slices[
        (slices["flag_name"] == "company_news_item_count_24h")
        & (slices["selected_top20pct"] == True)
        & (slices["flag_value"] == True)
    ].iloc[0]

    assert count_row["symbol_day_rows"] == 3
    assert count_row["non_null_rows"] == 2
    assert count_row["true_rows"] == 1
    assert dist_row["true_rows"] == 1
    assert dist_row["symbol_day_rows"] == 2
    assert selected_true["row_count"] == 1
    assert selected_true["mean_window_range_pct"] == 5.0


def test_build_research_news_flags_full_universe_export_without_api_key_marks_flags_missing() -> None:
    daily_features = pd.DataFrame(
        [
            {"trade_date": date(2026, 3, 20), "symbol": "AAA"},
        ]
    )

    flags, metadata = _build_research_news_flags_full_universe_export(
        daily_features=daily_features,
        benzinga_api_key="",
    )

    row = flags.iloc[0]
    assert metadata["status"] == "missing_api_key"
    assert pd.isna(row["has_company_news_24h"])
    assert pd.isna(row["company_news_item_count_24h"])
    assert pd.isna(row["has_company_news_preopen_window"])