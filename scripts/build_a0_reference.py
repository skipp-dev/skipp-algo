"""Bootstrap generator for the A0-Fast reference file (previous_close + ADV).

Today's committed ``services/a0_fast_detector/bootstrap/a0-reference.json``
covers only the ~58-symbol micro-cap shadow list (``A0_FAST_SYMBOLS``). This
module extends the same source-pure Databento reference construction
(:func:`open_prep.a0_reference.build_databento_reference`) to the FULL liquid
open_prep production candidate universe -- the ~900 symbols the realtime
signals producer monitors under ``DEFAULT_TOP_N=0`` (ALL) -- instead of the
micro-cap-only symbol source.

The heavy lifting (per-symbol Databento daily-bar fetch with batching,
symbology, caching, and ``previous_close`` shift) is delegated to the
existing, already-hardened :func:`databento_volatility_screener.load_daily_bars`.
This module only:

1. Extracts the candidate symbol list from a ``latest_open_prep_run.json``
   payload (mirroring ``open_prep.realtime_signals._load_watchlist``'s
   ``DEFAULT_TOP_N=0`` merge of ``ranked_v2`` + ``below_top_n_cutoff``
   overflow + ``enriched_quotes``).
2. Reshapes a ``load_daily_bars()`` frame into per-symbol
   :class:`open_prep.a0_reference.DatabentoDailyBar` lists.
3. Calls :func:`open_prep.a0_reference.build_databento_reference` per symbol
   and writes the resulting :class:`open_prep.a0_stream_state.StreamReference`
   rows to the reference JSON file in the exact list-of-objects shape
   ``services/a0_fast_detector/worker.py::_load_references`` consumes.

Symbols with insufficient or missing qualifying history are SKIPPED, never
fabricated -- the worker's ``StreamReference.is_valid_for()`` requires an
explicit, valid reference per symbol and fails closed (no A0) otherwise.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from open_prep.a0_reference import DatabentoDailyBar, build_databento_reference
from open_prep.a0_stream_state import StreamReference

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_SESSIONS = 15
DEFAULT_CORPORATE_ACTION_VERSION = "databento-adjusted-ohlcv-1d-v1"
DEFAULT_DATASET = "EQUS.MINI"
DEFAULT_REFERENCE_VERSION_PREFIX = "databento-bootstrap"


def extract_candidate_symbols_from_open_prep_run(payload: dict[str, Any]) -> list[str]:
    """Extract the FULL open_prep production candidate universe.

    Mirrors ``open_prep.realtime_signals.RealtimeSignalsMonitor._load_watchlist``'s
    ``DEFAULT_TOP_N=0`` (ALL) merge: ``ranked_v2`` (top-scored) plus overflow
    rows from ``filtered_out_v2`` whose only exclusion reason is
    ``below_top_n_cutoff``, plus any symbol seen in ``enriched_quotes`` not
    already covered. This is the same ~900-symbol universe the realtime
    producer monitors -- NOT the ~58-symbol micro-cap shadow list.
    """
    seen: set[str] = set()
    symbols: list[str] = []

    def _add(symbol_raw: Any) -> None:
        symbol = str(symbol_raw or "").strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            symbols.append(symbol)

    for row in payload.get("ranked_v2") or []:
        _add(row.get("symbol"))

    for row in payload.get("filtered_out_v2") or []:
        reasons = row.get("filter_reasons") or []
        if "below_top_n_cutoff" not in reasons:
            continue  # truly filtered out (e.g. price/volume floor) -- not part of the monitored universe
        _add(row.get("symbol"))

    for row in payload.get("enriched_quotes") or []:
        _add(row.get("symbol"))

    return symbols


def daily_bars_frame_to_bars_by_symbol(
    frame: pd.DataFrame,
    *,
    corporate_action_adjusted: bool = True,
    source: str = "databento:daily",
) -> dict[str, list[DatabentoDailyBar]]:
    """Reshape a ``load_daily_bars()``-shaped frame into per-symbol bar lists.

    Expects columns ``trade_date``, ``symbol``, ``close``, ``volume`` (the
    shape ``databento_volatility_screener.load_daily_bars`` returns).
    """
    bars_by_symbol: dict[str, list[DatabentoDailyBar]] = {}
    if frame.empty:
        return bars_by_symbol
    required = {"trade_date", "symbol", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"daily bars frame is missing required columns: {sorted(missing)}")

    for row in frame.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "") or "").strip().upper()
        if not symbol:
            continue
        trade_date_value = row.trade_date
        session_date = trade_date_value.isoformat() if hasattr(trade_date_value, "isoformat") else str(trade_date_value)
        close_value = getattr(row, "close", None)
        volume_value = getattr(row, "volume", None)
        if close_value is None or volume_value is None or pd.isna(close_value) or pd.isna(volume_value):
            continue
        bars_by_symbol.setdefault(symbol, []).append(
            DatabentoDailyBar(
                symbol=symbol,
                session_date=session_date,
                close=float(close_value),
                volume=int(volume_value),
                source=source,
                corporate_action_adjusted=corporate_action_adjusted,
            )
        )
    return bars_by_symbol


def build_reference_for_universe(
    symbols: list[str],
    bars_by_symbol: dict[str, list[DatabentoDailyBar]],
    *,
    as_of_session: str,
    reference_version: str,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    corporate_action_version: str = DEFAULT_CORPORATE_ACTION_VERSION,
) -> tuple[list[StreamReference], list[str]]:
    """Build a :class:`StreamReference` for every symbol with sufficient,
    source-pure, corporate-action-adjusted Databento daily history.

    Returns ``(references, skipped_symbols)``. Skipped symbols lack enough
    qualifying history and are OMITTED rather than fabricated with a
    zero/garbage reference -- the worker's ``StreamReference.is_valid_for()``
    requires an explicit valid reference and fails closed (no A0) for any
    symbol missing from the reference file.
    """
    references: list[StreamReference] = []
    skipped: list[str] = []
    for symbol in symbols:
        normalized = symbol.strip().upper()
        bars = bars_by_symbol.get(normalized, [])
        try:
            reference = build_databento_reference(
                symbol=normalized,
                bars=bars,
                as_of_session=as_of_session,
                lookback_sessions=lookback_sessions,
                reference_version=reference_version,
                corporate_action_version=corporate_action_version,
            )
        except ValueError as exc:
            logger.info("Skipping %s from A0 reference: %s", normalized, exc)
            skipped.append(normalized)
            continue
        references.append(reference)
    return references, skipped


def write_reference_file(references: list[StreamReference], path: Path) -> None:
    """Write references to the JSON list-of-objects shape
    ``services/a0_fast_detector/worker.py::_load_references`` consumes
    (a JSON array of ``StreamReference`` rows, NOT a symbol-keyed dict)."""
    payload = [asdict(reference) for reference in sorted(references, key=lambda ref: ref.symbol)]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True), encoding="utf-8")
    tmp_path.replace(path)


def _reference_version(as_of_session: str) -> str:
    return f"{DEFAULT_REFERENCE_VERSION_PREFIX}-{as_of_session.replace('-', '')}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the A0-Fast reference file (previous_close + ADV) for the full "
            "open_prep production candidate universe from Databento daily bars."
        )
    )
    parser.add_argument(
        "--open-prep-run",
        required=True,
        help="Path to a latest_open_prep_run.json snapshot to source the candidate universe from.",
    )
    parser.add_argument("--dataset", default=os.getenv("DATABENTO_EQUITY_DAILY_DATASET") or DEFAULT_DATASET)
    parser.add_argument(
        "--lookback-sessions",
        type=int,
        default=DEFAULT_LOOKBACK_SESSIONS,
        help="Number of prior completed sessions to average ADV over.",
    )
    parser.add_argument(
        "--as-of-session",
        default=None,
        help="ISO session date the reference is built as-of (default: today, US/Eastern).",
    )
    parser.add_argument("--output", required=True, help="Output path for the reference JSON file.")
    return parser


def main() -> int:
    """Live orchestration entrypoint. NOT exercised by unit tests -- requires
    DATABENTO_API_KEY and a live Databento historical fetch. See Task 0.2
    controller-verification: generate + spot-check against FMP previousClose
    for liquid names on a real trading day."""
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    load_dotenv()
    args = _build_parser().parse_args()

    databento_api_key = os.getenv("DATABENTO_API_KEY")
    if not databento_api_key:
        print(json.dumps({"error": "DATABENTO_API_KEY missing"}, indent=2, ensure_ascii=True))
        return 2

    from zoneinfo import ZoneInfo

    from databento_volatility_screener import list_recent_trading_days, load_daily_bars

    as_of_session = args.as_of_session or datetime.now(ZoneInfo("America/New_York")).date().isoformat()

    run_payload = json.loads(Path(args.open_prep_run).expanduser().read_text(encoding="utf-8"))
    symbols = extract_candidate_symbols_from_open_prep_run(run_payload)
    if not symbols:
        print(json.dumps({"error": "no candidate symbols extracted from open_prep run"}, indent=2))
        return 2

    trading_days = list_recent_trading_days(
        databento_api_key,
        dataset=args.dataset,
        lookback_days=args.lookback_sessions + 1,
        end_date=date.fromisoformat(as_of_session),
    )
    daily_bars_frame = load_daily_bars(
        databento_api_key,
        dataset=args.dataset,
        trading_days=trading_days,
        universe_symbols=set(symbols),
    )
    bars_by_symbol = daily_bars_frame_to_bars_by_symbol(daily_bars_frame)

    references, skipped = build_reference_for_universe(
        symbols,
        bars_by_symbol,
        as_of_session=as_of_session,
        reference_version=_reference_version(as_of_session),
        lookback_sessions=args.lookback_sessions,
    )
    write_reference_file(references, Path(args.output).expanduser())

    print(
        json.dumps(
            {
                "as_of_session": as_of_session,
                "candidate_symbols": len(symbols),
                "references_written": len(references),
                "skipped_symbols": len(skipped),
                "output": str(Path(args.output).expanduser()),
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
