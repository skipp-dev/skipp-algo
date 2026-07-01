"""Tests for scripts/refresh_overlay_enrichment.py — fast overlay refresh."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.bake_overlay_library import (
    OVERLAY_FIELDS,
    OVERLAY_LIBRARY_NAME,
    OVERLAY_SECTION_MARKERS,
    OVERLAY_SECTION_NAMES,
    WATERMARK_FIELDS,
)
from scripts.bake_overlay_library import (
    overlay_fields as extract_overlay_fields,
)
from scripts.refresh_overlay_enrichment import (
    _pine_bool,
    _split_csv_string,
    build_fast_overlay_manifest,
    refresh,
    render_overlay_pine_lines,
)

# ── Fixture enrichment dict ────────────────────────────────────

def _make_enrichment(**overrides: dict) -> dict:
    """Return a realistic enrichment dict with all 4 overlay domains populated."""
    base: dict = {
        "regime": {
            "regime": "RISK_ON",
            "vix_level": 15.3,
            "macro_bias": 0.42,
            "macro_bias_raw": 0.38,
            "macro_bias_pe_adjustment": 0.04,
            "market_pe_forward": 18.5,
            "market_pe_regime": "FAIR",
            "sector_breadth": 0.65,
        },
        "news": {
            "bullish_tickers": ["AAPL", "MSFT"],
            "bearish_tickers": ["TSLA"],
            "neutral_tickers": ["AMZN"],
            "news_heat_global": 0.73,
            "ticker_heat_map": "AAPL:0.8,TSLA:0.6",
            "news_category_map": "tech:3,auto:1",
            "news_count_map": "AAPL:5,TSLA:3",
            "breaking_tickers": ["NVDA"],
            "high_impact_news_count": 2,
            "most_mentioned_ticker": "AAPL",
        },
        "calendar": {
            "earnings_today_tickers": "AAPL,MSFT",
            "earnings_tomorrow_tickers": "GOOG",
            "earnings_bmo_tickers": "AAPL",
            "earnings_amc_tickers": "MSFT",
            "high_impact_macro_today": True,
            "macro_event_name": "FOMC Minutes",
            "macro_event_time": "14:00 ET",
        },
        "layering": {
            "global_heat": 0.68,
            "global_strength": 0.55,
            "tone": "BULLISH",
            "trade_state": "ALLOWED",
        },
    }
    for key, val in overrides.items():
        if isinstance(val, dict) and key in base:
            base[key].update(val)
        else:
            base[key] = val
    return base


# ── Unit tests ─────────────────────────────────────────────────


class TestPineBool:
    def test_truthy(self) -> None:
        assert _pine_bool(True) == "true"
        assert _pine_bool(1) == "true"

    def test_falsy(self) -> None:
        assert _pine_bool(False) == "false"
        assert _pine_bool(None) == "false"
        assert _pine_bool(0) == "false"


class TestSplitCsvString:
    def test_basic(self) -> None:
        assert _split_csv_string("A,B,C") == ["A", "B", "C"]

    def test_empty(self) -> None:
        assert _split_csv_string("") == []

    def test_trailing_comma(self) -> None:
        assert _split_csv_string("A,B,") == ["A", "B"]


# ── Pine rendering tests ──────────────────────────────────────


class TestRenderOverlayPineLines:
    def test_header_version_6(self) -> None:
        lines = render_overlay_pine_lines(_make_enrichment())
        assert lines[0] == "//@version=6"
        assert f'library("{OVERLAY_LIBRARY_NAME}")' in lines[1]

    def test_watermark_fields_present(self) -> None:
        lines = render_overlay_pine_lines(
            _make_enrichment(), asof_date="2026-06-08", asof_time="12:00:00 UTC",
        )
        text = "\n".join(lines)
        assert 'export const string ASOF_DATE = "2026-06-08"' in text
        assert 'export const string ASOF_TIME = "12:00:00 UTC"' in text

    def test_all_overlay_sections_present(self) -> None:
        lines = render_overlay_pine_lines(_make_enrichment())
        text = "\n".join(lines)
        for marker in OVERLAY_SECTION_MARKERS:
            assert marker in text, f"missing section marker: {marker}"

    def test_field_contract_matches_overlay_fields(self) -> None:
        lines = render_overlay_pine_lines(_make_enrichment())
        found = extract_overlay_fields(lines)
        contract = found - set(WATERMARK_FIELDS)
        assert contract == OVERLAY_FIELDS, (
            f"missing={OVERLAY_FIELDS - contract} extra={contract - OVERLAY_FIELDS}"
        )

    def test_regime_values_rendered(self) -> None:
        enr = _make_enrichment()
        lines = render_overlay_pine_lines(enr)
        text = "\n".join(lines)
        assert 'MARKET_REGIME = "RISK_ON"' in text
        assert "VIX_LEVEL = 15.3" in text
        assert "SECTOR_BREADTH = 0.65" in text

    def test_news_values_rendered(self) -> None:
        enr = _make_enrichment()
        lines = render_overlay_pine_lines(enr)
        text = "\n".join(lines)
        assert "NEWS_HEAT_GLOBAL = 0.73" in text
        assert "HIGH_IMPACT_NEWS_COUNT = 2" in text
        assert 'MOST_MENTIONED_TICKER = "AAPL"' in text

    def test_never_emits_nan_or_inf_pine_literals(self) -> None:
        """The overlay Pine boundary must never emit ``nan``/``inf`` float
        literals, regardless of non-finite enrichment values.
        """
        nan, inf = float("nan"), float("inf")
        enr = _make_enrichment(
            regime={
                "vix_level": nan, "macro_bias_raw": nan,
                "macro_bias_pe_adjustment": nan, "market_pe_forward": inf,
                "sector_breadth": nan,
            },
            news={"news_heat_global": nan},
            layering={"global_heat": nan, "global_strength": inf},
        )
        lines = render_overlay_pine_lines(enr)
        offending = [
            ln.strip()
            for ln in lines
            if "= nan" in ln.lower() or "= inf" in ln.lower() or "= -inf" in ln.lower()
        ]
        assert offending == [], f"non-finite Pine literals emitted: {offending}"

    def test_calendar_values_rendered(self) -> None:
        enr = _make_enrichment()
        lines = render_overlay_pine_lines(enr)
        text = "\n".join(lines)
        assert 'EARNINGS_TODAY_TICKERS = "AAPL,MSFT"' in text
        assert "HIGH_IMPACT_MACRO_TODAY = true" in text
        assert 'MACRO_EVENT_NAME = "FOMC Minutes"' in text

    def test_layering_values_rendered(self) -> None:
        enr = _make_enrichment()
        lines = render_overlay_pine_lines(enr)
        text = "\n".join(lines)
        assert "GLOBAL_HEAT = 0.68" in text
        assert 'TONE = "BULLISH"' in text
        assert 'TRADE_STATE = "ALLOWED"' in text

    def test_empty_enrichment_renders_defaults(self) -> None:
        lines = render_overlay_pine_lines({})
        text = "\n".join(lines)
        assert 'MARKET_REGIME = "NEUTRAL"' in text
        assert "VIX_LEVEL = 0.0" in text
        assert 'TONE = "NEUTRAL"' in text
        assert 'TRADE_STATE = "ALLOWED"' in text


# ── Manifest tests ────────────────────────────────────────────


class TestBuildFastOverlayManifest:
    def test_manifest_shape(self) -> None:
        fields = OVERLAY_FIELDS | set(WATERMARK_FIELDS)
        m = build_fast_overlay_manifest(
            fields,
            owner="preuss_steffen",
            version=1,
            out_pine=Path("pine/generated/smc_overlay_generated.pine"),
            asof_date="2026-06-08",
            asof_time="12:00:00 UTC",
        )
        assert m["library_name"] == OVERLAY_LIBRARY_NAME
        assert m["cadence_class"] == "fast_overlay"
        assert m["derived_from_source_artifact"] is False
        assert m["enrichment_source"] == "live_api"
        assert m["asof_date"] == "2026-06-08"
        assert m["overlay_field_count"] == len(OVERLAY_FIELDS)
        assert set(m["overlay_fields"]) == OVERLAY_FIELDS
        assert m["overlay_sections"] == list(OVERLAY_SECTION_NAMES)

    def test_version_wired(self) -> None:
        fields = OVERLAY_FIELDS | set(WATERMARK_FIELDS)
        m = build_fast_overlay_manifest(
            fields, owner="preuss_steffen", version=3,
            out_pine=Path("x.pine"), asof_date="", asof_time="",
        )
        assert m["library_version"] == 3
        assert "/3" in m["recommended_import_path"]


# ── Integration test (dry-run) ────────────────────────────────


class TestRefreshDryRun:
    def test_dry_run_returns_manifest_without_writing(self, tmp_path: Path) -> None:
        out_pine = tmp_path / "overlay.pine"
        out_manifest = tmp_path / "overlay.json"

        fake_enrichment = _make_enrichment()

        with patch(
            "scripts.generate_smc_micro_base_from_databento.build_enrichment",
            return_value=fake_enrichment,
        ):
            manifest = refresh(
                out_pine=out_pine,
                out_manifest=out_manifest,
                fmp_api_key="fake",
                dry_run=True,
            )

        assert not out_pine.exists()
        assert not out_manifest.exists()
        assert manifest["library_name"] == OVERLAY_LIBRARY_NAME

    def test_wet_run_writes_files(self, tmp_path: Path) -> None:
        out_pine = tmp_path / "overlay.pine"
        out_manifest = tmp_path / "overlay.json"

        fake_enrichment = _make_enrichment()

        with patch(
            "scripts.generate_smc_micro_base_from_databento.build_enrichment",
            return_value=fake_enrichment,
        ):
            refresh(
                out_pine=out_pine,
                out_manifest=out_manifest,
                fmp_api_key="fake",
                dry_run=False,
            )

        assert out_pine.exists()
        assert out_manifest.exists()

        pine_text = out_pine.read_text()
        assert "//@version=6" in pine_text
        assert 'MARKET_REGIME = "RISK_ON"' in pine_text

        written_manifest = json.loads(out_manifest.read_text())
        assert written_manifest["library_name"] == OVERLAY_LIBRARY_NAME
        assert written_manifest["derived_from_source_artifact"] is False
        assert written_manifest["enrichment_source"] == "live_api"

    def test_field_contract_on_wet_run(self, tmp_path: Path) -> None:
        out_pine = tmp_path / "overlay.pine"
        out_manifest = tmp_path / "overlay.json"

        with patch(
            "scripts.generate_smc_micro_base_from_databento.build_enrichment",
            return_value=_make_enrichment(),
        ):
            refresh(
                out_pine=out_pine,
                out_manifest=out_manifest,
                fmp_api_key="fake",
            )

        written_manifest = json.loads(out_manifest.read_text())
        assert set(written_manifest["overlay_fields"]) == OVERLAY_FIELDS
