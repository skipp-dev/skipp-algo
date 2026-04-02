"""Focused tests for v4 meta & volume-regime contract fields.

Covers:
  - _derive_volume_regime() with various DataFrame shapes
  - _read_previous_refresh_count() with present / missing / corrupt manifest
  - REFRESH_COUNT increment through build_enrichment()
  - VOLUME_LOW_TICKERS / HOLIDAY_SUSPECT_TICKERS Pine rendering
  - ASOF_TIME rendering in Pine output
  - Manifest top-level asof_time / refresh_count fields
  - Defaults when base_snapshot=None and manifest_path=None
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.generate_smc_micro_base_from_databento import (
    _derive_volume_regime,
    _read_previous_refresh_count,
    build_enrichment,
)
from scripts.generate_smc_micro_profiles import (
    LISTS,
    write_manifest,
    write_pine_library,
)


# ── Helpers ─────────────────────────────────────────────────────

def _empty_lists() -> dict[str, list[str]]:
    return {name: [] for name in LISTS}


def _stub_enrichment(**overrides: Any) -> dict[str, Any]:
    """Minimal enrichment dict with overridable sub-blocks."""
    base: dict[str, Any] = {
        "regime": {"regime": "NEUTRAL", "vix_level": 0, "macro_bias": 0, "sector_breadth": 0},
        "news": {
            "bullish_tickers": [], "bearish_tickers": [], "neutral_tickers": [],
            "news_heat_global": 0.0, "ticker_heat_map": "",
        },
        "calendar": {
            "earnings_today_tickers": "", "earnings_tomorrow_tickers": "",
            "earnings_bmo_tickers": "", "earnings_amc_tickers": "",
            "high_impact_macro_today": False, "macro_event_name": "", "macro_event_time": "",
        },
        "layering": {"global_heat": 0.0, "global_strength": 0.5, "tone": "NEUTRAL", "trade_state": "ALLOWED"},
        "providers": {"provider_count": 1, "stale_providers": ""},
        "volume_regime": {"low_tickers": [], "holiday_suspect_tickers": []},
        "meta": {"asof_time": "2025-06-01T12:00:00Z", "refresh_count": 1},
    }
    base.update(overrides)
    return base


def _make_snapshot(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ── _derive_volume_regime ───────────────────────────────────────

class TestDeriveVolumeRegime:
    def test_none_snapshot_returns_empty(self):
        result = _derive_volume_regime(None)
        assert result == {"low_tickers": [], "holiday_suspect_tickers": []}

    def test_empty_dataframe_returns_empty(self):
        result = _derive_volume_regime(pd.DataFrame())
        assert result == {"low_tickers": [], "holiday_suspect_tickers": []}

    def test_missing_adv_column_returns_empty(self):
        df = pd.DataFrame({"symbol": ["AAPL"], "price": [150]})
        result = _derive_volume_regime(df)
        assert result == {"low_tickers": [], "holiday_suspect_tickers": []}

    def test_low_ticker_below_threshold(self):
        df = _make_snapshot([
            {"symbol": "AAPL", "adv_dollar_rth_20d": 10_000_000},
            {"symbol": "PENNY", "adv_dollar_rth_20d": 1_000_000},
        ])
        result = _derive_volume_regime(df, adv_threshold=5_000_000)
        assert "PENNY" in result["low_tickers"]
        assert "AAPL" not in result["low_tickers"]

    def test_all_above_threshold(self):
        df = _make_snapshot([
            {"symbol": "AAPL", "adv_dollar_rth_20d": 80_000_000},
            {"symbol": "MSFT", "adv_dollar_rth_20d": 70_000_000},
        ])
        result = _derive_volume_regime(df)
        assert result["low_tickers"] == []

    def test_holiday_suspect_below_20pct_median(self):
        # Median = 50M.  20% of 50M = 10M.  THIN at 5M is below.
        df = _make_snapshot([
            {"symbol": "BIG1", "adv_dollar_rth_20d": 50_000_000},
            {"symbol": "BIG2", "adv_dollar_rth_20d": 100_000_000},
            {"symbol": "THIN", "adv_dollar_rth_20d": 5_000_000},
        ])
        result = _derive_volume_regime(df)
        assert "THIN" in result["holiday_suspect_tickers"]
        assert "BIG1" not in result["holiday_suspect_tickers"]

    def test_no_holiday_suspects_when_all_similar(self):
        df = _make_snapshot([
            {"symbol": "A", "adv_dollar_rth_20d": 50_000_000},
            {"symbol": "B", "adv_dollar_rth_20d": 60_000_000},
            {"symbol": "C", "adv_dollar_rth_20d": 55_000_000},
        ])
        result = _derive_volume_regime(df)
        assert result["holiday_suspect_tickers"] == []

    def test_tickers_sorted_alphabetically(self):
        df = _make_snapshot([
            {"symbol": "ZZZ", "adv_dollar_rth_20d": 100},
            {"symbol": "AAA", "adv_dollar_rth_20d": 200},
            {"symbol": "MMM", "adv_dollar_rth_20d": 50},
        ])
        result = _derive_volume_regime(df, adv_threshold=5_000_000)
        assert result["low_tickers"] == ["AAA", "MMM", "ZZZ"]

    def test_nan_adv_values_excluded(self):
        df = _make_snapshot([
            {"symbol": "GOOD", "adv_dollar_rth_20d": 10_000_000},
            {"symbol": "BAD", "adv_dollar_rth_20d": None},
        ])
        result = _derive_volume_regime(df)
        assert "BAD" not in result["low_tickers"]


# ── _read_previous_refresh_count ────────────────────────────────

class TestReadPreviousRefreshCount:
    def test_none_path_returns_zero(self):
        assert _read_previous_refresh_count(None) == 0

    def test_missing_file_returns_zero(self, tmp_path: Path):
        assert _read_previous_refresh_count(tmp_path / "nope.json") == 0

    def test_reads_count_from_manifest(self, tmp_path: Path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"refresh_count": 7}))
        assert _read_previous_refresh_count(manifest) == 7

    def test_missing_key_returns_zero(self, tmp_path: Path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"other_field": "x"}))
        assert _read_previous_refresh_count(manifest) == 0

    def test_corrupt_json_returns_zero(self, tmp_path: Path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text("NOT JSON {{{")
        assert _read_previous_refresh_count(manifest) == 0


# ── REFRESH_COUNT increment via build_enrichment ────────────────

class TestRefreshCountIncrement:
    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_first_run_refresh_count_is_1(self, mock_resolve, tmp_path: Path):
        from scripts.smc_provider_policy import ProviderResult
        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp", ok=True, stale=[],
        )
        enrichment = build_enrichment(
            fmp_api_key="k", symbols=["AAPL"],
            enrich_regime=True,
            manifest_path=tmp_path / "nonexistent.json",
        )
        assert enrichment is not None
        assert enrichment["meta"]["refresh_count"] == 1

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_increment_from_existing_manifest(self, mock_resolve, tmp_path: Path):
        from scripts.smc_provider_policy import ProviderResult
        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp", ok=True, stale=[],
        )
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({"refresh_count": 5}))
        enrichment = build_enrichment(
            fmp_api_key="k", symbols=["AAPL"],
            enrich_regime=True,
            manifest_path=manifest,
        )
        assert enrichment is not None
        assert enrichment["meta"]["refresh_count"] == 6


# ── Volume regime wiring via build_enrichment ───────────────────

class TestVolumeRegimeWiring:
    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_volume_regime_populated_from_snapshot(self, mock_resolve):
        from scripts.smc_provider_policy import ProviderResult
        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp", ok=True, stale=[],
        )
        df = _make_snapshot([
            {"symbol": "HIGH", "adv_dollar_rth_20d": 80_000_000},
            {"symbol": "LOW", "adv_dollar_rth_20d": 1_000_000},
        ])
        enrichment = build_enrichment(
            fmp_api_key="k", symbols=["HIGH", "LOW"],
            enrich_regime=True,
            base_snapshot=df,
        )
        assert enrichment is not None
        assert "LOW" in enrichment["volume_regime"]["low_tickers"]
        assert "HIGH" not in enrichment["volume_regime"]["low_tickers"]

    @patch("scripts.smc_provider_policy.resolve_domain")
    def test_volume_regime_empty_without_snapshot(self, mock_resolve):
        from scripts.smc_provider_policy import ProviderResult
        mock_resolve.return_value = ProviderResult(
            data={"regime": "NEUTRAL"}, provider="fmp", ok=True, stale=[],
        )
        enrichment = build_enrichment(
            fmp_api_key="k", symbols=["AAPL"],
            enrich_regime=True,
            base_snapshot=None,
        )
        assert enrichment is not None
        assert enrichment["volume_regime"]["low_tickers"] == []
        assert enrichment["volume_regime"]["holiday_suspect_tickers"] == []


# ── Pine rendering of meta & volume fields ──────────────────────

class TestPineRendering:
    def test_asof_time_rendered(self, tmp_path: Path):
        out = tmp_path / "lib.pine"
        enrichment = _stub_enrichment(
            meta={"asof_time": "2025-06-01T14:00:00Z", "refresh_count": 2},
        )
        write_pine_library(
            path=out, lists=_empty_lists(), asof_date="2025-06-01",
            universe_size=10, enrichment=enrichment,
        )
        text = out.read_text()
        assert 'ASOF_TIME = "2025-06-01T14:00:00Z"' in text

    def test_refresh_count_rendered_as_int(self, tmp_path: Path):
        out = tmp_path / "lib.pine"
        enrichment = _stub_enrichment(
            meta={"asof_time": "2025-06-01T14:00:00Z", "refresh_count": 42},
        )
        write_pine_library(
            path=out, lists=_empty_lists(), asof_date="2025-06-01",
            universe_size=10, enrichment=enrichment,
        )
        text = out.read_text()
        assert re.search(r"^export const int REFRESH_COUNT = 42$", text, re.MULTILINE)

    def test_volume_low_tickers_rendered(self, tmp_path: Path):
        out = tmp_path / "lib.pine"
        enrichment = _stub_enrichment(
            volume_regime={"low_tickers": ["PENNY", "TINY"], "holiday_suspect_tickers": []},
        )
        write_pine_library(
            path=out, lists=_empty_lists(), asof_date="2025-06-01",
            universe_size=10, enrichment=enrichment,
        )
        text = out.read_text()
        assert 'VOLUME_LOW_TICKERS = "PENNY,TINY"' in text

    def test_holiday_suspect_tickers_rendered(self, tmp_path: Path):
        out = tmp_path / "lib.pine"
        enrichment = _stub_enrichment(
            volume_regime={"low_tickers": [], "holiday_suspect_tickers": ["XMAS"]},
        )
        write_pine_library(
            path=out, lists=_empty_lists(), asof_date="2025-06-01",
            universe_size=10, enrichment=enrichment,
        )
        text = out.read_text()
        assert 'HOLIDAY_SUSPECT_TICKERS = "XMAS"' in text

    def test_provider_count_rendered_as_int(self, tmp_path: Path):
        out = tmp_path / "lib.pine"
        enrichment = _stub_enrichment(
            providers={"provider_count": 4, "stale_providers": ""},
        )
        write_pine_library(
            path=out, lists=_empty_lists(), asof_date="2025-06-01",
            universe_size=10, enrichment=enrichment,
        )
        text = out.read_text()
        assert re.search(r"^export const int PROVIDER_COUNT = 4$", text, re.MULTILINE)

    def test_defaults_when_no_enrichment(self, tmp_path: Path):
        out = tmp_path / "lib.pine"
        write_pine_library(
            path=out, lists=_empty_lists(), asof_date="2025-06-01",
            universe_size=0, enrichment=None,
        )
        text = out.read_text()
        assert 'ASOF_TIME = ""' in text
        assert "REFRESH_COUNT = 0" in text
        assert "PROVIDER_COUNT = 0" in text
        assert 'VOLUME_LOW_TICKERS = ""' in text
        assert 'HOLIDAY_SUSPECT_TICKERS = ""' in text


# ── Manifest top-level fields ───────────────────────────────────

class TestManifestMetaFields:
    def test_manifest_contains_asof_time_and_refresh_count(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        enrichment = _stub_enrichment(
            meta={"asof_time": "2025-06-01T14:30:00Z", "refresh_count": 5},
        )
        write_manifest(
            manifest_path,
            asof_date="2025-06-01",
            input_path=tmp_path / "in.csv",
            schema_path=tmp_path / "schema.json",
            features_path=tmp_path / "features.csv",
            lists_path=tmp_path / "lists.csv",
            state_path=tmp_path / "state.csv",
            diff_report_path=tmp_path / "diff.md",
            pine_path=tmp_path / "lib.pine",
            core_import_snippet_path=tmp_path / "snippet.pine",
            universe_size=10,
            lists={name: [] for name in LISTS},
            library_owner="test",
            library_version=1,
            recommended_import_path="test/path",
            enrichment=enrichment,
        )
        data = json.loads(manifest_path.read_text())
        assert data["asof_time"] == "2025-06-01T14:30:00Z"
        assert data["refresh_count"] == 5

    def test_manifest_defaults_without_enrichment(self, tmp_path: Path):
        manifest_path = tmp_path / "manifest.json"
        write_manifest(
            manifest_path,
            asof_date="2025-06-01",
            input_path=tmp_path / "in.csv",
            schema_path=tmp_path / "schema.json",
            features_path=tmp_path / "features.csv",
            lists_path=tmp_path / "lists.csv",
            state_path=tmp_path / "state.csv",
            diff_report_path=tmp_path / "diff.md",
            pine_path=tmp_path / "lib.pine",
            core_import_snippet_path=tmp_path / "snippet.pine",
            universe_size=0,
            lists={name: [] for name in LISTS},
            library_owner="test",
            library_version=1,
            recommended_import_path="test/path",
            enrichment=None,
        )
        data = json.loads(manifest_path.read_text())
        assert data["asof_time"] == ""
        assert data["refresh_count"] == 0
