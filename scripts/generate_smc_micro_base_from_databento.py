from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.generate_smc_micro_profiles import load_schema
from scripts.smc_microstructure_base_runtime import (
    ETF_KEYWORDS,
    MappingStatus,
    generate_base_from_bundle,
    infer_asset_type,
    infer_universe_bucket,
    run_databento_base_scan_pipeline,
)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an SMC microstructure base snapshot from a Databento workbook, an export bundle, or a fresh Databento full-universe scan."
    )
    parser.add_argument("workbook", nargs="?", type=Path, help="Legacy path to databento_volatility_production_*.xlsx")
    parser.add_argument("--bundle", type=Path, help="Manifest path, export directory, or bundle basename for Databento production exports")
    parser.add_argument("--run-scan", action="store_true", help="Run the full Databento production export first, then build the base snapshot from the generated bundle")
    parser.add_argument("--databento-api-key", default=os.getenv("DATABENTO_API_KEY", ""), help="Databento API key for --run-scan")
    parser.add_argument("--fmp-api-key", default=os.getenv("FMP_API_KEY", ""), help="Optional FMP API key for --run-scan")
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
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.run_scan:
        if not args.databento_api_key:
            raise ValueError("Databento API key is required when using --run-scan")
        run_databento_base_scan_pipeline(
            databento_api_key=str(args.databento_api_key).strip(),
            fmp_api_key=str(args.fmp_api_key).strip(),
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
        return

    if args.bundle is not None:
        generate_base_from_bundle(
            args.bundle,
            schema_path=args.schema,
            output_dir=args.export_dir,
            asof_date=args.asof_date,
            write_xlsx=bool(args.write_xlsx),
            library_owner=str(args.library_owner).strip(),
            library_version=int(args.library_version),
        )
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


if __name__ == "__main__":
    main()