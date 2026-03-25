from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest
import scripts.databento_production_export as export_mod

from scripts.generate_smc_micro_base_from_databento import (
    build_base_snapshot_from_workbook,
    write_mapping_report,
)
from scripts.smc_microstructure_base_runtime import (
    _assert_complete_symbol_coverage,
    build_base_snapshot_from_bundle_payload,
    evaluate_micro_library_publish_guard,
    generate_base_from_bundle,
    list_generated_base_csvs,
    resolve_base_csv_selection,
)


SCHEMA_PATH = Path("schema/schema.json")


def test_build_base_snapshot_from_workbook_maps_direct_and_derived_fields(tmp_path) -> None:
    workbook_path = tmp_path / "databento_volatility_production_fake.xlsx"

    summary = pd.DataFrame(
        [
            {
                "rank": 1,
                "trade_date": "2026-03-20",
                "symbol": "SPY",
                "exchange": "AMEX",
                "company_name": "SPDR S&P 500 ETF Trust",
                "market_cap": 600_000_000_000,
            },
            {
                "rank": 2,
                "trade_date": "2026-03-20",
                "symbol": "NVDA",
                "exchange": "NASDAQ",
                "company_name": "NVIDIA Corporation",
                "market_cap": 2_400_000_000_000,
            },
            {
                "rank": 1,
                "trade_date": "2026-03-19",
                "symbol": "NVDA",
                "exchange": "NASDAQ",
                "company_name": "NVIDIA Corporation",
                "market_cap": 2_380_000_000_000,
            },
        ]
    )
    daily_bars = pd.DataFrame(
        [
            {"trade_date": "2026-03-20", "symbol": "SPY", "close": 580.0, "volume": 1000},
            {"trade_date": "2026-03-19", "symbol": "SPY", "close": 575.0, "volume": 1200},
            {"trade_date": "2026-03-20", "symbol": "NVDA", "close": 120.0, "volume": 5000},
            {"trade_date": "2026-03-19", "symbol": "NVDA", "close": 118.0, "volume": 4000},
        ]
    )

    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        daily_bars.to_excel(writer, sheet_name="daily_bars", index=False)

    output, payload = build_base_snapshot_from_workbook(workbook_path, schema_path=SCHEMA_PATH)

    assert payload["asof_date"] == "2026-03-20"
    assert list(output["symbol"]) == ["NVDA", "SPY"]
    spy = output.loc[output["symbol"] == "SPY"].iloc[0]
    nvda = output.loc[output["symbol"] == "NVDA"].iloc[0]
    assert spy["asset_type"] == "etf"
    assert spy["universe_bucket"] == "us_etf"
    assert spy["history_coverage_days_20d"] == 2
    assert spy["adv_dollar_rth_20d"] == 635000.0
    assert nvda["asset_type"] == "stock"
    assert nvda["universe_bucket"] == "us_largecap"
    assert "avg_spread_bps_rth_20d" in payload["missing_fields"]


def test_mapping_report_writes_field_statuses(tmp_path) -> None:
    report_path = tmp_path / "mapping.md"
    payload = {
        "workbook_path": "fake.xlsx",
        "asof_date": "2026-03-20",
        "row_count": 2,
        "direct_fields": ["asof_date", "symbol"],
        "derived_fields": ["adv_dollar_rth_20d"],
        "missing_fields": ["avg_spread_bps_rth_20d"],
        "mapping_status": [
            {
                "field": "asof_date",
                "status": "direct",
                "source_sheet": "summary",
                "source_columns": ["trade_date"],
                "note": "direct",
            },
            {
                "field": "avg_spread_bps_rth_20d",
                "status": "missing",
                "source_sheet": "",
                "source_columns": [],
                "note": "missing",
            },
        ],
    }

    write_mapping_report(report_path, payload)

    report = report_path.read_text(encoding="utf-8")
    assert "# Databento Workbook To Microstructure Base Mapping: fake.xlsx" in report
    assert "|asof_date|direct|summary|trade_date|direct|" in report
    assert "|avg_spread_bps_rth_20d|missing|||missing|" in report


def test_build_base_snapshot_from_bundle_payload_derives_full_contract(tmp_path: Path) -> None:
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
    daily_bars = daily_features[
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

    bundle_payload = {
        "manifest_path": tmp_path / "fake_manifest.json",
        "bundle_dir": tmp_path,
        "base_prefix": "databento_volatility_production_fake",
        "manifest": {"trade_dates_covered": ["2026-03-19", "2026-03-20"]},
        "frames": {
            "daily_bars": daily_bars,
            "daily_symbol_features_full_universe": daily_features,
        },
    }

    output, payload, symbol_day_features = build_base_snapshot_from_bundle_payload(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        session_minute_detail=session_minute_detail,
    )

    assert payload["asof_date"] == "2026-03-20"
    assert payload["missing_fields"] == []
    assert len(symbol_day_features) == 2
    assert list(output["symbol"]) == ["AAA"]
    numeric_values = output.iloc[0].drop(labels=["asof_date", "symbol", "exchange", "asset_type", "universe_bucket"])
    assert pd.to_numeric(numeric_values, errors="coerce").notna().all()


def test_generate_base_from_bundle_writes_artifacts(tmp_path: Path) -> None:
    bundle_payload = {
        "manifest_path": tmp_path / "fake_manifest.json",
        "bundle_dir": tmp_path,
        "base_prefix": "databento_volatility_production_fake",
        "manifest": {"trade_dates_covered": ["2026-03-19", "2026-03-20"]},
        "frames": {
            "daily_bars": pd.DataFrame(
                [
                    {"trade_date": "2026-03-19", "symbol": "AAA", "open": 10.0, "high": 10.8, "low": 9.7, "close": 10.5, "volume": 1_500_000, "previous_close": 9.8},
                    {"trade_date": "2026-03-20", "symbol": "AAA", "open": 10.7, "high": 11.2, "low": 10.1, "close": 10.4, "volume": 1_900_000, "previous_close": 10.5},
                ]
            ),
            "daily_symbol_features_full_universe": pd.DataFrame(
                [
                    {"trade_date": "2026-03-19", "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_open": 10.0, "day_high": 10.8, "day_low": 9.7, "day_close": 10.5, "day_volume": 1_500_000, "previous_close": 9.8, "close_trade_hygiene_score": 0.82, "reclaimed_start_price_within_30s": True, "early_dip_pct_10s": -0.8, "open_to_current_pct": 1.6, "window_return_pct": 1.6, "close_preclose_return_pct": 0.4},
                    {"trade_date": "2026-03-20", "symbol": "AAA", "exchange": "NASDAQ", "company_name": "Alpha Holdings", "asset_type": "stock", "market_cap": 3_200_000_000, "day_open": 10.7, "day_high": 11.2, "day_low": 10.1, "day_close": 10.4, "day_volume": 1_900_000, "previous_close": 10.5, "close_trade_hygiene_score": 0.76, "reclaimed_start_price_within_30s": False, "early_dip_pct_10s": -1.0, "open_to_current_pct": -0.5, "window_return_pct": -0.5, "close_preclose_return_pct": -0.3},
                ]
            ),
        },
    }
    session_minute_detail = pd.DataFrame(
        [
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": pd.Timestamp("2026-03-19T13:30:00Z"), "session": "regular", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 50_000, "trade_count": 75},
            {"trade_date": "2026-03-19", "symbol": "AAA", "timestamp": pd.Timestamp("2026-03-19T21:10:00Z"), "session": "afterhours", "open": 10.5, "high": 10.55, "low": 10.45, "close": 10.48, "volume": 18_000, "trade_count": 20},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"), "session": "regular", "open": 10.7, "high": 10.8, "low": 10.5, "close": 10.6, "volume": 80_000, "trade_count": 95},
            {"trade_date": "2026-03-20", "symbol": "AAA", "timestamp": pd.Timestamp("2026-03-20T21:25:00Z"), "session": "afterhours", "open": 10.35, "high": 10.4, "low": 10.2, "close": 10.28, "volume": 21_000, "trade_count": 22},
        ]
    )

    result = generate_base_from_bundle(
        bundle_payload,
        schema_path=SCHEMA_PATH,
        output_dir=tmp_path,
        write_xlsx=True,
        session_minute_detail=session_minute_detail,
    )

    output_paths = result["output_paths"]
    assert output_paths["base_csv"].exists()
    assert output_paths["base_xlsx"].exists()
    assert output_paths["mapping_md"].exists()
    assert output_paths["mapping_json"].exists()
    assert output_paths["base_manifest"].exists()


def test_resolve_base_csv_selection_requires_explicit_choice_when_multiple_candidates(tmp_path: Path) -> None:
    newest = tmp_path / "z__smc_microstructure_base_2026-03-20.csv"
    older = tmp_path / "a__smc_microstructure_base_2026-03-19.csv"
    newest.write_text("symbol\nAAA\n", encoding="utf-8")
    older.write_text("symbol\nBBB\n", encoding="utf-8")

    candidates = [newest, older]

    assert resolve_base_csv_selection(candidates, None) is None
    assert resolve_base_csv_selection(candidates, "") is None
    assert resolve_base_csv_selection(candidates, older.name) == older


def test_resolve_base_csv_selection_keeps_single_candidate_autoselect(tmp_path: Path) -> None:
    only = tmp_path / "single__smc_microstructure_base_2026-03-20.csv"
    only.write_text("symbol\nAAA\n", encoding="utf-8")

    assert resolve_base_csv_selection([only], None) == only


def test_list_generated_base_csvs_orders_newest_first(tmp_path: Path) -> None:
    older = tmp_path / "older__smc_microstructure_base_2026-03-20.csv"
    newer = tmp_path / "newer__smc_microstructure_base_2026-03-21.csv"
    older.write_text("a\n", encoding="utf-8")
    newer.write_text("b\n", encoding="utf-8")
    older.touch()
    newer.touch()

    candidates = list_generated_base_csvs(tmp_path)

    assert candidates[0] == newer
    assert candidates[1] == older


def test_assert_complete_symbol_coverage_rejects_partial_frames() -> None:
    frame = pd.DataFrame(
        [
            {"symbol": "AAA", "trade_date": "2026-03-20", "timestamp": pd.Timestamp("2026-03-20T13:30:00Z")},
        ]
    )

    with pytest.raises(RuntimeError, match="incomplete symbol coverage"):
        _assert_complete_symbol_coverage(frame, {"AAA", "BBB"}, context="unit-test")


def test_evaluate_micro_library_publish_guard_requires_full_contract(tmp_path: Path) -> None:
    generated_dir = tmp_path / "pine" / "generated"
    generated_dir.mkdir(parents=True)
    manifest_path = generated_dir / "smc_micro_profiles_generated.json"
    snippet_path = generated_dir / "smc_micro_profiles_core_import_snippet.pine"
    library_path = generated_dir / "smc_micro_profiles_generated.pine"
    core_path = tmp_path / "SMC_Core_Engine.pine"

    manifest_path.write_text(
        json.dumps(
            {
                "library_owner": "preuss_steffen",
                "library_version": 1,
                "recommended_import_path": "preuss_steffen/smc_micro_profiles_generated/1",
                "core_import_snippet": "pine/generated/smc_micro_profiles_core_import_snippet.pine",
                "pine_library": "pine/generated/smc_micro_profiles_generated.pine",
            }
        ),
        encoding="utf-8",
    )
    snippet_path.write_text(
        "import preuss_steffen/smc_micro_profiles_generated/1 as mp\nstring clean_reclaim_tickers_effective = mp.CLEAN_RECLAIM_TICKERS\n",
        encoding="utf-8",
    )
    library_path.write_text("//@version=6\nlibrary(\"smc_micro_profiles_generated\")\n", encoding="utf-8")
    core_path.write_text("//@version=6\nimport preuss_steffen/smc_micro_profiles_generated/1 as mp\n", encoding="utf-8")

    guard = evaluate_micro_library_publish_guard(
        repo_root=tmp_path,
        library_owner="preuss_steffen",
        library_version=1,
    )

    assert guard["can_publish"] is False
    assert guard["contract"]["owner_version_ready"] is True
    assert guard["contract"]["full_contract_ready"] is False


def test_load_fundamental_reference_does_not_persist_empty_cache_without_key(tmp_path: Path) -> None:
    frame = export_mod._load_fundamental_reference(
        "",
        cache_dir=tmp_path,
        use_file_cache=True,
        force_refresh=False,
    )

    assert frame.empty
    assert export_mod._fundamental_reference_cache_path(tmp_path).exists() is False


def test_load_fundamental_reference_refreshes_stale_negative_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_path = export_mod._fundamental_reference_cache_path(tmp_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    export_mod._empty_fundamental_reference_frame().to_parquet(cache_path, index=False)
    stale_time = 1_700_000_000
    os.utime(cache_path, (stale_time, stale_time))

    class FakeFMPClient:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def get_profile_bulk(self) -> list[dict[str, object]]:
            return [{"symbol": "AAA", "companyName": "Alpha", "marketCap": 123.0}]

    monkeypatch.setattr(export_mod, "FMPClient", FakeFMPClient)
    monkeypatch.setattr(export_mod, "datetime", type("FakeDateTime", (), {
        "now": staticmethod(lambda tz=None: export_mod.datetime.fromtimestamp(stale_time + export_mod.FUNDAMENTAL_REFERENCE_EMPTY_CACHE_TTL_SECONDS + 60, tz=tz)),
        "fromtimestamp": staticmethod(export_mod.datetime.fromtimestamp),
    }))

    frame = export_mod._load_fundamental_reference(
        "demo-key",
        cache_dir=tmp_path,
        use_file_cache=True,
        force_refresh=False,
    )

    assert list(frame["symbol"]) == ["AAA"]