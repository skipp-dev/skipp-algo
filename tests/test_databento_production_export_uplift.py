"""Coverage uplift for `scripts.databento_production_export`.

Targets `main()` plus a wide selection of pure helpers (env / scoring /
window / merge utilities). The module is mostly orchestration around DataFrame
pipelines, so we lean on the small primitive helpers and on a fully mocked
`main()` invocation to lift baseline coverage cheaply.
"""

from __future__ import annotations

from datetime import date, time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from scripts import databento_production_export as dpe
from scripts.databento_production_export import (
    _bool_series,
    _coalesce_optional_merge_column,
    _empty_fundamental_reference_frame,
    _env_flag,
    _format_quality_window_label,
    _fundamental_reference_cache_path,
    _make_export_fmp_client,
    _numeric_series,
    _parse_window_time_et,
    _quality_window_export_tag,
    _score_extension,
    _score_inverse_pct,
    _score_log_ratio,
    _score_pct,
    _window_bounds_for_trade_date,
    _window_label_from_tag,
    configure_bullish_quality_score_profile,
    main,
)

# ---------------------------------------------------------------------------
# _env_flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("yes", True), ("on", True),
     ("TRUE", True), ("Yes", True),
     ("0", False), ("false", False), ("no", False), ("off", False)],
)
def test_env_flag_truthy_falsy(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("MY_FLAG", value)
    assert _env_flag("MY_FLAG") is expected


def test_env_flag_default_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_FLAG", raising=False)
    assert _env_flag("MISSING_FLAG") is False
    assert _env_flag("MISSING_FLAG", default=True) is True


def test_env_flag_default_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_FLAG", "")
    assert _env_flag("MY_FLAG") is False
    assert _env_flag("MY_FLAG", default=True) is True


# ---------------------------------------------------------------------------
# _make_export_fmp_client (patching seam)
# ---------------------------------------------------------------------------


def test_make_export_fmp_client_uses_default_factory_when_unpatched() -> None:
    sentinel = object()
    with patch.object(dpe, "make_fmp_client", return_value=sentinel) as mocked:
        # Reset module-level seam to default
        dpe.FMPClient = dpe._DEFAULT_FMP_CLIENT_FACTORY
        out = _make_export_fmp_client("api-key")
    mocked.assert_called_once_with("api-key")
    assert out is sentinel


def test_make_export_fmp_client_uses_override_when_patched() -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, api_key: str) -> None:
            captured["api_key"] = api_key

    saved = dpe.FMPClient
    try:
        dpe.FMPClient = FakeClient  # type: ignore[assignment]
        out = _make_export_fmp_client("override-key")
    finally:
        dpe.FMPClient = saved

    assert isinstance(out, FakeClient)
    assert captured == {"api_key": "override-key"}


# ---------------------------------------------------------------------------
# configure_bullish_quality_score_profile
# ---------------------------------------------------------------------------


def test_configure_bullish_quality_score_profile_swaps_global() -> None:
    original = dpe._DEFAULT_BULLISH_QUALITY_CFG
    try:
        configure_bullish_quality_score_profile(score_profile="aggressive")
        assert dpe._DEFAULT_BULLISH_QUALITY_CFG is not original
        configure_bullish_quality_score_profile(score_profile="conservative")
        assert dpe._DEFAULT_BULLISH_QUALITY_CFG is not original
    finally:
        dpe._DEFAULT_BULLISH_QUALITY_CFG = original


# ---------------------------------------------------------------------------
# _parse_window_time_et
# ---------------------------------------------------------------------------


def test_parse_window_time_et_iso() -> None:
    assert _parse_window_time_et("09:30:00") == time(9, 30)
    assert _parse_window_time_et("16:00") == time(16, 0)


# ---------------------------------------------------------------------------
# Scoring helpers (_score_pct / _score_inverse_pct / _score_log_ratio /
# _score_extension)
# ---------------------------------------------------------------------------


def test_score_pct_clamps_and_scales() -> None:
    assert _score_pct(50.0, floor=0.0, ceiling=100.0) == 50.0
    assert _score_pct(-10.0, floor=0.0, ceiling=100.0) == 0.0
    assert _score_pct(150.0, floor=0.0, ceiling=100.0) == 100.0


def test_score_pct_invalid_returns_zero() -> None:
    assert _score_pct(np.nan, floor=0.0, ceiling=100.0) == 0.0
    assert _score_pct(50.0, floor=10.0, ceiling=10.0) == 0.0  # ceiling<=floor
    assert _score_pct("bad", floor=0.0, ceiling=100.0) == 0.0


def test_score_inverse_pct_mirrors_score_pct() -> None:
    assert _score_inverse_pct(25.0, floor=0.0, ceiling=100.0) == 75.0
    assert _score_inverse_pct(150.0, floor=0.0, ceiling=100.0) == 0.0


def test_score_log_ratio_ranges() -> None:
    assert _score_log_ratio(10.0, 1.0) == 100.0    # ratio=10 → log10=1 → 50+50=100
    assert _score_log_ratio(1.0, 1.0) == 50.0      # ratio=1 → log10=0 → 50
    assert _score_log_ratio(0.0, 1.0) == 0.0       # zero → guard
    assert _score_log_ratio(-1.0, 1.0) == 0.0      # negative → guard
    assert _score_log_ratio(np.nan, 1.0) == 0.0
    assert _score_log_ratio(5.0, 0.0) == 0.0       # min<=0 → guard


def test_score_extension_branches() -> None:
    assert _score_extension(np.nan) == 0.0
    assert _score_extension(-1.0) == 0.0           # numeric<=0
    assert _score_extension(1.0) == _score_pct(1.0, floor=0.0, ceiling=2.0)
    assert _score_extension(5.0) == 100.0          # plateau 2..12
    assert _score_extension(12.0) == 100.0
    assert _score_extension(25.0) == 0.0           # >=25 → 0
    assert _score_extension(30.0) == 0.0
    # decay zone 12..25
    assert _score_extension(18.5) == _score_inverse_pct(18.5, floor=12.0, ceiling=25.0)


# ---------------------------------------------------------------------------
# _window_bounds_for_trade_date
# ---------------------------------------------------------------------------


def test_window_bounds_for_trade_date_returns_utc_pair() -> None:
    from scripts.bullish_quality_config import PremarketWindowDefinition

    wd = PremarketWindowDefinition(
        tag="0930_1000_et",
        label="0930-1000",
        start_time_et="09:30:00",
        end_time_et="10:00:00",
    )
    start_utc, end_utc = _window_bounds_for_trade_date(date(2026, 4, 23), wd)
    assert start_utc.tzinfo is not None
    assert end_utc.tzinfo is not None
    # Both anchored at UTC after conversion
    assert str(start_utc.tz) == "UTC"
    assert end_utc > start_utc


# ---------------------------------------------------------------------------
# _bool_series / _numeric_series
# ---------------------------------------------------------------------------


def test_bool_series_returns_default_when_column_missing() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3]})
    out = _bool_series(frame, "missing", default=True)
    assert out.tolist() == [True, True, True]
    assert out.dtype == bool


def test_bool_series_passes_through_bool_dtype() -> None:
    frame = pd.DataFrame({"flag": [True, False, pd.NA]})
    out = _bool_series(frame, "flag", default=False)
    assert out.tolist() == [True, False, False]


def test_bool_series_parses_string_form() -> None:
    frame = pd.DataFrame({"flag": ["true", "FALSE", "??"]})
    out = _bool_series(frame, "flag", default=False)
    assert out.tolist() == [True, False, False]


def test_numeric_series_handles_missing_and_text() -> None:
    frame = pd.DataFrame({"a": ["1.5", "bad", "3"]})
    out = _numeric_series(frame, "a")
    assert out.iloc[0] == 1.5
    assert pd.isna(out.iloc[1])
    assert out.iloc[2] == 3.0

    out2 = _numeric_series(frame, "missing", fill_value=7.0)
    assert out2.tolist() == [7.0, 7.0, 7.0]


# ---------------------------------------------------------------------------
# _coalesce_optional_merge_column
# ---------------------------------------------------------------------------


def test_coalesce_optional_merge_column_no_candidates_inserts_na() -> None:
    frame = pd.DataFrame({"unrelated": [1, 2, 3]})
    out = _coalesce_optional_merge_column(frame, "missing")
    assert "missing" in out.columns
    assert out["missing"].isna().all()


def test_coalesce_optional_merge_column_prefers_left_over_suffix() -> None:
    frame = pd.DataFrame({
        "value_x": [1, None, 3],
        "value_y": [10, 20, 30],
    })
    out = _coalesce_optional_merge_column(frame, "value")
    assert out["value"].tolist() == [1, 20, 3]
    assert "value_x" not in out.columns
    assert "value_y" not in out.columns


def test_coalesce_optional_merge_column_passes_through_existing() -> None:
    frame = pd.DataFrame({"value": [1, 2, 3]})
    out = _coalesce_optional_merge_column(frame, "value")
    assert out["value"].tolist() == [1, 2, 3]


# ---------------------------------------------------------------------------
# _fundamental_reference_cache_path / _empty_fundamental_reference_frame
# ---------------------------------------------------------------------------


def test_fundamental_reference_cache_path_returns_pathlike(tmp_path: Path) -> None:
    p = _fundamental_reference_cache_path(tmp_path)
    assert isinstance(p, Path)
    # Cache path is rooted under our supplied dir
    assert str(p).startswith(str(tmp_path))


def test_empty_fundamental_reference_frame_has_expected_columns() -> None:
    out = _empty_fundamental_reference_frame()
    assert isinstance(out, pd.DataFrame)
    assert out.empty
    assert "symbol" in out.columns


# ---------------------------------------------------------------------------
# _format_quality_window_label / _quality_window_export_tag /
# _window_label_from_tag
# ---------------------------------------------------------------------------


def test_format_quality_window_label_returns_local_range() -> None:
    label = _format_quality_window_label(
        date(2026, 4, 23),
        start_et=time(9, 30),
        end_et=time(10, 0),
        display_timezone="America/New_York",
    )
    assert label == "09:30-10:00"


def test_format_quality_window_label_handles_european_tz() -> None:
    label = _format_quality_window_label(
        date(2026, 4, 23),
        start_et=time(9, 30),
        end_et=time(10, 0),
        display_timezone="Europe/Berlin",
    )
    # 09:30 ET → 15:30 CET in April (CEST = UTC+2)
    assert "-" in label
    start, end = label.split("-")
    assert start.endswith(":30")
    assert end.endswith(":00")


def test_quality_window_export_tag_uses_hhmm() -> None:
    assert _quality_window_export_tag(time(9, 30), time(10, 0)) == "0930_1000_et"
    assert _quality_window_export_tag(time(4, 0), time(9, 30)) == "0400_0930_et"


def test_window_label_from_tag_unknown_passthrough() -> None:
    out = _window_label_from_tag(
        date(2026, 4, 23),
        "made_up_tag",
        display_timezone="America/New_York",
    )
    assert out == "made_up_tag"


def test_window_label_from_tag_resolves_known_tag() -> None:
    # Pick the first defined tag from the default config to avoid hard-coding
    cfg = dpe._DEFAULT_BULLISH_QUALITY_CFG
    tag = cfg.window_definitions[0].tag
    out = _window_label_from_tag(
        date(2026, 4, 23),
        tag,
        display_timezone="America/New_York",
    )
    # Format is HH:MM-HH:MM
    assert len(out) == 11
    assert out[2] == ":" and out[5] == "-" and out[8] == ":"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_raises_systemexit_when_databento_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "")
    monkeypatch.setattr(dpe, "load_dotenv", lambda *a, **kw: None)
    with pytest.raises(SystemExit, match="DATABENTO_API_KEY"):
        main([])


def test_main_invokes_pipeline_with_args(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "db-key")
    monkeypatch.setenv("FMP_API_KEY", "fmp-key")
    monkeypatch.setenv("BENZINGA_API_KEY", "bz-key")
    monkeypatch.setattr(dpe, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(dpe, "list_accessible_datasets", lambda *a, **kw: ["XNAS.ITCH"])
    monkeypatch.setattr(dpe, "choose_default_dataset", lambda available, requested_dataset=None: "XNAS.ITCH")

    captured: dict[str, Any] = {}

    def fake_pipeline(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "manifest": {"export_dir": "/tmp/exports/2026-04-23"},
            "output_checks": {"daily_features_full_universe_export_rows": 100},
            "batl_debug": {"sample": True},
            "exported_paths": {"daily_features": "/tmp/a.parquet", "summary": "/tmp/b.parquet"},
        }

    monkeypatch.setattr(dpe, "run_production_export_pipeline", fake_pipeline)

    main([
        "--dataset", "XNAS.ITCH",
        "--lookback-days", "5",
        "--top-fraction", "0.10",
        "--bullish-score-profile", "balanced",
        "--smc-base-only",
    ])

    assert captured["databento_api_key"] == "db-key"
    assert captured["fmp_api_key"] == "fmp-key"
    assert captured["benzinga_api_key"] == "bz-key"
    assert captured["dataset"] == "XNAS.ITCH"
    assert captured["lookback_days"] == 5
    assert captured["top_fraction"] == pytest.approx(0.10)
    assert captured["bullish_score_profile"] == "balanced"
    assert captured["smc_base_only"] is True
    assert captured["skip_cost_estimate"] is True  # estimate-costs flag default off

    out = capsys.readouterr().out
    assert "EXPORT_DIR /tmp/exports/2026-04-23" in out
    assert "OUTPUT_CHECKS" in out
    assert "BATL_DEBUG" in out
    assert "DAILY_FEATURES /tmp/a.parquet" in out
    assert "SUMMARY /tmp/b.parquet" in out


def test_main_estimate_costs_flag_clears_skip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABENTO_API_KEY", "db-key")
    monkeypatch.setenv("FMP_API_KEY", "")  # exercise the FMP-missing INFO branch
    monkeypatch.setattr(dpe, "load_dotenv", lambda *a, **kw: None)
    monkeypatch.setattr(dpe, "list_accessible_datasets", lambda *a, **kw: ["XNAS.ITCH"])
    monkeypatch.setattr(dpe, "choose_default_dataset", lambda available, requested_dataset=None: "XNAS.ITCH")

    captured: dict[str, Any] = {}

    def fake_pipeline(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "manifest": {"export_dir": "/tmp/x"},
            "output_checks": {},
            "batl_debug": {},
            "exported_paths": {},
        }

    monkeypatch.setattr(dpe, "run_production_export_pipeline", fake_pipeline)

    main(["--estimate-costs"])

    assert captured["skip_cost_estimate"] is False
    out = capsys.readouterr().out
    assert "INFO: FMP_API_KEY not set" in out
