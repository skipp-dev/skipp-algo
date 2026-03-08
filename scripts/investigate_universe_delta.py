from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import fetch_us_equity_universe, filter_supported_universe_for_databento


def main() -> None:
    repo_root = REPO_ROOT
    load_dotenv(repo_root / ".env")

    fmp_key = os.getenv("FMP_API_KEY", "")
    db_key = os.getenv("DATABENTO_API_KEY", "")
    if not db_key:
        raise SystemExit("DATABENTO_API_KEY must be set in .env")

    manifest_path = Path.home() / "Downloads" / "databento_volatility_production_20260307_114724_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    base = manifest_path.name.replace("_manifest.json", "")
    export_universe = pd.read_parquet(manifest_path.with_name(base + "__universe.parquet"))
    export_symbols = set(export_universe["symbol"].dropna().astype(str).str.upper())

    fmp_universe = fetch_us_equity_universe(fmp_key, min_market_cap=None)
    fmp_symbols = set(fmp_universe["symbol"].dropna().astype(str).str.upper())

    filtered_universe, unsupported = filter_supported_universe_for_databento(
        db_key,
        dataset=str(manifest.get("dataset") or "DBEQ.BASIC"),
        universe=fmp_universe,
        cache_dir=repo_root / "artifacts" / "databento_volatility_cache",
        use_file_cache=True,
        force_refresh=False,
    )
    filtered_symbols = set(filtered_universe["symbol"].dropna().astype(str).str.upper())
    unsupported_symbols = {str(symbol).upper() for symbol in unsupported}

    batl_fmp = fmp_universe[fmp_universe["symbol"].astype(str).str.upper().eq("BATL")]
    batl_filtered = filtered_universe[filtered_universe["symbol"].astype(str).str.upper().eq("BATL")]
    delta_vs_export = sorted(fmp_symbols - export_symbols)

    print(json.dumps(
        {
            "manifest_dataset": manifest.get("dataset"),
            "export_universe_rows": len(export_universe),
            "fmp_universe_rows": len(fmp_universe),
            "filtered_universe_rows": len(filtered_universe),
            "unsupported_count": len(unsupported_symbols),
            "batl_in_export_universe": "BATL" in export_symbols,
            "batl_in_fmp_universe": "BATL" in fmp_symbols,
            "batl_in_filtered_universe": "BATL" in filtered_symbols,
            "batl_marked_unsupported": "BATL" in unsupported_symbols,
            "batl_fmp_row": batl_fmp.to_dict(orient="records"),
            "batl_filtered_row": batl_filtered.to_dict(orient="records"),
            "delta_vs_export_count": len(delta_vs_export),
            "delta_vs_export_sample": delta_vs_export[:100],
        },
        indent=2,
        default=str,
    ))


if __name__ == "__main__":
    main()
