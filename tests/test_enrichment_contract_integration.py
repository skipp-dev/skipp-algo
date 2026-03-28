"""Integration tests for the enrichment contract across the Pine generation chain.

Exercises the real call chain:
    generate_pine_library_from_base → run_generation → publish_generation_result → write_pine_library

with no enrichment, partial enrichment, full enrichment, and degraded-provider
enrichment — verifying that all ``export const`` fields appear with correct
values in the generated Pine library file.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from scripts.generate_smc_micro_profiles import load_schema, LISTS
from scripts.smc_enrichment_types import EnrichmentDict
from scripts.smc_microstructure_base_runtime import generate_pine_library_from_base
from scripts.smc_schema_resolver import resolve_microstructure_schema_path

SCHEMA_PATH = resolve_microstructure_schema_path()

# ── All enrichment-related Pine constants ───────────────────────

ENRICHMENT_FIELDS = [
    # Meta
    "ASOF_TIME", "REFRESH_COUNT",
    # Regime
    "MARKET_REGIME", "VIX_LEVEL", "MACRO_BIAS", "SECTOR_BREADTH",
    "NEWS_BULLISH_TICKERS", "NEWS_BEARISH_TICKERS",
    "NEWS_NEUTRAL_TICKERS", "NEWS_HEAT_GLOBAL", "TICKER_HEAT_MAP",
    "EARNINGS_TODAY_TICKERS", "EARNINGS_TOMORROW_TICKERS",
    "EARNINGS_BMO_TICKERS", "EARNINGS_AMC_TICKERS",
    "HIGH_IMPACT_MACRO_TODAY", "MACRO_EVENT_NAME", "MACRO_EVENT_TIME",
    "GLOBAL_HEAT", "GLOBAL_STRENGTH", "TONE", "TRADE_STATE",
    "PROVIDER_COUNT", "STALE_PROVIDERS",
    "VOLUME_LOW_TICKERS", "HOLIDAY_SUSPECT_TICKERS",
]

LIST_FIELDS = [f"{n.upper()}_TICKERS" for n in LISTS]

CORE_FIELDS = ["ASOF_DATE", "ASOF_TIME", "UNIVERSE_ID", "LOOKBACK_DAYS", "UNIVERSE_SIZE", "REFRESH_COUNT"]


# ── Fixtures ────────────────────────────────────────────────────

def _base_row(sym: str) -> dict[str, object]:
    """Create one row matching the microstructure schema."""
    return {
        "asof_date": "2026-03-28",
        "symbol": sym,
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "universe_bucket": "test_bucket",
        "history_coverage_days_20d": 20,
        "adv_dollar_rth_20d": 150_000_000.0,
        "avg_spread_bps_rth_20d": 1.2,
        "rth_active_minutes_share_20d": 0.95,
        "open_30m_dollar_share_20d": 0.20,
        "close_60m_dollar_share_20d": 0.22,
        "clean_intraday_score_20d": 0.92,
        "consistency_score_20d": 0.90,
        "close_hygiene_20d": 0.91,
        "wickiness_20d": 0.10,
        "pm_dollar_share_20d": 0.15,
        "pm_trades_share_20d": 0.14,
        "pm_active_minutes_share_20d": 0.20,
        "pm_spread_bps_20d": 3.0,
        "pm_wickiness_20d": 0.12,
        "midday_dollar_share_20d": 0.24,
        "midday_trades_share_20d": 0.23,
        "midday_active_minutes_share_20d": 0.25,
        "midday_spread_bps_20d": 2.0,
        "midday_efficiency_20d": 0.80,
        "ah_dollar_share_20d": 0.12,
        "ah_trades_share_20d": 0.11,
        "ah_active_minutes_share_20d": 0.14,
        "ah_spread_bps_20d": 3.0,
        "ah_wickiness_20d": 0.10,
        "reclaim_respect_rate_20d": 0.90,
        "reclaim_failure_rate_20d": 0.08,
        "reclaim_followthrough_r_20d": 1.60,
        "ob_sweep_reversal_rate_20d": 0.25,
        "ob_sweep_depth_p75_20d": 0.30,
        "fvg_sweep_reversal_rate_20d": 0.20,
        "fvg_sweep_depth_p75_20d": 0.28,
        "stop_hunt_rate_20d": 0.10,
        "setup_decay_half_life_bars_20d": 30.0,
        "early_vs_late_followthrough_ratio_20d": 0.90,
        "stale_fail_rate_20d": 0.10,
    }


@pytest.fixture
def base_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame([_base_row("AAPL"), _base_row("TSLA"), _base_row("META")])
    csv_path = tmp_path / "base_snapshot.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


def _full_enrichment() -> EnrichmentDict:
    return {
        "regime": {
            "regime": "RISK_ON",
            "vix_level": 14.5,
            "macro_bias": 0.1,
            "sector_breadth": 0.72,
        },
        "news": {
            "bullish_tickers": ["AAPL", "META"],
            "bearish_tickers": ["TSLA"],
            "neutral_tickers": [],
            "news_heat_global": 0.35,
            "ticker_heat_map": "AAPL:0.8,META:0.5,TSLA:-0.6",
        },
        "calendar": {
            "earnings_today_tickers": "AAPL",
            "earnings_tomorrow_tickers": "META",
            "earnings_bmo_tickers": "AAPL",
            "earnings_amc_tickers": "",
            "high_impact_macro_today": True,
            "macro_event_name": "FOMC Rate Decision",
            "macro_event_time": "14:00 ET",
        },
        "layering": {
            "global_heat": 0.42,
            "global_strength": 0.65,
            "tone": "BULLISH",
            "trade_state": "ALLOWED",
        },
        "providers": {
            "provider_count": 4,
            "stale_providers": "",
        },
        "volume_regime": {
            "low_tickers": ["TSLA"],
            "holiday_suspect_tickers": [],
        },
        "meta": {
            "asof_time": "2026-03-28T14:30:00Z",
            "refresh_count": 5,
        },
    }


def _regime_only_enrichment() -> EnrichmentDict:
    return {
        "regime": {
            "regime": "RISK_OFF",
            "vix_level": 28.0,
            "macro_bias": -0.4,
            "sector_breadth": 0.35,
        },
        "providers": {"stale_providers": ""},
    }


def _degraded_enrichment() -> EnrichmentDict:
    """Enrichment where multiple providers failed — stale_providers populated."""
    return {
        "regime": {"regime": "NEUTRAL"},
        "news": {
            "bullish_tickers": [],
            "bearish_tickers": [],
            "neutral_tickers": [],
            "news_heat_global": 0.0,
            "ticker_heat_map": "",
        },
        "providers": {
            "provider_count": 3,
            "stale_providers": "regime,calendar",
        },
    }


def _run_pipeline(
    base_csv: Path,
    tmp_path: Path,
    enrichment: EnrichmentDict | None = None,
) -> str:
    """Run generate_pine_library_from_base and return the Pine text."""
    result = generate_pine_library_from_base(
        base_csv_path=base_csv,
        schema_path=SCHEMA_PATH,
        output_root=tmp_path,
        enrichment=enrichment,
    )
    assert "pine_path" in result
    pine_path = result["pine_path"]
    assert pine_path.exists()
    return pine_path.read_text(encoding="utf-8")


# ── Test 1: No enrichment → all fields present with defaults ───

class TestNoEnrichment:
    def test_all_fields_present(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        for field in ENRICHMENT_FIELDS + LIST_FIELDS + CORE_FIELDS:
            assert field in text, f"Missing field: {field}"

    def test_regime_defaults_neutral(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        assert 'MARKET_REGIME = "NEUTRAL"' in text
        assert "VIX_LEVEL = 0.0" in text
        assert "MACRO_BIAS = 0.0" in text
        assert "SECTOR_BREADTH = 0.0" in text

    def test_news_defaults_empty(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        assert 'NEWS_BULLISH_TICKERS = ""' in text
        assert "NEWS_HEAT_GLOBAL = 0.0" in text

    def test_calendar_defaults_safe(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        assert "HIGH_IMPACT_MACRO_TODAY = false" in text
        assert 'MACRO_EVENT_NAME = ""' in text

    def test_layering_defaults_neutral(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        assert 'TONE = "NEUTRAL"' in text
        assert 'TRADE_STATE = "ALLOWED"' in text

    def test_stale_providers_empty(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        assert 'STALE_PROVIDERS = ""' in text

    def test_meta_defaults(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        assert 'ASOF_TIME = ""' in text
        assert "REFRESH_COUNT = 0" in text


# ── Test 2: Full enrichment → values render correctly ───────────

class TestFullEnrichment:
    def test_regime_values(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert 'MARKET_REGIME = "RISK_ON"' in text
        assert "VIX_LEVEL = 14.5" in text
        assert "SECTOR_BREADTH = 0.72" in text

    def test_news_values(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert "AAPL" in text
        assert "TSLA" in text
        assert "NEWS_HEAT_GLOBAL = 0.35" in text

    def test_calendar_values(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert 'EARNINGS_TODAY_TICKERS = "AAPL"' in text
        assert "HIGH_IMPACT_MACRO_TODAY = true" in text
        assert 'MACRO_EVENT_NAME = "FOMC Rate Decision"' in text

    def test_layering_values(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert "GLOBAL_HEAT = 0.42" in text
        assert 'TONE = "BULLISH"' in text

    def test_volume_regime(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert "TSLA" in re.search(r'VOLUME_LOW_TICKERS = "([^"]*)"', text).group(1)

    def test_pine_syntax_valid(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert text.startswith("//@version=6\n")
        export_lines = [l for l in text.splitlines() if l.startswith("export const")]
        type_pat = re.compile(r'^export const (string|int|float|bool) [A-Z_]+ = .+')
        for line in export_lines:
            assert type_pat.match(line), f"Bad export line: {line}"

    def test_no_python_booleans(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        bool_lines = [l for l in text.splitlines() if "const bool " in l]
        for line in bool_lines:
            assert "True" not in line and "False" not in line, f"Python bool in: {line}"

    def test_meta_values(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        assert 'ASOF_TIME = "2026-03-28T14:30:00Z"' in text
        assert "REFRESH_COUNT = 5" in text


# ── Test 3: Partial enrichment (regime only) ────────────────────

class TestPartialEnrichment:
    def test_regime_rendered(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_regime_only_enrichment())
        assert 'MARKET_REGIME = "RISK_OFF"' in text
        assert "VIX_LEVEL = 28.0" in text

    def test_news_defaults_when_missing(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_regime_only_enrichment())
        assert 'NEWS_BULLISH_TICKERS = ""' in text
        assert "NEWS_HEAT_GLOBAL = 0.0" in text

    def test_calendar_defaults_when_missing(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_regime_only_enrichment())
        assert "HIGH_IMPACT_MACRO_TODAY = false" in text

    def test_layering_defaults_when_missing(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_regime_only_enrichment())
        assert 'TONE = "NEUTRAL"' in text
        assert 'TRADE_STATE = "ALLOWED"' in text

    def test_all_fields_still_present(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_regime_only_enrichment())
        for field in ENRICHMENT_FIELDS:
            assert field in text, f"Missing field with partial enrichment: {field}"


# ── Test 4: Degraded provider behavior ──────────────────────────

class TestDegradedProvider:
    def test_stale_providers_rendered(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_degraded_enrichment())
        assert 'STALE_PROVIDERS = "regime,calendar"' in text

    def test_defaults_for_failed_blocks(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_degraded_enrichment())
        # Regime block has only "regime": "NEUTRAL" — other fields default
        assert 'MARKET_REGIME = "NEUTRAL"' in text

    def test_all_fields_still_present(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_degraded_enrichment())
        for field in ENRICHMENT_FIELDS:
            assert field in text, f"Missing field with degraded providers: {field}"

    def test_provider_count_rendered(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_degraded_enrichment())
        assert "PROVIDER_COUNT = 3" in text


# ── Test 5: Return value contract ───────────────────────────────

class TestReturnContract:
    def test_returns_dict_with_path_values(self, base_csv: Path, tmp_path: Path):
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=_full_enrichment(),
        )
        assert isinstance(result, dict)
        for key, val in result.items():
            assert isinstance(val, Path), f"Value for {key!r} is {type(val)}, expected Path"

    def test_pine_path_key_present(self, base_csv: Path, tmp_path: Path):
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
        )
        assert "pine_path" in result

    def test_all_artifacts_exist_on_disk(self, base_csv: Path, tmp_path: Path):
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=_full_enrichment(),
        )
        for name, path in result.items():
            assert path.exists(), f"Artifact {name!r} not written: {path}"


# ── Test 6: V4 field inventory is complete and deterministic ────

# Canonical list of every export const that the v4 library must contain.
V4_FIELD_INVENTORY = [
    # Core + Meta
    "ASOF_DATE", "ASOF_TIME", "UNIVERSE_ID", "LOOKBACK_DAYS", "UNIVERSE_SIZE",
    "REFRESH_COUNT",
    # Microstructure lists
    "CLEAN_RECLAIM_TICKERS", "STOP_HUNT_PRONE_TICKERS",
    "MIDDAY_DEAD_TICKERS", "RTH_ONLY_TICKERS",
    "WEAK_PREMARKET_TICKERS", "WEAK_AFTERHOURS_TICKERS",
    "FAST_DECAY_TICKERS",
    # Regime
    "MARKET_REGIME", "VIX_LEVEL", "MACRO_BIAS", "SECTOR_BREADTH",
    # News
    "NEWS_BULLISH_TICKERS", "NEWS_BEARISH_TICKERS",
    "NEWS_NEUTRAL_TICKERS", "NEWS_HEAT_GLOBAL", "TICKER_HEAT_MAP",
    # Calendar
    "EARNINGS_TODAY_TICKERS", "EARNINGS_TOMORROW_TICKERS",
    "EARNINGS_BMO_TICKERS", "EARNINGS_AMC_TICKERS",
    "HIGH_IMPACT_MACRO_TODAY", "MACRO_EVENT_NAME", "MACRO_EVENT_TIME",
    # Layering
    "GLOBAL_HEAT", "GLOBAL_STRENGTH", "TONE", "TRADE_STATE",
    # Providers
    "PROVIDER_COUNT", "STALE_PROVIDERS",
    # Volume
    "VOLUME_LOW_TICKERS", "HOLIDAY_SUSPECT_TICKERS",
]


class TestV4FieldInventory:
    """Ensures every v4 field is present regardless of enrichment state."""

    def test_all_v4_fields_with_full_enrichment(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        for field in V4_FIELD_INVENTORY:
            assert field in text, f"Missing v4 field: {field}"

    def test_all_v4_fields_without_enrichment(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=None)
        for field in V4_FIELD_INVENTORY:
            assert field in text, f"Missing v4 field (no enrichment): {field}"

    def test_all_v4_fields_with_partial_enrichment(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_regime_only_enrichment())
        for field in V4_FIELD_INVENTORY:
            assert field in text, f"Missing v4 field (partial): {field}"

    def test_field_count_matches_inventory(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        export_lines = [l for l in text.splitlines() if l.startswith("export const")]
        assert len(export_lines) == len(V4_FIELD_INVENTORY), (
            f"Expected {len(V4_FIELD_INVENTORY)} export fields, got {len(export_lines)}"
        )

    def test_no_unexpected_export_fields(self, base_csv: Path, tmp_path: Path):
        text = _run_pipeline(base_csv, tmp_path, enrichment=_full_enrichment())
        export_lines = [l for l in text.splitlines() if l.startswith("export const")]
        found_names = set()
        for line in export_lines:
            # "export const TYPE NAME = ..." -> extract NAME
            parts = line.split(" = ", 1)[0].split()
            if len(parts) >= 4:
                found_names.add(parts[3])
        expected_names = set(V4_FIELD_INVENTORY)
        unexpected = found_names - expected_names
        assert not unexpected, f"Unexpected export fields: {unexpected}"

    def test_output_deterministic(self, base_csv: Path, tmp_path: Path):
        """Two generations with the same inputs produce identical output."""
        out1 = tmp_path / "run1"
        out2 = tmp_path / "run2"
        out1.mkdir()
        out2.mkdir()
        enr = _full_enrichment()
        text1 = _run_pipeline(base_csv, out1, enrichment=enr)
        text2 = _run_pipeline(base_csv, out2, enrichment=enr)
        assert text1 == text2


# ── Test 7: Manifest tracks enrichment ──────────────────────────

class TestManifestEnrichment:
    def test_manifest_contains_library_field_version(self, base_csv: Path, tmp_path: Path):
        import json
        generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=_full_enrichment(),
        )
        manifest_files = list(tmp_path.rglob("smc_micro_profiles_generated.json"))
        assert manifest_files, "No manifest file generated"
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        assert manifest.get("library_field_version") == "v4"

    def test_manifest_enrichment_blocks(self, base_csv: Path, tmp_path: Path):
        import json
        generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=_full_enrichment(),
        )
        manifest_files = list(tmp_path.rglob("smc_micro_profiles_generated.json"))
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        blocks = manifest.get("enrichment_blocks", [])
        assert "regime" in blocks
        assert "meta" in blocks

    def test_manifest_no_enrichment_blocks_empty(self, base_csv: Path, tmp_path: Path):
        import json
        generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=None,
        )
        manifest_files = list(tmp_path.rglob("smc_micro_profiles_generated.json"))
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        assert manifest.get("enrichment_blocks") == []
