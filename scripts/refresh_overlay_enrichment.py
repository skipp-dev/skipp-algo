#!/usr/bin/env python3
"""Refresh the FAST overlay Pine library with live enrichment data.

Unlike ``bake_overlay_library.py`` (which *derives* overlay values from the
already-generated main ``.pine`` artifact), this script re-runs the 4 fast
enrichment modules (regime, news, calendar, layering) against live API
data and renders their results directly into the overlay Pine library.

This enables a fast-cadence publish loop that does NOT depend on a full
Databento scan or the slow micro-profiles pipeline: the overlay values
can be refreshed intraday on a cron schedule and immediately published
to TradingView via the overlay publisher workflow.

Enrichment modules
------------------
1. Market Regime   – ``smc_regime_classifier`` via provider policy
2. News Sentiment  – ``smc_live_news_bus`` / provider policy
3. Calendar        – ``smc_calendar_collector`` via provider policy
4. Layering        – ``smc_library_layering`` (derived from regime + news)

Output files
~~~~~~~~~~~~
* ``pine/generated/smc_overlay_generated.pine``
* ``pine/generated/smc_overlay_generated.json``

Usage
-----
    python -m scripts.refresh_overlay_enrichment

Environment variables
~~~~~~~~~~~~~~~~~~~~~
* ``FMP_API_KEY``  – FinancialModelingPrep key (regime, technical, calendar)
* ``BENZINGA_API_KEY`` – Benzinga key (news, calendar fallback)
* ``NEWSAPI_KEY`` – NewsAPI.ai key (news fallback)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# ── sys.path bootstrap (repo-root convention) ──────────────────
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.bake_overlay_library import (
    DEFAULT_OWNER,
    OVERLAY_FIELDS,
    OVERLAY_LIBRARY_NAME,
    OVERLAY_SECTION_NAMES,
    WATERMARK_FIELDS,
    _overlay_header,
)
from scripts.bake_overlay_library import (
    overlay_fields as extract_overlay_fields,
)
from scripts.generate_smc_micro_profiles import (
    _pine_float,
    render_csv_export,
)
from scripts.smc_atomic_write import atomic_write_text


def _pine_bool(val: object) -> str:
    """Render a Python truthy value as Pine ``true`` / ``false``."""
    return "true" if val else "false"


def _split_csv_string(value: str) -> list[str]:
    """Split a comma-separated string, filtering empty parts."""
    return [s for s in value.split(",") if s]


# ── Render helpers ──────────────────────────────────────────────

def render_overlay_pine_lines(
    enrichment: dict,
    *,
    owner: str = DEFAULT_OWNER,
    version: int = 1,
    asof_date: str = "",
    asof_time: str = "",
) -> list[str]:
    """Render the overlay ``.pine`` from a live enrichment dict.

    The output is structurally identical to what ``bake_overlay_library``
    produces (same header, same section order, same field names) — only
    the *values* come from the live enrichment run rather than from the
    pre-baked main library.
    """
    lines: list[str] = list(_overlay_header(owner, version))

    # ── Watermark ───────────────────────────────────────────────
    lines.append("")
    lines.append("// ── Bake Watermark ──")
    lines.append(f'export const string ASOF_DATE = "{asof_date}"')
    lines.append(f'export const string ASOF_TIME = "{asof_time}"')

    # ── Market Regime ───────────────────────────────────────────
    regime = enrichment.get("regime") or {}
    lines.append("")
    lines.append("// ── Market Regime ──")
    lines.append(f'export const string MARKET_REGIME = "{regime.get("regime", "NEUTRAL")}"')
    lines.append(f'export const float VIX_LEVEL = {_pine_float(regime.get("vix_level") or 0.0)}')
    lines.append(f'export const float MACRO_BIAS = {_pine_float(regime.get("macro_bias") or 0.0)}')
    _raw = regime.get("macro_bias_raw")
    lines.append(f'export const float MACRO_BIAS_RAW = {_pine_float(_raw if _raw is not None else 0.0)}')
    lines.append(f'export const float MACRO_BIAS_PE_ADJUSTMENT = {_pine_float(regime.get("macro_bias_pe_adjustment") or 0.0)}')
    lines.append(f'export const float MARKET_PE_FORWARD = {_pine_float(regime.get("market_pe_forward") or 0.0)}')
    lines.append(f'export const string MARKET_PE_REGIME = "{regime.get("market_pe_regime") or "UNKNOWN"}"')
    lines.append(f'export const float SECTOR_BREADTH = {_pine_float(regime.get("sector_breadth") or 0.0)}')

    # ── News Sentiment ──────────────────────────────────────────
    news = enrichment.get("news") or {}
    lines.append("")
    lines.append("// ── News Sentiment ──")
    lines.append(render_csv_export("NEWS_BULLISH_TICKERS", news.get("bullish_tickers") or []))
    lines.append(render_csv_export("NEWS_BEARISH_TICKERS", news.get("bearish_tickers") or []))
    lines.append(render_csv_export("NEWS_NEUTRAL_TICKERS", news.get("neutral_tickers") or []))
    lines.append(f'export const float NEWS_HEAT_GLOBAL = {_pine_float(news.get("news_heat_global") or 0.0)}')
    lines.append(render_csv_export("TICKER_HEAT_MAP", _split_csv_string(news.get("ticker_heat_map") or "")))
    lines.append(f'export const string NEWS_CATEGORY_MAP = "{news.get("news_category_map") or ""}"')
    lines.append(f'export const string NEWS_COUNT_MAP = "{news.get("news_count_map") or ""}"')
    lines.append(f'export const string BREAKING_NEWS_TICKERS = "{",".join(news.get("breaking_tickers") or [])}"')
    lines.append(f'export const int HIGH_IMPACT_NEWS_COUNT = {int(news.get("high_impact_news_count") or 0)}')
    lines.append(f'export const string MOST_MENTIONED_TICKER = "{news.get("most_mentioned_ticker") or ""}"')

    # ── Earnings & Macro Calendar ───────────────────────────────
    cal = enrichment.get("calendar") or {}
    lines.append("")
    lines.append("// ── Earnings & Macro Calendar ──")
    lines.append(f'export const string EARNINGS_TODAY_TICKERS = "{cal.get("earnings_today_tickers") or ""}"')
    lines.append(f'export const string EARNINGS_TOMORROW_TICKERS = "{cal.get("earnings_tomorrow_tickers") or ""}"')
    lines.append(f'export const string EARNINGS_BMO_TICKERS = "{cal.get("earnings_bmo_tickers") or ""}"')
    lines.append(f'export const string EARNINGS_AMC_TICKERS = "{cal.get("earnings_amc_tickers") or ""}"')
    lines.append(f'export const bool HIGH_IMPACT_MACRO_TODAY = {_pine_bool(cal.get("high_impact_macro_today"))}')
    lines.append(f'export const string MACRO_EVENT_NAME = "{cal.get("macro_event_name") or ""}"')
    lines.append(f'export const string MACRO_EVENT_TIME = "{cal.get("macro_event_time") or ""}"')

    # ── Layering / Global Tone ──────────────────────────────────
    lay = enrichment.get("layering") or {}
    lines.append("")
    lines.append("// ── Layering / Global Tone ──")
    lines.append(f'export const float GLOBAL_HEAT = {_pine_float(lay.get("global_heat") or 0.0)}')
    lines.append(f'export const float GLOBAL_STRENGTH = {_pine_float(lay.get("global_strength") or 0.0)}')
    lines.append(f'export const string TONE = "{lay.get("tone") or "NEUTRAL"}"')
    lines.append(f'export const string TRADE_STATE = "{lay.get("trade_state") or "ALLOWED"}"')

    lines.append("")
    return lines


def build_fast_overlay_manifest(
    field_names: set[str],
    *,
    owner: str,
    version: int,
    out_pine: Path,
    asof_date: str,
    asof_time: str,
) -> dict:
    """Build the overlay manifest for a live-enrichment run."""
    contract_fields = sorted(field_names - set(WATERMARK_FIELDS))
    return {
        "schema_version": 1,
        "library_name": OVERLAY_LIBRARY_NAME,
        "library_owner": owner,
        "library_version": version,
        "recommended_import_path": f"{owner}/{OVERLAY_LIBRARY_NAME}/{version}",
        "pine_library": str(out_pine).replace("\\", "/"),
        "core_import_snippet": f"import {owner}/{OVERLAY_LIBRARY_NAME}/{version} as ov",
        "cadence_class": "fast_overlay",
        "derived_from_source_artifact": False,
        "enrichment_source": "live_api",
        "asof_date": asof_date,
        "asof_time": asof_time,
        "overlay_sections": list(OVERLAY_SECTION_NAMES),
        "overlay_field_count": len(contract_fields),
        "overlay_fields": contract_fields,
        "watermark_fields": list(WATERMARK_FIELDS),
    }


# Atomic writes use the repo-standard helper (scripts.smc_atomic_write).


def refresh(
    *,
    out_pine: Path | str = "pine/generated/smc_overlay_generated.pine",
    out_manifest: Path | str = "pine/generated/smc_overlay_generated.json",
    owner: str = DEFAULT_OWNER,
    version: int = 1,
    fmp_api_key: str = "",
    benzinga_api_key: str = "",
    newsapi_ai_key: str = "",
    symbols: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Run the 4 fast enrichment modules and write the overlay Pine library.

    Returns the overlay manifest dict.
    """
    from scripts.generate_smc_micro_base_from_databento import build_enrichment

    out_pine = Path(out_pine)
    out_manifest = Path(out_manifest)

    fmp_api_key = fmp_api_key or os.environ.get("FMP_API_KEY", "")
    benzinga_api_key = benzinga_api_key or os.environ.get("BENZINGA_API_KEY", "")
    newsapi_ai_key = newsapi_ai_key or os.environ.get("NEWSAPI_KEY", "")

    if symbols is None:
        symbols = _load_universe_symbols(out_manifest)

    now = datetime.now(UTC)
    asof_date = now.strftime("%Y-%m-%d")
    asof_time = now.strftime("%H:%M:%S UTC")

    enrichment = build_enrichment(
        fmp_api_key=fmp_api_key,
        symbols=symbols,
        benzinga_api_key=benzinga_api_key,
        newsapi_ai_key=newsapi_ai_key,
        enrich_regime=True,
        enrich_news=True,
        enrich_calendar=True,
        enrich_layering=True,
    ) or {}

    pine_lines = render_overlay_pine_lines(
        enrichment,
        owner=owner,
        version=version,
        asof_date=asof_date,
        asof_time=asof_time,
    )
    field_names = extract_overlay_fields(pine_lines)
    manifest = build_fast_overlay_manifest(
        field_names,
        owner=owner,
        version=version,
        out_pine=out_pine,
        asof_date=asof_date,
        asof_time=asof_time,
    )

    contract_fields = field_names - set(WATERMARK_FIELDS)
    missing = OVERLAY_FIELDS - contract_fields
    extra = contract_fields - OVERLAY_FIELDS
    if missing or extra:
        print(
            f"WARNING: overlay field contract drift "
            f"(missing={sorted(missing)} extra={sorted(extra)})",
            file=sys.stderr,
        )

    if dry_run:
        print(
            f"dry-run: would write {out_pine} ({len(pine_lines)} lines, "
            f"{len(contract_fields)} fields) + {out_manifest}",
            file=sys.stderr,
        )
        return manifest

    pine_text = "\n".join(pine_lines) + "\n"
    atomic_write_text(pine_text, out_pine)
    atomic_write_text(json.dumps(manifest, indent=2) + "\n", out_manifest)

    print(
        f"overlay-refresh: wrote {out_pine} ({len(pine_lines)} lines, "
        f"{len(contract_fields)} fields) + {out_manifest} "
        f"(asof_date={asof_date} asof_time={asof_time})",
        file=sys.stderr,
    )
    return manifest


def _load_universe_symbols(manifest_path: Path) -> list[str]:
    """Load the overlay symbol universe from the existing manifest or the main library manifest."""
    # Try the main micro-profiles manifest first (it has the full universe)
    main_manifest = manifest_path.parent / "smc_micro_profiles_generated.json"
    if main_manifest.exists():
        data = json.loads(main_manifest.read_text(encoding="utf-8"))
        symbols = data.get("universe_symbols") or data.get("scanned_symbols") or []
        if symbols:
            return symbols
    # Fallback: empty list means enrichment modules use their defaults
    return []


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Refresh overlay enrichment from live API data.",
    )
    p.add_argument(
        "--out-pine",
        default="pine/generated/smc_overlay_generated.pine",
        help="Output path for the overlay .pine library (default: %(default)s).",
    )
    p.add_argument(
        "--out-manifest",
        default="pine/generated/smc_overlay_generated.json",
        help="Output path for the overlay manifest (default: %(default)s).",
    )
    p.add_argument(
        "--owner",
        default=DEFAULT_OWNER,
        help="TradingView library owner (default: %(default)s).",
    )
    p.add_argument(
        "--version",
        type=int,
        default=1,
        help="Library version (default: %(default)s).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without writing.",
    )
    return p


def main() -> None:
    args = _build_parser().parse_args()
    refresh(
        out_pine=args.out_pine,
        out_manifest=args.out_manifest,
        owner=args.owner,
        version=args.version,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
