"""Tests for the fast/slow overlay library bake (scripts/bake_overlay_library.py).

These tests pin the Step-3 split contract: the derived overlay library must
carry exactly the high-cadence overlay fields (plus the bake watermark), must
NOT carry any of the heavy structural micro-profile fields, and its baked values
must be byte-identical to the source library it is derived from.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.bake_overlay_library import (
    OVERLAY_FIELDS,
    OVERLAY_LIBRARY_NAME,
    OVERLAY_SECTION_MARKERS,
    OVERLAY_SECTION_NAMES,
    WATERMARK_FIELDS,
    bake,
    build_overlay_manifest,
    overlay_fields,
    select_overlay_lines,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PINE = REPO_ROOT / "pine" / "generated" / "smc_micro_profiles_generated.pine"
SOURCE_MANIFEST = REPO_ROOT / "pine" / "generated" / "smc_micro_profiles_generated.json"

# Heavy structural / meta fields that MUST stay in the slow library only.
SLOW_FIELDS_THAT_MUST_BE_ABSENT = {
    "UNIVERSE_TICKERS",
    "UNIVERSE_TICKERS_PART_1",
    "UNIVERSE_TICKERS_PART_2",
    "CLEAN_RECLAIM_TICKERS",
    "FAST_DECAY_TICKERS",
    "STOP_HUNT_PRONE_TICKERS",
    "MIDDAY_DEAD_TICKERS",
    "RTH_ONLY_TICKERS",
    "WEAK_PREMARKET_TICKERS",
    "WEAK_AFTERHOURS_TICKERS",
    "UNIVERSE_SIZE",
    "REFRESH_COUNT",
    "PROVIDER_COUNT",
    "STALE_PROVIDERS",
    "TRUST_SCORE",
}

# A hermetic source fixture mirroring the real library layout: slow Core/
# Microstructure sections, the four contiguous overlay sections, then the
# Provider Status terminator and more slow sections.
SYNTHETIC_SOURCE = """//@version=6
library("smc_micro_profiles_generated")

// ── Core ──
export const string ASOF_DATE = "2026-05-27"
export const string ASOF_TIME = "2026-05-28T22:15:00Z"
export const int UNIVERSE_SIZE = 6889
export const int REFRESH_COUNT = 1

// ── Microstructure ──
export const string UNIVERSE_TICKERS = "AAPL,MSFT"
export const string CLEAN_RECLAIM_TICKERS = "TSLA"
export const string FAST_DECAY_TICKERS = "NVDA"

// ── Market Regime ──
export const string MARKET_REGIME = "NEUTRAL"
export const float VIX_LEVEL = 15.74
export const float MACRO_BIAS = 0.0344
export const float MACRO_BIAS_RAW = -0.125
export const float MACRO_BIAS_PE_ADJUSTMENT = 0.1594
export const float MARKET_PE_FORWARD = 7.0291
export const string MARKET_PE_REGIME = "CHEAP"
export const float SECTOR_BREADTH = 0.7273

// ── News Sentiment ──
export const string NEWS_BULLISH_TICKERS = "META,SHOP"
export const string NEWS_BEARISH_TICKERS = "CRM"
export const string NEWS_NEUTRAL_TICKERS = "AAPL,AMD"
export const float NEWS_HEAT_GLOBAL = 0.0352
export const string TICKER_HEAT_MAP = "AAPL:0.00,AMD:0.10"
export const string NEWS_CATEGORY_MAP = ""
export const string NEWS_COUNT_MAP = ""
export const string BREAKING_NEWS_TICKERS = ""
export const int HIGH_IMPACT_NEWS_COUNT = 0
export const string MOST_MENTIONED_TICKER = ""

// ── Earnings & Macro Calendar ──
export const string EARNINGS_TODAY_TICKERS = "COST,DELL"
export const string EARNINGS_TOMORROW_TICKERS = "BKE"
export const string EARNINGS_BMO_TICKERS = ""
export const string EARNINGS_AMC_TICKERS = ""
export const bool HIGH_IMPACT_MACRO_TODAY = true
export const string MACRO_EVENT_NAME = "GDP Growth Rate YoY (Q1)"
export const string MACRO_EVENT_TIME = "02:00 ET"

// ── Layering / Global Tone ──
export const float GLOBAL_HEAT = 0.4748
export const float GLOBAL_STRENGTH = 0.4748
export const string TONE = "BULLISH"
export const string TRADE_STATE = "ALLOWED"

// ── Provider Status ──
export const int PROVIDER_COUNT = 3
export const string STALE_PROVIDERS = ""

// ── Trust State ──
export const float TRUST_SCORE = 0.9
"""


def _export_lines_by_field(text: str) -> dict[str, str]:
    """Map FIELD -> full export line for every `export const TYPE FIELD = ...`."""
    import re

    pat = re.compile(r"^export const \w+ (?P<field>[A-Z][A-Z0-9_]*) =")
    out: dict[str, str] = {}
    for line in text.splitlines():
        match = pat.match(line)
        if match:
            out[match.group("field")] = line
    return out


# ── Contract: which fields end up in the overlay ────────────────────────────


def test_overlay_contract_fields_exact():
    lines = select_overlay_lines(SYNTHETIC_SOURCE)
    contract = overlay_fields(lines) - set(WATERMARK_FIELDS)
    assert contract == set(OVERLAY_FIELDS)


def test_overlay_includes_watermark():
    lines = select_overlay_lines(SYNTHETIC_SOURCE)
    found = overlay_fields(lines)
    for field in WATERMARK_FIELDS:
        assert field in found


def test_overlay_excludes_slow_structural_fields():
    lines = select_overlay_lines(SYNTHETIC_SOURCE)
    found = overlay_fields(lines)
    leaked = SLOW_FIELDS_THAT_MUST_BE_ABSENT & found
    assert not leaked, f"slow fields leaked into overlay: {sorted(leaked)}"


def test_overlay_field_count_is_29():
    assert len(OVERLAY_FIELDS) == 29


# ── Header / Pine validity ──────────────────────────────────────────────────


def test_overlay_header_is_valid_pine():
    lines = select_overlay_lines(SYNTHETIC_SOURCE)
    assert lines[0] == "//@version=6"
    assert f'library("{OVERLAY_LIBRARY_NAME}")' in lines
    assert any(line.endswith(" as ov") for line in lines)


def test_overlay_sections_present_in_order():
    lines = select_overlay_lines(SYNTHETIC_SOURCE)
    positions = [lines.index(marker) for marker in OVERLAY_SECTION_MARKERS]
    assert positions == sorted(positions)


# ── Byte-identical values ───────────────────────────────────────────────────


def test_overlay_values_byte_match_source():
    overlay = select_overlay_lines(SYNTHETIC_SOURCE)
    src_lines = _export_lines_by_field(SYNTHETIC_SOURCE)
    overlay_lines = _export_lines_by_field("\n".join(overlay))
    for field in set(OVERLAY_FIELDS) | set(WATERMARK_FIELDS):
        assert overlay_lines[field] == src_lines[field]


# ── Defensive failure modes ─────────────────────────────────────────────────


def test_select_overlay_lines_raises_on_missing_watermark():
    broken = SYNTHETIC_SOURCE.replace(
        'export const string ASOF_DATE = "2026-05-27"\n', ""
    )
    with pytest.raises(ValueError, match="ASOF_DATE"):
        select_overlay_lines(broken)


def test_select_overlay_lines_raises_on_no_overlay_sections():
    minimal = (
        '//@version=6\n'
        'library("smc_micro_profiles_generated")\n\n'
        '// ── Core ──\n'
        'export const string ASOF_DATE = "2026-05-27"\n'
        'export const string ASOF_TIME = "2026-05-28T22:15:00Z"\n'
    )
    with pytest.raises(ValueError, match="no overlay fields"):
        select_overlay_lines(minimal)


# ── Manifest shape ──────────────────────────────────────────────────────────


def test_build_overlay_manifest_keys():
    lines = select_overlay_lines(SYNTHETIC_SOURCE)
    fields = overlay_fields(lines)
    main_manifest = {
        "schema_version": "3.0.0",
        "library_name": "smc_micro_profiles_generated",
        "library_owner": "preuss_steffen",
        "asof_date": "2026-05-27",
        "asof_time": "2026-05-28T22:15:00Z",
    }
    manifest = build_overlay_manifest(
        main_manifest,
        fields,
        owner="preuss_steffen",
        version=1,
        out_pine=Path("pine/generated/smc_overlay_generated.pine"),
        source_pine=Path("pine/generated/smc_micro_profiles_generated.pine"),
        source_manifest=Path("pine/generated/smc_micro_profiles_generated.json"),
    )
    assert manifest["library_name"] == OVERLAY_LIBRARY_NAME
    assert manifest["cadence_class"] == "fast_overlay"
    assert manifest["derived_from_source_artifact"] is True
    assert manifest["overlay_field_count"] == 29
    assert manifest["overlay_fields"] == sorted(OVERLAY_FIELDS)
    assert manifest["watermark_fields"] == list(WATERMARK_FIELDS)
    assert manifest["overlay_sections"] == list(OVERLAY_SECTION_NAMES)
    assert manifest["asof_date"] == "2026-05-27"
    assert manifest["recommended_import_path"] == "preuss_steffen/smc_overlay_generated/1"
    assert manifest["core_import_snippet"].endswith(" as ov")


# ── End-to-end bake roundtrip ───────────────────────────────────────────────


def test_bake_roundtrip_writes_files(tmp_path):
    src_pine = tmp_path / "src.pine"
    src_manifest = tmp_path / "src.json"
    src_pine.write_text(SYNTHETIC_SOURCE, encoding="utf-8")
    src_manifest.write_text(
        json.dumps(
            {
                "schema_version": "3.0.0",
                "library_name": "smc_micro_profiles_generated",
                "library_owner": "preuss_steffen",
                "asof_date": "2026-05-27",
                "asof_time": "2026-05-28T22:15:00Z",
            }
        ),
        encoding="utf-8",
    )
    out_pine = tmp_path / "overlay.pine"
    out_manifest = tmp_path / "overlay.json"

    manifest = bake(
        source_pine=src_pine,
        source_manifest=src_manifest,
        out_pine=out_pine,
        out_manifest=out_manifest,
    )

    assert out_pine.exists()
    assert out_manifest.exists()
    pine_text = out_pine.read_text(encoding="utf-8")
    assert f'library("{OVERLAY_LIBRARY_NAME}")' in pine_text
    written = json.loads(out_manifest.read_text(encoding="utf-8"))
    assert written == manifest
    assert written["overlay_fields"] == sorted(OVERLAY_FIELDS)


# ── Drift guard against the committed real artifact ─────────────────────────


def test_real_artifact_matches_contract():
    assert SOURCE_PINE.exists(), "source micro-profiles .pine must be committed"
    text = SOURCE_PINE.read_text(encoding="utf-8")
    lines = select_overlay_lines(text)
    contract = overlay_fields(lines) - set(WATERMARK_FIELDS)
    assert contract == set(OVERLAY_FIELDS)
    # Real artifact values must survive the filter byte-identically.
    src_lines = _export_lines_by_field(text)
    overlay_lines = _export_lines_by_field("\n".join(lines))
    for field in set(OVERLAY_FIELDS) | set(WATERMARK_FIELDS):
        assert overlay_lines[field] == src_lines[field]
