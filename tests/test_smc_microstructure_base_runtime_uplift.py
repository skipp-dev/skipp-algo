"""Targeted coverage uplift for `scripts/smc_microstructure_base_runtime`.

The primary `tests/test_smc_microstructure_base_runtime.py` already exercises
the heavy bundle/snapshot/incremental paths. This file fills the remaining
~11% gap by hitting:

- `infer_universe_bucket` market-cap bands (etf / NaN / large / mid / small).
- `_resolve_incremental_trade_days` empty / no-previous / out-of-range / in-range.
- Direct unit tests for the small `_session_stats` / `_window_efficiency` /
  `_bar_spread_bps` / `_bar_wickiness` helpers (empty + non-empty branches).
- `build_bundle_mapping_statuses` direct/derived/fallback note coverage.
- `write_base_workbook` happy-path + empty-snapshot branch.
- `generate_pine_library_from_base` thin-wrapper proxy.
- `_safe_ratio` divisor-zero / non-finite branches.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from scripts import smc_microstructure_base_runtime as runtime
from scripts.smc_microstructure_base_runtime import (
    MappingStatus,
    _bar_spread_bps,
    _bar_wickiness,
    _resolve_incremental_trade_days,
    _safe_ratio,
    _session_stats,
    _window_efficiency,
    build_bundle_mapping_statuses,
    generate_pine_library_from_base,
    infer_asset_type,
    infer_universe_bucket,
    write_base_workbook,
)

# ---------------------------------------------------------------------------
# infer_asset_type / infer_universe_bucket
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "explicit", "expected"),
    [
        ("Apple Inc.", None, "stock"),
        ("Apple Inc.", "ETF", "etf"),
        ("Apple Inc.", "  Stock  ", "stock"),
        ("SPDR S&P 500 ETF Trust", None, "etf"),
        ("Vanguard Total Stock Market Index Fund ETF", None, "etf"),
        ("", None, "stock"),
        (None, None, "stock"),
    ],
)
def test_infer_asset_type_matrix(
    name: str | None, explicit: str | None, expected: str
) -> None:
    assert infer_asset_type(name or "", explicit_asset_type=explicit) == expected


@pytest.mark.parametrize(
    ("asset_type", "market_cap", "expected"),
    [
        ("etf", 1.0, "us_etf"),
        ("etf", None, "us_etf"),  # ETF short-circuits before market_cap check
        ("stock", None, "us_unknown"),
        ("stock", float("nan"), "us_unknown"),
        ("stock", 50_000_000_000.0, "us_largecap"),
        ("stock", 10_000_000_000.0, "us_largecap"),  # boundary
        ("stock", 5_000_000_000.0, "us_midcap"),
        ("stock", 2_000_000_000.0, "us_midcap"),  # boundary
        ("stock", 500_000_000.0, "us_smallcap"),
    ],
)
def test_infer_universe_bucket_bands(
    asset_type: str, market_cap: float | None, expected: str
) -> None:
    assert infer_universe_bucket(asset_type, market_cap) == expected


# ---------------------------------------------------------------------------
# _resolve_incremental_trade_days
# ---------------------------------------------------------------------------


def test_resolve_incremental_trade_days_empty_input() -> None:
    assert _resolve_incremental_trade_days([], None) == []
    assert _resolve_incremental_trade_days([], date(2026, 4, 23)) == []


def test_resolve_incremental_trade_days_previous_none_returns_full_list() -> None:
    days = [date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23)]
    assert _resolve_incremental_trade_days(days, None) == days


def test_resolve_incremental_trade_days_previous_not_in_list_returns_full() -> None:
    days = [date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23)]
    assert _resolve_incremental_trade_days(days, date(2026, 1, 1)) == days


def test_resolve_incremental_trade_days_in_range_slices_with_one_day_overlap() -> None:
    days = [
        date(2026, 4, 20),
        date(2026, 4, 21),
        date(2026, 4, 22),
        date(2026, 4, 23),
    ]
    # previous_asof = 22 → previous_index=2 → start_index=1 → days[1:] (21,22,23)
    out = _resolve_incremental_trade_days(days, date(2026, 4, 22))
    assert out == [date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23)]


def test_resolve_incremental_trade_days_first_element_clamps_to_zero() -> None:
    days = [date(2026, 4, 20), date(2026, 4, 21)]
    # previous_asof = 20 → previous_index=0 → start_index=max(0,-1)=0 → full list
    assert _resolve_incremental_trade_days(days, date(2026, 4, 20)) == days


# ---------------------------------------------------------------------------
# _session_stats / _window_efficiency / _bar_spread_bps / _bar_wickiness
# ---------------------------------------------------------------------------


def test_window_efficiency_empty_returns_zero() -> None:
    assert _window_efficiency(pd.DataFrame()) == 0.0


def test_window_efficiency_zero_range_returns_zero() -> None:
    frame = pd.DataFrame(
        [
            {"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0},
            {"open": 100.0, "close": 100.0, "high": 100.0, "low": 100.0},
        ]
    )
    assert _window_efficiency(frame) == 0.0


def test_window_efficiency_normal_range_returns_clipped_ratio() -> None:
    frame = pd.DataFrame(
        [
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 100.0},
            {"open": 100.0, "high": 110.0, "low": 90.0, "close": 108.0},
        ]
    )
    # |close-open| = |108-100| = 8; range = 110-90 = 20; ratio = 0.4
    assert _window_efficiency(frame) == pytest.approx(0.4)


def test_window_efficiency_nan_open_or_close_returns_zero() -> None:
    frame = pd.DataFrame(
        [
            {"open": np.nan, "high": 105.0, "low": 95.0, "close": 100.0},
        ]
    )
    assert _window_efficiency(frame) == 0.0


def test_bar_spread_bps_zero_mid_yields_nan_and_positive_mid_yields_value() -> None:
    frame = pd.DataFrame(
        [
            {"high": 0.0, "low": 0.0},  # mid=0 → NaN
            {"high": 101.0, "low": 99.0},  # mid=100, spread=2 → 200 bps
        ]
    )
    out = _bar_spread_bps(frame)
    assert np.isnan(out[0])
    assert out[1] == pytest.approx(200.0)


def test_bar_wickiness_zero_range_yields_nan_otherwise_ratio() -> None:
    frame = pd.DataFrame(
        [
            {"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0},
            # range=20, upper_wick = 110-max(100,108)=2, lower_wick=min(100,108)-90=10
            # raw=(2+10)/20=0.6 (already in [0,1] so no clip)
            {"open": 100.0, "high": 110.0, "low": 90.0, "close": 108.0},
            # Force >1 case to exercise the upper-clip: open=close=100, high=200, low=0
            # upper_wick=100, lower_wick=100, range=200 → raw=1.0 (boundary, no clip)
            {"open": 100.0, "high": 200.0, "low": 0.0, "close": 100.0},
        ]
    )
    series = _bar_wickiness(frame)
    assert pd.isna(series.iloc[0])
    assert series.iloc[1] == pytest.approx(0.6)
    assert series.iloc[2] == pytest.approx(1.0)


def test_session_stats_empty_returns_all_zero_dict() -> None:
    out = _session_stats(pd.DataFrame(), available_minutes=60)
    assert out == {
        "dollar_volume": 0.0,
        "trade_proxy": 0.0,
        "active_minutes": 0.0,
        "active_minutes_share": 0.0,
        "spread_bps": 0.0,
        "wickiness": 0.0,
        "efficiency": 0.0,
    }


def test_session_stats_aggregates_non_empty_frame() -> None:
    frame = pd.DataFrame(
        [
            {
                "dollar_volume": 1000.0,
                "trade_proxy": 10.0,
                "active_minute": 1,
                "spread_bps_proxy": 5.0,
                "wickiness_proxy": 0.2,
                "open": 100.0,
                "close": 110.0,
                "high": 110.0,
                "low": 100.0,
            },
            {
                "dollar_volume": 2000.0,
                "trade_proxy": 20.0,
                "active_minute": 1,
                "spread_bps_proxy": 7.0,
                "wickiness_proxy": 0.4,
                "open": 110.0,
                "close": 105.0,
                "high": 115.0,
                "low": 105.0,
            },
        ]
    )
    out = _session_stats(frame, available_minutes=4)
    assert out["dollar_volume"] == 3000.0
    assert out["trade_proxy"] == 30.0
    assert out["active_minutes"] == 2.0
    assert out["active_minutes_share"] == pytest.approx(0.5)
    assert out["spread_bps"] == pytest.approx(6.0)
    assert out["wickiness"] == pytest.approx(0.3)
    # |close-open| = |105-100| = 5; range = 115-100 = 15; eff = 5/15 ≈ 0.333
    assert out["efficiency"] == pytest.approx(5.0 / 15.0)


# ---------------------------------------------------------------------------
# _safe_ratio
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("numerator", "denominator", "default", "expected"),
    [
        (10.0, 2.0, 0.0, 5.0),
        (10.0, 0.0, 0.0, 0.0),
        (10.0, 0, 0.0, 0.0),
        (10.0, None, -1.0, -1.0),
        (None, 2.0, -1.0, -1.0),
        (float("nan"), 2.0, 0.0, 0.0),
        (10.0, float("nan"), 0.0, 0.0),
        (float("inf"), 2.0, 0.0, 0.0),
        (10.0, float("inf"), 0.0, 0.0),
    ],
)
def test_safe_ratio_branches(
    numerator: Any, denominator: Any, default: float, expected: float
) -> None:
    assert _safe_ratio(numerator, denominator, default=default) == expected


# ---------------------------------------------------------------------------
# build_bundle_mapping_statuses
# ---------------------------------------------------------------------------


def test_build_bundle_mapping_statuses_direct_field() -> None:
    statuses = build_bundle_mapping_statuses(["asof_date", "symbol", "exchange"])
    assert all(isinstance(s, MappingStatus) for s in statuses)
    assert {s.field for s in statuses} == {"asof_date", "symbol", "exchange"}
    assert all(s.status == "direct" for s in statuses)


def test_build_bundle_mapping_statuses_known_derived_field() -> None:
    statuses = build_bundle_mapping_statuses(["adv_dollar_rth_20d"])
    assert len(statuses) == 1
    assert statuses[0].field == "adv_dollar_rth_20d"
    assert statuses[0].status == "derived"
    # Must come from the curated derived_note dict, not the generic fallback.
    assert "Derived from the Databento production bundle plus session-minute" not in statuses[0].note


def test_build_bundle_mapping_statuses_unknown_field_uses_fallback_note() -> None:
    statuses = build_bundle_mapping_statuses(["totally_made_up_field"])
    assert len(statuses) == 1
    s = statuses[0]
    assert s.field == "totally_made_up_field"
    assert s.status == "derived"
    assert s.source_sheet == "daily_symbol_features_full_universe,session_minute_detail_full_universe"
    assert s.source_columns == []
    assert s.note.startswith("Derived from the Databento production bundle")


def test_build_bundle_mapping_statuses_preserves_input_order() -> None:
    cols = ["exchange", "totally_made_up_field", "asof_date", "wickiness_20d"]
    statuses = build_bundle_mapping_statuses(cols)
    assert [s.field for s in statuses] == cols


# ---------------------------------------------------------------------------
# write_base_workbook
# ---------------------------------------------------------------------------


def _mapping_payload_for(snapshot: pd.DataFrame) -> dict[str, Any]:
    return {
        "bundle_manifest_path": "/tmp/manifest.json",
        "asof_date": "2026-04-23",
        "row_count": len(snapshot),
        "direct_fields": ["symbol"],
        "derived_fields": ["adv_dollar_rth_20d"],
        "missing_fields": [],
        "mapping_status": [
            {
                "field": "symbol",
                "status": "direct",
                "source_sheet": "daily_symbol_features_full_universe",
                "source_columns": ["symbol"],
                "note": "Direct symbol from daily feature export.",
            }
        ],
    }


def test_write_base_workbook_happy_path(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    snapshot = pd.DataFrame(
        [
            {"symbol": "AAA", "adv_dollar_rth_20d": 1.0},
            {"symbol": "BBB", "adv_dollar_rth_20d": 2.0},
        ]
    )
    out = tmp_path / "out" / "base.xlsx"
    write_base_workbook(out, snapshot, _mapping_payload_for(snapshot))
    assert out.exists() and out.stat().st_size > 0

    sheets = pd.read_excel(out, sheet_name=None)
    assert set(sheets.keys()) == {"base_snapshot", "summary", "mapping_status"}
    base_sheet = sheets["base_snapshot"].reset_index(drop=True)
    assert list(base_sheet.columns) == ["symbol", "adv_dollar_rth_20d"]
    assert base_sheet["symbol"].tolist() == ["AAA", "BBB"]
    assert base_sheet["adv_dollar_rth_20d"].tolist() == [1.0, 2.0]
    summary_row = sheets["summary"].iloc[0]
    assert summary_row["bundle_manifest_path"] == "/tmp/manifest.json"
    assert summary_row["asof_date"] == "2026-04-23"
    assert summary_row["row_count"] == 2
    assert summary_row["base_snapshot_sheet_count"] == 1


def test_write_base_workbook_empty_snapshot_emits_empty_sheet(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    snapshot = pd.DataFrame(columns=["symbol", "adv_dollar_rth_20d"])
    out = tmp_path / "out" / "empty.xlsx"
    write_base_workbook(out, snapshot, _mapping_payload_for(snapshot))
    assert out.exists()
    sheets = pd.read_excel(out, sheet_name=None)
    assert "base_snapshot" in sheets
    assert sheets["base_snapshot"].empty
    # Summary still records 0 rows + sheet count of 1.
    assert sheets["summary"].iloc[0]["row_count"] == 0
    assert sheets["summary"].iloc[0]["base_snapshot_sheet_count"] == 1


# ---------------------------------------------------------------------------
# generate_pine_library_from_base
# ---------------------------------------------------------------------------


def test_generate_pine_library_from_base_proxies_to_run_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_generation(
        *,
        schema_path: Path,
        input_path: Path,
        overrides_path: Path | None,
        output_root: Path,
        library_owner: str,
        library_version: int,
        enrichment: Any,
    ) -> dict[str, Path]:
        captured["schema_path"] = schema_path
        captured["input_path"] = input_path
        captured["overrides_path"] = overrides_path
        captured["output_root"] = output_root
        captured["library_owner"] = library_owner
        captured["library_version"] = library_version
        captured["enrichment"] = enrichment
        return {"pine_path": output_root / "lib.pine"}

    monkeypatch.setattr(runtime, "run_generation", fake_run_generation)

    base_csv = tmp_path / "base.csv"
    base_csv.write_text("symbol\nAAA\n")
    schema = tmp_path / "schema.json"
    schema.write_text("{}")
    output_root = tmp_path / "out"

    result = generate_pine_library_from_base(
        base_csv_path=base_csv,
        schema_path=schema,
        output_root=output_root,
        library_owner="custom_owner",
        library_version=7,
    )

    assert result == {"pine_path": output_root / "lib.pine"}
    assert captured["input_path"] == base_csv
    assert captured["schema_path"] == schema
    assert captured["output_root"] == output_root
    assert captured["overrides_path"] is None
    assert captured["library_owner"] == "custom_owner"
    assert captured["library_version"] == 7
    assert captured["enrichment"] is None


def test_generate_pine_library_from_base_passes_overrides_and_enrichment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        runtime,
        "run_generation",
        lambda **kwargs: captured.update(kwargs) or {"ok": tmp_path / "x"},
    )

    overrides = tmp_path / "overrides.json"
    overrides.write_text("{}")
    enrichment = {"asof_date": "2026-04-23"}
    generate_pine_library_from_base(
        base_csv_path=tmp_path / "base.csv",
        schema_path=tmp_path / "schema.json",
        output_root=tmp_path / "out",
        overrides_path=overrides,
        enrichment=enrichment,  # type: ignore[arg-type]
    )
    assert captured["overrides_path"] == overrides
    assert captured["enrichment"] == enrichment
    # Defaults preserved when not overridden.
    assert captured["library_owner"] == "preuss_steffen"
    assert captured["library_version"] == 1
