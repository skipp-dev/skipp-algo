from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.smc_live_news_bus import (
    DEFAULT_SYMBOL_LIMIT,
    DEFAULT_TV_SYMBOL_LIMIT,
    export_live_news_snapshot,
    resolve_live_news_symbols,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a provider-neutral live SMC news snapshot as a sidecar artifact.",
    )
    parser.add_argument("--symbols", default="", help="Comma-separated explicit symbol scope")
    parser.add_argument("--base-csv", type=Path, help="Base snapshot CSV used to derive the live symbol scope")
    parser.add_argument("--base-manifest", type=Path, help="SMC base manifest used to resolve the current base CSV")
    parser.add_argument("--export-dir", type=Path, default=Path("artifacts/smc_microstructure_exports"), help="Directory that contains SMC base manifests and default live-news outputs")
    parser.add_argument("--symbol-limit", type=int, default=DEFAULT_SYMBOL_LIMIT, help="Max symbols to derive from the base CSV when no explicit scope is given")
    parser.add_argument("--page-size", type=int, default=100, help="FMP/Benzinga page size for one-shot polling")
    parser.add_argument("--tv-max-per-ticker", type=int, default=3, help="Max TradingView headlines per symbol")
    parser.add_argument("--tv-max-total", type=int, default=25, help="Max total TradingView headlines across the scoped symbols")
    parser.add_argument("--tv-symbol-limit", type=int, default=DEFAULT_TV_SYMBOL_LIMIT, help="Max symbols to fan out to TradingView for the supplemental watchlist lane")
    parser.add_argument("--story-window-hours", type=int, default=24, help="How long stories stay active inside the emitted snapshot")
    parser.add_argument("--skip-tradingview", action="store_true", help="Disable the TradingView supplemental headline lane")
    parser.add_argument("--output", type=Path, default=Path("artifacts/smc_microstructure_exports") / "smc_live_news_snapshot.json", help="Output JSON snapshot path")
    parser.add_argument("--state", type=Path, default=Path("artifacts/smc_microstructure_exports") / "smc_live_news_state.json", help="Persistent state path for provider cursors and seen canonical stories")
    parser.add_argument("--fmp-api-key", default=os.getenv("FMP_API_KEY", ""), help="FMP API key")
    parser.add_argument("--benzinga-api-key", default=os.getenv("BENZINGA_API_KEY", ""), help="Benzinga API key")
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    explicit_symbols = [symbol for symbol in str(args.symbols).split(",") if symbol.strip()]
    symbols, scope_metadata = resolve_live_news_symbols(
        symbols=explicit_symbols,
        base_csv_path=args.base_csv,
        base_manifest_path=args.base_manifest,
        export_dir=args.export_dir,
        symbol_limit=int(args.symbol_limit),
    )
    snapshot = export_live_news_snapshot(
        symbols=symbols,
        output_path=args.output,
        state_path=args.state,
        fmp_api_key=str(args.fmp_api_key).strip(),
        benzinga_api_key=str(args.benzinga_api_key).strip(),
        include_tradingview=not bool(args.skip_tradingview),
        page_size=int(args.page_size),
        tv_max_per_ticker=int(args.tv_max_per_ticker),
        tv_max_total=int(args.tv_max_total),
        tv_symbol_limit=int(args.tv_symbol_limit),
        story_window_seconds=max(int(args.story_window_hours), 1) * 60 * 60,
        scope_metadata=scope_metadata,
    )
    logging.info(
        "Live news snapshot complete: %s",
        json.dumps(
            {
                "output": str(args.output),
                "stories": snapshot["summary"]["active_story_count"],
                "new_stories": snapshot["summary"]["new_story_count"],
                "actionable_symbols": snapshot["summary"]["actionable_symbols"],
            },
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
