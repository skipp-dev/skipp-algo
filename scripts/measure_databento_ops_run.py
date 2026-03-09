from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import build_data_status_result
from scripts.databento_preopen_fast import run_preopen_fast_refresh
from scripts.databento_production_export import run_production_export_pipeline
from scripts.generate_databento_watchlist import LongDipConfig, generate_watchlist_result


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure end-to-end Databento ops run (refresh + watchlist).")
    parser.add_argument(
        "--run-profile",
        choices=["full_history", "preopen_fast"],
        default="preopen_fast",
        help="full_history runs the historical full-universe export; preopen_fast builds a reduced current premarket refresh from the latest full-history bundle.",
    )
    parser.add_argument("--dataset", default=os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"))
    parser.add_argument("--lookback-days", type=int, default=int(os.getenv("DATABENTO_LOOKBACK_DAYS", "30")))
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--force-refresh", action="store_true", default=False)
    parser.add_argument("--no-force-refresh", action="store_true", default=False)
    parser.add_argument(
        "--export-dir",
        default=str(Path.home() / "Downloads"),
        help="Directory used by production export and watchlist generation.",
    )
    parser.add_argument(
        "--report-path",
        default=str(REPO_ROOT / "artifacts" / "ops_run_report.json"),
        help="JSON report path.",
    )
    parser.add_argument(
        "--preopen-scope-days",
        type=int,
        default=0,
        help="Use symbols selected_top20pct in the last N completed trade days for the reduced preopen scope. Use 0 for adaptive auto mode.",
    )
    return parser


def main() -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()
    effective_force_refresh = bool(args.force_refresh and not args.no_force_refresh)

    databento_api_key = os.getenv("DATABENTO_API_KEY")
    fmp_api_key = os.getenv("FMP_API_KEY", "")

    export_dir = Path(args.export_dir).expanduser()
    cache_dir = REPO_ROOT / "artifacts" / "databento_volatility_cache"
    report_path = Path(args.report_path).expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "started_at": _iso_now(),
        "run_profile": args.run_profile,
        "dataset": args.dataset,
        "lookback_days": int(args.lookback_days),
        "top_n": int(args.top_n),
        "force_refresh": effective_force_refresh,
        "has_databento_key": bool(databento_api_key),
        "has_fmp_key": bool(fmp_api_key),
        "steps": {},
        "findings": [],
    }

    if not databento_api_key:
        report["error"] = "DATABENTO_API_KEY missing"
        report["finished_at"] = _iso_now()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 2

    t0 = time.perf_counter()
    try:
        if args.run_profile == "full_history":
            run_production_export_pipeline(
                databento_api_key=databento_api_key,
                fmp_api_key=fmp_api_key,
                dataset=args.dataset,
                lookback_days=int(args.lookback_days),
                cache_dir=cache_dir,
                export_dir=export_dir,
                use_file_cache=True,
                force_refresh=effective_force_refresh,
                second_detail_scope="full_universe",
            )
        else:
            run_preopen_fast_refresh(
                databento_api_key=databento_api_key,
                dataset=args.dataset,
                export_dir=export_dir,
                bundle=export_dir,
                scope_days=None if int(args.preopen_scope_days) <= 0 else int(args.preopen_scope_days),
            )
        refresh_seconds = time.perf_counter() - t0
        report["steps"]["refresh_data_basis"] = {"ok": True, "duration_seconds": round(refresh_seconds, 3)}
    except Exception as exc:
        refresh_seconds = time.perf_counter() - t0
        report["steps"]["refresh_data_basis"] = {
            "ok": False,
            "duration_seconds": round(refresh_seconds, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }
        report["findings"].append("Refresh Data Basis failed before watchlist generation.")
        report["finished_at"] = _iso_now()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 1

    t1 = time.perf_counter()
    try:
        watch = generate_watchlist_result(export_dir=export_dir, cfg=LongDipConfig(top_n=int(args.top_n)))
        watch_seconds = time.perf_counter() - t1
        report["steps"]["generate_watchlist"] = {
            "ok": True,
            "duration_seconds": round(watch_seconds, 3),
            "rows": int(len(watch.get("watchlist_table", []))) if isinstance(watch, dict) else 0,
            "warnings": watch.get("warnings", []) if isinstance(watch, dict) else [],
            "trade_date": watch.get("trade_date") if isinstance(watch, dict) else None,
            "source_data_fetched_at": watch.get("source_data_fetched_at") if isinstance(watch, dict) else None,
        }
    except Exception as exc:
        watch_seconds = time.perf_counter() - t1
        report["steps"]["generate_watchlist"] = {
            "ok": False,
            "duration_seconds": round(watch_seconds, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }
        report["findings"].append("Generate Watchlist failed.")
        report["finished_at"] = _iso_now()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 1

    status = build_data_status_result(export_dir)
    report["status_after_run"] = {
        "is_stale": status.is_stale,
        "staleness_reason": status.staleness_reason,
        "export_generated_at": status.export_generated_at,
        "premarket_fetched_at": status.premarket_fetched_at,
        "intraday_fetched_at": status.intraday_fetched_at,
        "second_detail_fetched_at": status.second_detail_fetched_at,
    }
    if status.is_stale:
        report["findings"].append("Post-run status is stale.")

    warnings_list = report["steps"]["generate_watchlist"].get("warnings", [])
    if warnings_list:
        report["findings"].append("Watchlist produced warnings.")

    total_seconds = float(report["steps"]["refresh_data_basis"]["duration_seconds"]) + float(
        report["steps"]["generate_watchlist"]["duration_seconds"]
    )
    report["total_duration_seconds"] = round(total_seconds, 3)
    report["total_duration_minutes"] = round(total_seconds / 60.0, 3)
    report["finished_at"] = _iso_now()

    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
