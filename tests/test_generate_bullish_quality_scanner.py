from __future__ import annotations

from pathlib import Path

import pandas as pd

import scripts.generate_bullish_quality_scanner as bullish_scanner_module
from scripts.bullish_quality_config import build_default_bullish_quality_config
from scripts.generate_bullish_quality_scanner import generate_bullish_quality_scanner_result


def _write_exact_named_frame(export_dir: Path, name: str, frame: pd.DataFrame) -> None:
    frame.to_parquet(export_dir / f"{name}.parquet", index=False)


def test_generate_bullish_quality_scanner_result_ranks_top_n_per_window(tmp_path: Path) -> None:
    cfg = build_default_bullish_quality_config()
    window_features = pd.DataFrame(
        {
            "trade_date": ["2026-03-10", "2026-03-10", "2026-03-10"],
            "symbol": ["AAA", "BBB", "CCC"],
            "window_tag": [cfg.window_definitions[-1].tag] * 3,
            "source_data_fetched_at": ["2026-03-10T09:31:00+00:00"] * 3,
            "passes_quality_filter": [True, True, True],
            "window_quality_score": [88.0, 95.0, 70.0],
            "window_dollar_volume": [1_000_000.0, 2_000_000.0, 500_000.0],
            "window_return_pct": [1.0, 2.0, 0.5],
            "window_close_position_pct": [95.0, 98.0, 80.0],
            "quality_filter_reason": ["eligible", "eligible", "eligible"],
        }
    )
    daily_features = pd.DataFrame(
        {
            "trade_date": ["2026-03-10"],
            "symbol": ["AAA"],
        }
    )
    _write_exact_named_frame(tmp_path, "premarket_window_features_full_universe", window_features)
    _write_exact_named_frame(tmp_path, "daily_symbol_features_full_universe", daily_features)

    result = generate_bullish_quality_scanner_result(export_dir=tmp_path, cfg=build_default_bullish_quality_config())

    assert result.trade_date is not None
    assert result.trade_date.isoformat() == "2026-03-10"
    assert result.latest_window_table["symbol"].tolist()[:3] == ["BBB", "AAA", "CCC"][: len(result.latest_window_table)]
    assert result.rankings_table["quality_rank_within_window"].tolist() == [1, 2, 3]
    assert result.warnings == []


def test_generate_bullish_quality_scanner_result_warns_when_no_candidates_pass(tmp_path: Path) -> None:
    cfg = build_default_bullish_quality_config()
    window_features = pd.DataFrame(
        {
            "trade_date": ["2026-03-10"],
            "symbol": ["AAA"],
            "window_tag": [cfg.window_definitions[-1].tag],
            "source_data_fetched_at": ["2026-03-10T09:31:00+00:00"],
            "passes_quality_filter": [False],
            "window_quality_score": [12.0],
            "window_dollar_volume": [100_000.0],
            "window_return_pct": [-0.5],
            "window_close_position_pct": [20.0],
            "quality_filter_reason": ["window_return_below_min"],
        }
    )
    daily_features = pd.DataFrame(
        {
            "trade_date": ["2026-03-10"],
            "symbol": ["AAA"],
        }
    )
    _write_exact_named_frame(tmp_path, "premarket_window_features_full_universe", window_features)
    _write_exact_named_frame(tmp_path, "daily_symbol_features_full_universe", daily_features)

    result = generate_bullish_quality_scanner_result(export_dir=tmp_path, cfg=cfg)

    assert result.rankings_table.empty
    assert result.latest_window_table.empty
    assert result.filter_diagnostics_table.loc[0, "pass_rows"] == 0
    assert result.warnings == ["No bullish-quality candidates matched the configured filters."]


def test_generate_bullish_quality_scanner_result_falls_back_to_valid_production_bundle(tmp_path: Path) -> None:
    cfg = build_default_bullish_quality_config()

    # Deliberately create a fast manifest that should be ignored by production-prefixed fallback.
    (tmp_path / "databento_preopen_fast_20260310_093100_manifest.json").write_text("{}", encoding="utf-8")

    prod_base = "databento_volatility_production_20260310_093100"
    (tmp_path / f"{prod_base}_manifest.json").write_text(
        '{"export_generated_at": "2026-03-10T09:31:00+00:00", "premarket_fetched_at": "2026-03-10T09:30:00+00:00"}',
        encoding="utf-8",
    )
    window_features = pd.DataFrame(
        {
            "trade_date": ["2026-03-10"],
            "symbol": ["AAA"],
            "window_tag": [cfg.window_definitions[-1].tag],
            "passes_quality_filter": [True],
            "window_quality_score": [91.0],
            "window_dollar_volume": [1_500_000.0],
            "window_return_pct": [1.5],
            "window_close_position_pct": [96.0],
            "quality_filter_reason": ["eligible"],
        }
    )
    daily_features = pd.DataFrame({"trade_date": ["2026-03-10"], "symbol": ["AAA"]})
    window_features.to_parquet(tmp_path / f"{prod_base}__premarket_window_features_full_universe.parquet", index=False)
    daily_features.to_parquet(tmp_path / f"{prod_base}__daily_symbol_features_full_universe.parquet", index=False)

    result = generate_bullish_quality_scanner_result(export_dir=tmp_path, cfg=cfg)

    assert result.trade_date is not None
    assert result.trade_date.isoformat() == "2026-03-10"
    assert result.latest_window_table["symbol"].tolist() == ["AAA"]
    assert any("Fell back to the latest manifest-backed production bundle" in warning for warning in result.warnings)


def test_generate_bullish_quality_scanner_result_uses_manifest_timestamp_when_windows_empty(monkeypatch, tmp_path: Path) -> None:
    cfg = build_default_bullish_quality_config()
    trade_date = pd.Timestamp("2026-03-11").date()

    def _fake_loader(export_dir: Path):
        _ = export_dir
        return (
            pd.DataFrame(columns=["trade_date", "symbol"]),
            pd.DataFrame({"trade_date": [trade_date], "symbol": ["AAA"]}),
            [],
            {"premarket_fetched_at": "2026-03-11T09:25:00+00:00"},
        )

    monkeypatch.setattr(bullish_scanner_module, "load_bullish_quality_inputs", _fake_loader)

    result = bullish_scanner_module.generate_bullish_quality_scanner_result(export_dir=tmp_path, cfg=cfg)

    assert result.trade_date == trade_date
    assert result.source_data_fetched_at == "2026-03-11T09:25:00+00:00"
    assert "No premarket window feature rows were available." in result.warnings