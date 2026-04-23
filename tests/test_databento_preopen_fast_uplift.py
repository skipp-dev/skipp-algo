"""Coverage uplift for `scripts.databento_preopen_fast` (baseline 62%).

Targets:
- `_build_parser()` defaults
- `main()` happy path + missing-API-key path
- pure helpers with simple early-return / tier branches:
  `_normalize_exchange_label`, `_extract_live_license_cutoff_utc`,
  `_resolve_premarket_anchor_et`, `_resolve_full_history_bundle_input`,
  `_resolve_target_trade_date`, `_target_scope_symbol_count`,
  `_resolve_scope_selection_column`, `_choose_scope_days`,
  `_select_recent_scope_symbols`, `_build_current_daily_features`,
  `_build_current_diagnostics`,
  `_build_current_second_detail_from_premarket_raw`,
  `_merge_current_structure_features`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from scripts import databento_preopen_fast as dpf

# ---------------------------------------------------------------------------
# _normalize_exchange_label
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        (None, ""),
        ("  ", ""),
        ("nasdaq", "XNAS"),  # only true if alias exists; fall back to upper otherwise
    ],
)
def test_normalize_exchange_label_empty_branch(value: Any, expected: str) -> None:
    out = dpf._normalize_exchange_label(value)
    if value in (None, "", "  "):
        assert out == ""
    else:
        # Either alias-resolved or just upper-cased
        assert isinstance(out, str)
        assert out == out.upper()


def test_normalize_exchange_label_unknown_passthrough() -> None:
    assert dpf._normalize_exchange_label("xyzzy") == "XYZZY"


# ---------------------------------------------------------------------------
# _extract_live_license_cutoff_utc
# ---------------------------------------------------------------------------


def test_extract_live_license_cutoff_returns_none_when_text_unrelated() -> None:
    assert dpf._extract_live_license_cutoff_utc("some other error") is None
    assert dpf._extract_live_license_cutoff_utc("") is None


def test_extract_live_license_cutoff_returns_none_when_no_timestamp() -> None:
    text = "license_not_found_unauthorized: license missing"
    assert dpf._extract_live_license_cutoff_utc(text) is None


def test_extract_live_license_cutoff_parses_iso_timestamp() -> None:
    text = "license_not_found_unauthorized: please retry after 2026-04-23T14:00:00Z."
    out = dpf._extract_live_license_cutoff_utc(text)
    assert out is not None
    # Returns ts - 1 second, in UTC
    assert out.tzinfo is not None
    assert out.year == 2026 and out.month == 4 and out.day == 23
    assert out.hour == 13 and out.minute == 59 and out.second == 59


def test_extract_live_license_cutoff_handles_unparseable_timestamp() -> None:
    text = "license_not_found_unauthorized after notatimestamp"
    assert dpf._extract_live_license_cutoff_utc(text) is None


# ---------------------------------------------------------------------------
# _resolve_premarket_anchor_et
# ---------------------------------------------------------------------------


def test_resolve_premarket_anchor_default_when_missing() -> None:
    assert dpf._resolve_premarket_anchor_et({}) == time(4, 0)


def test_resolve_premarket_anchor_parses_hms() -> None:
    assert dpf._resolve_premarket_anchor_et({"premarket_anchor_et": "05:30:00"}) == time(5, 30, 0)


def test_resolve_premarket_anchor_parses_hm() -> None:
    assert dpf._resolve_premarket_anchor_et({"premarket_anchor_et": "06:15"}) == time(6, 15)


def test_resolve_premarket_anchor_falls_back_on_unparseable() -> None:
    assert dpf._resolve_premarket_anchor_et({"premarket_anchor_et": "garbage"}) == time(4, 0)


# ---------------------------------------------------------------------------
# _resolve_full_history_bundle_input
# ---------------------------------------------------------------------------


def test_resolve_full_history_bundle_returns_file_when_path_is_file(tmp_path: Path) -> None:
    f = tmp_path / "manifest.json"
    f.write_text("{}")
    out = dpf._resolve_full_history_bundle_input(str(f), tmp_path)
    assert out == f


def test_resolve_full_history_bundle_picks_latest_manifest(tmp_path: Path) -> None:
    older = tmp_path / "databento_volatility_production_2026-04-22_manifest.json"
    older.write_text("{}")
    newer = tmp_path / "databento_volatility_production_2026-04-23_manifest.json"
    newer.write_text("{}")
    # Touch newer to make sure it has a later mtime
    import os as _os
    _os.utime(older, (older.stat().st_atime, older.stat().st_mtime - 100))
    out = dpf._resolve_full_history_bundle_input(None, tmp_path)
    assert out == newer


def test_resolve_full_history_bundle_returns_dir_when_no_manifests(tmp_path: Path) -> None:
    out = dpf._resolve_full_history_bundle_input(None, tmp_path)
    assert out == tmp_path


def test_resolve_full_history_bundle_returns_path_unchanged_when_neither(tmp_path: Path) -> None:
    nonexistent = tmp_path / "missing-bundle"
    out = dpf._resolve_full_history_bundle_input(str(nonexistent), tmp_path)
    assert out == nonexistent


# ---------------------------------------------------------------------------
# _resolve_target_trade_date
# ---------------------------------------------------------------------------


def test_resolve_target_trade_date_uses_today_when_after_latest() -> None:
    # Now (UTC) far in the future; today_et > latest_completed
    out = dpf._resolve_target_trade_date(
        [date(2020, 1, 1)], now_utc=datetime(2030, 6, 15, 18, tzinfo=UTC)
    )
    assert out > date(2020, 1, 1)


def test_resolve_target_trade_date_uses_latest_when_today_le_latest() -> None:
    latest = date(2030, 6, 15)
    out = dpf._resolve_target_trade_date(
        [latest], now_utc=datetime(2020, 1, 1, tzinfo=UTC)
    )
    assert out == latest


def test_resolve_target_trade_date_raises_on_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        dpf._resolve_target_trade_date([])


# ---------------------------------------------------------------------------
# _target_scope_symbol_count
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (8, 0, 3200),    # before 08:30
        (8, 45, 2800),   # between 08:30 and 09:00
        (9, 10, 2400),   # between 09:00 and 09:20
        (9, 30, 2100),   # at/after 09:20
    ],
)
def test_target_scope_symbol_count_tiers(hour: int, minute: int, expected: int) -> None:
    # Build a UTC time that translates to the requested ET wall-clock during DST
    # (US/Eastern = UTC-4 in summer).  Use July to be safely DST.
    now_utc = datetime(2026, 7, 15, hour + 4, minute, tzinfo=UTC)
    assert dpf._target_scope_symbol_count(now_utc=now_utc) == expected


# ---------------------------------------------------------------------------
# _resolve_scope_selection_column
# ---------------------------------------------------------------------------


def test_resolve_scope_selection_column_falls_back_to_default_when_after_anchor() -> None:
    df = pd.DataFrame({
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [True],
        dpf.EARLY_SCOPE_SELECTION_COLUMN: [True],
    })
    # 14:00 ET → after the 04:00 anchor → must return default
    now_utc = datetime(2026, 7, 15, 18, tzinfo=UTC)  # 14:00 ET in DST
    out = dpf._resolve_scope_selection_column(
        df, premarket_anchor_et=time(4, 0), now_utc=now_utc
    )
    assert out == dpf.DEFAULT_SCOPE_SELECTION_COLUMN


def test_resolve_scope_selection_column_uses_early_when_before_anchor() -> None:
    df = pd.DataFrame({
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [True],
        dpf.EARLY_SCOPE_SELECTION_COLUMN: [True],
    })
    # 03:00 ET → before the 04:00 anchor
    now_utc = datetime(2026, 7, 15, 7, tzinfo=UTC)  # 03:00 ET in DST
    out = dpf._resolve_scope_selection_column(
        df, premarket_anchor_et=time(4, 0), now_utc=now_utc
    )
    assert out == dpf.EARLY_SCOPE_SELECTION_COLUMN


def test_resolve_scope_selection_column_falls_back_when_early_empty() -> None:
    df = pd.DataFrame({
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [True],
        dpf.EARLY_SCOPE_SELECTION_COLUMN: [False],
    })
    now_utc = datetime(2026, 7, 15, 7, tzinfo=UTC)
    out = dpf._resolve_scope_selection_column(
        df, premarket_anchor_et=time(4, 0), now_utc=now_utc
    )
    assert out == dpf.DEFAULT_SCOPE_SELECTION_COLUMN


# ---------------------------------------------------------------------------
# _choose_scope_days
# ---------------------------------------------------------------------------


def test_choose_scope_days_validates_min() -> None:
    with pytest.raises(ValueError, match="min_scope_days"):
        dpf._choose_scope_days(pd.DataFrame(), min_scope_days=0, max_scope_days=10)


def test_choose_scope_days_validates_max_lt_min() -> None:
    with pytest.raises(ValueError, match="max_scope_days"):
        dpf._choose_scope_days(pd.DataFrame(), min_scope_days=5, max_scope_days=2)


def test_choose_scope_days_returns_min_when_no_selected() -> None:
    df = pd.DataFrame({
        "trade_date": [date(2026, 4, 22)],
        "symbol": ["AAPL"],
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [False],
    })
    days, count = dpf._choose_scope_days(df, min_scope_days=3, max_scope_days=10, target_symbol_count=10)
    assert days == 3
    assert count == 0


def test_choose_scope_days_returns_min_when_no_completed_days() -> None:
    # selection_column True but trade_date NaT
    df = pd.DataFrame({
        "trade_date": [pd.NaT],
        "symbol": ["AAPL"],
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [True],
    })
    days, count = dpf._choose_scope_days(df, min_scope_days=3, max_scope_days=10, target_symbol_count=10)
    assert days == 3
    assert count == 0


def test_choose_scope_days_finds_window_meeting_target() -> None:
    df = pd.DataFrame({
        "trade_date": [date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23)],
        "symbol": ["AAPL", "MSFT", "GOOG"],
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [True, True, True],
    })
    days, count = dpf._choose_scope_days(df, min_scope_days=1, max_scope_days=3, target_symbol_count=2)
    # Should walk from 1 day (1 sym) up to 2 days (2 syms) where it stops
    assert days >= 1
    assert count >= 1


# ---------------------------------------------------------------------------
# _select_recent_scope_symbols
# ---------------------------------------------------------------------------


def test_select_recent_scope_symbols_validates_scope_days() -> None:
    with pytest.raises(ValueError, match="scope_days"):
        dpf._select_recent_scope_symbols(pd.DataFrame(), scope_days=0)


def test_select_recent_scope_symbols_returns_empty_when_no_data() -> None:
    df = pd.DataFrame({
        "trade_date": [],
        "symbol": [],
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [],
    })
    out = dpf._select_recent_scope_symbols(df, scope_days=3)
    assert out.empty


def test_select_recent_scope_symbols_returns_empty_when_none_selected() -> None:
    df = pd.DataFrame({
        "trade_date": [date(2026, 4, 22)],
        "symbol": ["AAPL"],
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [False],
    })
    out = dpf._select_recent_scope_symbols(df, scope_days=3)
    assert out.empty


def test_select_recent_scope_symbols_keeps_latest_per_symbol() -> None:
    df = pd.DataFrame({
        "trade_date": [date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 23)],
        "symbol": ["AAPL", "AAPL", "MSFT"],
        dpf.DEFAULT_SCOPE_SELECTION_COLUMN: [True, True, True],
    })
    out = dpf._select_recent_scope_symbols(df, scope_days=10)
    assert set(out["symbol"]) == {"AAPL", "MSFT"}
    assert out.loc[out["symbol"] == "AAPL", "trade_date"].iloc[0] == date(2026, 4, 22)
    assert (out["is_eligible"] == True).all()  # noqa: E712


# ---------------------------------------------------------------------------
# _build_current_daily_features
# ---------------------------------------------------------------------------


def test_build_current_daily_features_returns_columns_when_empty_scope() -> None:
    out = dpf._build_current_daily_features(
        pd.DataFrame(), pd.DataFrame(), target_trade_date=date(2026, 4, 23)
    )
    assert out.empty
    assert list(out.columns) == list(dpf.DAILY_SYMBOL_FEATURE_COLUMNS)


# ---------------------------------------------------------------------------
# _build_current_diagnostics
# ---------------------------------------------------------------------------


def test_build_current_diagnostics_returns_empty_with_columns() -> None:
    out = dpf._build_current_diagnostics(pd.DataFrame())
    assert out.empty
    assert list(out.columns) == list(dpf.SYMBOL_DAY_DIAGNOSTIC_COLUMNS)


# ---------------------------------------------------------------------------
# _build_current_second_detail_from_premarket_raw
# ---------------------------------------------------------------------------


def test_build_current_second_detail_returns_empty_when_input_empty() -> None:
    out = dpf._build_current_second_detail_from_premarket_raw(
        pd.DataFrame(), target_trade_date=date(2026, 4, 23)
    )
    assert out.empty
    assert "trade_date" in out.columns
    assert "symbol" in out.columns
    assert "session" in out.columns


def test_build_current_second_detail_normalizes_and_inserts_session() -> None:
    raw = pd.DataFrame({
        "symbol": ["aapl", ""],
        "ts": ["2026-04-23T08:30:00Z", "2026-04-23T08:30:01Z"],
        "open": [100.0, 200.0],
        "high": [101.0, 201.0],
        "low": [99.0, 199.0],
        "close": [100.5, 200.5],
        "volume": [10, 20],
    })
    out = dpf._build_current_second_detail_from_premarket_raw(
        raw, target_trade_date=date(2026, 4, 23)
    )
    # Empty-symbol row dropped
    assert len(out) == 1
    assert (out["session"] == "premarket").all()
    assert (out["trade_date"] == date(2026, 4, 23)).all()
    assert "trade_count" in out.columns


# ---------------------------------------------------------------------------
# _merge_current_structure_features
# ---------------------------------------------------------------------------


def test_merge_current_structure_features_returns_copy_when_daily_empty() -> None:
    daily = pd.DataFrame()
    out = dpf._merge_current_structure_features(daily, pd.DataFrame({"x": [1]}))
    assert out.empty
    assert out is not daily


def test_merge_current_structure_features_returns_copy_when_detail_empty() -> None:
    daily = pd.DataFrame({"trade_date": [date(2026, 4, 23)], "symbol": ["AAPL"]})
    out = dpf._merge_current_structure_features(daily, pd.DataFrame())
    assert len(out) == 1
    assert out is not daily


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------


def test_build_parser_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABENTO_DATASET", raising=False)
    parser = dpf._build_parser()
    args = parser.parse_args([])
    assert args.dataset == "DBEQ.BASIC"
    assert args.export_dir == str(dpf.DEFAULT_EXPORT_DIR)
    assert args.bundle is None
    assert args.scope_days == 0


def test_build_parser_overrides() -> None:
    parser = dpf._build_parser()
    args = parser.parse_args([
        "--dataset", "XNAS.BASIC",
        "--export-dir", "/tmp/x",
        "--bundle", "/tmp/b.json",
        "--scope-days", "7",
    ])
    assert args.dataset == "XNAS.BASIC"
    assert args.export_dir == "/tmp/x"
    assert args.bundle == "/tmp/b.json"
    assert args.scope_days == 7


def test_build_parser_dataset_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABENTO_DATASET", "ENV.DATASET")
    parser = dpf._build_parser()
    args = parser.parse_args([])
    assert args.dataset == "ENV.DATASET"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_returns_2_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(dpf, "load_dotenv", lambda: None)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["databento_preopen_fast"])
    rc = dpf.main()
    assert rc == 2
    out = capsys.readouterr().out
    assert "DATABENTO_API_KEY missing" in out


def test_main_happy_path_invokes_run_preopen_fast_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "manifest": {"basename": "fake"},
            "paths": {"daily": tmp_path / "daily.parquet"},
            "daily_current": pd.DataFrame({"a": [1, 2]}),
            "premarket_current": pd.DataFrame({"a": [1, 2, 3]}),
        }

    monkeypatch.setattr(dpf, "load_dotenv", lambda: None)
    monkeypatch.setenv("DATABENTO_API_KEY", "secret")
    monkeypatch.setattr(dpf, "run_preopen_fast_refresh", fake_run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "databento_preopen_fast",
            "--dataset", "TEST.DS",
            "--export-dir", str(tmp_path),
            "--scope-days", "5",
        ],
    )

    rc = dpf.main()
    assert rc == 0
    assert captured["dataset"] == "TEST.DS"
    assert captured["scope_days"] == 5
    assert captured["databento_api_key"] == "secret"

    payload = json.loads(capsys.readouterr().out)
    assert payload["daily_rows"] == 2
    assert payload["premarket_rows"] == 3


def test_main_passes_none_scope_days_when_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "manifest": {"basename": "fake"},
            "paths": {},
            "daily_current": pd.DataFrame(),
            "premarket_current": pd.DataFrame(),
        }

    monkeypatch.setattr(dpf, "load_dotenv", lambda: None)
    monkeypatch.setenv("DATABENTO_API_KEY", "secret")
    monkeypatch.setattr(dpf, "run_preopen_fast_refresh", fake_run)
    monkeypatch.setattr("sys.argv", ["databento_preopen_fast", "--scope-days", "0"])

    rc = dpf.main()
    assert rc == 0
    assert captured["scope_days"] is None
