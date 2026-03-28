from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_smc_micro_profiles import load_schema, write_pine_library
from scripts.smc_microstructure_base_runtime import (
    ETF_KEYWORDS,
    MappingStatus,
    generate_base_from_bundle,
    generate_pine_library_from_base,
    infer_asset_type,
    infer_universe_bucket,
    run_databento_base_scan_pipeline,
)
from scripts.smc_regime_classifier import classify_market_regime
from scripts.smc_news_scorer import compute_news_sentiment
from scripts.smc_calendar_collector import collect_earnings_and_macro
from scripts.smc_library_layering import compute_library_layering

logger = logging.getLogger(__name__)


DERIVED_FIELD_NOTES = {
    "asset_type": "Derived heuristically from company_name ETF/fund keywords; defaults to stock when no ETF marker is present.",
    "universe_bucket": "Derived from asset_type plus market_cap bands: ETF -> us_etf, else large/mid/small-cap buckets.",
    "history_coverage_days_20d": "Derived as trailing daily_bars row count up to the selected asof_date, capped at 20 sessions.",
    "adv_dollar_rth_20d": "Derived as mean(close * volume) over trailing daily_bars rows up to the selected asof_date, capped at 20 sessions.",
}


def load_workbook_frames(path: Path) -> dict[str, pd.DataFrame]:
    workbook = pd.ExcelFile(path)
    frames: dict[str, pd.DataFrame] = {}
    for sheet_name in workbook.sheet_names:
        frames[sheet_name] = workbook.parse(sheet_name)
    return frames


def choose_asof_date(summary: pd.DataFrame, asof_date: str | None = None) -> str:
    trade_dates = pd.to_datetime(summary["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if asof_date is not None:
        if asof_date not in set(trade_dates.dropna()):
            raise ValueError(f"Requested asof_date {asof_date} is not present in the workbook")
        return asof_date
    latest = trade_dates.dropna().max()
    if not latest:
        raise ValueError("Workbook summary sheet does not contain a valid trade_date")
    return str(latest)


def build_trailing_daily_metrics(daily_bars: pd.DataFrame, asof_date: str) -> pd.DataFrame:
    frame = daily_bars.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
    frame = frame.loc[frame["trade_date"] <= pd.Timestamp(asof_date)].copy()
    frame = frame.sort_values(["symbol", "trade_date"])
    frame["dollar_volume"] = pd.to_numeric(frame["close"], errors="coerce") * pd.to_numeric(frame["volume"], errors="coerce")
    trailing = frame.groupby("symbol", group_keys=False).tail(20)
    metrics = (
        trailing.groupby("symbol", dropna=False)
        .agg(
            history_coverage_days_20d=("trade_date", "nunique"),
            adv_dollar_rth_20d=("dollar_volume", "mean"),
        )
        .reset_index()
    )
    metrics["history_coverage_days_20d"] = metrics["history_coverage_days_20d"].fillna(0).astype(int)
    return metrics


def build_mapping_statuses(required_columns: list[str]) -> list[MappingStatus]:
    direct = {
        "asof_date": MappingStatus("asof_date", "direct", "summary", ["trade_date"], "Latest trade_date snapshot selected from workbook summary."),
        "symbol": MappingStatus("symbol", "direct", "summary", ["symbol"], "Copied from workbook summary."),
        "exchange": MappingStatus("exchange", "direct", "summary", ["exchange"], "Copied from workbook summary."),
    }
    derived = {
        name: MappingStatus(name, "derived", "summary,daily_bars", [], DERIVED_FIELD_NOTES[name])
        for name in DERIVED_FIELD_NOTES
    }
    statuses: list[MappingStatus] = []
    for field in required_columns:
        if field in direct:
            statuses.append(direct[field])
        elif field in derived:
            statuses.append(derived[field])
        else:
            statuses.append(
                MappingStatus(
                    field,
                    "missing",
                    "",
                    [],
                    "Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.",
                )
            )
    return statuses


def build_base_snapshot_from_workbook(
    workbook_path: Path,
    *,
    schema_path: Path,
    asof_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    schema = load_schema(schema_path)
    frames = load_workbook_frames(workbook_path)
    if "summary" not in frames or "daily_bars" not in frames:
        raise ValueError("Workbook must contain summary and daily_bars sheets")

    summary = frames["summary"].copy()
    summary["trade_date"] = pd.to_datetime(summary["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    selected_asof_date = choose_asof_date(summary, asof_date=asof_date)
    latest = summary.loc[summary["trade_date"] == selected_asof_date].copy()
    latest = latest.sort_values(["symbol", "rank"]).drop_duplicates(subset=["symbol"], keep="first")

    daily_metrics = build_trailing_daily_metrics(frames["daily_bars"], selected_asof_date)
    snapshot = latest.merge(daily_metrics, on="symbol", how="left")

    snapshot["asof_date"] = selected_asof_date
    snapshot["asset_type"] = snapshot["company_name"].map(infer_asset_type)
    snapshot["universe_bucket"] = [
        infer_universe_bucket(asset_type, market_cap)
        for asset_type, market_cap in zip(snapshot["asset_type"], snapshot.get("market_cap", pd.Series(dtype=float)), strict=False)
    ]

    required_columns = [str(column) for column in schema["required_columns"]]
    output = pd.DataFrame(index=snapshot.index)
    output["asof_date"] = snapshot["asof_date"]
    output["symbol"] = snapshot["symbol"].astype(str).str.upper()
    output["exchange"] = snapshot["exchange"].astype(str).str.upper()
    output["asset_type"] = snapshot["asset_type"]
    output["universe_bucket"] = snapshot["universe_bucket"]
    output["history_coverage_days_20d"] = snapshot["history_coverage_days_20d"].fillna(0).astype(int)
    output["adv_dollar_rth_20d"] = pd.to_numeric(snapshot["adv_dollar_rth_20d"], errors="coerce")

    for column in required_columns:
        if column not in output.columns:
            output[column] = pd.NA
    output = output[required_columns].sort_values(["symbol"]).reset_index(drop=True)

    statuses = build_mapping_statuses(required_columns)
    missing_fields = [status.field for status in statuses if status.status == "missing"]
    derived_fields = [status.field for status in statuses if status.status == "derived"]
    payload = {
        "workbook_path": str(workbook_path),
        "asof_date": selected_asof_date,
        "row_count": len(output),
        "direct_fields": [status.field for status in statuses if status.status == "direct"],
        "derived_fields": derived_fields,
        "missing_fields": missing_fields,
        "mapping_status": [
            {
                "field": status.field,
                "status": status.status,
                "source_sheet": status.source_sheet,
                "source_columns": status.source_columns,
                "note": status.note,
            }
            for status in statuses
        ],
    }
    return output, payload


def write_mapping_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def md_row(*cells: str) -> str:
        return "|" + "|".join(cells) + "|"

    lines = [
        f"# Databento Workbook To Microstructure Base Mapping: {Path(payload['workbook_path']).name}",
        "",
        f"- Workbook: {payload['workbook_path']}",
        f"- Selected asof_date: {payload['asof_date']}",
        f"- Output rows: {payload['row_count']}",
        f"- Direct fields: {len(payload['direct_fields'])}",
        f"- Derived fields: {len(payload['derived_fields'])}",
        f"- Missing fields: {len(payload['missing_fields'])}",
        "",
        md_row("Contract field", "Status", "Source sheet", "Source columns", "Note"),
        md_row("---", "---", "---", "---", "---"),
    ]
    for status in payload["mapping_status"]:
        source_columns = ", ".join(status["source_columns"]) if status["source_columns"] else ""
        lines.append(md_row(status["field"], status["status"], status["source_sheet"], source_columns, status["note"]))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def build_default_output_paths(workbook_path: Path, asof_date: str) -> tuple[Path, Path, Path]:
    stem = workbook_path.stem
    base_csv = Path("data/input") / f"{stem}_microstructure_base_{asof_date}.csv"
    report_md = Path("reports") / f"{stem}_microstructure_mapping_{asof_date}.md"
    report_json = Path("reports") / f"{stem}_microstructure_mapping_{asof_date}.json"
    return base_csv, report_md, report_json


# ── FMP enrichment helpers ──────────────────────────────────────────

def _make_fmp_client(api_key: str) -> Any:
    """Lazy-import FMPClient to avoid hard dependency when enrichment is off."""
    from open_prep.macro import FMPClient
    return FMPClient(api_key=api_key, retry_attempts=2, timeout_seconds=12)


def _fetch_regime_data(fmp: Any) -> dict[str, Any]:
    """Fetch VIX + sector performance from FMP, return regime dict."""
    vix_level: float | None = None
    macro_bias = 0.0
    sectors: list[dict[str, Any]] = []
    stale: list[str] = []

    try:
        vix_row = fmp.get_index_quote("^VIX")
        raw = vix_row.get("price")
        if raw is not None:
            vix_level = float(raw)
    except Exception:
        logger.warning("FMP VIX fetch failed — using default", exc_info=True)
        stale.append("fmp_vix")

    try:
        sectors = fmp.get_sector_performance()
    except Exception:
        logger.warning("FMP sector-performance fetch failed — using default", exc_info=True)
        stale.append("fmp_sectors")

    regime = classify_market_regime(vix_level, macro_bias, sectors)
    regime["stale_providers"] = stale
    return regime


def _fetch_news_data(fmp: Any, symbols: list[str]) -> dict[str, Any]:
    """Fetch latest stock news from FMP and score sentiment."""
    stale: list[str] = []
    articles: list[dict[str, Any]] = []

    try:
        raw = fmp.get_stock_latest_news(limit=100)
        for item in raw:
            headline = item.get("title") or item.get("headline") or ""
            tickers = item.get("tickers") or []
            if isinstance(tickers, str):
                tickers = [t.strip() for t in tickers.split(",") if t.strip()]
            symbol_field = item.get("symbol") or ""
            if symbol_field and not tickers:
                tickers = [symbol_field]
            articles.append({"headline": headline, "tickers": tickers})
    except Exception:
        logger.warning("FMP news fetch failed — using default", exc_info=True)
        stale.append("fmp_news")

    result = compute_news_sentiment(symbols, articles)
    result["stale_providers"] = stale
    return result


def _fetch_calendar_data(fmp: Any, symbols: list[str]) -> dict[str, Any]:
    """Fetch earnings calendar and macro events from FMP."""
    stale: list[str] = []
    earnings: list[dict[str, Any]] = []
    macro_events: list[dict[str, Any]] = []
    today = date.today()
    tomorrow = today + timedelta(days=1)

    try:
        raw = fmp.get_earnings_calendar(today, tomorrow)
        for row in raw:
            sym = row.get("symbol") or ""
            d = row.get("date") or ""
            timing = (row.get("time") or "").lower()
            if timing in ("bmo", "amc"):
                pass  # keep as-is
            elif timing.startswith("before"):
                timing = "bmo"
            elif timing.startswith("after"):
                timing = "amc"
            earnings.append({"symbol": sym, "date": d, "timing": timing})
    except Exception:
        logger.warning("FMP earnings-calendar fetch failed — using default", exc_info=True)
        stale.append("fmp_earnings")

    try:
        raw_macro = fmp.get_macro_calendar(today, today)
        for evt in raw_macro:
            name = evt.get("event") or evt.get("name") or ""
            time_utc = evt.get("date") or evt.get("time_utc") or ""
            macro_events.append({"name": name, "time_utc": time_utc})
    except Exception:
        logger.warning("FMP macro-calendar fetch failed — using default", exc_info=True)
        stale.append("fmp_macro")

    result = collect_earnings_and_macro(symbols, earnings, macro_events, reference_date=today)
    result["stale_providers"] = stale
    return result


def _fetch_technical_summary(fmp: Any, symbol: str = "SPY") -> tuple[float, str]:
    """Fetch a rough directional strength + bias from RSI for *symbol*."""
    try:
        data = fmp.get_technical_indicator(symbol, "1day", "rsi", indicator_period=14)
        rsi_val = data.get("rsi") if data else None
        if rsi_val is not None:
            rsi = float(rsi_val)
            strength = abs(rsi - 50.0) / 50.0
            bias = "BULLISH" if rsi > 55 else ("BEARISH" if rsi < 45 else "NEUTRAL")
            return (min(strength, 1.0), bias)
    except Exception:
        logger.warning("FMP technical fetch failed — using default", exc_info=True)
    return (0.5, "NEUTRAL")


def build_enrichment(
    *,
    fmp_api_key: str,
    symbols: list[str],
    enrich_regime: bool = False,
    enrich_news: bool = False,
    enrich_calendar: bool = False,
    enrich_layering: bool = False,
) -> dict[str, Any] | None:
    """Build the enrichment dict by calling the AP-1..AP-5 helpers.

    Each block is wrapped in its own try/except — on failure the block
    uses neutral defaults and the failing provider is recorded in
    ``stale_providers``.
    """
    if not any([enrich_regime, enrich_news, enrich_calendar, enrich_layering]):
        return None

    fmp = _make_fmp_client(fmp_api_key) if fmp_api_key else None
    enrichment: dict[str, Any] = {}
    all_stale: list[str] = []

    # ── Regime ──────────────────────────────────────────────────
    regime_result: dict[str, Any] = {"regime": "NEUTRAL"}
    if enrich_regime:
        if fmp is not None:
            try:
                regime_result = _fetch_regime_data(fmp)
                all_stale.extend(regime_result.pop("stale_providers", []))
            except Exception:
                logger.warning("Regime enrichment failed — using defaults", exc_info=True)
                all_stale.append("regime")
        else:
            all_stale.append("fmp_missing")
        enrichment["regime"] = regime_result

    # ── News ────────────────────────────────────────────────────
    news_result: dict[str, Any] = {}
    if enrich_news:
        if fmp is not None:
            try:
                news_result = _fetch_news_data(fmp, symbols)
                all_stale.extend(news_result.pop("stale_providers", []))
            except Exception:
                logger.warning("News enrichment failed — using defaults", exc_info=True)
                all_stale.append("news")
        else:
            all_stale.append("fmp_missing")
        enrichment["news"] = {
            "bullish_tickers": news_result.get("bullish_tickers", []),
            "bearish_tickers": news_result.get("bearish_tickers", []),
            "neutral_tickers": news_result.get("neutral_tickers", []),
            "news_heat_global": news_result.get("news_heat_global", 0.0),
            "ticker_heat_map": news_result.get("ticker_heat_map", ""),
        }

    # ── Calendar ────────────────────────────────────────────────
    calendar_result: dict[str, Any] = {}
    if enrich_calendar:
        if fmp is not None:
            try:
                calendar_result = _fetch_calendar_data(fmp, symbols)
                all_stale.extend(calendar_result.pop("stale_providers", []))
            except Exception:
                logger.warning("Calendar enrichment failed — using defaults", exc_info=True)
                all_stale.append("calendar")
        else:
            all_stale.append("fmp_missing")
        enrichment["calendar"] = {
            "earnings_today_tickers": calendar_result.get("earnings_today_tickers", ""),
            "earnings_tomorrow_tickers": calendar_result.get("earnings_tomorrow_tickers", ""),
            "earnings_bmo_tickers": calendar_result.get("earnings_bmo_tickers", ""),
            "earnings_amc_tickers": calendar_result.get("earnings_amc_tickers", ""),
            "high_impact_macro_today": calendar_result.get("high_impact_macro_today", False),
            "macro_event_name": calendar_result.get("macro_event_name", ""),
            "macro_event_time": calendar_result.get("macro_event_time", ""),
        }

    # ── Layering ────────────────────────────────────────────────
    if enrich_layering:
        tech_strength, tech_bias = (0.5, "NEUTRAL")
        if fmp is not None:
            try:
                tech_strength, tech_bias = _fetch_technical_summary(fmp)
            except Exception:
                logger.warning("Technical fetch for layering failed — using defaults", exc_info=True)
                all_stale.append("fmp_technical")
        else:
            all_stale.append("fmp_missing")

        # Determine news tone for layering
        bullish_count = len(news_result.get("bullish_tickers", []))
        bearish_count = len(news_result.get("bearish_tickers", []))
        if bullish_count > bearish_count:
            news_tone = "BULLISH"
        elif bearish_count > bullish_count:
            news_tone = "BEARISH"
        else:
            news_tone = "NEUTRAL"

        try:
            layering = compute_library_layering(
                regime=regime_result.get("regime", "NEUTRAL"),
                news=news_tone,
                technical_strength=tech_strength,
                technical_bias=tech_bias,
            )
        except Exception:
            logger.warning("Layering computation failed — using defaults", exc_info=True)
            layering = {
                "global_heat": 0.0,
                "global_strength": 0.5,
                "tone": "NEUTRAL",
                "trade_state": "ALLOWED",
            }
            all_stale.append("layering")
        enrichment["layering"] = layering

    # ── Providers ───────────────────────────────────────────────
    enrichment["providers"] = {
        "stale_providers": ",".join(sorted(set(all_stale))),
    }

    return enrichment


def finalize_pipeline(
    *,
    base_result: dict[str, Any],
    schema_path: Path,
    output_root: Path,
    fmp_api_key: str = "",
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    enrich_regime: bool = False,
    enrich_news: bool = False,
    enrich_calendar: bool = False,
    enrich_layering: bool = False,
) -> dict[str, Any]:
    """Shared post-base orchestration: enrichment + Pine library generation.

    Called by both the ``--run-scan`` and ``--bundle`` CLI paths as well
    as UI-triggered flows.  Returns a structured, machine-readable result
    dict that downstream gates / CI can consume directly.
    """
    base_csv = Path(base_result["output_paths"]["base_csv"])
    symbols = sorted(
        base_result["base_snapshot"]["symbol"].dropna().unique().tolist()
    )

    # ── Enrichment ──────────────────────────────────────────────
    enrichment = build_enrichment(
        fmp_api_key=fmp_api_key,
        symbols=symbols,
        enrich_regime=enrich_regime,
        enrich_news=enrich_news,
        enrich_calendar=enrich_calendar,
        enrich_layering=enrich_layering,
    )

    # ── Pine library generation ─────────────────────────────────
    pine_paths = generate_pine_library_from_base(
        base_csv_path=base_csv,
        schema_path=schema_path,
        output_root=output_root,
        library_owner=library_owner,
        library_version=library_version,
        enrichment=enrichment,
    )

    return {
        "status": "ok",
        "base_csv": str(base_csv),
        "symbols_count": len(symbols),
        "enrichment_keys": list(enrichment.keys()) if enrichment else [],
        "stale_providers": (
            enrichment.get("providers", {}).get("stale_providers", "")
            if enrichment
            else ""
        ),
        "pine_paths": {k: str(v) for k, v in pine_paths.items()},
        "base_result_keys": list(base_result.keys()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an SMC microstructure base snapshot from a Databento workbook, an export bundle, or a fresh Databento full-universe scan."
    )
    parser.add_argument("workbook", nargs="?", type=Path, help="Legacy path to databento_volatility_production_*.xlsx")
    parser.add_argument("--bundle", type=Path, help="Manifest path, export directory, or bundle basename for Databento production exports")
    parser.add_argument("--run-scan", action="store_true", help="Run the full Databento production export first, then build the base snapshot from the generated bundle")
    parser.add_argument("--databento-api-key", default=os.getenv("DATABENTO_API_KEY", ""), help="Databento API key for --run-scan")
    parser.add_argument("--fmp-api-key", default=os.getenv("FMP_API_KEY", ""), help="FMP API key for enrichment and --run-scan")
    parser.add_argument("--dataset", default=os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"), help="Databento dataset for --run-scan")
    parser.add_argument("--lookback-days", type=int, default=30, help="Trading-day lookback for --run-scan")
    parser.add_argument("--export-dir", type=Path, default=Path("artifacts/smc_microstructure_exports"), help="Output directory for bundle/base artifacts")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass file cache during --run-scan")
    parser.add_argument("--write-xlsx", action="store_true", help="Also emit an .xlsx base workbook for bundle/scan generation")
    parser.add_argument("--library-owner", default="preuss_steffen", help="TradingView owner for the generated library import path metadata")
    parser.add_argument("--library-version", type=int, default=1, help="TradingView library version for generated import metadata")
    from scripts.smc_schema_resolver import resolve_microstructure_schema_path
    parser.add_argument("--schema", type=Path, default=resolve_microstructure_schema_path(), help="Path to the microstructure schema")
    parser.add_argument("--asof-date", help="Optional YYYY-MM-DD trade date to extract; defaults to the latest workbook trade_date")
    parser.add_argument("--output-csv", type=Path, help="Output path for the generated partial base snapshot CSV")
    parser.add_argument("--report-md", type=Path, help="Output path for the markdown mapping report")
    parser.add_argument("--report-json", type=Path, help="Output path for the JSON mapping report")
    # Enrichment flags
    parser.add_argument("--enrich-regime", action="store_true", help="Add market-regime enrichment (VIX, sector performance via FMP)")
    parser.add_argument("--enrich-news", action="store_true", help="Add news-sentiment enrichment (FMP stock news)")
    parser.add_argument("--enrich-calendar", action="store_true", help="Add earnings/macro calendar enrichment (FMP)")
    parser.add_argument("--enrich-layering", action="store_true", help="Add pre-computed layering signals (smc_core)")
    parser.add_argument("--enrich-all", action="store_true", help="Enable all enrichment blocks")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    enrich_regime, enrich_news, enrich_calendar, enrich_layering = _resolve_enrichment_flags(args)
    fmp_api_key = str(args.fmp_api_key).strip()

    finalize_kwargs = dict(
        schema_path=args.schema,
        output_root=args.export_dir,
        fmp_api_key=fmp_api_key,
        library_owner=str(args.library_owner).strip(),
        library_version=int(args.library_version),
        enrich_regime=enrich_regime,
        enrich_news=enrich_news,
        enrich_calendar=enrich_calendar,
        enrich_layering=enrich_layering,
    )

    if args.run_scan:
        if not args.databento_api_key:
            raise ValueError("Databento API key is required when using --run-scan")
        base_result = run_databento_base_scan_pipeline(
            databento_api_key=str(args.databento_api_key).strip(),
            fmp_api_key=fmp_api_key,
            dataset=str(args.dataset).strip(),
            export_dir=args.export_dir,
            schema_path=args.schema,
            lookback_days=int(args.lookback_days),
            force_refresh=bool(args.force_refresh),
            cache_dir=Path("artifacts") / "databento_volatility_cache",
            use_file_cache=True,
            display_timezone="Europe/Berlin",
            bullish_score_profile="balanced",
            write_xlsx=bool(args.write_xlsx),
            library_owner=str(args.library_owner).strip(),
            library_version=int(args.library_version),
        )
        result = finalize_pipeline(base_result=base_result, **finalize_kwargs)
        logger.info("Pipeline complete: %s", json.dumps(result, indent=2))
        return

    if args.bundle is not None:
        bundle_result = generate_base_from_bundle(
            args.bundle,
            schema_path=args.schema,
            output_dir=args.export_dir,
            asof_date=args.asof_date,
            write_xlsx=bool(args.write_xlsx),
            library_owner=str(args.library_owner).strip(),
            library_version=int(args.library_version),
        )
        result = finalize_pipeline(base_result=bundle_result, **finalize_kwargs)
        logger.info("Pipeline complete: %s", json.dumps(result, indent=2))
        return

    if args.workbook is None:
        raise ValueError("Provide either a legacy workbook path, --bundle, or --run-scan")

    output, payload = build_base_snapshot_from_workbook(args.workbook, schema_path=args.schema, asof_date=args.asof_date)
    default_csv, default_md, default_json = build_default_output_paths(args.workbook, payload["asof_date"])
    output_csv = args.output_csv or default_csv
    report_md = args.report_md or default_md
    report_json = args.report_json or default_json
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_csv, index=False)
    write_mapping_report(report_md, payload)
    report_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _resolve_enrichment_flags(args: argparse.Namespace) -> tuple[bool, bool, bool, bool]:
    """Return (regime, news, calendar, layering) booleans."""
    if args.enrich_all:
        return True, True, True, True
    return (
        bool(args.enrich_regime),
        bool(args.enrich_news),
        bool(args.enrich_calendar),
        bool(args.enrich_layering),
    )


if __name__ == "__main__":
    main()